# Subtitle Editor — Implementation Plan

## Context

After transcription (Phase 1) and before burn-in (Phase 2), users need to review and edit subtitles. Currently the SRT preview is read-only. We need a real-time subtitle editor page that lets users: play the video with live subtitle overlay, edit text and timing inline, visually adjust timing on a timeline, configure background color and pixel-level positioning, then save back to SRT and preview the burn-in result.

## What Exists (Reuse)

- `GET /api/videos/{video_id}/srt?language=en` — returns parsed segments
- `src/processor/subtitle.py`: `parse_srt()`, `_seconds_to_srt_timestamp()`, `_timestamp_to_seconds()`, `srt_to_ass()`
- `src/processor/ffmpeg.py`: `burn_subtitles()`, `get_video_info()`
- `src/api/task_manager.py`: background tasks + SSE streaming
- `src/api/models.py`: `SubtitleSegment(id, startTime, endTime, text, translation)`
- `ui-app/src/api/types.ts`: `SubtitleSegment`, `SrtResponse` types
- `SubtitleProcess.tsx` lines 259-353: style controls (font, size, outline, margin, position grid)

## What's Missing (Build)

- **No save endpoint** — cannot write edited SRT back to disk
- **No video player with custom controls** — only native `<video>` without sync
- **No subtitle overlay on video** — only separate text list
- **No timeline component** — no visual timing editor
- **No background color** in style config
- **No horizontal margin / pixel position** control

---

## Task List

### Backend

#### B1. `write_srt()` — `src/processor/subtitle.py`

Add inverse of `parse_srt()`:
```python
def write_srt(segments: list[dict], output_path: Path) -> Path:
    # segments: [{index, start (float sec), end (float sec), text}, ...]
    # Renumbers sequentially, formats timestamps, writes standard SRT
```
Uses existing `_seconds_to_srt_timestamp()`. Dependencies: none.

#### B2. Pydantic models — `src/api/models.py`

Add:
```python
class SaveSrtRequest(BaseModel):
    language: str
    segments: list[SubtitleSegment]

class PreviewFrameRequest(BaseModel):
    language: str = "en"
    timestamp: float = 0.0
    subtitle_style: dict | None = None

class PreviewClipRequest(BaseModel):
    language: str = "en"
    start: float = 0.0
    duration: float = 10.0
    subtitle_style: dict | None = None
```
Dependencies: none.

#### B3. Editor router — `src/api/routers/editor.py`

3 endpoints:

| Method | Path | Purpose |
|--------|------|---------|
| `PUT` | `/api/videos/{video_id}/srt` | Save edited segments → writes SRT to disk |
| `POST` | `/api/videos/{video_id}/preview-frame` | Render single frame with burned subtitle → returns JPEG |
| `POST` | `/api/videos/{video_id}/preview-clip` | Render 5-10s clip with burned subtitle → background task + SSE |

**Save endpoint**: converts `SubtitleSegment[]` timestamps → seconds → calls `write_srt()` → returns updated `SrtResponse`.

**Preview frame**: `ffmpeg -ss {ts} -i {video} -vf "subtitles={srt}:force_style='{style}'" -frames:v 1 -q:v 2 {out.jpg}` — returns JPEG, takes 1-3s.

**Preview clip**: reuses `FFmpegProcessor.burn_subtitles()` with `-ss` and `-t` flags, runs as background task.

Dependencies: B1, B2.

#### B4. Register router — `src/api/__init__.py`

Add `from src.api.routers import editor` + `app.include_router(editor.router)`. Dependencies: B3.

#### B5. Extend subtitle style — `config/subtitle_styles.yaml` + `src/processor/subtitle.py` + `src/processor/ffmpeg.py`

Add to style config:
```yaml
background_color: ""      # empty = transparent, e.g. "&H80000000" for semi-transparent black
background_opacity: 0     # 0-255 (ASS BackColour alpha)
margin_h: 0               # horizontal offset in pixels
```

Update `srt_to_ass()`: map `background_color` → ASS `BackColour`, set `BorderStyle=3` (opaque box) when background is set.
Update `_build_style_string()`: map `background_color` → `BackColour`, `margin_h` → `MarginL`/`MarginR`.

Dependencies: none.

---

### Frontend

#### F1. SRT timestamp utilities — `ui-app/src/utils/srtTime.ts`

```typescript
export function srtTimestampToSeconds(ts: string): number;     // "HH:MM:SS,mmm" → float
export function secondsToSrtTimestamp(seconds: number): string; // float → "HH:MM:SS,mmm"
export function formatDisplayTime(seconds: number): string;     // float → "MM:SS.m"
```

Dependencies: none.

#### F2. `useVideoPlayer` hook — `ui-app/src/hooks/useVideoPlayer.ts`

Encapsulates HTML5 `<video>` control:
- State: `isPlaying`, `currentTime` (60fps via requestAnimationFrame), `duration`, `playbackRate`
- Methods: `play()`, `pause()`, `togglePlay()`, `seek(time)`, `stepFrame(±1)`, `setPlaybackRate(rate)`
- Input: `React.RefObject<HTMLVideoElement>`

Dependencies: none.

#### F3. `VideoPlayer` component — `ui-app/src/components/editor/VideoPlayer.tsx`

Video element + custom controls bar:
- Play/pause button, current time / duration display
- Seek bar (styled range input)
- Playback speed selector (0.25x–2x)
- Volume control
- Accepts `children` prop for subtitle overlay
- Dark background, controls at bottom with backdrop blur

Dependencies: F2.

#### F4. `SubtitleOverlay` component — `ui-app/src/components/editor/SubtitleOverlay.tsx`

CSS-positioned div over `<video>` showing active subtitle:
- Finds active segment via binary search on `currentTime`
- Styled with: font, size, color, outline (text-stroke), shadow, **background color + opacity** (rgba box behind text)
- Positioned with `marginV` (bottom offset) and `marginH` (horizontal offset)
- **Drag-to-reposition**: mousedown on subtitle text → track delta → call `onDragPosition(marginH, marginV)`
- Constrained within video bounds

Dependencies: F1 (for `srtTimestampToSeconds`).

#### F5. `SegmentList` component — `ui-app/src/components/editor/SegmentList.tsx`

Editable scrollable list of subtitle segments:
- Each row: segment number, start/end time inputs (monospace, validated), text textarea (auto-resize)
- Action buttons on hover: split, merge with next, delete
- "+" button to add segment after current
- Active segment highlighted + auto-scrolled into view
- Click segment → seeks video to that time
- Timestamp validation on blur (format, start < end)

Split: at current playback time, divides text at nearest word boundary.
Merge: combines text with next segment, extends end time, removes next.

Dependencies: F1.

#### F6. `Timeline` component — `ui-app/src/components/editor/Timeline.tsx`

SVG-based visual timeline:
- Segments as colored rectangles on time axis
- Red playhead line at `currentTime`
- Time tick marks with labels
- **Draggable segment edges**: mousedown on left/right handle → drag → updates start/end time
- Click empty area → seeks video
- Clamping: start ≥ 0, start < end - 0.1s, end ≤ next segment start (or duration)
- Active segment highlighted in primary color

Dependencies: F1.

#### F7. `StylePanel` component — `ui-app/src/components/editor/StylePanel.tsx`

Extended from existing SubtitleProcess style controls:
- **Existing**: font selector, font size slider, outline width, vertical margin, shadow toggle, bold toggle, position grid
- **New**: background color picker (`<input type="color">`), background opacity slider (0-100%), horizontal margin slider (-200 to +200px)
- Coordinate display: `X: +12px  Y: -30px`

Dependencies: none.

#### F8. `SubtitleEditor` page — `ui-app/src/pages/SubtitleEditor.tsx`

Main page orchestrating all components. Route: `/editor/:videoId?lang=en`

**Layout** (3-panel):
```
┌─────────────────────────────────────────────────┐
│ TopBar: breadcrumb "Subtitle Editor"            │
├─────────────────────────┬───────────────────────┤
│ Video Player (60%)      │ Tabs: Segments|Style  │
│ ┌─────────────────────┐ │ ┌───────────────────┐ │
│ │ <video> + subtitle  │ │ │ Editable segment  │ │
│ │ overlay             │ │ │ list OR style     │ │
│ │                     │ │ │ panel             │ │
│ └─────────────────────┘ │ │                   │ │
│ ┌─────────────────────┐ │ │                   │ │
│ │ SVG Timeline        │ │ └───────────────────┘ │
│ └─────────────────────┘ │ [Save] [Preview Burn] │
├─────────────────────────┴───────────────────────┤
```

**State**: segments (editable copy), originalSegments (for dirty detection), style, player hook.

**Handlers**: segment update/delete/split/merge/add, timeline resize, overlay drag, save, preview burn-in.

**Keyboard shortcuts**:
- `Space` / `K` — play/pause
- `J` — rewind 5s
- `L` — forward 5s
- `←` / `→` — step ±1 frame (1/30s)
- `Ctrl+S` / `Cmd+S` — save (prevent default)

**Save**: calls `PUT /api/videos/{videoId}/srt`, resets dirty state, shows "Saved" indicator.

**Preview burn-in**: calls `POST /api/videos/{videoId}/preview-clip`, subscribes SSE, shows result in modal player.

Dependencies: F1-F7, B3 (API endpoints).

#### F9. Register route — `ui-app/src/App.tsx`

```typescript
<Route path="/editor/:videoId" element={<SubtitleEditorPage />} />
```

Dependencies: F8.

#### F10. "Edit Subtitles" entry point — `ui-app/src/pages/DownloadTranscribe.tsx`

Add button on video result card (next to Transcribe button):
```tsx
<button onClick={() => navigate(`/editor/${videoId}?lang=${lang}`)}>
  Edit Subtitles
</button>
```
Only shown when video has SRT files.

Dependencies: F9.

---

## Dependency Graph

```
Level 0 (parallel):  B1, B2, B5, F1, F2, F4, F5, F6, F7

Level 1:  B3 (←B1,B2)  |  F3 (←F2)

Level 2:  B4 (←B3)  |  F8 (←F1-F7, B3)

Level 3:  F9 (←F8)  |  F10 (←F9)
```

**Recommended sequence**: B1+B2+B5 → B3+B4 → F1+F2 → F3+F4+F5+F6+F7 (parallel) → F8 → F9+F10

---

## New Files

| File | Lines (est.) | Purpose |
|------|-------------|---------|
| `src/api/routers/editor.py` | ~100 | Save SRT, preview frame, preview clip endpoints |
| `ui-app/src/pages/SubtitleEditor.tsx` | ~400 | Main editor page |
| `ui-app/src/hooks/useVideoPlayer.ts` | ~80 | Video player state hook |
| `ui-app/src/components/editor/VideoPlayer.tsx` | ~150 | Player + custom controls |
| `ui-app/src/components/editor/SubtitleOverlay.tsx` | ~120 | Live subtitle on video |
| `ui-app/src/components/editor/SegmentList.tsx` | ~200 | Editable segment list |
| `ui-app/src/components/editor/Timeline.tsx` | ~180 | SVG timeline with drag |
| `ui-app/src/components/editor/StylePanel.tsx` | ~160 | Extended style controls |
| `ui-app/src/utils/srtTime.ts` | ~30 | Timestamp parsing utils |

## Modified Files

| File | Change |
|------|--------|
| `src/processor/subtitle.py` | Add `write_srt()` |
| `src/processor/ffmpeg.py` | Add `BackColour`, `MarginL/R` to style string |
| `src/api/models.py` | Add `SaveSrtRequest`, `PreviewFrameRequest`, `PreviewClipRequest` |
| `src/api/__init__.py` | Register editor router |
| `config/subtitle_styles.yaml` | Add `background_color`, `background_opacity`, `margin_h` |
| `ui-app/src/api/client.ts` | Add `putSrt`, `postPreviewFrame`, `postPreviewClip` |
| `ui-app/src/api/types.ts` | Add request types |
| `ui-app/src/App.tsx` | Add `/editor/:videoId` route |
| `ui-app/src/pages/DownloadTranscribe.tsx` | Add "Edit Subtitles" button |

---

## Verification Checklist

1. Download + transcribe a video → SRT exists
2. Click "Edit Subtitles" → navigates to `/editor/{videoId}?lang=zh`
3. Video plays with subtitle overlay synced to playback
4. Edit segment text inline → dirty indicator appears
5. Drag segment edge on timeline → timing updates in list + overlay reflects change
6. Set background color to semi-transparent black → subtitle shows background box
7. Drag subtitle text on video → marginH/marginV update in style panel
8. Click Save → `PUT /api/videos/{id}/srt` → re-fetch confirms changes persisted
9. Click "Preview Burn-in" → short clip renders via SSE → modal shows result with burned subtitles
10. Go to Process page → burn-in uses the edited SRT
