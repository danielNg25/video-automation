"""OCR-based subtitle extraction using PaddleOCR.

Extracts burned-in Chinese subtitles from video frames instead of
transcribing audio. Auto-detects subtitle regions and filters out
watermarks/UI elements using position, frequency, and size heuristics.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


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
    ):
        self.fps = fps
        self.confidence_threshold = confidence_threshold
        self.similarity_threshold = similarity_threshold
        self.ocr_region = ocr_region
        self.progress_callback = progress_callback

        region_cfg = subtitle_region_config or {}
        self.min_y = region_cfg.get("min_y", 0.65)
        self.max_watermark_freq = region_cfg.get("max_watermark_frequency", 0.80)
        self.min_text_height = region_cfg.get("min_text_height", 0.02)
        self.horizontal_margin = region_cfg.get("horizontal_margin", 0.10)

        self._ocr_engine = None

    def _get_ocr(self, lang: str = "ch"):
        """Lazy-init PaddleOCR engine."""
        if self._ocr_engine is None:
            from paddleocr import PaddleOCR

            self._ocr_engine = PaddleOCR(lang=lang)
        return self._ocr_engine

    def transcribe(
        self, video_path: str, language: str = "zh", task: str = "transcribe"
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

        # Extract frames
        self._emit_progress(0.05, "Extracting frames...")
        with tempfile.TemporaryDirectory() as tmpdir:
            frames = proc.extract_frames(video_path, Path(tmpdir), fps=self.fps)

            if not frames:
                logger.warning("No frames extracted from video")
                return []

            total_frames = len(frames)
            ocr_lang = "ch" if language == "zh" else "en"
            ocr = self._get_ocr(ocr_lang)

            if self.ocr_region:
                return self._ocr_with_manual_region(
                    frames, ocr, frame_height, frame_width
                )

            # Two-pass auto-detection approach
            # Pass 1: Sample every 5th frame to build watermark map
            self._emit_progress(0.10, "Analyzing subtitle regions (sampling)...")
            sample_indices = list(range(0, total_frames, 5))
            all_sample_detections = []

            for i, idx in enumerate(sample_indices):
                result = ocr.ocr(str(frames[idx]))
                detections = self._parse_ocr_result(result)
                all_sample_detections.append((idx, detections))

            # Build watermark position index from samples
            watermark_positions = self._build_watermark_positions(
                all_sample_detections, len(sample_indices), frame_height
            )

            # Pass 2: OCR all frames, skip watermark positions
            frame_texts = []
            for i, frame_path in enumerate(frames):
                pct = 0.15 + (i / total_frames) * 0.65
                if i % 10 == 0:
                    self._emit_progress(
                        pct, f"Running OCR on frame {i + 1}/{total_frames}..."
                    )

                result = ocr.ocr(str(frame_path))
                detections = self._parse_ocr_result(result)

                # Filter: keep only subtitle-classified text
                subtitle_text = self._filter_subtitle_text(
                    detections, watermark_positions, frame_height, frame_width
                )
                frame_texts.append(subtitle_text)

            # Deduplicate consecutive frames into segments
            self._emit_progress(0.85, "Deduplicating and generating SRT...")
            segments = self._deduplicate_frames(frame_texts)

        return segments

    def _ocr_with_manual_region(
        self,
        frames: list[Path],
        ocr,
        frame_height: int,
        frame_width: int,
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
            pct = 0.15 + (i / total_frames) * 0.65
            if i % 10 == 0:
                self._emit_progress(
                    pct, f"Running OCR on frame {i + 1}/{total_frames}..."
                )

            result = ocr.ocr(str(frame_path))
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
        """Parse PaddleOCR result into list of (bbox, text, confidence).

        Handles both v2 format [[(bbox, (text, conf)), ...]] and
        v3 format [{"rec_texts": [...], "rec_scores": [...], "dt_polys": [...]}].
        """
        detections = []
        if not result:
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
                # Convert numpy array to list if needed
                bbox = poly.tolist() if hasattr(poly, "tolist") else list(poly)
                # Ensure 4-point bbox format [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                if len(bbox) >= 4:
                    detections.append((bbox[:4], text, score))
                elif len(bbox) == 2:
                    # rect format [x1,y1,x2,y2] → expand to 4 corners
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
        Positions appearing in >max_watermark_freq of samples = watermark.

        Returns:
            Set of Y-buckets identified as watermarks.
        """
        bucket_size = max(1, int(frame_height * 0.05))
        position_counts: dict[int, int] = defaultdict(int)

        for _, detections in sample_detections:
            seen_buckets: set[int] = set()
            for bbox, text, conf in detections:
                if conf < self.confidence_threshold:
                    continue
                center_y = (bbox[0][1] + bbox[2][1]) / 2
                bucket = int(center_y) // bucket_size
                if bucket not in seen_buckets:
                    position_counts[bucket] += 1
                    seen_buckets.add(bucket)

        watermark_buckets = set()
        for bucket, count in position_counts.items():
            if count / sample_count > self.max_watermark_freq:
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
    ) -> str:
        """Filter detections to keep only subtitle text.

        Applies position, size, centering, and watermark filters.
        """
        bucket_size = max(1, int(frame_height * 0.05))
        texts = []

        for bbox, text, conf in detections:
            if conf < self.confidence_threshold:
                continue

            center_y = (bbox[0][1] + bbox[2][1]) / 2
            center_x = (bbox[0][0] + bbox[2][0]) / 2
            text_height = abs(bbox[2][1] - bbox[0][1])

            # Position: bottom portion of frame
            if center_y < self.min_y * frame_height:
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

        return " ".join(texts) if texts else ""

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

    def _emit_progress(self, progress: float, message: str):
        """Emit progress update if callback is set."""
        if self.progress_callback:
            self.progress_callback(progress, message)
