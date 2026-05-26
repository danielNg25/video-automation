# Subtitle Style — Canonical Spec & Unified Renderers

**Status:** Design  
**Date:** 2026-05-26  
**Owner:** Daniel

## Problem

The subtitle style system has accreted three parallel rendering paths and an inconsistent persistence model. Symptoms we've hit recently:

- Yellow background renders as black in the export. Root cause: the FE save payload didn't include `background_color` at all.
- "Turn blur off" is silently ignored. Root cause: blur fields are never persisted from the FE; the BE defaults `blur_enabled` to `True`.
- Editor preview opacity looks different from the exported file. Root cause: `_build_style_string` treats opacity as raw 0–255, `generate_subtitle_background_images` treats it as 0–100 percent.
- `margin_v: 393` lands at a different relative position when source and output dims differ. Root cause: the editor's HTML overlay assumes a hardcoded 1920px canvas, the export uses output dims, and there's no shared scaling convention.
- Editing the global YAML default has no effect on a video that already has a per-video style JSON. Root cause: per-video JSON fully *replaces* the global default rather than merging.

Each fix has been a one-line patch that addresses the bug-of-the-day without touching the structural mess. This spec is the structural fix.

## Goals

1. **One schema** for every consumer (FE state, FE save payload, BE storage, BE renderer inputs).
2. **One renderer per surface** (HTML overlay, ffmpeg burn-in) — both consume the same schema deterministically.
3. **One loader** — `load_style(video_id)` is the only entry point. No more duplicated `_load_video_style` impls in `process.py` and `editor.py`.
4. **No silent field drops.** Every field the user can set in the FE flows through save → load → render with the same value.
5. **Resolution-independent storage.** Same spec produces visually-equivalent output at any (vertical) resolution the source/export uses.

## Non-goals

- Aspect-flip support (vertical source → horizontal export). All Douyin → all socials are vertical-to-vertical.
- Pixel-perfect agreement between HTML overlay and ffmpeg-rendered frames. The HTML overlay is the "fast positional preview"; the existing **Preview Frame / Preview Clip** ffmpeg buttons remain the trusted-fidelity check.
- Per-platform subtitle style overrides. The current YAML has a `platforms:` section that's not in active use; this spec doesn't preserve it. (Can be re-added later if needed.)

## Architecture overview

```
┌─────────────────────────────────────────────────────────────┐
│ config/subtitle_styles.yaml  (global default, full spec)    │
└─────────────────────────────────────────────────────────────┘
                          │ deep-merge
                          ▼
┌─────────────────────────────────────────────────────────────┐
│ data/srt/{id}_style.json  (per-video DELTA, partial spec)   │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │ load_style(video_id)  │ ← src/processor/style.py
              └───────────────────────┘
                          │ SubtitleStyleSpec (Pydantic)
                          ▼
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌─────────────────────┐         ┌─────────────────────────┐
│ HTML overlay        │         │ render_for_ffmpeg(spec) │
│ (editor live view)  │         │  → ASS + PNG overlays   │
│ specToCss(spec, h)  │         │ src/processor/          │
└─────────────────────┘         │   style_render.py       │
                                └─────────────────────────┘
                                          │
                                          ├── _run_export_ffmpeg
                                          ├── preview_clip
                                          └── preview_frame
```

## 1. Canonical schema

All spatial fields stored as **percentages of canvas dimensions**. UI sliders show pixels in the source video's coords (intuitive for the user); FE converts on read/write.

```python
# src/processor/style.py

class TextStyle(BaseModel):
    font_name: Literal["Arial", "Roboto", "Impact", "Georgia", "Courier New", "Helvetica"] = "Arial"
    font_size: float = 3.0          # % of canvas height
    color: str = "#FFFFFF"          # hex
    bold: bool = True

class PositionStyle(BaseModel):
    alignment: Literal[
        "bottom-left", "bottom-center", "bottom-right",
        "center-left", "center-center", "center-right",
        "top-left",    "top-center",    "top-right",
    ] = "bottom-center"
    margin_v: float = 5.0           # % of canvas height, from anchor edge
    margin_h: float = 0.0           # % of canvas width, offset from anchor center

class OutlineStyle(BaseModel):
    width: float = 0.15             # % of canvas height
    color: str = "#000000"

class ShadowStyle(BaseModel):
    depth: float = 0.05             # % of canvas height; 0 = off
    color: str = "#000000"

class BackgroundStyle(BaseModel):
    shape: Literal["none", "rect", "rounded"] = "none"
    color: str = "#000000"
    opacity: int = 0                # 0–100 percent
    radius: float = 0.94            # % of canvas height (only when shape=rounded)
    padding_x: float = 0.83         # % of canvas width
    padding_y: float = 0.5          # % of canvas height

class BlurStyle(BaseModel):
    enabled: bool = False           # OFF by default per user request
    mode: Literal["blur", "pixelate", "fill"] = "blur"
    strength: int = 15              # opaque to renderers; passed through to ffmpeg filter

class SubtitleStyleSpec(BaseModel):
    text:       TextStyle       = Field(default_factory=TextStyle)
    position:   PositionStyle   = Field(default_factory=PositionStyle)
    outline:    OutlineStyle    = Field(default_factory=OutlineStyle)
    shadow:     ShadowStyle     = Field(default_factory=ShadowStyle)
    background: BackgroundStyle = Field(default_factory=BackgroundStyle)
    blur:       BlurStyle       = Field(default_factory=BlurStyle)
```

**Color format:** always `#RRGGBB` hex in the schema. Renderers convert to libass `&HAABBGGRR` and PIL `(r,g,b,a)` as needed. The pre-existing ASS-literal-color escape hatch is dropped (consistent input format makes diffs and migrations cleaner).

## 2. Persistence: delta over global default

### Global default

`config/subtitle_styles.yaml` — a full `SubtitleStyleSpec` serialized as YAML for human-readability. Loaded once at API startup, validated against the Pydantic model. Editable via `PUT /api/subtitle-styles`. The `platforms:` per-platform override section is removed.

### Per-video delta

`data/srt/{video_id}_style.json` — a **partial** spec. Only fields the user customized for this video appear. Example after the user changes only background color and opacity:

```json
{
  "background": {
    "color": "#FFFF00",
    "opacity": 90
  }
}
```

Missing fields fall back to the global default via deep-merge at load time.

### Loader

```python
# src/processor/style.py

def load_style(video_id: str | None = None) -> SubtitleStyleSpec:
    """Return the merged spec for a video, or the pure global default."""
    global_dict = yaml.safe_load(Path("config/subtitle_styles.yaml").read_text())
    if video_id is None:
        return SubtitleStyleSpec(**global_dict)
    per_video_path = Path(f"data/srt/{video_id}_style.json")
    if per_video_path.exists():
        delta = json.loads(per_video_path.read_text())
        # Auto-migrate legacy flat px-based JSONs (see migration below).
        delta = _migrate_if_legacy(delta, video_id)
        merged = _deep_merge(global_dict, delta)
        return SubtitleStyleSpec(**merged)
    return SubtitleStyleSpec(**global_dict)

def save_style_delta(video_id: str, delta: dict) -> None:
    """Replace the per-video file with `delta`. FE computes the diff client-side."""
    path = Path(f"data/srt/{video_id}_style.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(delta, indent=2))

def save_global_default(spec: SubtitleStyleSpec) -> None:
    """Rewrite config/subtitle_styles.yaml. Triggered by `Save as Default`."""
    yaml_text = yaml.safe_dump(spec.model_dump(), sort_keys=False, default_flow_style=False)
    Path("config/subtitle_styles.yaml").write_text(yaml_text)
```

`_deep_merge` is a 10-line recursive merge: dicts merge, scalars from `delta` replace those from `global_dict`. Lists replace (we have none in the schema currently).

### Migration

Existing per-video JSONs use flat snake_case keys with pixel values (`{font_size: 37, margin_v: 393, background_opacity: 90}`). On first load post-upgrade, `_migrate_if_legacy(delta, video_id)`:

1. Detects legacy shape: top-level keys are not in `{text, position, outline, shadow, background, blur}`.
2. Reads source video dims from `task_manager.video_index[video_id]` (height for vertical fields, width for horizontal).
3. Maps each legacy key to its new nested path and converts px → percentage.
4. Writes the converted JSON back to disk in the new shape.
5. Logs `migrated style for {video_id}: {N legacy fields converted}`.

Migration code lives in `src/processor/style.py::_migrate_if_legacy`. It stays for ~3 releases, then can be deleted; pre-existing JSONs that never re-opened can be deleted manually (or the migrator stays indefinitely — it's <50 lines).

### API endpoints

| Method | Path                                   | Body                       | Returns                              |
|--------|----------------------------------------|----------------------------|--------------------------------------|
| GET    | `/api/subtitle-styles`                 | —                          | full `SubtitleStyleSpec` (global)    |
| PUT    | `/api/subtitle-styles`                 | full `SubtitleStyleSpec`   | full `SubtitleStyleSpec`             |
| GET    | `/api/videos/{id}/style`               | —                          | merged `SubtitleStyleSpec` + `is_custom: bool` |
| PUT    | `/api/videos/{id}/style`               | partial `SubtitleStyleSpec` (delta) | merged `SubtitleStyleSpec`  |
| DELETE | `/api/videos/{id}/style`               | —                          | merged `SubtitleStyleSpec` (= global)|

The duplicated `_load_video_style` helpers in [editor.py:184](src/api/routers/editor.py#L184) and [process.py:163](src/api/routers/process.py#L163) are removed. Both routers import `load_style` from `src/processor/style.py`.

## 3. Renderers

### 3a. HTML overlay (FE live preview)

`ui-app/src/components/editor/SubtitleRenderer.tsx` — replaces today's `SubtitleOverlay`.

```ts
function specToOverlay(
  spec: SubtitleStyleSpec, videoW: number, videoH: number,
): { textStyle: CSSProperties; containerStyle: CSSProperties } {
  const px = (pct: number, base: number) => pct * base / 100;
  // Spatial vertical → videoH; spatial horizontal → videoW.
  const fontSize  = px(spec.text.font_size,  videoH);
  const marginV   = px(spec.position.margin_v, videoH);
  const marginH   = px(spec.position.margin_h, videoW);
  const outline   = px(spec.outline.width,  videoH);
  const radius    = px(spec.background.radius, videoH);
  const padX      = px(spec.background.padding_x, videoW);
  const padY      = px(spec.background.padding_y, videoH);
  // … assemble CSS
}
```

Anchor logic from `spec.position.alignment` decides `top` vs `bottom`, `left` vs `right`, etc. The text element's `background-color` is `rgba(r, g, b, opacity/100)` when `background.shape != "none"`, with `border-radius: ${radius}px` when `shape == "rounded"`. Outline is rendered via `WebkitTextStroke` + `text-shadow` (the existing technique, parameterized).

Drag-to-position writes back **percentages** so the underlying state stays canonical:

```ts
onDragPosition(dragDxPx, dragDyPx) {
  draft.position.margin_h = (currentPxH + dragDxPx) * 100 / videoW;
  draft.position.margin_v = (currentPxV + dragDyPx) * 100 / videoH;
}
```

### 3b. ffmpeg renderer (export + previews)

`src/processor/style_render.py` — new single entry point.

```python
@dataclass
class RenderArtifacts:
    ass_path: Path
    bg_pngs: list[BgPng] | None   # None when shape != "rounded" or opacity == 0

def render_for_ffmpeg(
    spec: SubtitleStyleSpec, srt_path: Path,
    canvas_w: int, canvas_h: int, output_dir: Path,
) -> RenderArtifacts:
    px = _resolve_px(spec, canvas_w, canvas_h)
    ass_path = _write_ass(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    bg_pngs = None
    if spec.background.shape == "rounded" and spec.background.opacity > 0:
        bg_pngs = _render_bg_pngs(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    return RenderArtifacts(ass_path=ass_path, bg_pngs=bg_pngs)
```

**Background dispatch:**
- `shape == "none"` → ASS has no box, no PNG list. The libass `BackColour` is `&H00000000` and `BorderStyle=1` (outline only).
- `shape == "rect"` → ASS uses `BackColour=convert(spec.background.color, opacity)` with `BorderStyle=3` (libass draws a rectangular box). No PNG list.
- `shape == "rounded"` → ASS has no box (same as "none"); PNG list renders rounded rectangles via PIL and overlays them in the filter chain. This is the current export path made explicit.

**Callers (collapse 3 paths into 1):**
- `_run_export_ffmpeg` in [process.py:179](src/api/routers/process.py#L179): replaces `srt_to_ass(...)` + `generate_subtitle_background_images(...)` with a single `render_for_ffmpeg(...)` call.
- `preview_clip` in [editor.py:386](src/api/routers/editor.py#L386): drops the `_build_style_string` + libass-only path; uses `render_for_ffmpeg` with `canvas_w/h = source dims`. Renders the same way the export does.
- `preview_frame` in [editor.py:320](src/api/routers/editor.py#L320): same switch. Now the editor's "Preview Frame" button is pixel-equivalent to the export.

**Removed code:**
- `srt_to_ass`'s dead `bg_box_colour` computation.
- `_build_style_string` (~40 lines) — folded into `style_render._write_ass`.
- `generate_subtitle_background_images` — folded into `style_render._render_bg_pngs`.
- The two `_load_video_style` impls.

## 4. FE StylePanel and state

### State model

`EditorTab.tsx` carries three pieces of state:

```ts
const [globalDefault, setGlobalDefault] = useState<SubtitleStyleSpec | null>(null);
const [savedSpec,     setSavedSpec]     = useState<SubtitleStyleSpec | null>(null); // last-loaded merged
const [draftSpec,     setDraftSpec]     = useState<SubtitleStyleSpec | null>(null); // live editing
```

On mount: `Promise.all([getSubtitleStyleDefault(), getVideoStyle(videoId)])`. `globalDefault` and `savedSpec` are set from those results; `draftSpec = structuredClone(savedSpec)`.

On save: `delta = diffSpec(draftSpec, globalDefault)` — returns only paths where draft differs from global. `PUT /api/videos/:id/style` with `delta`. `savedSpec` updates from the response; `draftSpec` is unchanged.

`diffSpec` is a depth-2 walk (the schema has fixed nesting): for each top-level group, for each leaf field, include the field iff `draft[group][key] !== global[group][key]`. Drops empty groups so the on-disk file stays minimal.

### StylePanel UI

The panel reorganizes around the schema's nesting. Each section is collapsible (uses existing material-symbols chevron pattern). Each customized leaf shows a small primary-colored dot + a "↺" reset-to-global affordance on hover.

```
Text                                              [▾]
├─ Font         (dropdown: Arial / Roboto / Impact / Georgia / Courier New / Helvetica)
├─ Size         (slider 12–72px, displays px in source-video coords)
├─ Color        (color picker)               ← NEW
└─ Bold         (toggle)

Position                                          [▾]
├─ Alignment    (3×3 grid of anchor buttons) ← NEW
├─ Vertical     (slider, displays px from anchor edge)
└─ Horizontal   (slider, displays px offset from anchor center)

Outline                                           [▾]
├─ Width        (slider 0–4px)
└─ Color        (color picker)               ← NEW

Shadow                                            [▾]
├─ Depth        (slider; 0 = off)
└─ Color        (color picker)               ← NEW

Background                                        [▾]
├─ Shape        (segmented: none / rect / rounded)
├─ Color        (color picker)
├─ Opacity      (slider 0–100%)
├─ Radius       (slider, shown only when shape=rounded)
└─ Padding      (X and Y sliders)

Blur                                              [▾]
├─ Enabled      (toggle, default OFF)
├─ Mode         (blur / pixelate / fill)
└─ Strength     (slider 5–30)
```

### Slider px display logic

Sliders work in source-video pixels for user intuition. Storage stays in percent. Two-way conversion:

```ts
// Read: % → px in source dims
const sliderValue = Math.round(draft.text.font_size * sourceH / 100);
// Write: px in source dims → %
onChange = (px) => { draft.text.font_size = px * 100 / sourceH; }
```

The panel reads `sourceH`/`sourceW` from the loaded `videoMeta`. Sliders min/max stay in px (e.g. 12–72 for font size).

### Buttons

- **Save** — saves segments + style delta concurrently (existing behavior). Style PUT carries the delta.
- **Save as Default** — `PUT /api/subtitle-styles` with the full `draftSpec`. Confirmation toast: *"Saved to global. Per-video overrides keep their values."*
- **Reset to global** — `DELETE /api/videos/:id/style`. Confirmation modal.

### Live preview

`SubtitleRenderer` (Section 3a) consumes `draftSpec` directly. Re-renders on every keystroke — same as today, just from the new spec shape. Drag-to-position writes percentages back into `draftSpec.position`.

The **Preview Frame** and **Preview Clip** buttons hit endpoints that use `render_for_ffmpeg` — they're the trusted-fidelity check, equivalent to what the export will produce.

### Font availability

Docker image extended in `Dockerfile`:

```dockerfile
# Free/open fonts that cover Arial, Helvetica, Roboto, Courier substitutes:
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-roboto \
    fonts-dejavu \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Optional: Microsoft fonts for Impact + Georgia + the real Arial.
# Requires accepting the MS EULA and enabling the `contrib` apt component.
# Skip this block if you don't want to redistribute MS fonts in the image —
# the FE dropdown will silently fall back to Liberation/DejaVu for those names.
RUN sed -i 's/main$/main contrib/' /etc/apt/sources.list.d/debian.sources && \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections && \
    apt-get update && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f && rm -rf /var/lib/apt/lists/*
```

Adds ~30 MB to image size. fontconfig aliases ensure `Arial` resolves to Liberation Sans (or real Arial if MS fonts installed) and Helvetica resolves to a sans-serif. The FE font dropdown shows all six options; libass picks the best installed match. Implementation note for the plan: if the MS-fonts block is skipped, decide whether to (a) trim the FE dropdown to the four guaranteed names or (b) accept Impact/Georgia silently substituting in the export.

## 5. Blur and style_matcher rework

### Blur is now part of the spec

`spec.blur` persists in the per-video delta + global YAML just like every other field. The `style.get("blur_enabled", True)` default-True fallback at [process.py:223](src/api/routers/process.py#L223) is deleted — `spec.blur.enabled` is always defined. **Default value is `False`** in the global YAML, so a fresh install ships with blur off; the user opts in.

### `style_matcher` becomes `suggest_position`

Today's `style_matcher.match_style` forcibly overrides `margin_v` and a couple of other fields based on the OCR-detected region, but only when blur is on. This silently overwrites the position the user set in the editor and couples blur to position.

The new behavior:

```
load_style(video_id):
  spec = deep_merge(global, per_video_delta)
  if not per_video_delta.has_path("position.*") and ocr_region_exists(video_id):
    spec.position = suggest_position(ocr_region, source_dims)   # in-memory only
  return spec
```

- `style_matcher.match_style` is renamed `suggest_position` and narrows its return to `PositionStyle` (alignment + margin_v + margin_h). Same math, narrower output.
- The seed runs whenever no `position.*` field is in the per-video delta. It's **not persisted** — the next load could pick up an improved OCR region. The user sees consistent values across reloads because the OCR region doesn't change without explicit re-detection.
- The first time the user drags or saves, the manual position lands in the delta and the seeding stops applying.
- Blur and position are now decoupled. Toggling blur off no longer changes position.

### "Re-align to OCR region" button

Small button in the StylePanel's Position section, only visible when an OCR region exists. Clicking strips `position` from the current delta client-side and PUTs the modified delta to `/api/videos/:id/style`. The next reload sees no per-video position and re-seeds from `suggest_position`. Confirmation modal — it's destructive for the user's manual placement.

No new endpoint needed: PUT-replace semantics on the delta already cover both "set this field" and "clear this field back to global."

### Files touched

- `src/processor/style_matcher.py` — `match_style` → `suggest_position`. Returns only `PositionStyle`.
- `src/processor/style.py` (new) — calls `suggest_position` when seeding.
- [src/api/routers/process.py:222-242](src/api/routers/process.py#L222) — the `if blur_enabled` block deletes. The conditional now reads `spec.blur.enabled` directly and applies blur independently from position.

## 6. Testing strategy

### 6a. Schema layer (`tests/test_style_spec.py`)

- Valid `SubtitleStyleSpec` round-trips through JSON.
- Deep merge: `_deep_merge(global, delta)` correctly nests overrides.
- Loader with no per-video file → pure global default.
- Loader with per-video file → merged result.
- `diffSpec(draft, global)` returns only changed paths; empty groups are pruned.
- Legacy migration: `{font_size: 37, margin_v: 393}` + source dims `(720, 1280)` → `{text: {font_size: 2.89}, position: {margin_v: 30.7}}`. Migrated file is rewritten on disk.

### 6b. Renderer layer

`tests/test_style_render.py`:
- Spec with `background.shape == "none"` → `RenderArtifacts.bg_pngs is None`; ASS has no `BorderStyle=3`.
- Spec with `background.shape == "rect"` → `bg_pngs is None`; ASS uses `BackColour={converted hex with alpha}` and `BorderStyle=3`.
- Spec with `background.shape == "rounded"` → `bg_pngs` is non-empty; first entry has expected dimensions.
- Percentage → px conversion: `spec.position.margin_v = 30.7` at canvas (720, 1280) → 393 px; at (1080, 1920) → 590 px.
- Colors: `text.color = "#FF0000"` → ASS `PrimaryColour=&H000000FF`. `outline.color = "#00FF00"` → `OutlineColour=&H0000FF00`.

`ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx` (Vitest):
- Spec → CSS conversion is deterministic; same input always emits same `style` object.
- Drag callback computes percentage write-back correctly for known displacements.

### 6c. End-to-end sanity

`tests/test_export_style.py::test_export_honors_full_spec` (marked `@pytest.mark.integration`, ~10s):
- Use a 5-second fixture video.
- Save a spec with every visible field set non-default (`font_size: 10%, margin_v: 20%, bg.shape: rounded, bg.color: #FFFF00, outline.color: #FF0000, …`).
- Run the export endpoint.
- Probe a frame at t=2.5s with PIL: assert the yellow pixel cluster sits in the expected y-band, red outline pixels exist around the text, etc.

Manual smoke (3 min) after the dust settles:
1. Fresh video → drag subtitle position → Save → reload page → position persists at the dragged location.
2. Pick yellow rounded background @ 70% opacity → Preview Frame → Export → all three previews (HTML overlay, preview frame MP4, export MP4) show yellow rounded backgrounds at the same place.
3. Toggle blur on → blur applies in export → toggle off → blur disappears, position unchanged.

## Migration impact

| Surface | Change | User-visible impact |
|---|---|---|
| Existing per-video JSONs | Auto-migrated to nested percent-based shape on first load post-upgrade | None if all fields lived in the old schema. Visual positions stay equivalent. |
| Global YAML | Rewritten as full `SubtitleStyleSpec` shape. Old `platforms:` section removed. | Per-platform overrides are gone. If you used them, you'd need to re-create them at the per-video level. |
| `blur` field in per-video JSONs | Most legacy JSONs don't carry it; merging picks up the new `blur.enabled: false` global default | Existing videos that relied on the implicit `blur=True` will export without blur after the upgrade. Consistent with "blur is opt-in." |
| Settings → Subtitle Style page | Doesn't exist today; this spec doesn't add it either | No regression. `Save as Default` from EditorTab continues to be the global-edit surface. |

## Out of scope

- Settings → Subtitle Style page (global default editor outside any video). Can be added later; the new endpoints support it already.
- Per-platform style overrides (re-adding `platforms:` to YAML). The current schema is flat and platform-agnostic.
- Migration to support aspect-flipped exports. Not a current use case.
- Detection of installed fonts at runtime (Section 4's font list is statically declared and the Dockerfile install matches it).

## Critical files

- `src/processor/style.py` *(new)* — `SubtitleStyleSpec`, `load_style`, `save_style_delta`, `save_global_default`, `_deep_merge`, `_migrate_if_legacy`.
- `src/processor/style_render.py` *(new)* — `render_for_ffmpeg`, `_write_ass`, `_render_bg_pngs`. Absorbs the current `srt_to_ass` and `generate_subtitle_background_images`.
- `src/processor/style_matcher.py` *(modified)* — `match_style` → `suggest_position`. Narrower return.
- [src/api/routers/process.py](src/api/routers/process.py) — `_load_subtitle_style` deletes; `_run_export_ffmpeg` calls `render_for_ffmpeg`; `_subtitle_styles_*` endpoints take/return `SubtitleStyleSpec`.
- [src/api/routers/editor.py](src/api/routers/editor.py) — `_load_video_style` deletes; `preview_frame` + `preview_clip` call `render_for_ffmpeg`.
- [config/subtitle_styles.yaml](config/subtitle_styles.yaml) — rewritten as a full `SubtitleStyleSpec` with `blur.enabled: false`.
- `ui-app/src/components/editor/SubtitleRenderer.tsx` *(new, replaces `SubtitleOverlay.tsx`)*.
- [ui-app/src/components/editor/StylePanel.tsx](ui-app/src/components/editor/StylePanel.tsx) — reorganized around schema sections; new color pickers and alignment grid; reads/writes nested spec.
- [ui-app/src/pages/videoDetail/EditorTab.tsx](ui-app/src/pages/videoDetail/EditorTab.tsx) — state model around `globalDefault` / `savedSpec` / `draftSpec`; `diffSpec` for delta save.
- [Dockerfile](Dockerfile) — adds font packages.
- `tests/test_style_spec.py`, `tests/test_style_render.py`, `tests/test_export_style.py`, `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx` *(all new)*.
