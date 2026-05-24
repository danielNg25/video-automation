# OCR speedup: RapidOCR + frame-diff + hardware-aware execution provider

**Status:** Approved (brainstorming complete; awaiting plan)
**Owner:** Daniel
**Target file:** [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)
**Date:** 2026-05-19

## Context

OCR is the dominant cost in the pipeline today. A typical 1–2-minute Douyin video takes ~60–180 s of wall time in the transcribe stage; a 10-minute video takes ~10 minutes. The cause is **sequential per-frame PaddleOCR calls** in [src/transcriber/ocr.py](../../../src/transcriber/ocr.py), with two structural multipliers:

1. **Two passes over the frames**: pass 1 samples every 5th frame to build a watermark-Y-position index ([ocr.py:140-156](../../../src/transcriber/ocr.py#L140-L156)); pass 2 OCRs every frame ([ocr.py:158-186](../../../src/transcriber/ocr.py#L158-L186)). For a 60-frame video this is 12 + 60 = 72 OCR calls.
2. **PaddleOCR is forced to CPU + MKL-DNN disabled** ([ocr.py:62](../../../src/transcriber/ocr.py#L62)) because of the Paddle 3.x PIR/OneDNN crash documented in our previous fixes. We have no realistic GPU path on the current stack — Paddle 3.x GPU under Docker amd64 emulation on Apple Silicon is unworkable, and on Windows/Linux the PIR bug still applies.

We want to cut OCR wall time by ~10× without losing accuracy and without changing how the user runs the system (same Docker image, same `docker compose up -d --build`, same `ocr.yaml` config shape).

## Goal

- **Target**: ~5–15 s of wall time for a 1–2-minute video on Apple Silicon (Docker amd64 CPU); ~2–5 s when an NVIDIA GPU is available on a Windows/Linux host.
- **No accuracy regression**: same PP-OCRv5 models, same filtering heuristics, same output SRT format.
- **Same operational surface**: identical Docker run command, same config file shape (with new optional fields), same volume layout.

## Approach

Three layered changes, applied together:

### 1. Engine swap: PaddleOCR → RapidOCR

RapidOCR ([github.com/RapidAI/RapidOCR](https://github.com/RapidAI/RapidOCR)) ships PaddleOCR's PP-OCRv5 detection + recognition models as ONNX, run via ONNX Runtime. Drop-in replacement with the same model weights — therefore the same recognition quality.

Side benefits:
- Kills the Paddle 3.x PIR/OneDNN crash entirely. Removes the `paddle.set_flags({"FLAGS_use_mkldnn": False})` workaround at [ocr.py:62](../../../src/transcriber/ocr.py#L62).
- Removes `paddlepaddle` (~500 MB) and `paddleocr` (~100 MB) from the Docker image.
- Unlocks ONNX Runtime's execution providers (see §3) for hardware acceleration when present.

### 2. Frame-diff skipping

Before each OCR call, compare the **bottom strip of the current frame** to the same strip of the previous frame using mean-absolute-difference over uint8 pixels (cheap, ~1 ms per comparison for a 1080-wide strip).

- If the difference score is **below `frame_diff_threshold`** → skip OCR; reuse the previous frame's filtered subtitle text and bbox for this timestamp.
- Otherwise → OCR this frame, cache its result as the "previous", continue.

Typical Douyin videos repeat each subtitle across 2–5 frames at 1–2 fps (a subtitle stays on screen for 2–5 s). Frame-diff is expected to skip 70–90 % of OCR calls. Hardware-agnostic, stacks multiplicatively with the engine swap.

### 3. Hardware-aware execution provider

ONNX Runtime exposes a list of installed execution providers via `onnxruntime.get_available_providers()`. On `_get_ocr()` init, probe and pick:

| Host | Provider chosen |
|---|---|
| Apple Silicon Mac (Docker amd64 / Rosetta) | `CPUExecutionProvider` |
| Linux + NVIDIA | `CUDAExecutionProvider` |
| Windows + NVIDIA | `CUDAExecutionProvider`, fallback to `DmlExecutionProvider` |
| Windows + AMD / Intel GPU | `DmlExecutionProvider` |
| Anywhere else | `CPUExecutionProvider` |

Config knob `execution_provider: auto | cpu | cuda | directml | coreml` lets the user override the auto-pick.

The same Docker image works on all targets — GPU users just need to pass `--gpus all` to docker (Linux NVIDIA) or use a CUDA-enabled Docker Desktop integration on Windows. We document this; we don't add new Dockerfile stages for GPU images.

## Structural changes — [src/transcriber/ocr.py](../../../src/transcriber/ocr.py)

| Today | After |
|---|---|
| `_get_ocr()` builds `PaddleOCR(...)` after `paddle.set_flags({"FLAGS_use_mkldnn": False})` | `_get_ocr()` builds `RapidOCR(...)` after `_pick_provider()` chooses an execution provider |
| Two passes over frames | Single streaming pass: each frame → frame-diff check → either skip-with-cached-result or OCR-and-cache |
| Watermark Y-positions built upfront from every-5th-frame samples | Watermark Y-positions built incrementally on-the-fly from a rolling ring buffer of recent OCR results (default ring size 50). After the buffer fills, the same `max_watermark_frequency` heuristic applies. |
| `_parse_ocr_result()` handles PaddleOCR v2 + v3 shapes | Add a third branch for RapidOCR's result shape (list of tuples `[(bbox_pts, text, conf), ...]`) |
| `_filter_subtitle_text_with_boxes()` | **Unchanged** — same heuristics, same return shape |
| `_save_ocr_metadata()` | **Unchanged** — same JSON shape (downstream blur code keeps working) |

New small helpers (private to `OCRTranscriber`):

- `_FrameDiffer`:
  - State: `prev_strip: np.ndarray | None`, `prev_text: str`, `prev_bboxes: list[list[list]]`.
  - `is_same(strip: np.ndarray) -> bool`: mean-abs-diff against `prev_strip`; True iff diff < threshold.
  - `update(strip, text, bboxes)`: cache for next comparison.
- `_pick_provider() -> str`: queries `onnxruntime.get_available_providers()` and returns the best per the table above (or honours the user-set `execution_provider` config override). Logs the choice once.
- `_WatermarkBuffer` (or inline as a small deque): ring of last N detection sets; same `Counter`-based consistency check as today, just streamed.

`transcribe()` becomes a single linear loop over frames. The previous two-pass scaffolding is removed.

## Config additions — `config/config.example.yaml` (under `ocr:`)

```yaml
ocr:
  fps: 1
  crop_bottom_pct: 0.3
  # NEW — frame-diff skipping
  enable_frame_diff: true         # set false to force OCR on every frame
  frame_diff_threshold: 3.0       # mean abs pixel diff; 0=identical, higher=more permissive

  # NEW — execution provider auto-detected; override if needed
  execution_provider: auto        # auto | cpu | cuda | directml | coreml
```

All have sensible defaults; existing user `config.yaml` files keep working without edits.

## Dependencies — `pyproject.toml`

- **Add**: `rapidocr-onnxruntime>=1.4.0` (CPU, ~150 MB install with bundled CPU provider).
- **Add** optional extra `[gpu]`: `onnxruntime-gpu` for NVIDIA hosts.
- **Drop**: `paddlepaddle`, `paddleocr` (saves ~600 MB in the image).
- The `Dockerfile` change is just the install line; no new stages or `--platform` changes.

## Migration & cleanup

- Remove `paddle.set_flags(...)` and all Paddle imports from [ocr.py](../../../src/transcriber/ocr.py).
- The existing `paddleocr_cache` Docker volume becomes orphaned. Documented in [DOCKER.md](../../../DOCKER.md) cleanup section; **not auto-deleted** (user opts in with `docker volume rm douyin-automation_paddleocr_cache`).
- New named volume `rapidocr_models` (~150 MB of ONNX weights) added to [docker-compose.yml](../../../docker-compose.yml), mounted to wherever RapidOCR caches models (likely `~/.cache/rapidocr` inside the container — verify during implementation).

## Backwards compatibility

- `_ocr_meta.json` shape unchanged (same `subtitle_region` block).
- SRT format unchanged.
- All existing tests in `tests/test_*` keep passing.

## Testing

**New unit tests** — `tests/test_ocr_frame_diff.py`:
- Synthetic strips: identical → `is_same == True`; 5%-pixel-flipped → `is_same == True`; 50%-pixel-flipped → `is_same == False`.
- Mocked OCR engine: with diff threshold tight, every frame OCRs; with default threshold and a sequence of identical frames, only the first OCRs and subsequent frames reuse the cache. Assert the OCR engine's call count.

**Updated unit tests** — `tests/test_ocr.py` (create if absent):
- `_pick_provider()` returns `'CPUExecutionProvider'` when only CPU is available; returns `'CUDAExecutionProvider'` when CUDA is mock-listed; honours config override.
- `_parse_ocr_result()` adapter for RapidOCR's shape produces the same `(bbox_4pts, text, conf)` tuples downstream code expects.

**Integration smoke** (manual, documented in plan):
- Pick one of the user's existing videos (e.g., `data/raw/7595865200734014772.mp4`).
- Run `transcribe()` on it with the old code (capture SRT + timings) and the new code (same).
- Assert: number of segments matches ± 1; first/last segment timestamps match ± 0.5 s; per-segment text overlap ≥ 90 % via `difflib.SequenceMatcher.ratio()`.
- Wall time should drop ≥ 5× on CPU.

## Out of scope

- **Custom-trained models** for stylised Douyin fonts. We stick with the stock PP-OCRv5 weights RapidOCR ships.
- **GPU passthrough on Apple Silicon Docker**. Docker on Mac can't expose the M-series GPU to the container; Mac runs stay on CPU.
- **Multi-process / multi-GPU parallel OCR**. Single-process + frame-diff + RapidOCR is enough to hit the target without the complexity of process pools, queues, or batching across N images per call.
- **Per-region OCR** (split detection from recognition into separate stages). Possible future win but not needed now.
- **Re-introducing `_redistribute_slots` or any pre-deleted TTS logic**. This spec is OCR-only.

## Critical files

- [src/transcriber/ocr.py](../../../src/transcriber/ocr.py) — rewrite of `transcribe()`, `_get_ocr()`, `_parse_ocr_result()`; new `_FrameDiffer` and `_pick_provider()`; remove Paddle imports / flag-setting.
- [pyproject.toml](../../../pyproject.toml) — swap `paddlepaddle` / `paddleocr` for `rapidocr-onnxruntime`; add `[gpu]` extra.
- [config/config.example.yaml](../../../config/config.example.yaml) — add `enable_frame_diff`, `frame_diff_threshold`, `execution_provider` under `ocr:`.
- [docker-compose.yml](../../../docker-compose.yml) — add `rapidocr_models` named volume.
- [DOCKER.md](../../../DOCKER.md) — note `paddleocr_cache` is orphaned and how to clean it; document GPU options.
- [CHANGELOG.md](../../../CHANGELOG.md) — `[Unreleased] / Changed` entry.
- `tests/test_ocr_frame_diff.py` (new) and `tests/test_ocr.py` (updated or new).

## Verification

1. **Unit tests** (≈1 s): `python -m pytest tests/test_ocr_frame_diff.py tests/test_ocr.py -v`.
2. **Integration smoke** (≈5–15 s on CPU): run `python -m src transcribe data/raw/7595865200734014772.mp4` and assert it completes in single-digit seconds for a short clip; confirm wall time improvement vs a captured pre-change baseline.
3. **A/B segment diff**: produce SRTs with both implementations, compare segment counts and text overlap as described in the testing section.
4. **Docker image size**: `docker image inspect douyin-automation-app:latest --format '{{.Size}}'` should drop by ~600 MB after the dependency swap.
