# Phase 3 — OCR Subtitle Extraction (Week 3)

## Context

Whisper speech-to-text is inaccurate on Douyin videos due to background noise, music, and multiple speakers. However, Douyin videos already have burned-in Chinese subtitles. Extracting text via OCR from the video frames is far more accurate than transcribing audio. The user selects a region on the video where subtitles appear, and the system extracts text from that area.

## Pipeline

```
Video → Extract frames (ffmpeg, 2 FPS) → Crop to user-selected region → PaddleOCR per frame
→ Deduplicate consecutive identical text (SequenceMatcher > 0.85) → Merge into segments → SRT
```

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

Add `paddlepaddle>=2.6.0` and `paddleocr>=2.7.0` to base dependencies.

**Dependencies**: none.

#### 3.2 Add `extract_frames()` — `src/processor/ffmpeg.py`

```python
def extract_frames(self, video_path: Path, output_dir: Path, fps: float = 2.0, crop_region: dict | None = None) -> list[Path]:
```

- ffmpeg `-vf fps={fps}` to extract JPEG frames
- If `crop_region` provided (0-1 ratios: `{x, y, w, h}`), probe dimensions via `get_video_info()`, compute absolute pixels, chain `crop=w:h:x:y` filter
- Output: `frame_%06d.jpg`, return sorted list of paths

**Dependencies**: none.

#### 3.3 Create `OCRTranscriber` — `src/transcriber/ocr.py`

```python
class OCRTranscriber(BaseTranscriber):
    def __init__(self, fps=2.0, confidence_threshold=0.7, similarity_threshold=0.85, ocr_region=None): ...
    def transcribe(self, video_path, language="zh", task="transcribe") -> list[dict]: ...
```

Internal pipeline:
1. Create temp dir, extract frames via `FFmpegProcessor.extract_frames()` with crop region
2. Lazy-init PaddleOCR (`lang='ch'` for Chinese)
3. OCR each frame → `(timestamp, text, confidence)`
4. Deduplicate: `SequenceMatcher.ratio() > similarity_threshold` → extend segment end time, else start new
5. Filter: min segment duration 0.5s, min confidence
6. Return `list[dict]` with `{start, end, text}` — same format as Whisper backends

**Dependencies**: 6.1, 6.2.

#### 3.4 Extend transcriber factory — `src/transcriber/__init__.py`

Add `"ocr"` case to `get_transcriber()`. OCR is never auto-selected — always explicit user choice.

**Dependencies**: 6.3.

#### 3.5 OCR config — `config/config.example.yaml`

```yaml
ocr:
  fps: 2.0
  confidence_threshold: 0.7
  similarity_threshold: 0.85
  default_region:
    x: 0.05    # 5% from left
    y: 0.75    # 75% from top (bottom 25%)
    w: 0.90    # 90% width
    h: 0.20    # 20% height
```

**Dependencies**: none.

---

### API

#### 3.6 Extend API models — `src/api/models.py`

Add to `TranscribeRequest`:
```python
method: str = "audio"              # "audio" (Whisper) or "ocr" (PaddleOCR)
ocr_region: dict | None = None     # {"x": 0.05, "y": 0.75, "w": 0.90, "h": 0.20}
```

Backward compatible — existing callers without `method` default to Whisper.

**Dependencies**: none.

#### 3.7 Update router + task manager

- `src/api/routers/transcribe.py`: pass `method` and `ocr_region` to `run_transcribe()`. Add `GET /api/videos/{video_id}/sample-frame?timestamp=1.0` endpoint (returns JPEG for region picker).
- `src/api/task_manager.py`: when `method="ocr"`, route to OCR backend. Progress: "Extracting frames..." → "Running OCR on frame 12/120..." → "Generating SRT..."

**Dependencies**: 6.4, 6.6.

---

### UI

#### 3.8 Types + client — `ui-app/src/api/types.ts` + `client.ts`

Add `OcrRegion` type. Extend `postTranscribe()` with `method` and `ocrRegion` params. Add `getSampleFrame(videoId, timestamp)`.

**Dependencies**: 6.6.

#### 3.9 Region picker — `ui-app/src/components/OcrRegionPicker.tsx`

- Displays sample frame image (from `GET /api/videos/{id}/sample-frame`)
- Draggable/resizable rectangle overlay (default: bottom 20%)
- Emits `onChange(region: OcrRegion)` with 0-1 percentage coordinates
- "Reset to Default" button for standard Douyin subtitle position

**Dependencies**: 6.8.

#### 3.10 Update DownloadTranscribe page

- Add method toggle: "Audio (Whisper)" / "OCR (Extract Subtitles)"
- When OCR selected: show `OcrRegionPicker`, hide "English (Translate)" language option
- Update `handleTranscribe()` to pass method + region
- OCR-specific progress messages from SSE stream

**Dependencies**: 6.8, 6.9.

---

### Tests

#### 3.11 Unit tests

- `tests/test_transcriber.py`: `TestOCRTranscriber` — mock PaddleOCR, test dedup logic, factory selection, backward compat
- `tests/test_processor.py`: `extract_frames` — mock ffmpeg, test frame count, crop region computation

**Dependencies**: 6.3, 6.4.

---

## Dependency Graph

```
6.1 (deps) → 6.2 (extract_frames) → 6.3 (OCRTranscriber) → 6.4 (factory)
                                           ↓
6.5 (config)                          6.6 (models) → 6.7 (router + task manager)
                                                           ↓
                                                      6.8 (client) → 6.9 (region picker) → 6.10 (page UI)

6.11 (tests) ← 6.3, 6.4
```

**Recommended sequence**: 6.1+6.5 → 6.2 → 6.3+6.4 → 6.6+6.7 → 6.8+6.9+6.10 → 6.11

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

### V3.3: OCR transcription produces SRT

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "method": "ocr"}'
# Subscribe SSE:
curl -N http://localhost:8000/api/events/{task_id}
```

**Expected**: SSE shows "Running OCR on frame 12/120...", SRT file created with Chinese text.

### V3.4: Whisper backward compatibility

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>"}'
```

**Expected**: Still uses Whisper (no `method` field defaults to `"audio"`).

### V3.5: Sample frame endpoint

```bash
curl -o frame.jpg http://localhost:8000/api/videos/<id>/sample-frame?timestamp=2.0
```

**Expected**: Valid JPEG image.

### V3.6: Region picker UI

1. Select a video → toggle to "OCR" method
2. See sample frame with rectangle overlay at bottom 20%
3. Drag/resize the rectangle → coordinates update
4. Click Transcribe → OCR runs on selected region only

### V3.7: OCR accuracy

Compare OCR-extracted SRT with the visible burned-in subtitles. Chinese text should match with high accuracy.

### V3.8: Unit tests pass

```bash
python3 -m pytest tests/test_transcriber.py tests/test_processor.py -v
```

---

## Edge Cases

1. **No burned-in subtitles**: OCR returns empty segments. Warn user: "No text detected — try Audio (Whisper) instead."
2. **PaddleOCR model download**: First run downloads ~150MB. Show progress message.
3. **Subtitle position varies**: Some videos have subtitles at top or middle. Region picker handles this.
4. **OCR noise from watermarks/logos**: Confidence threshold (0.7) filters most noise. Region cropping avoids logo areas.
5. **Fast subtitle changes**: At 2 FPS, minimum 0.5s resolution. Increase FPS in config if needed.
6. **Long videos**: 60s video × 2 FPS = 120 frames. ~30-60s processing on CPU. SSE shows per-frame progress.
7. **Vietnamese/English burned-in subs**: PaddleOCR supports `lang='en'` for Latin-script subtitles if needed.
