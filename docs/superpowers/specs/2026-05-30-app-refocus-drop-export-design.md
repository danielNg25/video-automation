# App Refocus — Drop the Per-Platform Export Pipeline

> **Sub-project 1 of 3** in the post-merge refocus. Sub-project 2 (SRT import → new version) and sub-project 3 (standalone SRT→Dub tool) get their own specs and PRs after this lands.

## Goal

Remove the per-platform video export pipeline and everything that supports it (subtitle styling, ExportTab, per-platform configs, `processor/` module). After this PR, the app is **download → transcribe → translate → dub**, with the user downloading the SRT + dub WAV and assembling the final video in their own tool (DaVinci, Premiere, etc.).

## Why

The app's value is the Douyin-specific pipeline: scraping a closed-platform video, extracting burned-in subtitles via OCR, LLM translation, and multi-provider dubbing with timing-aware planner/atempo. That's the unique part. The export step — burn-in + reformat per platform — is well-served by external tools, and the in-app version requires a styling system that has accumulated a lot of code with limited payoff. Drop it; let the user export in DaVinci.

The pipeline's `Process` stage is already a no-op as of an earlier change ([src/pipeline.py:275](src/pipeline.py#L275) — comment says "skipped, export via Video Studio"), so the deletion has already started; this spec finishes the job and removes the dead surface area in the FE + the style system.

## Non-goals

- **No change to the existing editor's "preview" surface** — the user explicitly asked to keep it for visual verification. Segment list, video playback, text editing, add/delete/split/merge, the versioning system from PR #19, and the DubTab all stay.
- **No replacement for what we delete.** Users wanting a styled, platform-formatted MP4 use DaVinci/Premiere/CapCut/etc.
- **No CLI behavior reduction beyond what the pipeline already does.** `python -m src process URL` still runs download → transcribe → translate → TTS; the `--platforms` flag is removed because there's nothing to format for.
- **Sub-projects 2 and 3** (SRT import + standalone SRT→Dub tool) are out of scope.

## Architecture

This is a deletion-heavy spec. The new app shape is:

```
Pipeline stages:   Download  →  Transcribe (OCR)  →  Translate (LLM)  →  TTS (assembler + planner + atempo)
                                                                              │
                                                                              ▼
Outputs:                       data/raw/{id}.mp4              data/srt/{id}_{lang}.srt
                                                              data/tts/{id}_{lang}_{ver}_{provider}_{voice}.wav
Per-video UI:      Subtitle tab (segments + version panel) + Dub tab (picker + audio library)
                                                              ↑
                                                              user downloads SRT + WAV here
```

Everything between the pipeline outputs and the platform-specific MP4 disappears. The user assembles the final video themselves.

## What goes

### Backend deletions

- `src/processor/__init__.py` — `process_for_all_platforms` and friends
- `src/processor/ffmpeg.py` — `FFmpegProcessor` class (burn / reformat / preview-clip)
- `src/processor/style.py` — `SubtitleStyleSpec` Pydantic schema + loader + migrator
- `src/processor/style_render.py` — ASS file + PNG overlay rendering
- `src/processor/subtitle.py` — keep `parse_srt` and `write_srt` (the editor + dub planner need them); delete `_seconds_to_ass_timestamp`, `break_long_lines`, `merge_subtitles`, `select_subtitle_for_platform`, `build_background_overlay_filter`, `build_background_drawtext_filter`, `generate_subtitle_background_images`, and everything else style/burn-in-related. The two SRT IO helpers move to `src/utils/srt_io.py` so the `processor/` directory can be removed entirely; the `processor/` package is deleted.
- `src/processor/CLAUDE.md` — deleted with the directory
- `src/api/routers/process.py` — the `/api/videos/{id}/process` and `/api/videos/{id}/preview-mix` routes; the latter's caller in EditorTab was already removed in PR #19, so the route is fully orphaned
- `src/api/routers/replacement.py` — the subtitle-replacement flow that bakes a new SRT into a video; superseded by "edit SRT externally + assemble in DaVinci"
- The "Process" stage in `src/pipeline.py:275-302`. Drop the stage entry from `STAGE_PROGRESS_RANGES` and replace the "stage complete" emit with a clean pipeline-end emit. Re-spread the progress ranges so TTS covers 0.70..1.00.
- The `--platforms` CLI flag in `src/cli.py` (if present); the `process` command's signature drops platform-related kwargs.
- `src/api/__init__.py` — drop the `app.include_router(process_router.router)` and the `replacement_router` line (if present)
- BE style endpoints under `src/api/routers/editor.py` — `GET/PUT/DELETE /api/videos/{id}/style` and `GET/PUT /api/subtitle-styles` and the `preview_frame` route (it served styled-burn-in previews) and `preview_clip`. These all depend on `SubtitleStyleSpec` and the burn-in machinery.

### Frontend deletions

- `ui-app/src/pages/videoDetail/ExportTab.tsx` — the export tab UI
- `ui-app/src/components/editor/StylePanel.tsx`
- `ui-app/src/components/editor/SubtitleRenderer.tsx` — the styled overlay on the video player. Replaced by **nothing** — the editor's segment list is sufficient for verifying timing; the video plays without subtitle overlays.
- `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx` — tests for the deleted renderer
- `ui-app/src/utils/diffSpec.ts` and `ui-app/src/utils/__tests__/diffSpec.test.ts` — utility for diffing `SubtitleStyleSpec`, no longer needed
- Any client-side type defs for `SubtitleStyleSpec`, style-related fields on `Video`, `Platform`, etc. (`ui-app/src/api/types.ts`)
- Style-related API client functions in `ui-app/src/api/client.ts` (e.g. `getStyleSpec`, `putStyleSpec`, `getVideoStyle`, `putVideoStyle`, `deleteVideoStyle`, `getSubtitleStyles`, `putSubtitleStyles`, `getExportProgress`, `postProcess`, `getPreviewMixUrl` if it survived, the preview-frame and preview-clip clients)
- `ui-app/src/pages/videoDetail/EditorTab.tsx` — large simplification: drop the entire StylePanel rendering, the per-video-style state (`draftSpec`, `savedSpec`, `globalDefault`, `setDraftSpec`, etc.), the `handleRealignToOcr` callback, the dual `handleSave` (which currently does SRT + style in one transaction — becomes SRT-only). The Subtitle tab's "Save" button just writes the working draft.
- The "Export" tab itself in the per-video page nav (`ui-app/src/pages/VideoDetail.tsx` — remove the ExportTab import + route entry)

### Config deletions

- `config/platforms.yaml` — per-platform specs (resolution, CRF, max duration, etc.)
- `config/subtitle_styles.yaml` — default ASS styling
- Mentions in `config/config.example.yaml` of platforms or styles (clean up)

### Data directory deletions (optional in the PR; mention as a manual cleanup step)

- `data/output/` — per-platform MP4s
- `data/preview/` — preview frames + clips
- `data/{video_id}_style.json` — per-video style deltas

The PR doesn't `rm` user data; instead the README adds a "post-merge cleanup" note.

### Tests deletions

- `tests/test_processor.py` — covered the deleted `processor/` module
- `tests/test_export_style.py` — covered the per-spec export integration test
- `tests/test_style_spec.py` — covered `SubtitleStyleSpec`
- `tests/test_style_render.py` — covered `style_render.py`
- `tests/test_subtitle_replacement.py` — covered `src/api/routers/replacement.py`
- Any other test files that imported any of the deleted modules

After deletions, run `python -m pytest tests/ -x` and clean up any residual import errors in tests/ that didn't get deleted explicitly but referenced something now gone.

## What stays

- All download/transcribe/translate/TTS code (`src/downloader/`, `src/transcriber/`, `src/translator/`, `src/tts/`)
- All versioning code from PR #19 (`src/api/versions.py`, `src/api/routers/versions.py`, the FE picker/panel/hook)
- The Subtitle editor UI for **viewing + editing text + adjusting timestamps + add/delete/split/merge + save + save as version** (PR #17 work)
- The Dub tab (picker + audio library + generation)
- The pipeline orchestrator's first four stages (Download → Transcribe → Translate → TTS)
- `parse_srt` and `write_srt` (relocated to `src/utils/srt_io.py`)
- All the API endpoints that don't depend on the export pipeline

## Code surface after refocus

| Module | Lines after | Role |
|---|---|---|
| `src/downloader/` | unchanged | Douyin API + yt-dlp |
| `src/transcriber/` | unchanged | OCR pipeline |
| `src/translator/` | unchanged | LLM + profiles |
| `src/tts/` | unchanged | assembler + planner + atempo + providers |
| `src/processor/` | **DELETED** | — |
| `src/utils/srt_io.py` | new (~80) | extracted `parse_srt` + `write_srt` |
| `src/pipeline.py` | -30 lines | 4 stages instead of 5; clean progress ranges |
| `src/api/routers/process.py` | **DELETED** | — |
| `src/api/routers/replacement.py` | **DELETED** | — |
| `src/api/routers/editor.py` | ~-200 lines | drop style + preview-frame/clip handlers |
| `src/api/routers/versions.py` | unchanged | |
| `src/api/routers/tts.py` | unchanged | |
| `src/api/routers/transcribe.py` | unchanged | |
| `src/api/routers/translate.py` | unchanged | |
| `src/api/routers/download.py` | unchanged | |
| `ui-app/src/pages/videoDetail/ExportTab.tsx` | **DELETED** | — |
| `ui-app/src/components/editor/StylePanel.tsx` | **DELETED** | — |
| `ui-app/src/components/editor/SubtitleRenderer.tsx` | **DELETED** | — |
| `ui-app/src/pages/videoDetail/EditorTab.tsx` | ~-300 lines | drop style state, dual-save → SRT-only, drop renderer import |
| `ui-app/src/pages/VideoDetail.tsx` | -20 lines | drop ExportTab import + tab nav entry |
| Tests | net -300 to -500 lines | delete the dead test files |

Net expected: ~-2000 to -3000 lines of code, +80 (new `srt_io.py`).

## Migration notes

- Existing `data/{video_id}_style.json` files become orphaned but harmless. README adds a one-liner: "Safe to delete `data/*_style.json` after this update — they're no longer read."
- Existing `data/output/*` files are orphaned. Same note.
- `data/preview/*` files are orphaned. Same note.
- No DB migration. No schema change.
- Users currently mid-pipeline (with a video in the "process" stage) — the stage is already a no-op, so they're fine.

## Tests

This is a deletion PR. The verification surface is:

1. `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py` — full BE suite passes. Expected ~50-100 fewer tests than today (since the deleted modules took their tests with them). No regressions in the surviving tests.
2. `cd ui-app && npx vitest run` — full FE suite passes. Expected one less test file (SubtitleRenderer). The remaining tests cover SegmentList, VersionPicker, VersionPanel, DubTab, useVersions, StopButton — all untouched by this PR.
3. `cd ui-app && npm run build` — build succeeds with no new errors. Pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may still be there; not in scope.
4. `ruff check src/ tests/` — no new errors.

Manual smoke test (after merge):
- Run `python -m src process URL` end-to-end → pipeline runs Download → Transcribe → Translate → TTS and ends. No Process stage logged; no `data/output/` files created.
- Open a video in the UI → Subtitle tab renders the segment list + video player (no subtitle overlay, no style panel). Save / Save as version still work.
- Dub tab renders the version picker, audio library, all controls. Generate Dub still produces a `_v{N}_{provider}_{voice}.wav` and adds it to the library.
- Verify the Export tab is gone from the page nav.

## Out of scope (next PRs)

- **Sub-project 2:** SRT import → creates new version snapshot. New endpoint + button on the Subtitle tab.
- **Sub-project 3:** Standalone "SRT → Dub" tool — separate page, upload SRT, generate dub, download WAV. Stateless-ish (recent dubs list).

## Critical files (the deletion targets, for the implementer)

- BE delete: `src/processor/` (entire dir), `src/api/routers/process.py`, `src/api/routers/replacement.py`
- BE modify: `src/pipeline.py` (drop Process stage), `src/api/routers/editor.py` (drop style/preview routes), `src/api/__init__.py` (drop router registrations), `src/cli.py` (drop `--platforms`)
- BE move: `src/processor/subtitle.py` `parse_srt`/`write_srt` → `src/utils/srt_io.py`
- BE config delete: `config/platforms.yaml`, `config/subtitle_styles.yaml`
- FE delete: `ui-app/src/pages/videoDetail/ExportTab.tsx`, `ui-app/src/components/editor/StylePanel.tsx`, `ui-app/src/components/editor/SubtitleRenderer.tsx`, `ui-app/src/utils/diffSpec.ts` and their tests
- FE modify: `ui-app/src/pages/videoDetail/EditorTab.tsx` (drop style + dual-save), `ui-app/src/pages/VideoDetail.tsx` (drop ExportTab nav), `ui-app/src/api/client.ts` (drop style + process clients), `ui-app/src/api/types.ts` (drop style types)
- Tests delete: `tests/test_processor.py`, `tests/test_export_style.py`, `tests/test_style_spec.py`, `tests/test_style_render.py`, `tests/test_subtitle_replacement.py`
- CHANGELOG + README rollup
