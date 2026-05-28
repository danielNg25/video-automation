"""OCR-based subtitle extraction using PaddleOCR.

Extracts burned-in Chinese subtitles from video frames instead of
transcribing audio. Auto-detects subtitle regions and filters out
watermarks/UI elements using position, frequency, and size heuristics.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


_PROVIDER_PRIORITY = [
    "CUDAExecutionProvider",        # NVIDIA — best perf
    "DmlExecutionProvider",         # Windows GPU (NVIDIA / AMD / Intel)
    "CoreMLExecutionProvider",      # macOS native (not usable from Docker)
    "CPUExecutionProvider",         # always available
]


def _pick_provider(override: str = "auto") -> str:
    """Pick the best ONNX Runtime execution provider for this host.

    `override` may be one of: 'auto', 'cpu', 'cuda', 'directml', 'coreml'.
    A non-'auto' value returns the matching ORT provider name unconditionally
    (the caller is responsible for ensuring the matching ORT package is
    installed). 'auto' probes onnxruntime for available providers and
    picks the highest-priority one that's actually present, falling back
    to CPU. Returns 'CPUExecutionProvider' if onnxruntime can't be imported.
    """
    if override and override != "auto":
        return {
            "cpu": "CPUExecutionProvider",
            "cuda": "CUDAExecutionProvider",
            "directml": "DmlExecutionProvider",
            "coreml": "CoreMLExecutionProvider",
        }.get(override, "CPUExecutionProvider")

    try:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
    except Exception as e:
        logger.warning(
            f"onnxruntime not importable yet ({e}); defaulting to CPU provider"
        )
        return "CPUExecutionProvider"

    for ep in _PROVIDER_PRIORITY:
        if ep in available:
            return ep
    return "CPUExecutionProvider"


class OCRTranscriber(BaseTranscriber):
    """Extracts subtitles from video frames via PaddleOCR with auto-detection."""

    def __init__(
        self,
        fps: float = 2.0,
        confidence_threshold: float = 0.7,
        similarity_threshold: float = 0.85,
        subtitle_region_config: dict | None = None,
        ocr_region: dict | None = None,
        progress_callback=None,
        crop_bottom_pct: float = 0.0,
        execution_provider: str = "auto",
    ):
        self.fps = fps
        self.confidence_threshold = confidence_threshold
        self.similarity_threshold = similarity_threshold
        self.ocr_region = ocr_region
        self.progress_callback = progress_callback
        self.crop_bottom_pct = crop_bottom_pct
        self.execution_provider = execution_provider

        region_cfg = subtitle_region_config or {}
        self.min_y = region_cfg.get("min_y", 0.65)
        self.max_watermark_freq = region_cfg.get("max_watermark_frequency", 0.80)
        self.min_text_height = region_cfg.get("min_text_height", 0.02)
        self.horizontal_margin = region_cfg.get("horizontal_margin", 0.10)

        self._ocr_engine = None

    def _get_ocr(self, lang: str = "ch"):
        """Lazy-init RapidOCR engine on first use.

        Picks an ONNX Runtime execution provider via `_pick_provider`. For
        CUDA hosts the three stages (detection / classification /
        recognition) each get `*_use_cuda=True`. For non-CUDA providers
        we fall through to CPU — RapidOCR doesn't expose DirectML/CoreML
        toggles as cleanly, and the CPU path is already fast enough for
        the Apple Silicon case once frame-diff is in play.

        Note: `lang` is currently informational only — RapidOCR ships
        PP-OCRv4 models that already cover Chinese + English; switching
        language models is a separate config knob if we ever need it.
        """
        if self._ocr_engine is None:
            provider = _pick_provider(self.execution_provider)
            use_cuda = provider == "CUDAExecutionProvider"
            logger.info(
                f"OCR engine: RapidOCR (provider={provider}, use_cuda={use_cuda})"
            )
            if provider in ("DmlExecutionProvider", "CoreMLExecutionProvider"):
                logger.info(
                    f"Note: provider {provider} is recognised by ORT but RapidOCR "
                    f"1.x exposes only CUDA toggles — falling through to CPU for "
                    f"this run. Combined with frame-diff this is still 5–10× "
                    f"faster than the previous Paddle pipeline."
                )

            from rapidocr_onnxruntime import RapidOCR

            self._ocr_engine = RapidOCR(
                det_use_cuda=use_cuda,
                cls_use_cuda=use_cuda,
                rec_use_cuda=use_cuda,
            )
        return self._ocr_engine

    def transcribe(
        self,
        video_path: str,
        language: str = "zh",
        task: str = "transcribe",
        task_id: str | None = None,
    ) -> list[dict]:
        """Extract subtitles from burned-in text in video frames.

        Args:
            video_path: Path to video file.
            language: Source language code ('zh' maps to PaddleOCR 'ch').
            task: Ignored for OCR (always extracts source text).

        Returns:
            List of segment dicts with 'start', 'end', 'text' keys.
        """
        from src.processor.ffmpeg import FFmpegProcessor

        video_path = Path(video_path) if isinstance(video_path, str) else video_path

        # Get video dimensions
        proc = FFmpegProcessor()
        info = proc.get_video_info(video_path)
        frame_height = info["height"]
        frame_width = info["width"]

        # Pre-crop: extract only bottom N% of frame if configured
        crop_pct = self.crop_bottom_pct
        if crop_pct > 0:
            self._emit_progress(0.05, f"Extracting frames (crop bottom {crop_pct:.0%})...")
            # When cropped, the frame dimensions change for filtering
            cropped_height = int(frame_height * crop_pct)
            cropped_width = frame_width
            logger.info(
                f"Pre-cropping to bottom {crop_pct:.0%}: "
                f"{frame_width}x{cropped_height} (from {frame_width}x{frame_height})"
            )
        else:
            self._emit_progress(0.05, "Extracting frames...")
            cropped_height = frame_height
            cropped_width = frame_width

        with tempfile.TemporaryDirectory() as tmpdir:
            frames = proc.extract_frames(
                video_path, Path(tmpdir), fps=self.fps, crop_bottom_pct=crop_pct
            )

            if not frames:
                logger.warning("No frames extracted from video")
                return []

            total_frames = len(frames)
            ocr_lang = "ch" if language == "zh" else "en"
            ocr = self._get_ocr(ocr_lang)

            if self.ocr_region:
                return self._ocr_with_manual_region(
                    frames, ocr, frame_height, frame_width, task_id=task_id
                )

            # Single streaming pass: OCR every frame, build a rolling
            # watermark Y-index from recent detections, filter, and append.
            # Pre-image frame-diff skipping was attempted but didn't help
            # at typical Douyin sampling rates (1-2 fps with constantly
            # changing video content under a small subtitle strip) — the
            # engine swap to RapidOCR provides the bulk of the speedup.
            ring: list[list[tuple]] = []  # recent detection sets
            RING_SIZE = 50
            REFRESH_EVERY = 10
            watermark_positions: set[int] = set()

            frame_texts: list[str] = []
            # One inner list per analyzed frame that had at least one subtitle box.
            # Per-frame grouping is required so _save_ocr_metadata can pick the
            # largest single-frame bbox instead of unioning across frames.
            all_subtitle_bboxes: list[list[list]] = []

            effective_min_y = 0.0 if crop_pct > 0 else self.min_y
            crop_y_offset = (
                int(frame_height * (1 - crop_pct)) if crop_pct > 0 else 0
            )

            for i, frame_path in enumerate(frames):
                # Cancel check: short-circuit if the task is being cancelled.
                if task_id is not None:
                    from src.api.task_manager import get_task_manager_instance
                    tm = get_task_manager_instance()
                    if tm is not None:
                        t = tm.tasks.get(task_id)
                        if t is not None and t.status == "cancelling":
                            logger.info(f"OCR loop cancelled at frame {i}/{len(frames)}")
                            return self._deduplicate_frames(frame_texts)

                pct = 0.10 + (i / total_frames) * 0.75
                if i % 10 == 0:
                    self._emit_progress(
                        pct, f"OCR frame {i + 1}/{total_frames}..."
                    )

                result, _elapse = ocr(str(frame_path))
                detections = self._parse_ocr_result(result)

                # Refresh watermark index from rolling buffer.
                ring.append(detections)
                if len(ring) > RING_SIZE:
                    ring.pop(0)
                if (i + 1) % REFRESH_EVERY == 0 or i == total_frames - 1:
                    watermark_positions = self._build_watermark_positions(
                        # _build_watermark_positions takes (idx, detections)
                        # tuples but uses only the detections; pass 0 for idx.
                        [(0, d) for d in ring],
                        len(ring),
                        cropped_height,
                    )

                subtitle_text, subtitle_bboxes = self._filter_subtitle_text_with_boxes(
                    detections, watermark_positions, cropped_height, cropped_width,
                    min_y_override=effective_min_y,
                    crop_y_offset=crop_y_offset,
                )
                frame_texts.append(subtitle_text)
                if subtitle_bboxes:
                    all_subtitle_bboxes.append(subtitle_bboxes)

            logger.info(f"OCR streaming: {total_frames} engine calls")

            # Deduplicate consecutive frames into segments
            self._emit_progress(0.85, "Deduplicating and generating SRT...")
            segments = self._deduplicate_frames(frame_texts)

        # Save OCR metadata with subtitle region for Phase 6 blur
        if all_subtitle_bboxes:
            video_stem = video_path.stem
            srt_dir = video_path.parent.parent / "srt"
            self._save_ocr_metadata(
                srt_dir, video_stem, frame_width, frame_height,
                all_subtitle_bboxes, total_frames,
            )

        return segments

    def _ocr_with_manual_region(
        self,
        frames: list[Path],
        ocr,
        frame_height: int,
        frame_width: int,
        task_id: str | None = None,
    ) -> list[dict]:
        """OCR using a manually specified region."""
        region = self.ocr_region
        rx, ry = region["x"], region["y"]
        rw, rh = region["w"], region["h"]

        # Convert fractional coords to pixel bounds
        x_min = int(rx * frame_width)
        y_min = int(ry * frame_height)
        x_max = int((rx + rw) * frame_width)
        y_max = int((ry + rh) * frame_height)

        total_frames = len(frames)
        frame_texts = []

        for i, frame_path in enumerate(frames):
            # Cancel check: short-circuit if the task is being cancelled.
            if task_id is not None:
                from src.api.task_manager import get_task_manager_instance
                tm = get_task_manager_instance()
                if tm is not None:
                    t = tm.tasks.get(task_id)
                    if t is not None and t.status == "cancelling":
                        logger.info(f"OCR loop cancelled at frame {i}/{len(frames)}")
                        return self._deduplicate_frames(frame_texts)

            pct = 0.15 + (i / total_frames) * 0.65
            if i % 10 == 0:
                self._emit_progress(
                    pct, f"Running OCR on frame {i + 1}/{total_frames}..."
                )

            # RapidOCR is callable: ocr(image) returns (result, timings).
            result, _elapse = ocr(str(frame_path))
            detections = self._parse_ocr_result(result)

            # Keep only detections within the manual region
            texts = []
            for bbox, text, conf in detections:
                if conf < self.confidence_threshold:
                    continue
                center_y = (bbox[0][1] + bbox[2][1]) / 2
                center_x = (bbox[0][0] + bbox[2][0]) / 2
                if x_min <= center_x <= x_max and y_min <= center_y <= y_max:
                    texts.append(text)

            frame_texts.append(" ".join(texts) if texts else "")

        self._emit_progress(0.85, "Deduplicating and generating SRT...")
        return self._deduplicate_frames(frame_texts)

    @staticmethod
    def _parse_ocr_result(result) -> list[tuple]:
        """Parse OCR engine result into list of (bbox, text, confidence).

        Handles three shapes:
            - RapidOCR:     [[bbox_pts, text, conf], ...]  (current)
            - PaddleOCR v3: [{"rec_texts": [...], "rec_scores": [...],
                              "dt_polys": [...]}]
            - PaddleOCR v2: [[(bbox, (text, conf)), ...]]

        Paddle shapes are kept so this function can be used against
        captured fixtures or if we ever flip back. Every branch normalises
        to the same `(bbox_4pts, text, float_conf)` tuple expected by
        `_filter_subtitle_text_with_boxes` and watermark logic.
        """
        detections = []
        if not result:
            return detections

        # RapidOCR: list of [bbox_pts, text, conf]
        # (PP-OCR style, the only shape RapidOCR 1.x emits)
        if (
            isinstance(result, list)
            and len(result) > 0
            and isinstance(result[0], list)
            and len(result[0]) == 3
            and isinstance(result[0][1], str)
        ):
            for item in result:
                bbox, text, conf = item
                bbox = bbox.tolist() if hasattr(bbox, "tolist") else list(bbox)
                try:
                    conf_f = float(conf)
                except (TypeError, ValueError):
                    conf_f = 0.0
                detections.append((bbox, text, conf_f))
            return detections

        # PaddleOCR v3: list of result dicts with rec_texts/rec_scores/dt_polys
        if isinstance(result, list) and len(result) > 0 and isinstance(result[0], dict):
            res = result[0]
            texts = res.get("rec_texts", [])
            scores = res.get("rec_scores", [])
            polys = res.get("dt_polys", res.get("rec_polys", []))

            for i, text in enumerate(texts):
                score = scores[i] if i < len(scores) else 0.0
                poly = polys[i] if i < len(polys) else [[0, 0], [0, 0], [0, 0], [0, 0]]
                bbox = poly.tolist() if hasattr(poly, "tolist") else list(poly)
                if len(bbox) >= 4:
                    detections.append((bbox[:4], text, score))
                elif len(bbox) == 2:
                    x1, y1 = bbox[0]
                    x2, y2 = bbox[1]
                    detections.append(
                        ([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], text, score)
                    )
            return detections

        # PaddleOCR v2: [[(bbox, (text, conf)), ...]]
        if not result[0]:
            return detections
        for line in result[0]:
            bbox = line[0]
            text = line[1][0]
            confidence = line[1][1]
            detections.append((bbox, text, confidence))
        return detections

    def _build_watermark_positions(
        self,
        sample_detections: list[tuple[int, list]],
        sample_count: int,
        frame_height: int,
    ) -> set[int]:
        """Identify Y-positions that are likely watermarks based on frequency.

        Groups detections by Y-position bucket (±5% of frame height).
        A position is a watermark only if:
        1. Text appears there in >max_watermark_freq of samples
        2. The most frequent single text accounts for >60% of appearances
           (same text = watermark, varying text = subtitles)

        Returns:
            Set of Y-buckets identified as watermarks.
        """
        from collections import Counter

        bucket_size = max(1, int(frame_height * 0.05))
        position_counts: dict[int, int] = defaultdict(int)
        position_texts: dict[int, list[str]] = defaultdict(list)

        for _, detections in sample_detections:
            seen_buckets: set[int] = set()
            for bbox, text, conf in detections:
                if conf < self.confidence_threshold:
                    continue
                center_y = (bbox[0][1] + bbox[2][1]) / 2
                bucket = int(center_y) // bucket_size
                position_texts[bucket].append(text)
                if bucket not in seen_buckets:
                    position_counts[bucket] += 1
                    seen_buckets.add(bucket)

        watermark_buckets = set()
        for bucket, count in position_counts.items():
            if count / sample_count <= self.max_watermark_freq:
                continue

            # Check text consistency: watermarks show the same text repeatedly,
            # subtitles show different text at the same Y-position
            texts = position_texts[bucket]
            if texts:
                most_common_count = Counter(texts).most_common(1)[0][1]
                text_consistency = most_common_count / len(texts)
                if text_consistency < 0.6:
                    logger.debug(
                        f"Y-bucket {bucket}: high frequency but varying text "
                        f"(consistency={text_consistency:.0%}) — keeping as subtitle"
                    )
                    continue

            watermark_buckets.add(bucket)
            logger.debug(
                f"Watermark detected at Y-bucket {bucket} "
                f"({count}/{sample_count} = {count / sample_count:.0%})"
            )

        if watermark_buckets:
            logger.info(f"Filtered {len(watermark_buckets)} watermark region(s)")

        return watermark_buckets

    def _filter_subtitle_text(
        self,
        detections: list[tuple],
        watermark_positions: set[int],
        frame_height: int,
        frame_width: int,
        min_y_override: float | None = None,
    ) -> str:
        """Filter detections to keep only subtitle text.

        Applies position, size, centering, and watermark filters.
        """
        text, _ = self._filter_subtitle_text_with_boxes(
            detections, watermark_positions, frame_height, frame_width,
            min_y_override=min_y_override,
        )
        return text

    def _filter_subtitle_text_with_boxes(
        self,
        detections: list[tuple],
        watermark_positions: set[int],
        frame_height: int,
        frame_width: int,
        min_y_override: float | None = None,
        crop_y_offset: int = 0,
    ) -> tuple[str, list[list]]:
        """Filter detections to keep only subtitle text, returning text and bboxes.

        Args:
            crop_y_offset: Y offset to add to bboxes when frames were pre-cropped,
                to convert back to full-frame coordinates.

        Returns:
            Tuple of (joined text, list of 4-point bboxes in full-frame coords).
        """
        bucket_size = max(1, int(frame_height * 0.05))
        min_y = min_y_override if min_y_override is not None else self.min_y
        texts = []
        bboxes = []

        for bbox, text, conf in detections:
            if conf < self.confidence_threshold:
                continue

            center_y = (bbox[0][1] + bbox[2][1]) / 2
            center_x = (bbox[0][0] + bbox[2][0]) / 2
            text_height = abs(bbox[2][1] - bbox[0][1])

            # Position: bottom portion of frame
            if center_y < min_y * frame_height:
                continue

            # Size: minimum readable text
            if text_height < self.min_text_height * frame_height:
                continue

            # Centering: within horizontal margins
            if not (
                self.horizontal_margin * frame_width
                < center_x
                < (1 - self.horizontal_margin) * frame_width
            ):
                continue

            # Watermark: skip positions identified as watermarks
            y_bucket = int(center_y) // bucket_size
            if y_bucket in watermark_positions:
                continue

            texts.append(text)
            # Convert bbox to full-frame coordinates if cropped
            if crop_y_offset > 0:
                adjusted = [[p[0], p[1] + crop_y_offset] for p in bbox]
                bboxes.append(adjusted)
            else:
                bboxes.append(bbox)

        return " ".join(texts) if texts else "", bboxes

    def _deduplicate_frames(self, frame_texts: list[str]) -> list[dict]:
        """Merge consecutive frames with similar text into segments.

        Uses SequenceMatcher to detect similarity between adjacent frames.
        """
        if not frame_texts:
            return []

        segments = []
        frame_duration = 1.0 / self.fps
        current_text = ""
        current_start = 0.0

        for i, text in enumerate(frame_texts):
            timestamp = i * frame_duration

            if not text:
                # Empty frame closes current segment
                if current_text:
                    end = timestamp
                    if end - current_start >= 0.5:
                        segments.append(
                            {"start": current_start, "end": end, "text": current_text}
                        )
                    current_text = ""
                continue

            if not current_text:
                # Start new segment
                current_text = text
                current_start = timestamp
                continue

            # Check similarity with current segment text
            ratio = SequenceMatcher(None, current_text, text).ratio()
            if ratio >= self.similarity_threshold:
                # Similar enough — extend segment, keep longer text
                if len(text) > len(current_text):
                    current_text = text
            else:
                # Different text — close current, start new
                end = timestamp
                if end - current_start >= 0.5:
                    segments.append(
                        {"start": current_start, "end": end, "text": current_text}
                    )
                current_text = text
                current_start = timestamp

        # Close final segment
        if current_text:
            end = len(frame_texts) * frame_duration
            if end - current_start >= 0.5:
                segments.append(
                    {"start": current_start, "end": end, "text": current_text}
                )

        logger.info(
            f"OCR produced {len(segments)} segments from {len(frame_texts)} frames"
        )
        return segments

    def _save_ocr_metadata(
        self,
        srt_dir: Path,
        video_id: str,
        video_width: int,
        video_height: int,
        subtitle_boxes_per_frame: list[list[list]],
        frames_analyzed: int,
    ) -> None:
        """Save OCR metadata: x extent unions across frames; y/height is median.

        Two competing requirements:
          - The blur must cover the *longest* subtitle line that ever appears
            (otherwise the original Chinese leaks out the sides on long-text
            frames). → use UNION of x-extents across frames.
          - The blur must NOT be vertically inflated by occasional multi-line
            wrap frames (otherwise the band is way taller than typical
            subtitles and the new burned text looks wrong). → use MEDIAN of
            y_min and y_max across frames.

        Each frame contributes one bbox computed as the within-frame union of
        all subtitle-classified text boxes (so multi-line subs are covered as
        a single block on the frames that have them).
        """
        if not subtitle_boxes_per_frame:
            logger.info("No subtitle boxes collected — skipping OCR metadata save")
            return

        # (x_min, x_max, y_min, y_max) per frame.
        records: list[tuple[int, int, int, int]] = []
        for frame_bboxes in subtitle_boxes_per_frame:
            xs: list[float] = []
            ys: list[float] = []
            for bbox in frame_bboxes:
                if len(bbox) < 4:
                    continue
                for point in bbox:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
            if not xs or not ys:
                continue
            x_min = max(0, int(min(xs)))
            x_max = min(video_width, int(max(xs)))
            y_min = max(0, int(min(ys)))
            y_max = min(video_height, int(max(ys)))
            if x_max <= x_min or y_max <= y_min:
                continue
            records.append((x_min, x_max, y_min, y_max))

        if not records:
            logger.info("No usable subtitle bboxes — skipping OCR metadata save")
            return

        # Horizontal: union — span enough to cover every frame's subtitle.
        union_x_min = min(r[0] for r in records)
        union_x_max = max(r[1] for r in records)

        # Vertical: median of each edge — tracks typical subtitle position
        # without being dragged tall by multi-line frames.
        sorted_y_min = sorted(r[2] for r in records)
        sorted_y_max = sorted(r[3] for r in records)
        median_y_min = sorted_y_min[len(sorted_y_min) // 2]
        median_y_max = sorted_y_max[len(sorted_y_max) // 2]

        x = union_x_min
        y = median_y_min
        w = union_x_max - union_x_min
        h = median_y_max - median_y_min
        if w <= 0 or h <= 0:
            logger.info(
                f"Aggregated region degenerate (w={w}, h={h}) — skipping save"
            )
            return

        region = {"x": x, "y": y, "width": w, "height": h}

        meta = {
            "video_id": video_id,
            "video_width": video_width,
            "video_height": video_height,
            "subtitle_region": region,
            "frames_analyzed": frames_analyzed,
        }

        meta_path = srt_dir / f"{video_id}_ocr_meta.json"
        srt_dir.mkdir(parents=True, exist_ok=True)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

        logger.info(
            f"Saved OCR metadata: x={region['x']} y={region['y']} "
            f"w={region['width']} h={region['height']} "
            f"(union-x + median-y/h across {len(records)} frame bboxes) "
            f"→ {meta_path.name}"
        )

    def _emit_progress(self, progress: float, message: str):
        """Emit progress update if callback is set."""
        if self.progress_callback:
            self.progress_callback(progress, message)
