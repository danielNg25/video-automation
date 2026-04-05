# Phase 6 — Subtitle Replacement (Blur + Reposition)

## Context

Douyin videos have burned-in Chinese subtitles. When we add translated subtitles (English/Vietnamese), the original Chinese text is still visible underneath. This phase:

1. **Detects** the original subtitle region using OCR bounding boxes (from Phase 3)
2. **Blurs/covers** that region to hide the original Chinese text
3. **Repositions** the new translated subtitle to match the same location and height

This produces a clean result where the translated subtitle appears exactly where the original was, with no Chinese text bleeding through.

## Pipeline Position

```
Download → Transcribe/OCR → Translate → TTS → [Subtitle Replacement] → Process → Upload
```

This runs before the final burn-in (Phase 2 Process). The blur is applied as an ffmpeg video filter, and the new subtitle position/size is derived from the detected original region.

## Architecture

- **OCR region data**: Phase 3 OCR already detects text bounding boxes per frame. We reuse this data to identify where original subtitles are.
- **Blur filter**: ffmpeg `boxblur` or `avgblur` applied to a crop region per frame
- **Subtitle repositioning**: Auto-set `margin_v`, `margin_h`, and `font_size` in ASS style based on detected region dimensions
- **Two modes**: auto (uses OCR bounding boxes) or manual (user draws region on a frame)

---

## Task List

### Backend

#### 6.1 Subtitle region detector — `src/processor/region_detector.py`

Analyzes OCR results to determine the consistent subtitle region across frames.

```python
class SubtitleRegionDetector:
    def detect_region(
        self,
        ocr_results: list[dict],  # from Phase 3 OCR: [{frame, boxes: [{text, bbox, confidence}]}]
        video_width: int,
        video_height: int,
    ) -> SubtitleRegion:
        """Detect the subtitle region from OCR bounding boxes."""
```

**Algorithm:**
1. Collect all OCR bounding boxes classified as "subtitle" (from Phase 3 auto-detect: bottom 35%, frequency <80%)
2. Compute the bounding rectangle that encompasses all subtitle text across frames
3. Add padding (10px each side) for clean blur coverage
4. Return `SubtitleRegion(x, y, width, height)` in pixel coordinates

```python
@dataclass
class SubtitleRegion:
    x: int       # left edge
    y: int       # top edge
    width: int   # region width
    height: int  # region height

    @property
    def center_x(self) -> int: ...
    @property
    def center_y(self) -> int: ...
    @property
    def bottom(self) -> int: ...
```

**Dependencies**: Phase 3 OCR data (stored in `data/srt/{video_id}_ocr_meta.json`).

#### 6.2 Blur filter in ffmpeg — `src/processor/ffmpeg.py`

Add method to apply blur over a specific region:

```python
def apply_region_blur(
    self,
    video_path: Path,
    region: SubtitleRegion,
    output_path: Path,
    blur_strength: int = 15,    # boxblur kernel size
    blur_mode: str = "blur",    # "blur" | "fill" (solid color) | "pixelate"
) -> Path:
    """Apply blur/fill over a region to hide original subtitles."""
```

**ffmpeg filter for region blur:**
```bash
# Crop the region, blur it, overlay it back at the same position
ffmpeg -i video.mp4 -filter_complex \
  "[0:v]crop={w}:{h}:{x}:{y},boxblur={strength}[blur]; \
   [0:v][blur]overlay={x}:{y}[out]" \
  -map "[out]" -map 0:a -c:a copy output.mp4
```

**Alternative modes:**
- `blur`: Gaussian/box blur (default, natural look)
- `fill`: Solid color rectangle (black/matching background)
- `pixelate`: Mosaic effect (`scale=iw/10:ih/10,scale=iw:ih:flags=neighbor`)

**Dependencies**: 6.1.

#### 6.3 Subtitle style matcher — `src/processor/style_matcher.py`

Derives subtitle styling from the detected region so the new subtitle matches the original's position and size.

```python
class SubtitleStyleMatcher:
    def match_style(
        self,
        region: SubtitleRegion,
        video_width: int,
        video_height: int,
        base_style: dict,     # from config/subtitle_styles.yaml
    ) -> dict:
        """Derive ASS style params that position new subtitle in the original's location."""
```

**Calculations:**
- `margin_v`: distance from bottom = `video_height - region.bottom + padding`
- `margin_h`: offset from center = `region.center_x - video_width // 2`
- `font_size`: estimate from region height. If region height ~50px at 1080p, font_size ≈ 24
- `alignment`: if region is centered (center_x within 10% of video center) → alignment 2 (bottom-center). If left-aligned → 1. If top → 8.

Returns a style dict that can be merged with the base style for `srt_to_ass()`.

**Dependencies**: 6.1.

#### 6.4 Combined blur + burn pipeline — `src/processor/ffmpeg.py`

Add method that combines blur + subtitle burn in a single ffmpeg pass:

```python
def blur_and_burn_subtitles(
    self,
    video_path: Path,
    subtitle_path: Path,
    region: SubtitleRegion,
    output_path: Path,
    blur_strength: int = 15,
    blur_mode: str = "blur",
    style: dict | None = None,
) -> Path:
    """Single-pass: blur original subtitle region + burn new subtitle."""
```

**ffmpeg filter chain:**
```bash
ffmpeg -i video.mp4 -filter_complex \
  "[0:v]crop={w}:{h}:{x}:{y},boxblur={strength}[blur]; \
   [0:v][blur]overlay={x}:{y},subtitles={srt}:force_style='{style}'[out]" \
  -map "[out]" -map 0:a output.mp4
```

This avoids double-encoding (blur → save → burn → save).

**Dependencies**: 6.2, 6.3.

#### 6.5 Update batch processor — `src/processor/__init__.py`

Extend `process_for_all_platforms` to accept optional `subtitle_region` and `blur_settings`:

```python
subtitle_region: SubtitleRegion | None = None,
blur_settings: dict | None = None,  # {blur_strength, blur_mode}
```

When region is provided, use `blur_and_burn_subtitles` instead of `burn_and_reformat`. When combined with TTS audio, use a new combined method that does blur + burn + audio mix in one pass.

**Dependencies**: 6.4.

#### 6.6 OCR metadata persistence — `src/transcriber/ocr.py` update

Ensure Phase 3 OCR saves bounding box metadata to `data/srt/{video_id}_ocr_meta.json`:

```json
{
  "video_id": "abc123",
  "video_width": 1080,
  "video_height": 1920,
  "subtitle_region": {"x": 90, "y": 1550, "width": 900, "height": 80},
  "watermark_regions": [{"x": 20, "y": 30, "width": 200, "height": 40}],
  "frames_analyzed": 120,
  "confidence": 0.95
}
```

If OCR metadata doesn't exist (video was transcribed via Whisper, not OCR), the region detector returns `None` and blur is skipped.

**Dependencies**: Phase 3 OCR module.

#### 6.7 Unit tests — `tests/test_subtitle_replacement.py`

Test cases:
- Region detector: given OCR boxes, correctly computes bounding region
- Style matcher: region → correct margin_v, font_size, alignment
- Blur ffmpeg command: verify filter_complex string is correct
- Combined blur + burn command: verify single-pass filter chain
- Edge cases: no OCR data → skip blur, very small region → minimum size

**Dependencies**: 6.1-6.5.

---

### API

#### 6.8 Subtitle replacement models — `src/api/models.py`

```python
class SubtitleRegionResponse(BaseModel):
    x: int
    y: int
    width: int
    height: int
    confidence: float

class BlurSettings(BaseModel):
    enabled: bool = True
    strength: int = 15         # blur kernel size
    mode: str = "blur"         # "blur" | "fill" | "pixelate"
    fill_color: str = "#000000"  # only used when mode="fill"

class SubtitleReplacementRequest(BaseModel):
    video_id: str
    language: str = "en"
    blur_settings: BlurSettings = BlurSettings()
    manual_region: SubtitleRegionResponse | None = None  # override auto-detect
    auto_match_style: bool = True  # derive font size/position from original
```

**Dependencies**: none.

#### 6.9 Subtitle replacement router — `src/api/routers/replacement.py`

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/videos/{video_id}/subtitle-region` | Get auto-detected region (from OCR metadata) |
| `POST` | `/api/videos/{video_id}/subtitle-region` | Set manual region override |
| `POST` | `/api/videos/{video_id}/preview-blur` | Preview: render single frame with blur applied → JPEG |
| `POST` | `/api/process-with-replacement` | Full process: blur + burn + reformat → `{task_id}` |

**Preview blur endpoint:** Takes timestamp + region + blur_settings, renders a single frame showing the blur result. Lets user verify the blur coverage before full processing.

**Dependencies**: 6.1, 6.2, 6.8.

#### 6.10 Register router + update process flow

- `src/api/__init__.py`: register replacement router
- `src/api/routers/process.py`: add `blur_settings` and `subtitle_region` to `ProcessRequest`
- `src/api/task_manager.py`: update `run_process` to handle blur when region is available

**Dependencies**: 6.9.

---

### UI

#### 6.11 TypeScript types — `ui-app/src/api/types.ts`

`SubtitleRegion`, `BlurSettings`, `SubtitleReplacementRequest`.

**Dependencies**: none.

#### 6.12 API client functions — `ui-app/src/api/client.ts`

`getSubtitleRegion`, `setSubtitleRegion`, `postPreviewBlur`, `postProcessWithReplacement`.

**Dependencies**: 6.11.

#### 6.13 Region selector component — `ui-app/src/components/editor/RegionSelector.tsx`

Interactive component to view and adjust the subtitle region on a video frame:

- Shows a video frame (thumbnail or specific timestamp) as background
- Auto-detected region drawn as a dashed rectangle overlay
- User can drag edges to resize or drag the whole region to reposition
- "Auto-detect" button to reset to OCR-detected region
- Coordinates display: `x: 90, y: 1550, w: 900, h: 80`

**Implementation**: Similar to Timeline drag logic (F6 in subtitle editor plan) — mouse handlers on SVG/div overlay.

**Dependencies**: 6.12.

#### 6.14 Blur preview component — `ui-app/src/components/editor/BlurPreview.tsx`

Shows before/after comparison:
- Left: original frame (with Chinese subtitles visible)
- Right: blurred frame (Chinese subtitles hidden)
- Blur mode selector: blur / fill / pixelate
- Blur strength slider (5-30)
- "Refresh Preview" button to re-render

Uses `POST /api/videos/{video_id}/preview-blur` to get the blurred frame as JPEG.

**Dependencies**: 6.12.

#### 6.15 Subtitle replacement section on Process page — `ui-app/src/pages/SubtitleProcess.tsx`

Add collapsible "Original Subtitle Removal" section (before existing platform selector):

1. **Auto-detect status**: "Subtitle region detected" (green) or "No OCR data — blur disabled" (gray)
2. **Region preview**: embedded RegionSelector showing detected/manual region
3. **Blur controls**: mode dropdown + strength slider
4. **Before/after preview**: BlurPreview component
5. **Style match toggle**: "Match new subtitle to original position" — auto-adjusts font_size and margins
6. **Override position**: manual margin_v / margin_h / font_size inputs (shown when style match is off)

When user clicks Process, the blur settings are sent along with the existing process request.

**Dependencies**: 6.13, 6.14.

---

## Dependency Graph

```
Level 0 (parallel):  6.1, 6.6, 6.8, 6.11

Level 1:  6.2, 6.3 (←6.1)  |  6.12 (←6.11)

Level 2:  6.4 (←6.2, 6.3)  |  6.9 (←6.1, 6.2, 6.8)  |  6.13, 6.14 (←6.12)

Level 3:  6.5 (←6.4)  |  6.10 (←6.9)  |  6.15 (←6.13, 6.14)

Level 4:  6.7 (←6.1-6.5)
```

**Recommended sequence**: 6.1+6.6+6.8 → 6.2+6.3 → 6.4+6.5 → 6.9+6.10 → 6.11+6.12 → 6.13+6.14+6.15 → 6.7

---

## Verification Checklist

### V6.1: Region auto-detection
```bash
curl http://localhost:8000/api/videos/{id}/subtitle-region
```
**Expected**: Returns `{x, y, width, height, confidence}` from OCR metadata.

### V6.2: Blur preview
```bash
curl -X POST http://localhost:8000/api/videos/{id}/preview-blur \
  -d '{"timestamp": 5.0, "blur_settings": {"strength": 15, "mode": "blur"}}' \
  --output preview.jpg
```
**Expected**: JPEG shows the original subtitle area blurred out.

### V6.3: Three blur modes work
Test `blur`, `fill`, and `pixelate` modes — each produces visually distinct output.

### V6.4: Style matching
When `auto_match_style` is true, the new subtitle appears at the same vertical position and approximate font size as the original.

### V6.5: Single-pass processing
Processing with blur enabled produces one ffmpeg call (not two separate encode passes). Verify via log output.

### V6.6: Blur + TTS combined
Process with both blur and TTS enabled → output has: blurred original subs, new translated subs, dubbed audio.

### V6.7: No OCR data graceful fallback
For videos transcribed via Whisper (no OCR metadata), `GET /subtitle-region` returns 404. Process works normally without blur.

### V6.8: Manual region override
User draws custom region in UI → `POST /subtitle-region` → subsequent processing uses manual region instead of auto-detected.

### V6.9: UI flow
1. Open Process page → "Original Subtitle Removal" section shows auto-detected region
2. Adjust blur strength → click "Refresh Preview" → before/after shows updated blur
3. Toggle style match → new subtitle position adjusts
4. Process video → output has clean replacement

### V6.10: Unit tests pass
```bash
python3 -m pytest tests/test_subtitle_replacement.py -v
```

---

## Edge Cases

1. **No subtitles detected**: Some Douyin videos don't have burned-in subs. OCR metadata shows no subtitle region → blur section disabled in UI.
2. **Moving subtitle position**: Some videos have subtitles that move between top and bottom. Region detector should compute the union of all positions, or detect multiple regions.
3. **Subtitle region overlaps with content**: If the subtitle area contains important visual content, blurring may remove it. The fill mode with a semi-transparent color is gentler.
4. **Very small or very large region**: Clamp region to reasonable bounds (min 50px height, max 40% of frame height).
5. **Different subtitle positions per segment**: If the video switches between bottom and top subtitles, the region detector should return the most frequent position (bottom), with a confidence score.
