# Phase 3 — OCR Subtitle Extraction (Week 3)

## Context

Whisper speech-to-text is inaccurate on Douyin videos due to background noise, music, and multiple speakers. However, Douyin videos already have burned-in Chinese subtitles. Extracting text via OCR from the video frames is far more accurate than transcribing audio.

## Pipeline

```
Video → Extract frames (ffmpeg, 2 FPS) → PaddleOCR on full frame (no pre-crop)
→ Auto-classify text regions (subtitle vs watermark/UI) → Deduplicate → SRT
```

## Key Design: Auto-Detect Subtitle Region

Instead of requiring users to manually draw a crop rectangle, we run PaddleOCR on the **full frame** and auto-classify detected text regions:

**PaddleOCR returns bounding boxes** — for each detected text, we get `(bbox_coords, text, confidence)`. We classify each detection as "subtitle" or "noise" using three heuristics:

1. **Position filter**: Douyin subtitles are consistently in the bottom 20-30% of the frame. Text in the top corners (watermarks, usernames) or edges (UI elements) is filtered out.

2. **Frequency filter**: Real subtitles appear in ~10-50% of frames at similar Y-positions (they change as speech progresses). Watermarks/usernames appear in 90%+ of frames at the exact same position. Text that appears too consistently = watermark.

3. **Size + centering filter**: Subtitles are typically larger, horizontally centered text. Small text in corners = UI noise.

**Workflow**: Auto-detect → show detected region to user for confirmation → allow manual override if wrong. No mandatory region picker step.

## Architecture

Fits into existing `src/transcriber/` module as a new backend:
- `OCRTranscriber(BaseTranscriber)` — same ABC, same segment format `{start, end, text}`
- Selected via factory when user chooses "OCR" method (never auto-selected)
- Uses PaddleOCR (best Chinese accuracy, works macOS + Linux, no GPU required)
- Frame extraction via ffmpeg (no opencv dependency needed)

---

## Task List

### Backend

#### 3.1 Add PaddleOCR dependencies — `pyproject.toml`

Add `paddlepaddle>=2.6.0` and `paddleocr>=2.7.0` to base dependencies. Both work on macOS and Linux without GPU.

**Dependencies**: none.

#### 3.2 Add `extract_frames()` — `src/processor/ffmpeg.py`

```python
def extract_frames(self, video_path: Path, output_dir: Path, fps: float = 2.0) -> list[Path]:
```

- ffmpeg `-vf fps={fps}` to extract JPEG frames
- Output: `frame_%06d.jpg`, return sorted list of paths
- No cropping — full frames for auto-detection

**Dependencies**: none.

#### 3.3 Create `OCRTranscriber` — `src/transcriber/ocr.py`

```python
class OCRTranscriber(BaseTranscriber):
    def __init__(self, fps=2.0, confidence_threshold=0.7, similarity_threshold=0.85): ...
    def transcribe(self, video_path, language="zh", task="transcribe") -> list[dict]: ...
```

Internal pipeline:

1. **Extract frames** via `FFmpegProcessor.extract_frames()` at configured FPS (full frame, no crop)
2. **Lazy-init PaddleOCR** (`lang='ch'` for Chinese, `'en'` for English)
3. **OCR each frame** → collect all `(bbox, text, confidence)` detections
4. **Auto-classify** each detection as subtitle or noise:
   - `_classify_detections(all_detections, frame_count, video_height, video_width) -> list[SubtitleDetection]`
   - Position: keep text in bottom 35% of frame (`bbox_center_y > 0.65 * height`)
   - Frequency: discard text appearing in >80% of frames at same Y-position (±5% tolerance) — it's a watermark
   - Size: discard text smaller than 2% of frame height — too small to be a subtitle
   - Centering: prefer text within middle 80% horizontally (`0.1 * width < bbox_center_x < 0.9 * width`)
5. **Deduplicate** consecutive frames: `SequenceMatcher.ratio() > similarity_threshold` → extend segment end time, else start new
6. **Filter**: min segment duration 0.5s, min confidence threshold
7. **Return** `list[dict]` with `{start, end, text}` — same format as Whisper backends

**Auto-detection helper functions**:

```python
def _is_watermark(bbox_y: float, frame_count: int, appearances: int, total_frames: int) -> bool:
    """Text appearing in >80% of frames at same position = watermark."""
    return appearances / total_frames > 0.80

def _is_subtitle_region(bbox: list, frame_height: int, frame_width: int) -> bool:
    """Text in bottom 35%, horizontally centered, minimum size."""
    center_y = (bbox[0][1] + bbox[2][1]) / 2
    center_x = (bbox[0][0] + bbox[2][0]) / 2
    text_height = abs(bbox[2][1] - bbox[0][1])

    in_bottom = center_y > 0.65 * frame_height
    is_centered = 0.1 * frame_width < center_x < 0.9 * frame_width
    is_readable = text_height > 0.02 * frame_height

    return in_bottom and is_centered and is_readable

def _build_position_index(all_frame_detections: list) -> dict:
    """Group detections by Y-position (±5% tolerance) to identify watermarks."""
    # Returns {y_bucket: {text_hash: frame_count}} for frequency analysis
```

**Two-pass approach**:
- **Pass 1 (sampling)**: OCR a subset of frames (every 5th frame) to build the position index and identify watermark positions
- **Pass 2 (full)**: OCR all frames, skip detections at watermark positions, keep only subtitle-classified text

This is more efficient than OCR-ing every frame twice.

**Dependencies**: 3.1, 3.2.

#### 3.4 Extend transcriber factory — `src/transcriber/__init__.py`

Add `"ocr"` case to `get_transcriber()`. OCR is never auto-selected — always explicit user choice.

**Dependencies**: 3.3.

#### 3.5 OCR config — `config/config.example.yaml`

```yaml
ocr:
  fps: 2.0                          # Frames per second to extract
  confidence_threshold: 0.7         # Minimum PaddleOCR confidence
  similarity_threshold: 0.85        # SequenceMatcher ratio for dedup
  subtitle_region:
    min_y: 0.65                     # Only text below 65% of frame height
    max_watermark_frequency: 0.80   # Text in >80% of frames = watermark
    min_text_height: 0.02           # Min text height as fraction of frame
    horizontal_margin: 0.10         # Ignore text in outer 10% left/right
```

**Dependencies**: none.

---

### API

#### 3.6 Extend API models — `src/api/models.py`

Add to `TranscribeRequest`:
```python
method: str = "audio"              # "audio" (Whisper) or "ocr" (PaddleOCR)
ocr_region: dict | None = None     # Optional manual override: {"x": 0.05, "y": 0.75, "w": 0.90, "h": 0.20}
```

When `ocr_region` is `None` (default), auto-detection is used. When provided, it overrides auto-detection and crops to the specified region.

Backward compatible — existing callers without `method` default to Whisper.

**Dependencies**: none.

#### 3.7 Update router + task manager

- `src/api/routers/transcribe.py`: pass `method` and `ocr_region` to `run_transcribe()`. Add `GET /api/videos/{video_id}/sample-frame?timestamp=1.0` endpoint (returns JPEG for manual override).
- `src/api/task_manager.py`: when `method="ocr"`, route to OCR backend. Progress messages:
  - "Extracting frames..." (0.05)
  - "Analyzing subtitle regions (sampling)..." (0.10)
  - "Running OCR on frame 12/120..." (0.15-0.80)
  - "Deduplicating and generating SRT..." (0.85)
  - "Complete" (1.0)

**Dependencies**: 3.4, 3.6.

---

### UI

#### 3.8 Types + client — `ui-app/src/api/types.ts` + `client.ts`

Add `OcrRegion` type (optional, for manual override). Extend `postTranscribe()` with `method` and optional `ocrRegion` params. Add `getSampleFrame(videoId, timestamp)`.

**Dependencies**: 3.6.

#### 3.9 Update DownloadTranscribe page

- Add method toggle: "Audio (Whisper)" / "OCR (Extract Subtitles)" — segmented control or two buttons
- When OCR selected: just click Transcribe — auto-detection handles the rest (no mandatory region picker)
- **Optional**: "Advanced: Select Region" expandable section with sample frame + draggable rectangle for manual override
- Hide "English (Translate)" language option when OCR is selected (OCR extracts source text only, translation is a separate step)
- OCR-specific progress messages from SSE stream
- After OCR completes: show auto-detected region info ("Detected subtitle area: bottom 22% of frame, filtered 3 watermark regions")

**Dependencies**: 3.8.

---

### Tests

#### 3.10 Unit tests

- `tests/test_transcriber.py`: `TestOCRTranscriber`:
  - Test auto-classification: mock PaddleOCR to return detections at various positions, verify subtitle vs watermark classification
  - Test watermark filtering: text appearing in >80% frames at same Y = filtered
  - Test dedup logic: identical consecutive frames merge, different frames separate
  - Test empty frames close segment, min duration filter
  - Test factory returns correct class, backward compat
- `tests/test_processor.py`: `extract_frames` — mock ffmpeg, test frame count

**Dependencies**: 3.3, 3.4.

---

## Dependency Graph

```
3.1 (deps) → 3.2 (extract_frames) → 3.3 (OCRTranscriber + auto-detect) → 3.4 (factory)
                                           ↓
3.5 (config)                          3.6 (models) → 3.7 (router + task manager)
                                                           ↓
                                                      3.8 (client) → 3.9 (page UI)

3.10 (tests) ← 3.3, 3.4
```

**Recommended sequence**: 3.1+3.5 → 3.2 → 3.3+3.4 → 3.6+3.7 → 3.8+3.9 → 3.10

---

## Verification Checklist

### V3.1: PaddleOCR installed

```bash
python3 -c "from paddleocr import PaddleOCR; print('OK')"
```

### V3.2: Frame extraction works

```bash
python3 -c "
from src.processor.ffmpeg import FFmpegProcessor
from pathlib import Path
import tempfile

proc = FFmpegProcessor()
with tempfile.TemporaryDirectory() as tmpdir:
    frames = proc.extract_frames(Path('data/raw/<id>.mp4'), Path(tmpdir), fps=1.0)
    print(f'Extracted {len(frames)} frames')
"
```

### V3.3: Auto-detection filters watermarks

```bash
# OCR a Douyin video with visible watermark + subtitles
# Verify: watermark text (username, TikTok logo) is NOT in the SRT
# Verify: subtitle text IS in the SRT
```

### V3.4: OCR transcription produces SRT

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "method": "ocr"}'
curl -N http://localhost:8000/api/events/{task_id}
```

**Expected**: SSE shows "Analyzing subtitle regions..." then "Running OCR on frame 12/120...", SRT file created with Chinese text.

### V3.5: Whisper backward compatibility

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>"}'
```

**Expected**: Still uses Whisper (no `method` field defaults to `"audio"`).

### V3.6: Manual region override works

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "method": "ocr", "ocr_region": {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.25}}'
```

**Expected**: OCR only runs on the specified region, ignoring auto-detection.

### V3.7: UI flow

1. Select a video → toggle to "OCR" method
2. Click Transcribe → auto-detection runs (no region picker required)
3. Progress shows "Analyzing subtitle regions..." then per-frame OCR progress
4. SRT preview shows extracted Chinese subtitles
5. (Optional) Expand "Advanced: Select Region" → draw rectangle → re-run OCR on manual region

### V3.8: Unit tests pass

```bash
python3 -m pytest tests/test_transcriber.py tests/test_processor.py -v
```

---

## Edge Cases

1. **No burned-in subtitles**: Auto-detection finds no subtitle-classified text. Return empty segments, warn user: "No subtitles detected — try Audio (Whisper) instead."
2. **PaddleOCR model download**: First run downloads ~150MB. Show progress message.
3. **Subtitle position varies**: Some videos have subtitles at top or middle. Auto-detect may miss them. User can use manual region override. Consider widening `min_y` in config.
4. **Multiple text lines at different positions**: Auto-detect groups by Y-position. If subtitles appear at two Y-levels (e.g., speaker name + dialogue), both are captured.
5. **Watermark overlaps subtitle region**: Frequency filter handles this — watermarks appear in 90%+ frames, subtitles in 10-50%. If a watermark is inside the subtitle area, it's still filtered by frequency.
6. **Fast subtitle changes**: At 2 FPS, minimum 0.5s resolution. Increase FPS in config if needed.
7. **Long videos**: 60s video × 2 FPS = 120 frames. Two-pass approach (sample + full) keeps processing efficient.
8. **Animated/moving subtitles**: Some Douyin videos have subtitles that bounce or animate. Position tolerance (±5% for watermark grouping) handles minor movement. Large movement may cause missed grouping — user can lower `max_watermark_frequency`.
