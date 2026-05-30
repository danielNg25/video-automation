# App Refocus — Drop Export Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the per-platform video export surface (Process stage, ExportTab, StylePanel, `processor/` module's burn-in code, `SubtitleStyleSpec` system, replacement router, platform/style configs). After this PR the app is download → transcribe → translate → dub; the user exports the final video themselves in DaVinci/Premiere/etc.

**Architecture:** Deletion-heavy. `parse_srt` + `write_srt` stay (heavily used by translator, TTS, transcribe router). `FFmpegProcessor` gets slimmed in place — keep `get_video_info` (OCR uses it), `extract_frames` (OCR), `generate_proxy` (editor.py serves a proxy MP4 to the video player); delete every burn/reformat/style/blur method. The Subtitle editor still shows segments + a raw video player; the subtitle overlay (`SubtitleRenderer.tsx`) goes — the segment list is the timing reference.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic v2 (BE), React 19 + TypeScript + Tailwind 4 + Vite + vitest (FE).

---

## Context the implementer needs

**Spec:** [docs/superpowers/specs/2026-05-30-app-refocus-drop-export-design.md](docs/superpowers/specs/2026-05-30-app-refocus-drop-export-design.md) — read first.

**Files at HEAD (read before starting):**
- [src/api/__init__.py](src/api/__init__.py) — router registry; lines 17 (imports) and 46-54 (`include_router` calls)
- [src/pipeline.py](src/pipeline.py) — `STAGE_PROGRESS_RANGES` at line ~30, `Process` stage placeholder at line 275-302
- [src/cli.py](src/cli.py) — `--platforms` flag at lines 47 and 164; `process` and `batch` commands
- [src/processor/ffmpeg.py](src/processor/ffmpeg.py) — `FFmpegProcessor` class; see "Slim ffmpeg.py" task for the method list to keep vs delete
- [src/processor/subtitle.py](src/processor/subtitle.py) — `parse_srt` and `write_srt` are the load-bearing helpers; everything else goes
- [src/api/routers/editor.py](src/api/routers/editor.py) — style endpoints + preview-frame + preview-clip + generate_proxy caller at line 169
- [src/api/routers/process.py](src/api/routers/process.py) — entire file deletes
- [src/api/routers/replacement.py](src/api/routers/replacement.py) — entire file deletes
- [src/transcriber/ocr.py:148-156](src/transcriber/ocr.py#L148-L156) — uses `FFmpegProcessor.get_video_info` and `extract_frames`; survives unchanged
- [src/translator/llm.py](src/translator/llm.py) — uses `parse_srt` + `write_srt`; survives unchanged once those stay where they are
- [src/tts/runner.py:170,190](src/tts/runner.py#L170-L190) — uses `parse_srt`; survives unchanged
- [src/api/routers/transcribe.py:13,118](src/api/routers/transcribe.py#L13-L118) — uses `parse_srt`; survives unchanged
- [ui-app/src/pages/VideoDetail.tsx](ui-app/src/pages/VideoDetail.tsx) — ExportTab import at line 7, ExportTab tab nav at line 511
- [ui-app/src/pages/videoDetail/EditorTab.tsx](ui-app/src/pages/videoDetail/EditorTab.tsx) — imports SubtitleRenderer/StylePanel/diffSpec at lines 3-9; renders SubtitleRenderer at line 546, StylePanel at line 608; `handleSave` does dual SRT+style save at lines 291/335
- [ui-app/src/components/editor/SubtitleRenderer.tsx](ui-app/src/components/editor/SubtitleRenderer.tsx)
- [ui-app/src/components/editor/StylePanel.tsx](ui-app/src/components/editor/StylePanel.tsx)
- [ui-app/src/utils/diffSpec.ts](ui-app/src/utils/diffSpec.ts)
- [ui-app/src/api/client.ts](ui-app/src/api/client.ts) — style/process/preview API clients to drop

**Commands you'll use:**
- BE tests: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py`
- FE tests: `cd ui-app && npx vitest run`
- FE build: `cd ui-app && npm run build`
- BE lint: `ruff check src/ tests/`
- Find stragglers: `grep -rln "<symbol>" src/ tests/ ui-app/src/`

**Repo rules:**
- Branch: `feature/app-refocus-drop-export` already exists with the spec commit `ce0f686`. Stay on it.
- Bundle CHANGELOG + README into Task 7.
- No "Co-Authored-By", no AI mentions.

---

## File structure after this PR

| Path | Action | Final responsibility |
|------|--------|---------------------|
| `src/processor/__init__.py` | Modify (empty) | No re-exports |
| `src/processor/ffmpeg.py` | Slim | Keep `_verify_ffmpeg`, `get_video_info`, `extract_frames`, `generate_proxy`, `_escape_filter_path`. Delete the rest. |
| `src/processor/subtitle.py` | Slim | Keep `parse_srt` + `write_srt`. Delete everything else. |
| `src/processor/style.py` | **Delete** | |
| `src/processor/style_render.py` | **Delete** | |
| `src/processor/style_matcher.py` | **Delete** | |
| `src/processor/region_detector.py` | **Delete** | (unused by OCR after style stuff goes; verify via grep) |
| `src/processor/CLAUDE.md` | **Delete** | |
| `src/api/routers/process.py` | **Delete** | |
| `src/api/routers/replacement.py` | **Delete** | |
| `src/api/routers/editor.py` | Slim | Drop style + preview-frame + preview-clip handlers; keep the `generate_proxy` proxy-serving endpoint, the SRT PUT, video metadata, OCR region |
| `src/api/__init__.py` | Modify | Drop `process` and `replacement` from imports + `include_router` calls |
| `src/pipeline.py` | Modify | Drop "process" stage from `STAGE_PROGRESS_RANGES`; re-spread (tts covers 0.70-1.00); drop the placeholder Process stage block at lines 275-302 |
| `src/cli.py` | Modify | Drop `--platforms` flag from `process` and `batch`; drop `platform_list` from their bodies; drop platform refs in the stage display |
| `ui-app/src/pages/videoDetail/ExportTab.tsx` | **Delete** | |
| `ui-app/src/components/editor/StylePanel.tsx` | **Delete** | |
| `ui-app/src/components/editor/SubtitleRenderer.tsx` | **Delete** | |
| `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx` | **Delete** | |
| `ui-app/src/utils/diffSpec.ts` | **Delete** | |
| `ui-app/src/utils/__tests__/diffSpec.test.ts` | **Delete** | |
| `ui-app/src/pages/VideoDetail.tsx` | Modify | Drop ExportTab import + tab nav at line 511 |
| `ui-app/src/pages/videoDetail/EditorTab.tsx` | Slim | Drop SubtitleRenderer/StylePanel/diffSpec imports + their JSX; drop `draftSpec`/`savedSpec`/`globalDefault` state + the `handleSave` dual SRT+style transaction (becomes SRT-only); drop `handleRealignToOcr` |
| `ui-app/src/api/client.ts` | Modify | Drop style + process + preview clients |
| `ui-app/src/api/types.ts` | Modify | Drop SubtitleStyleSpec + related types |
| `config/platforms.yaml` | **Delete** | |
| `config/subtitle_styles.yaml` | **Delete** | |
| `config/config.example.yaml` | Modify | Drop any platform/style references |
| `tests/test_processor.py` | **Delete** | |
| `tests/test_export_style.py` | **Delete** | |
| `tests/test_style_spec.py` | **Delete** | |
| `tests/test_style_render.py` | **Delete** | |
| `tests/test_subtitle_replacement.py` | **Delete** | |
| `tests/test_preview_mix_endpoint.py` | **Delete** | (tests deleted preview-mix endpoint) |
| `CHANGELOG.md` | Modify (Task 7) | |
| `README.md` | Modify (Task 7) | |

---

### Task 1: Slim `src/processor/ffmpeg.py` and `src/processor/subtitle.py`; delete the rest of `processor/`

Strip everything from `processor/` that's not used by surviving callers. After this task, the dead style/burn/reformat code is gone but the surviving callers (translator, TTS, transcribe router, OCR, editor's proxy endpoint) still import successfully.

**Files:**
- Modify: `src/processor/__init__.py`
- Modify: `src/processor/ffmpeg.py`
- Modify: `src/processor/subtitle.py`
- Delete: `src/processor/style.py`, `src/processor/style_render.py`, `src/processor/style_matcher.py`, `src/processor/region_detector.py`, `src/processor/CLAUDE.md`

- [ ] **Step 1.1: Inventory current `__init__.py` and confirm callers**

Read `src/processor/__init__.py` to see what it re-exports. Confirm by running:

```bash
grep -rn "from src.processor" src/ tests/ 2>&1
```

Expected callers (everything else gets cleaned up):
- `src/transcriber/ocr.py` — `FFmpegProcessor` (uses `get_video_info`, `extract_frames`)
- `src/api/routers/editor.py` — `FFmpegProcessor` (uses `generate_proxy`)
- `src/api/routers/transcribe.py` — `parse_srt`
- `src/translator/llm.py` — `parse_srt`, `write_srt`
- `src/tts/runner.py` — `parse_srt`

None of these need anything from `style.py`, `style_render.py`, `style_matcher.py`, `region_detector.py`, or the burn/reformat methods on `FFmpegProcessor`.

- [ ] **Step 1.2: Empty `src/processor/__init__.py`**

Replace contents with:

```python
"""Video processing helpers — kept after the per-platform export pipeline
was removed.

Surviving exports:
    - ``ffmpeg.FFmpegProcessor`` (slimmed) for OCR + proxy-video generation
    - ``subtitle.parse_srt`` / ``subtitle.write_srt`` for SRT IO

Everything else (burn-in, per-platform reformat, ASS/PNG style rendering,
SubtitleStyleSpec, region detection, style matching) was deleted when the
app refocused away from in-app exports.
"""
```

Drop every `from src.processor.X import Y` and `__all__` block at the file's top level.

- [ ] **Step 1.3: Slim `src/processor/ffmpeg.py`**

Open `src/processor/ffmpeg.py`. The class `FFmpegProcessor` currently has many methods. Keep only:

- `__init__`
- `_verify_ffmpeg`
- `get_video_info` (used by `src/transcriber/ocr.py:154`)
- `extract_frames` (used by `src/transcriber/ocr.py`)
- `generate_proxy` (used by `src/api/routers/editor.py:169`)
- `_escape_filter_path` (only keep if any surviving method references it; otherwise delete)

**Delete** these methods (find them by searching `def burn_subtitles\|def reformat_for_platform\|def burn_and_reformat\|def mix_audio\|def _build_style_string\|def _escape_filter_chain_value\|def _build_blur_filter\|def apply_region_blur\|def extract_single_frame\|def apply_blur_to_frame\|def blur_and_burn_subtitles\|def blur_burn_and_reformat\|def blur_burn_reformat_and_dub\|def burn_reformat_and_dub`):

- `_build_style_string`
- `_escape_filter_chain_value` (if not used by surviving code)
- `burn_subtitles`
- `reformat_for_platform`
- `burn_and_reformat`
- `mix_audio`
- `_build_blur_filter`
- `apply_region_blur`
- `extract_single_frame` — verify with `grep -rn "extract_single_frame" src/ tests/` first. If only used by the deleted preview-frame endpoint, delete; if used elsewhere, keep.
- `apply_blur_to_frame`
- `blur_and_burn_subtitles`
- `blur_burn_and_reformat`
- `blur_burn_reformat_and_dub`
- `burn_reformat_and_dub`

Also delete any module-level constants only used by these methods (e.g. ASS template strings, blur filter constants).

Drop the `from src.processor.region_detector import SubtitleRegion` import at the top of the file (line ~15) and any `SubtitleRegion`-typed parameters.

- [ ] **Step 1.4: Slim `src/processor/subtitle.py`**

Open `src/processor/subtitle.py`. Keep **only**:

- `parse_srt`
- `_timestamp_to_seconds` (helper used by `parse_srt`)
- `_seconds_to_srt_timestamp` (helper used by `write_srt`)
- `write_srt`

**Delete**:

- `_seconds_to_ass_timestamp`
- `break_long_lines`
- `merge_subtitles`
- `select_subtitle_for_platform`
- `_LANGUAGE_FALLBACK` (module-level constant only used by `select_subtitle_for_platform`)
- `build_background_overlay_filter`
- `build_background_drawtext_filter`
- `generate_subtitle_background_images`
- Any other function in the file not in the keep list

Also drop imports that become unused (e.g. `import textwrap`, `from PIL import ...` if present).

- [ ] **Step 1.5: Delete the unused submodules**

```bash
git rm src/processor/style.py src/processor/style_render.py src/processor/style_matcher.py src/processor/region_detector.py src/processor/CLAUDE.md
```

Verify with grep that nothing in `src/`, `tests/`, or `ui-app/src/` references the deleted symbols (except the FE which still has style references — those die in Task 4):

```bash
grep -rln "SubtitleStyleSpec\|style_matcher\|style_render\|SubtitleRegion\|region_detector" src/ tests/ 2>&1
```

Expected: empty for `src/` and `tests/` after this task. If `region_detector` is referenced anywhere else (e.g. via dynamic import), investigate and resolve.

- [ ] **Step 1.6: Run the BE suite — confirm imports still resolve**

Some tests will fail because they imported deleted modules (e.g. `tests/test_style_spec.py` imports `SubtitleStyleSpec`). Those tests are deleted in Task 6. For this task's verification, **only run the tests that DON'T import deleted modules**:

```bash
python -m pytest tests/ -x \
  --ignore=tests/test_pipeline_cancel_integration.py \
  --ignore=tests/test_processor.py \
  --ignore=tests/test_export_style.py \
  --ignore=tests/test_style_spec.py \
  --ignore=tests/test_style_render.py \
  --ignore=tests/test_subtitle_replacement.py \
  --ignore=tests/test_preview_mix_endpoint.py \
  2>&1 | tail -10
```

Expected: green. If any other tests fail because they reference deleted symbols, either add them to the ignore list (if they'll be deleted in Task 6 too) or fix the test.

- [ ] **Step 1.7: Lint**

```bash
ruff check src/processor/ src/transcriber/ocr.py src/translator/llm.py src/tts/runner.py src/api/routers/editor.py src/api/routers/transcribe.py 2>&1 | tail -10
```

Expected: no new errors introduced by this task.

- [ ] **Step 1.8: Commit**

```bash
git add -A
git commit -m "refactor(processor): slim ffmpeg + subtitle; delete style modules

FFmpegProcessor keeps only the methods OCR and the editor's proxy
endpoint need: get_video_info, extract_frames, generate_proxy. The
burn-in, per-platform reformat, audio mix, blur, and combined
blur+burn+reformat methods are deleted (~600 lines).

subtitle.py keeps only parse_srt + write_srt (the SRT IO heavily used
by translator, TTS, and the transcribe router). The SRT→ASS
conversion, line-breaking, platform selection, and background-image
generation helpers are deleted.

style.py (SubtitleStyleSpec), style_render.py (ASS+PNG renderer),
style_matcher.py (auto-fit-to-OCR-region), region_detector.py,
processor/CLAUDE.md are deleted entirely.

The processor/ package keeps an empty __init__.py describing what
survives. Sub-project 1 of 3 in the post-merge refocus."
```

---

### Task 2: Drop the export-related BE routers

Delete `src/api/routers/process.py` and `src/api/routers/replacement.py` entirely. Strip the style + preview-frame + preview-clip handlers from `src/api/routers/editor.py` while preserving the SRT PUT, video metadata, OCR region, and the proxy-video endpoint.

**Files:**
- Delete: `src/api/routers/process.py`, `src/api/routers/replacement.py`
- Modify: `src/api/routers/editor.py`
- Modify: `src/api/__init__.py`

- [ ] **Step 2.1: Delete the routers**

```bash
git rm src/api/routers/process.py src/api/routers/replacement.py
```

- [ ] **Step 2.2: Drop the router registrations in `src/api/__init__.py`**

Open `src/api/__init__.py`. In the import block around line 17, remove `process` and `replacement` from the `from src.api.routers import (...)` list. In the `include_router` block around lines 46-54, delete:

```python
app.include_router(process.router)
app.include_router(replacement.router)
```

The remaining `include_router` calls stay: `download`, `transcribe`, `translate`, `editor`, `settings`, `pipeline`, `tts`, plus the versions router added by PR #19.

- [ ] **Step 2.3: Strip style + preview handlers from `src/api/routers/editor.py`**

In `src/api/routers/editor.py`:

1. Find every handler decorated with `@router.get("/api/videos/{video_id}/style", ...)`, `@router.put(...)`, `@router.delete(...)` and the global `@router.get("/api/subtitle-styles", ...)` / `@router.put(...)`. **Delete them all.**
2. Find the `preview_frame` and `preview_clip` handlers (search `def preview_frame\|def preview_clip` or `preview-frame\|preview-clip`). **Delete them all.**
3. **Keep**: the `PUT /api/videos/{video_id}/srt` handler (writes the working draft), the `GET /api/videos/{video_id}/proxy` handler (uses `FFmpegProcessor.generate_proxy`), the `GET /api/videos/{video_id}/ocr-region` handler (if present — the editor uses it).
4. Drop now-unused imports from the file (e.g. `from src.processor.style import SubtitleStyleSpec`, anything related to the deleted handlers). `ruff check --fix` is OK to use for this.

- [ ] **Step 2.4: Run BE suite (with the same ignores as Task 1.6)**

```bash
python -m pytest tests/ -x \
  --ignore=tests/test_pipeline_cancel_integration.py \
  --ignore=tests/test_processor.py \
  --ignore=tests/test_export_style.py \
  --ignore=tests/test_style_spec.py \
  --ignore=tests/test_style_render.py \
  --ignore=tests/test_subtitle_replacement.py \
  --ignore=tests/test_preview_mix_endpoint.py \
  2>&1 | tail -10
```

Expected: green.

- [ ] **Step 2.5: Commit**

```bash
git add -A
git commit -m "refactor(api): delete process + replacement routers; strip style/preview from editor

POST /api/videos/{id}/process and POST /api/videos/{id}/replace-subtitle
disappear with the export pipeline. The editor router loses its style
CRUD (GET/PUT/DELETE /api/videos/{id}/style, GET/PUT /api/subtitle-styles),
its preview-frame endpoint, and its preview-clip endpoint — all of which
served the burn-in preview flow that's no longer in scope.

Survivors in editor.py: PUT /api/videos/{id}/srt (working-draft save),
GET /api/videos/{id}/proxy (video-player proxy via FFmpegProcessor.generate_proxy),
GET /api/videos/{id}/ocr-region."
```

---

### Task 3: Drop Process stage from pipeline + CLI

The Process stage is already a no-op (see [src/pipeline.py:275-302](src/pipeline.py#L275-L302)). Clean it up properly: remove the stage from `STAGE_PROGRESS_RANGES`, drop the placeholder code, drop the `--platforms` CLI flag.

**Files:**
- Modify: `src/pipeline.py`
- Modify: `src/cli.py`

- [ ] **Step 3.1: Remove the Process stage from `STAGE_PROGRESS_RANGES`**

Open `src/pipeline.py`. Find `STAGE_PROGRESS_RANGES` (around line 30). The current entries look like:

```python
STAGE_PROGRESS_RANGES = {
    "download":   (0.00, 0.20),
    "transcribe": (0.20, 0.45),
    "translate":  (0.45, 0.55),
    "tts":        (0.55, 0.70),
    "process":    (0.70, 1.00),
}
```

Replace with (TTS now covers the tail):

```python
STAGE_PROGRESS_RANGES = {
    "download":   (0.00, 0.20),
    "transcribe": (0.20, 0.45),
    "translate":  (0.45, 0.60),
    "tts":        (0.60, 1.00),
}
```

- [ ] **Step 3.2: Delete the Process stage block in `process_single`**

Find the comment `# --- Stage: Process — skipped, export via Video Studio ---` (around line 275). Delete from that comment through to (but not including) the next stage or the function's closing `register_processed` call. Specifically, delete lines around 275-302:

```python
# --- Stage: Process — skipped, export via Video Studio ---
if not state.is_stage_complete("process"):
    # ... whatever placeholder logic is there ...
    emit("process", 1.0, "Pipeline complete — use Video Studio to export")
    state.mark_stage_complete("process", { ... })
```

Replace with nothing — the function flows straight from the TTS stage's completion to `register_processed`.

- [ ] **Step 3.3: Update `process_batch`'s signature**

Search `def process_batch` in `src/pipeline.py`. If it takes a `platforms` (or `platform_list`) argument, remove it from the signature and from any internal usage. Pass-through to `process_single` drops the same arg.

- [ ] **Step 3.4: Drop `--platforms` from `src/cli.py`**

In `src/cli.py`:

1. Find `@click.option("--platforms", ...)` decorators on the `process` and `batch` commands (lines 47 and 164). Delete both decorator lines.
2. Drop `platforms` from the corresponding function signatures (around lines 57 and 170).
3. Drop the `platform_list = [...]` parsing lines (lines 64 and 187).
4. Drop `platforms` and `platform_list` from any subsequent code in the command bodies, including the call to `pipeline.process_single(url, platform_list, options, on_progress)` — becomes `pipeline.process_single(url, options, on_progress)`. Same for `pipeline.process_batch`.
5. In the `stage_idx` dict (around line 86), remove `"process": 3` and `"upload": 4`. Keep `"download": 1`, `"transcribe": 2`, `"translate": 2`, `"tts": 3`.
6. Drop the `"process": "[blue]⚙[/blue]"` line from the stage icons dict around line 82.
7. Drop the `outputs = result.get("stage_results", {}).get("process", {}).get("outputs", {})` line around line 104 and any subsequent display of `outputs` (it printed per-platform output file paths).
8. In the `status` command around line 237, drop the `Platforms: {', '.join(state.platforms)}` line.

- [ ] **Step 3.5: Update `pipeline.process_single`'s signature**

The CLI now calls `pipeline.process_single(url, options, on_progress)` without `platform_list`. Update `process_single`'s signature in `src/pipeline.py` to remove the `platforms` (or `platform_list`) positional argument. Verify by `grep -n "process_single" src/`.

If the API task_manager also calls `process_single` (search `process_single` in `src/api/task_manager.py`), update that call site too.

- [ ] **Step 3.6: Run BE suite + lint**

```bash
python -m pytest tests/ -x \
  --ignore=tests/test_pipeline_cancel_integration.py \
  --ignore=tests/test_processor.py \
  --ignore=tests/test_export_style.py \
  --ignore=tests/test_style_spec.py \
  --ignore=tests/test_style_render.py \
  --ignore=tests/test_subtitle_replacement.py \
  --ignore=tests/test_preview_mix_endpoint.py \
  2>&1 | tail -10
```

Expected: green. The pipeline integration test (`tests/test_pipeline_cancel_integration.py` is intentionally ignored) and any pipeline-specific tests must pass.

```bash
ruff check src/pipeline.py src/cli.py src/api/task_manager.py 2>&1 | tail -5
```

Expected: no new errors.

- [ ] **Step 3.7: Commit**

```bash
git add src/pipeline.py src/cli.py src/api/task_manager.py
git commit -m "refactor(pipeline): drop Process stage + --platforms CLI flag

The Process stage was already a no-op (commented 'skipped, export via
Video Studio'). Removing the dead placeholder, the stage entry from
STAGE_PROGRESS_RANGES (TTS now covers 0.60-1.00), and the platform
plumbing in the CLI's process / batch / status commands.

process_single's signature loses the platform_list argument; same for
process_batch. Callers in src/api/task_manager.py updated."
```

---

### Task 4: Delete FE export surface

Delete ExportTab + StylePanel + SubtitleRenderer + diffSpec. Strip their imports + renderings from EditorTab. Drop the export tab nav entry in VideoDetail. Clean up `client.ts` and `types.ts`.

**Files:**
- Delete: `ui-app/src/pages/videoDetail/ExportTab.tsx`
- Delete: `ui-app/src/components/editor/StylePanel.tsx`
- Delete: `ui-app/src/components/editor/SubtitleRenderer.tsx`
- Delete: `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx`
- Delete: `ui-app/src/utils/diffSpec.ts`
- Delete: `ui-app/src/utils/__tests__/diffSpec.test.ts`
- Modify: `ui-app/src/pages/VideoDetail.tsx`
- Modify: `ui-app/src/pages/videoDetail/EditorTab.tsx`
- Modify: `ui-app/src/api/client.ts`
- Modify: `ui-app/src/api/types.ts`

- [ ] **Step 4.1: Delete the FE files**

```bash
git rm ui-app/src/pages/videoDetail/ExportTab.tsx \
       ui-app/src/components/editor/StylePanel.tsx \
       ui-app/src/components/editor/SubtitleRenderer.tsx \
       ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx \
       ui-app/src/utils/diffSpec.ts \
       ui-app/src/utils/__tests__/diffSpec.test.ts
```

- [ ] **Step 4.2: Drop ExportTab from `ui-app/src/pages/VideoDetail.tsx`**

In `ui-app/src/pages/VideoDetail.tsx`:

1. Remove `import { ExportTab } from './videoDetail/ExportTab';` at line 7.
2. Find the tab nav block. Remove the "Export" tab entry and the `<ExportTab .../>` JSX render at line 511. The tabs remaining: "Subtitle" (Editor) and "Dub". Any state setting the active tab to `'export'` should be cleaned up too — if `activeTab === 'export'` was a code path, drop it.

- [ ] **Step 4.3: Strip style + renderer + dual-save from `ui-app/src/pages/videoDetail/EditorTab.tsx`**

In `ui-app/src/pages/videoDetail/EditorTab.tsx`:

1. Drop imports at lines 3, 6, 9:

```ts
import { SubtitleRenderer } from '../../components/editor/SubtitleRenderer';
import { StylePanel } from '../../components/editor/StylePanel';
import { diffSpec } from '../../utils/diffSpec';
```

Also drop any related type imports (e.g. `SubtitleStyleSpec`).

2. Drop the style state declarations: `draftSpec`, `savedSpec`, `globalDefault`, `setDraftSpec`, `setSavedSpec`, `setGlobalDefault`, and any associated `useEffect` that loads them.

3. Drop the `handleRealignToOcr` callback (and its dependencies).

4. Find `handleSave` (around line 280-300). It currently does `Promise.all([putSrt(...), putVideoStyle(...)])`. Simplify to **SRT only**:

```tsx
const handleSave = useCallback(async () => {
  if (!videoId || saving) return;
  setSaving(true);
  setSaveStatus('idle');
  try {
    const res = await putSrt(videoId, { language: activeLang, segments });
    setSegments(res.segments);
    setOriginalSegments(res.segments);
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 3000);
  } catch {
    setSaveStatus('error');
  } finally {
    setSaving(false);
  }
}, [videoId, activeLang, segments, saving]);
```

Drop the `draftSpec` / `globalDefault` checks at the top of the function — they're no longer relevant.

5. Drop the `<SubtitleRenderer .../>` JSX block at line 546. The video player just plays raw — no subtitle overlay.

6. Drop the `<StylePanel .../>` JSX block at line 608 and anything immediately around it (e.g. a conditional render of a "Style" sub-tab).

7. Drop the `videoRect` state if it's only used by `SubtitleRenderer`. Same for `sourceW`/`sourceH` state if only used by StylePanel.

After this step, `EditorTab.tsx` should drop ~200-300 lines.

- [ ] **Step 4.4: Strip style + process + preview clients from `ui-app/src/api/client.ts`**

Open `ui-app/src/api/client.ts`. Delete every function that wraps a deleted endpoint:

- `getStyleSpec`, `putStyleSpec`, `getSubtitleStyles`, `putSubtitleStyles`
- `getVideoStyle`, `putVideoStyle`, `deleteVideoStyle`
- `getExportProgress`, `postProcess`
- `getPreviewFrameUrl`, `previewClip`, anything else `preview-*`
- `postReplaceSubtitle` (replacement router is gone)

Find them via:

```bash
grep -n "preview\|style\|process\|replacement" ui-app/src/api/client.ts
```

Resolve each hit: if it's a wrapper for a deleted endpoint, delete it.

- [ ] **Step 4.5: Drop style types from `ui-app/src/api/types.ts`**

Drop any interface or type definition that mirrored `SubtitleStyleSpec` or `Platform` or `DubStatusEntry` (DubStatusEntry was already removed but double-check). Also drop any `style?: SubtitleStyleSpec` field on `Video`/`VideoResponse`.

- [ ] **Step 4.6: Run FE tests + build + lint**

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
```

Expected: green (the deleted SubtitleRenderer and diffSpec tests went with their source; everything else stays).

```bash
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: build succeeds. The two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may still be there — not in scope.

```bash
cd ui-app && npx eslint src/pages/videoDetail/ src/api/ src/components/editor/ 2>&1 | tail -10
```

Expected: no new errors introduced by this task.

- [ ] **Step 4.7: Commit**

```bash
git add -A
git commit -m "refactor(fe): delete ExportTab, StylePanel, SubtitleRenderer, diffSpec

The per-platform export UI and the styled subtitle overlay go away
with the BE export pipeline. EditorTab loses ~250 lines: the style
state, the SubtitleRenderer JSX, the StylePanel JSX, the
handleRealignToOcr callback, and the dual-save (SRT + style)
transaction in handleSave — saving now just writes the SRT.

VideoDetail drops the Export tab from the nav. The video player still
plays the raw MP4; the segment list on the side is the timing
reference. Users who want a styled, platform-formatted MP4 export in
DaVinci/Premiere/etc.

client.ts and types.ts lose the wrappers/types for the deleted style
and process endpoints."
```

---

### Task 5: Delete config files

**Files:**
- Delete: `config/platforms.yaml`, `config/subtitle_styles.yaml`
- Modify: `config/config.example.yaml`

- [ ] **Step 5.1: Delete the configs**

```bash
git rm config/platforms.yaml config/subtitle_styles.yaml
```

- [ ] **Step 5.2: Clean `config/config.example.yaml`**

Open `config/config.example.yaml`. Search for any sections referencing `platforms`, `subtitle_styles`, `subtitle_style`, `process`. Delete those sections. The surviving sections cover: API endpoints, OCR settings, TTS settings, translation profiles, etc.

After editing, make sure the file is still valid YAML:

```bash
python -c "import yaml; yaml.safe_load(open('config/config.example.yaml').read())" && echo OK
```

Expected: `OK`.

- [ ] **Step 5.3: Verify no surviving code reads the deleted configs**

```bash
grep -rn "platforms.yaml\|subtitle_styles.yaml" src/ tests/ ui-app/src/ 2>&1
```

Expected: empty. If hits remain, they're dead code paths — resolve.

- [ ] **Step 5.4: Commit**

```bash
git add -A
git commit -m "chore(config): delete platforms.yaml and subtitle_styles.yaml

Per-platform output specs and ASS subtitle styling configs are no
longer read by any surviving code. config.example.yaml's platforms
section also removed (clean YAML)."
```

---

### Task 6: Delete tests for deleted code; clean up the ignore list

The Task 1.6 / 2.4 / 3.6 test runs all used a manual `--ignore` list. Now those tests get deleted, and the full suite should pass with no ignores.

**Files:**
- Delete: `tests/test_processor.py`, `tests/test_export_style.py`, `tests/test_style_spec.py`, `tests/test_style_render.py`, `tests/test_subtitle_replacement.py`, `tests/test_preview_mix_endpoint.py`

- [ ] **Step 6.1: Delete the test files**

```bash
git rm tests/test_processor.py tests/test_export_style.py tests/test_style_spec.py tests/test_style_render.py tests/test_subtitle_replacement.py tests/test_preview_mix_endpoint.py
```

- [ ] **Step 6.2: Hunt for stragglers**

```bash
grep -rln "SubtitleStyleSpec\|style_matcher\|style_render\|SubtitleRegion\|region_detector\|select_subtitle_for_platform\|process_for_all_platforms\|FFmpegProcessor.burn_subtitles\|FFmpegProcessor.reformat_for_platform\|FFmpegProcessor.burn_and_reformat\|merge_subtitles\|_seconds_to_ass_timestamp\|break_long_lines\|build_background_overlay_filter\|build_background_drawtext_filter\|generate_subtitle_background_images\|postProcess\|postReplaceSubtitle\|getStyleSpec\|putStyleSpec\|getSubtitleStyles\|putSubtitleStyles\|getVideoStyle\|putVideoStyle\|deleteVideoStyle\|getExportProgress\|previewClip\|getPreviewFrameUrl" src/ tests/ ui-app/src/ 2>&1
```

Expected: empty. If any hits remain, investigate. Most should be inside docs/superpowers/ files (specs/plans of prior work) — those should also be considered but only flagged, not modified (specs are historical record).

If the grep finds any `from src.processor.X import Y` lines in surviving code where Y is a deleted symbol, fix those imports.

- [ ] **Step 6.3: Run the full BE suite (no ignores except the integration test)**

```bash
python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10
```

Expected: green. Compare test count to baseline (before this PR was ~370 passed; after this PR should be ~300 passed — roughly 70 tests went with the deleted files).

If anything fails, investigate. Don't add to the ignore list — delete the failing test if its target is gone, or fix it if it's a legitimate regression.

- [ ] **Step 6.4: Full FE suite + build**

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: green; build succeeds (modulo the two pre-existing errors).

- [ ] **Step 6.5: BE lint**

```bash
ruff check src/ tests/ 2>&1 | tail -10
```

Expected: count of errors should be ≤ the count before this PR.

- [ ] **Step 6.6: Commit**

```bash
git add -A
git commit -m "test: delete tests for deleted export/style/replacement code

Removed: test_processor.py, test_export_style.py, test_style_spec.py,
test_style_render.py, test_subtitle_replacement.py,
test_preview_mix_endpoint.py.

These all targeted modules and endpoints removed in the previous
commits. Full BE suite now runs without any --ignore beyond the
integration test that needs Docker."
```

---

### Task 7: CHANGELOG + README

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 7.1: CHANGELOG entry**

In `CHANGELOG.md`, find `## [Unreleased]`. Add a new `### Removed` subsection above any existing `### Added` / `### Fixed`:

```markdown
### Removed
- **Per-platform video export pipeline.** The app no longer burns subtitles into videos or reformats per platform. Users export the SRT + dub WAV and assemble the final video in their own tool (DaVinci, Premiere, etc.). Deletions: the entire `src/processor/` style/burn-in code (`SubtitleStyleSpec`, `style_render.py`, `style_matcher.py`, `region_detector.py`), the `processor/ffmpeg.py` burn/reformat/blur/mix methods (kept `get_video_info`, `extract_frames`, `generate_proxy` for OCR + editor proxy), most of `processor/subtitle.py` (kept `parse_srt` + `write_srt`), `src/api/routers/process.py`, `src/api/routers/replacement.py`, the style and preview-frame/clip handlers in `editor.py`, the Process stage in the pipeline orchestrator, the `--platforms` CLI flag, `ExportTab`, `StylePanel`, `SubtitleRenderer`, `diffSpec` and their tests, `config/platforms.yaml`, `config/subtitle_styles.yaml`, and ~70 corresponding pytest tests. Roughly −2500 lines net. Sub-project 1 of 3 in the post-merge refocus; sub-projects 2 (SRT import → version snapshot) and 3 (standalone SRT→Dub tool) follow.
```

- [ ] **Step 7.2: README progress section**

In `README.md`, find the most recent progress subsection (probably "Dub-Shortening Toggle (2026-05-29)" or "Subtitle Versioning + Dub-Version Picker (2026-05-29)"). Insert this new subsection immediately after it (before the next `---` or section break):

```markdown
### App Refocus — Drop Export Pipeline (2026-05-30)

> Sub-project 1 of 3 in the post-merge refocus. See [`docs/superpowers/specs/2026-05-30-app-refocus-drop-export-design.md`](docs/superpowers/specs/2026-05-30-app-refocus-drop-export-design.md) and [`docs/superpowers/plans/2026-05-30-app-refocus-drop-export.md`](docs/superpowers/plans/2026-05-30-app-refocus-drop-export.md).

- [x] **Task 1** — Slim `src/processor/`: `ffmpeg.py` keeps `get_video_info`/`extract_frames`/`generate_proxy`; `subtitle.py` keeps `parse_srt`/`write_srt`. Delete `style.py`, `style_render.py`, `style_matcher.py`, `region_detector.py`, the CLAUDE.md.
- [x] **Task 2** — Delete `src/api/routers/process.py` and `src/api/routers/replacement.py`; strip style + preview-frame/clip handlers from `editor.py`.
- [x] **Task 3** — Drop the Process stage from `src/pipeline.py` (TTS now covers 0.60–1.00) and the `--platforms` CLI flag from `src/cli.py`.
- [x] **Task 4** — Delete `ExportTab`, `StylePanel`, `SubtitleRenderer`, `diffSpec` and their tests. Strip them from `EditorTab.tsx` and `VideoDetail.tsx`. Clean style/process clients from `api/client.ts`.
- [x] **Task 5** — Delete `config/platforms.yaml` and `config/subtitle_styles.yaml`; clean `config.example.yaml`.
- [x] **Task 6** — Delete `tests/test_processor.py`, `test_export_style.py`, `test_style_spec.py`, `test_style_render.py`, `test_subtitle_replacement.py`, `test_preview_mix_endpoint.py`. Full BE suite runs without `--ignore`.
- [x] **Task 7** — CHANGELOG + README updates.

**Not in this PR:** sub-project 2 (SRT import → new version snapshot) and sub-project 3 (standalone SRT → Dub tool). Separate specs + PRs.

**Post-merge cleanup (manual, one-time):** these directories/files are no longer read by the app; safe to delete to reclaim disk:
- `data/output/` (per-platform MP4s)
- `data/preview/` (preview frames + clips)
- `data/*_style.json` (per-video style deltas)
```

- [ ] **Step 7.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(refocus): CHANGELOG + README rollup for the export-pipeline drop"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

```bash
python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10
```

Expected: green. Test count ~300 (was ~370 before this PR).

- [ ] **Step F.2: Full FE suite**

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
```

Expected: green. Test file count one less than before (SubtitleRenderer.test.tsx gone).

- [ ] **Step F.3: FE build is clean**

```bash
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: succeeds (modulo the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).

- [ ] **Step F.4: BE lint**

```bash
ruff check src/ tests/ 2>&1 | tail -5
```

Expected: error count ≤ baseline.

- [ ] **Step F.5: Sanity grep — nothing references deleted modules**

```bash
grep -rln "from src.processor.style\|from src.processor.style_render\|from src.processor.style_matcher\|from src.processor.region_detector\|select_subtitle_for_platform\|process_for_all_platforms" src/ tests/ ui-app/src/ 2>&1
```

Expected: empty (ignore `docs/superpowers/` hits — those are historical specs/plans).

- [ ] **Step F.6: Manual smoke (after merge)**

1. Start the app: `make api` and `make ui` (or via Docker). Open a video in the UI.
2. **Subtitle tab**: segment list renders. Video player plays the raw MP4 (no subtitle overlay). Save / Save as version still work. The Export tab is gone from the page nav — only Subtitle and Dub remain.
3. **Dub tab**: unchanged from previous PRs. Generate / download work.
4. **CLI**: `python -m src process URL` runs Download → Transcribe → Translate → TTS and ends. No "Process" stage logged. No `--platforms` flag accepted (will error if passed).
5. Verify `data/output/` is never written to during a pipeline run.

---

## Self-review checklist (for the implementer)

- [ ] Each spec requirement maps to a task: `processor/` slim (T1), routers (T2), pipeline + CLI (T3), FE export surface (T4), configs (T5), test deletions (T6), docs (T7).
- [ ] No "TBD" / "implement later" / "similar to Task N" in any step.
- [ ] No AI-attribution strings in any commit message.
- [ ] Branch stays `feature/app-refocus-drop-export`; no new branches.
- [ ] After Task 6, the test suite runs without the long `--ignore` list (only the integration test stays ignored).
- [ ] `parse_srt` and `write_srt` are still at `src/processor/subtitle.py` and all their callers (translator, TTS runner, transcribe router) work unchanged.
- [ ] `FFmpegProcessor` survives at `src/processor/ffmpeg.py` with just OCR + proxy methods; OCR works; editor's `/proxy` endpoint works.
