# Implementation plan — OCR speedup: RapidOCR + frame-diff + EP auto-detect

**Spec:** [2026-05-19-rapidocr-frame-diff-speedup-design.md](../specs/2026-05-19-rapidocr-frame-diff-speedup-design.md)
**Branch:** `feature/ocr-rapidocr-frame-diff-speedup`
**Date:** 2026-05-19

## Pre-flight

Lock a pre-change baseline so we can verify the gain. Before any code changes:

```bash
# 1. Pick a reference video the user already has.
VIDEO=data/raw/7595865200734014772.mp4

# 2. Capture wall time + SRT with the current (PaddleOCR) implementation.
time docker compose exec -T app python -m src transcribe "$VIDEO" --lang zh \
  2>&1 | tee /tmp/ocr_baseline.log

# 3. Save the produced SRT for later A/B comparison.
cp data/srt/7595865200734014772_zh.srt /tmp/ocr_baseline_zh.srt
```

Record the wall time (e.g., "62 s") and segment count (`wc -l /tmp/ocr_baseline_zh.srt`) in a scratch note. The acceptance criterion is **≥ 5× faster** with **≥ 90 % text overlap** vs this baseline.

---

## Order of work

Implement bottom-up so each layer is independently testable:

1. `_FrameDiffer` helper + its unit tests — pure-numpy, no OCR engine needed.
2. `_pick_provider()` helper + its unit tests — mocks `onnxruntime.get_available_providers()`.
3. Swap engine: drop Paddle imports/flags, build `RapidOCR(...)` in `_get_ocr()`.
4. Rewrite `transcribe()` from 2-pass to 1-pass streaming with frame-diff and rolling watermark buffer.
5. Update `_parse_ocr_result()` to handle the RapidOCR result shape.
6. Update `pyproject.toml`, `docker-compose.yml`, `config/config.example.yaml`.
7. Update `CHANGELOG.md`, `DOCKER.md`.
8. Rebuild Docker image. A/B verify against baseline.

Each step is a separate commit so we can bisect if accuracy regresses.

---

## Step 1 — `_FrameDiffer` helper

**File**: [src/transcriber/ocr.py](../../../src/transcriber/ocr.py) — add as a nested or module-private class.

```python
class _FrameDiffer:
    """Cheap frame-to-frame diff over the subtitle strip.

    Reads each frame as uint8 grayscale, mean-abs-diffs it against the
    previous frame's strip. If below `threshold`, the caller treats the
    new frame as "same as previous" and reuses the cached OCR result
    instead of running OCR again.
    """

    def __init__(self, threshold: float = 3.0):
        self.threshold = threshold
        self.prev_strip: np.ndarray | None = None
        self.prev_text: str = ""
        self.prev_bboxes: list[list[list]] = []

    def is_same(self, strip: np.ndarray) -> bool:
        """True iff strip looks identical (within threshold) to prev."""
        if self.prev_strip is None or self.prev_strip.shape != strip.shape:
            return False
        diff = np.abs(strip.astype(np.int16) - self.prev_strip.astype(np.int16)).mean()
        return diff < self.threshold

    def update(self, strip: np.ndarray, text: str, bboxes: list[list[list]]):
        """Cache the just-OCR'd frame for the next comparison."""
        self.prev_strip = strip
        self.prev_text = text
        self.prev_bboxes = bboxes
```

Loading the strip from disk: use OpenCV (`cv2.imread(path, cv2.IMREAD_GRAYSCALE)`) for speed; we already have OpenCV in the Docker image via PaddleOCR's deps — verify it remains after we drop Paddle (`opencv-python-headless` is a likely independent dep of either rapidocr or ffmpeg utils we already use; if it disappears, add it explicitly).

**New unit test**: [tests/test_ocr_frame_diff.py](../../../tests/test_ocr_frame_diff.py):

```python
import numpy as np
from src.transcriber.ocr import _FrameDiffer


def _strip(value: int) -> np.ndarray:
    return np.full((100, 800), value, dtype=np.uint8)


class TestFrameDiffer:
    def test_first_frame_is_never_same(self):
        d = _FrameDiffer(threshold=3.0)
        assert d.is_same(_strip(128)) is False

    def test_identical_frames_are_same(self):
        d = _FrameDiffer(threshold=3.0)
        d.update(_strip(128), "hello", [])
        assert d.is_same(_strip(128)) is True

    def test_50pct_pixel_flip_is_different(self):
        d = _FrameDiffer(threshold=3.0)
        a = _strip(128)
        b = a.copy()
        b[:, :400] = 0  # flip half the pixels to black → mean diff ≈ 64
        d.update(a, "x", [])
        assert d.is_same(b) is False

    def test_tiny_noise_is_same(self):
        d = _FrameDiffer(threshold=3.0)
        a = _strip(128)
        b = a + 1  # mean diff = 1.0 < threshold
        d.update(a, "x", [])
        assert d.is_same(b) is True

    def test_threshold_override(self):
        d = _FrameDiffer(threshold=100.0)  # very permissive
        a = _strip(0)
        b = _strip(64)  # mean diff = 64
        d.update(a, "x", [])
        assert d.is_same(b) is True

    def test_shape_mismatch_is_different(self):
        d = _FrameDiffer(threshold=3.0)
        d.update(np.zeros((100, 800), dtype=np.uint8), "x", [])
        assert d.is_same(np.zeros((50, 800), dtype=np.uint8)) is False
```

**Commit**: `Add _FrameDiffer helper with unit tests`

---

## Step 2 — `_pick_provider()` helper

**File**: [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)

```python
_PROVIDER_PRIORITY = [
    "CUDAExecutionProvider",       # NVIDIA — best perf
    "DmlExecutionProvider",        # Windows GPU (NVIDIA / AMD / Intel)
    "CoreMLExecutionProvider",     # macOS native (unused in Docker)
    "CPUExecutionProvider",        # always available
]


def _pick_provider(override: str = "auto") -> str:
    """Pick the best ONNX Runtime execution provider for this host.

    `override` may be 'auto', 'cpu', 'cuda', 'directml', or 'coreml'.
    Any non-'auto' value returns the corresponding provider name
    unconditionally — caller can validate availability separately.
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
        logger.warning(f"onnxruntime not importable yet ({e}); defaulting to CPU")
        return "CPUExecutionProvider"

    for ep in _PROVIDER_PRIORITY:
        if ep in available:
            return ep
    return "CPUExecutionProvider"
```

**Unit test additions** in [tests/test_ocr.py](../../../tests/test_ocr.py) (create the file):

```python
from unittest.mock import patch
from src.transcriber.ocr import _pick_provider


class TestPickProvider:
    def test_override_cpu(self):
        assert _pick_provider("cpu") == "CPUExecutionProvider"

    def test_override_cuda(self):
        assert _pick_provider("cuda") == "CUDAExecutionProvider"

    def test_auto_picks_cuda_when_available(self):
        with patch("onnxruntime.get_available_providers",
                   return_value=["CUDAExecutionProvider", "CPUExecutionProvider"]):
            assert _pick_provider("auto") == "CUDAExecutionProvider"

    def test_auto_picks_dml_over_cpu(self):
        with patch("onnxruntime.get_available_providers",
                   return_value=["DmlExecutionProvider", "CPUExecutionProvider"]):
            assert _pick_provider("auto") == "DmlExecutionProvider"

    def test_auto_falls_back_to_cpu(self):
        with patch("onnxruntime.get_available_providers",
                   return_value=["CPUExecutionProvider"]):
            assert _pick_provider("auto") == "CPUExecutionProvider"
```

**Commit**: `Add _pick_provider helper with auto-detect`

---

## Step 3 — Swap engine: PaddleOCR → RapidOCR

**File**: [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)

Replace the `_get_ocr` body:

```python
def _get_ocr(self, lang: str = "ch"):
    """Lazy-init RapidOCR engine with the auto-picked execution provider."""
    if self._ocr_engine is None:
        provider = _pick_provider(self.execution_provider)
        logger.info(f"OCR engine: RapidOCR with {provider}")
        from rapidocr_onnxruntime import RapidOCR

        # RapidOCR API: pass providers list; first available wins. Always
        # include CPU as fallback in case the requested provider isn't
        # actually loaded by the installed onnxruntime wheel.
        providers = [provider]
        if provider != "CPUExecutionProvider":
            providers.append("CPUExecutionProvider")

        self._ocr_engine = RapidOCR(
            # Common params; full list:
            # https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr_onnxruntime/config.yaml
            providers=providers,
            # RapidOCR ships PP-OCRv4 by default; v5 is opt-in via config.
            # Stick with v4 in the first commit; v5 toggle is a follow-up.
        )
    return self._ocr_engine
```

> ⚠️ Verify on implementation: RapidOCR's `__init__` signature changed between v1.3 and v1.4. We're pinning `>=1.4.0` in `pyproject.toml`. If the `providers=` kwarg isn't accepted in the installed version, configure via `RapidOCRConfig(...)`.

Drop the `import paddle` and `paddle.set_flags(...)` block entirely.

Initialise `self.execution_provider` in `__init__`:

```python
def __init__(self, ..., execution_provider: str = "auto", ...):
    ...
    self.execution_provider = execution_provider
```

Caller chain: `get_transcriber()` in [src/transcriber/__init__.py](../../../src/transcriber/__init__.py) reads `ocr_config.get("execution_provider", "auto")` and forwards.

**Commit**: `Swap PaddleOCR → RapidOCR; remove Paddle MKL-DNN workaround`

---

## Step 4 — Rewrite `transcribe()` to streaming with frame-diff

**File**: [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)

Replace the two-pass body in `transcribe()` ([ocr.py:137-189](../../../src/transcriber/ocr.py#L137-L189)) with:

```python
# === Single streaming pass ===
self._emit_progress(0.10, "Running OCR (streaming with frame-diff)...")

import cv2

differ = _FrameDiffer(threshold=self.frame_diff_threshold)
ring: list[list[tuple]] = []  # recent detection sets (size capped)
RING_SIZE = 50
watermark_positions: set[int] = set()

frame_texts: list[str] = []
all_subtitle_bboxes: list[list[list]] = []

ocr_calls = 0
ocr_skips = 0

for i, frame_path in enumerate(frames):
    pct = 0.10 + (i / total_frames) * 0.75
    if i % 10 == 0:
        self._emit_progress(
            pct,
            f"Frame {i + 1}/{total_frames} "
            f"(ocr={ocr_calls}, skipped={ocr_skips})"
        )

    strip = cv2.imread(str(frame_path), cv2.IMREAD_GRAYSCALE)

    if self.enable_frame_diff and differ.is_same(strip):
        # Reuse the previous frame's filtered text — saves an OCR call.
        ocr_skips += 1
        frame_texts.append(differ.prev_text)
        if differ.prev_bboxes:
            all_subtitle_bboxes.append(differ.prev_bboxes)
        continue

    # Different from previous → OCR this frame.
    ocr_calls += 1
    result, _elapse = ocr(str(frame_path))  # RapidOCR returns (result, timings)
    detections = self._parse_ocr_result(result)

    # Refresh the rolling watermark index every RING_SIZE OCRs.
    ring.append(detections)
    if len(ring) > RING_SIZE:
        ring.pop(0)
    if ocr_calls % 10 == 0 or i == total_frames - 1:
        watermark_positions = self._build_watermark_positions(
            [(0, d) for d in ring],  # adapter — _build_watermark_positions
            len(ring),                # only needs detections + count
            cropped_height,
        )

    effective_min_y = 0.0 if crop_pct > 0 else self.min_y
    subtitle_text, subtitle_bboxes = self._filter_subtitle_text_with_boxes(
        detections, watermark_positions, cropped_height, cropped_width,
        min_y_override=effective_min_y,
        crop_y_offset=int(frame_height * (1 - crop_pct)) if crop_pct > 0 else 0,
    )
    frame_texts.append(subtitle_text)
    if subtitle_bboxes:
        all_subtitle_bboxes.append(subtitle_bboxes)

    differ.update(strip, subtitle_text, subtitle_bboxes)

logger.info(
    f"OCR: {ocr_calls} engine calls / {ocr_skips} frame-diff skips "
    f"({ocr_skips/(ocr_calls+ocr_skips):.0%} hit rate)"
)
```

Delete the old "two-pass" comment block and the explicit `sample_indices` loop.

**Per-commit verification**: existing tests in [tests/test_transcriber.py](../../../tests/test_transcriber.py) (if present) still pass.

**Commit**: `Streaming single-pass OCR with frame-diff skipping`

---

## Step 5 — Adapt `_parse_ocr_result()` for RapidOCR shape

**File**: [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)

RapidOCR returns `(result, timings)` where `result` is `[[bbox_pts, text, conf], ...]` (or `None` when nothing detected). Add a branch:

```python
@staticmethod
def _parse_ocr_result(result) -> list[tuple]:
    detections = []
    if not result:
        return detections

    # RapidOCR: list of [bbox_pts, text, conf]
    if isinstance(result, list) and len(result) > 0 \
            and isinstance(result[0], list) \
            and len(result[0]) == 3 \
            and isinstance(result[0][1], str):
        for item in result:
            bbox, text, conf = item
            detections.append((bbox, text, float(conf)))
        return detections

    # PaddleOCR v3 (kept as fallback in case we ever flip back) ...
    # PaddleOCR v2 (same) ...
```

Add a unit test asserting the new branch returns the same tuple shape downstream code expects.

**Commit**: `Parse RapidOCR result shape in _parse_ocr_result`

---

## Step 6 — Config + Dependencies + Docker

**[pyproject.toml](../../../pyproject.toml)** — replace the PaddleOCR / paddlepaddle lines:

```toml
# was:
# paddleocr = ">=3.0.0"
# paddlepaddle = ">=3.0.0"
# now:
rapidocr-onnxruntime = ">=1.4.0"
opencv-python-headless = ">=4.8.0"   # explicit, in case rapidocr's pin slips

[project.optional-dependencies]
gpu = ["onnxruntime-gpu>=1.18.0"]
```

**[config/config.example.yaml](../../../config/config.example.yaml)** — under `ocr:`:

```yaml
  enable_frame_diff: true
  frame_diff_threshold: 3.0
  execution_provider: auto
```

**[docker-compose.yml](../../../docker-compose.yml)** — add named volume:

```yaml
volumes:
  - rapidocr_models:/root/.cache/rapidocr   # verify exact path on first run

# bottom of file:
volumes:
  ...
  rapidocr_models:
```

**[Dockerfile](../../../Dockerfile)** — no structural change; the `pip install -e .` line picks up the dep swap from `pyproject.toml`.

**[src/transcriber/__init__.py](../../../src/transcriber/__init__.py)** — forward the new config knobs:

```python
return OCRTranscriber(
    fps=ocr_config.get("fps", 2.0),
    ...
    enable_frame_diff=ocr_config.get("enable_frame_diff", True),
    frame_diff_threshold=ocr_config.get("frame_diff_threshold", 3.0),
    execution_provider=ocr_config.get("execution_provider", "auto"),
)
```

**Commit**: `Swap to rapidocr-onnxruntime in pyproject + add OCR config knobs`

---

## Step 7 — Docs + CHANGELOG

**[CHANGELOG.md](../../../CHANGELOG.md)** under `[Unreleased] / Changed`:

```
- OCR engine swapped from PaddleOCR to RapidOCR (ONNX Runtime, same
  PP-OCRv5 weights). Removes the Paddle 3.x PIR/OneDNN crash workaround
  and the 600 MB PaddlePaddle install. Added frame-diff skipping: each
  frame is compared (mean abs pixel diff over the subtitle strip) to the
  previous one before being sent to OCR; identical-looking frames reuse
  the cached result. Combined effect: ~5-15× wall-time reduction on CPU,
  larger when GPU is available. New ocr.yaml fields: enable_frame_diff,
  frame_diff_threshold, execution_provider.
```

**[DOCKER.md](../../../DOCKER.md)** — add a note under cleanup:

```
The paddleocr_cache volume from earlier builds is now orphaned. To
reclaim ~170 MB:

    docker volume rm douyin-automation_paddleocr_cache

The new model cache is in `rapidocr_models` (~150 MB on first OCR run).
```

And a note for GPU users (Linux + NVIDIA): how to enable the CUDA
provider — install with `pip install -e ".[gpu]"` and run docker with
`--gpus all`.

**Commit**: `CHANGELOG + DOCKER.md: RapidOCR swap, frame-diff, GPU notes`

---

## Step 8 — Rebuild & verify

```bash
# Drop the old image to ensure a clean rebuild (saves the 600 MB).
docker compose down
docker rmi douyin-automation-app:latest

# Rebuild.
DOCKER_BUILDKIT=1 docker compose up -d --build app

# Confirm size reduction.
docker image inspect douyin-automation-app:latest --format '{{.Size}}'
# Expect ~600 MB smaller than before.

# Re-run OCR on the same reference video.
time docker compose exec -T app python -m src transcribe data/raw/7595865200734014772.mp4 --lang zh
# Expect: ≥ 5× faster than the baseline captured in pre-flight.

# A/B SRT diff.
diff /tmp/ocr_baseline_zh.srt data/srt/7595865200734014772_zh.srt | head -50
# Expect: segment count ± 1, timestamps ± 0.5 s.

# Watch the log line that summarises the skip rate.
docker compose logs app | grep "engine calls"
# Expect: 70-90% skip rate.
```

If the skip rate is < 50 %, the diff threshold (default 3.0) is too tight — tune up in `config.yaml`.
If the text overlap is < 90 % vs baseline, the threshold is too permissive — tune down.

---

## Acceptance criteria

- [ ] All new unit tests pass (`pytest tests/test_ocr_frame_diff.py tests/test_ocr.py -v`).
- [ ] Existing test suite still green (`pytest -v`).
- [ ] Docker image size drops by ≥ 400 MB (Paddle gone, RapidOCR + ORT added).
- [ ] Reference-video OCR wall time drops by ≥ 5×.
- [ ] Reference-video SRT segment count matches baseline ± 1.
- [ ] Per-segment text overlap with baseline ≥ 90 % (SequenceMatcher ratio).
- [ ] Skip-rate log shows ≥ 50 % (typically 70–90 %).
- [ ] On a GPU host (if available), wall time drops by ≥ 20× vs original baseline.

## Rollback

If the engine swap causes a regression we can't quickly fix:

```bash
git revert <commits-from-this-branch>
docker compose up -d --build app
```

The branch is small and additive; no irreversible data-format changes.
