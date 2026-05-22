# Pipeline Page Cleanup + Dubsync as Default Subtitle

**Status:** Draft — ready for implementation planning
**Date:** 2026-05-21
**Scope:** `ui-app/src/pages/DownloadTranscribe.tsx` (major refactor), `ui-app/src/pages/SubtitleEditor.tsx` (warning banner), `src/api/routers/transcribe.py` (prefer dubsync), `src/api/routers/editor.py` (write to dubsync when present), `tests/`.

## Problem

Two unrelated user-facing concerns surfaced after the TTS providers cleanup landed.

**1. Pipeline page feels messy.** The current `DownloadTranscribe.tsx` (~897 lines) renders a 5-step stepper with numbered circles, connector lines, and per-step expansion panels. Steps 1, 2, and 5 (Download, Transcribe, Process) contain mostly informational text with no actual user config — they take vertical space without giving the user anything to do. Step 4 (TTS) has 7+ fields stacked (provider, voice profile, voice picker, voice preview, API-key warning, playback speed, underlay, info text). The visual ceremony is heavy for what's effectively "set three dropdowns and click Run."

**2. The dub-synced subtitle isn't surfaced in the UI.** `{video_id}_{lang}.dubsync.srt` (text matches what was actually spoken in the dub; timings re-anchored to dub positions) is preferred by the burn-in step (Task 10 of the dubbing redesign) but the GET/PUT SRT endpoints serving the in-app preview, the Download SRT button, and the Subtitle Editor all hardcode `{video_id}_{lang}.srt`. Users see and edit the pre-dub translation, not the version that matches the audio.

## Goals

In priority order:

1. **Simplify the pipeline page** — keep all current configuration capability, but as a flat compact form. Drop the 5-step stepper UI entirely. Move advanced settings behind a single "Advanced" toggle.
2. **Default to dubsync** — when `{id}_{lang}.dubsync.srt` exists, the GET endpoint returns it, the download endpoint serves it, and the editor edits it. Add a warning banner in the editor when editing a dubsync file.
3. **Preserve all current functionality** — single-URL and batch modes, batch concurrency control, download-only button, run-pipeline button, error banner, video library, all existing config inputs.
4. **No surprises during a run** — replace the running-stepper visualization with a compact progress strip that shows the current stage name and overall percentage. Pipeline-stage progress is still visible; just less chrome.

## Non-goals

- Settings page changes. The TTS Dubbing section in Settings (playback speed, underlay) stays where it is.
- New features beyond the redesign — no batch templating, no per-video config overrides, no saved presets.
- Backend changes outside the SRT-serving endpoints. The pipeline runner, task manager, processor, planner, and assembler are not touched.
- Visual tokens / theme. Use the existing surface / primary / outline-variant tailwind classes already in use elsewhere.

## Part 1 — Pipeline Page Redesign (Option A: Compact form)

### Current structure (to be replaced)

```
URL Input card          (keep)
Error banner            (keep)
Pipeline Stepper card   (DELETE):
  Step 1: Download      (no config — just info text)
  Step 2: Transcribe    (no config — just OCR info)
  Step 3: Translate     Translation profile + LLM Backend + Model + API-key warning
  Step 4: TTS           Provider + Voice profile + Voice picker + Preview + API-key warning
                        + Playback speed + Underlay + Info text
  Step 5: Process       Blur toggle + Subtitle Burn-in info + Platform reformat info
Video Library           (keep)
```

### New structure

```
URL Input card                 (keep, unchanged)
Error banner                   (keep, unchanged)
Configuration card             (NEW — replaces the stepper)
Running progress strip         (NEW — only visible while a pipeline is running)
Video Library                  (keep, unchanged)
```

### Configuration card layout

The card has three rows of essentials plus a collapsible Advanced section. Provider+voice get larger weight (they're the primary user choice on each run); other fields get a single grid row.

```
┌─ Configuration ────────────────────────────────────────────────────────┐
│                                                                        │
│  Translation Profile [Vietnamese ▾]    LLM Backend [DeepSeek ▾]       │
│                                                                        │
│  TTS Provider [Google ▾]   Voice [vi-VN-Wavenet-A ▾]   [▶ Preview]   │
│                                                                        │
│  ⚙ Advanced settings  ▼                                                │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │ Playback speed  [1.5 ×]                                          │ │
│  │ Original underlay  [-18 dB ▾]                                    │ │
│  │ LLM model  [DeepSeek V3 ▾]                                       │ │
│  │ Blur original subtitles  [ON ●]                                  │ │
│  │ ElevenLabs Voice ID  [____________] [Save]   (only if EL chosen) │ │
│  └──────────────────────────────────────────────────────────────────┘ │
│                                                                        │
│  [⚠ No API key configured for google — Configure]   (when applicable) │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

**Visual notes:**

- Card uses the existing `bg-surface-container-low rounded-xl` pattern from the URL card.
- Section heading "Configuration" in the same uppercase tracking-widest style as "Source URL".
- Field labels use the existing `text-[10px] text-zinc-500 uppercase tracking-tighter font-bold` style.
- Inputs / selects use the existing `bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary` style.
- Advanced toggle: a single text button "⚙ Advanced settings ▾" that expands the panel inline (chevron rotates).
- Voice preview button: the existing `<TTSPreview>` component, rendered next to the Voice select (already wired in the current code — just moved into the new layout).
- Missing-API-key banner: the existing amber banner pattern, rendered at the bottom of the card when applicable.

### Running progress strip (replaces the running-stepper visualization)

When `isPipeline === true`, render a thin progress strip in place of the configuration card OR above the video library. Single row showing:

```
[████████░░░░░░░] 43%  Stage 3 of 5 — Translating (segment 12/47)
```

Implementation: a flex row with a slim progress bar (existing pattern in the URL card's batch progress), the percent number (existing `text-primary` style), and the stage name + message from `pipelineMessage` / `pipelineStage`. No expansion, no per-stage circles. The configuration card can either be hidden during a run, or shown collapsed/dimmed. Pick **hidden** (cleaner) — the user can't change config mid-run anyway.

When `isPipeline === false`, the strip is not rendered; the configuration card is back.

### What gets DELETED

Specific JSX deletions from `DownloadTranscribe.tsx`:

- The `const steps = [...]` array (currently defined around line 350).
- The `getStepState`, `toggleStep`, `expandedStep`, `setExpandedStep` state + handlers.
- The entire Pipeline Stepper `<div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">` block (currently lines ~462-827).
- The per-step info text strings (download "no configuration needed", transcribe "OCR via PaddleOCR", process "blur+burn+reformat in a single ffmpeg pass").
- The Process step's three info boxes (Blur, Subtitle Burn-in, Platform Reformat).

### What gets KEPT, RELOCATED

All form fields move from inside step-expansion panels into the new Configuration card:

| Field | Was in step | Moves to |
|---|---|---|
| Translation Profile | Translate (3) | Top row, column 1 |
| LLM Backend | Translate (3) | Top row, column 2 |
| LLM Model | Translate (3) | Advanced panel |
| TTS Provider | TTS (4) | Middle row, column 1 |
| Voice Profile | TTS (4) | (folded into Voice picker — profile drives provider+language defaults but not voice anymore since Task 5 wired per-provider voice override) |
| Voice (Google/OpenAI dropdown) | TTS (4) | Middle row, column 2 |
| Voice ID input (ElevenLabs) | TTS (4) | Advanced panel (only renders when provider === 'elevenlabs') |
| Voice Preview button | TTS (4) | Inline with Voice (middle row, column 3) |
| Playback Speed | TTS (4) | Advanced panel |
| Original Underlay | TTS (4) | Advanced panel |
| Blur original subs toggle | Process (5) | Advanced panel |
| TTS API-key warning | TTS (4) | Bottom of card (existing amber banner pattern) |
| LLM API-key warning | Translate (3) | Bottom of card |

Note on Voice Profile: in the current code, the voice profile (`female-vi-natural`, `male-vi-natural`, etc.) bundles `(provider, voice, language, speed, pitch)`. After Task 5 (voice picker), the per-run UI lets the user override provider + voice independently. The profile name still matters for `language` (so the preview picks vi or en) and as a backend identifier. **Decision**: keep the Voice Profile dropdown in the Advanced panel; it pre-populates Voice and Provider when changed but the user's last override wins. If the user always picks Provider + Voice manually, they never need to touch Voice Profile.

### What ABOUT the Voice Profile selector?

Re-evaluating: every shipped profile now has `provider: google` (Task 3 of the providers cleanup). So Voice Profile dropdown options like `female-vi-natural` and `male-vi-natural` differ only in `voice` (Wavenet-A vs Wavenet-B) and `language` (vi vs en). The Provider + Voice + Language are already covered by the new compact form's direct controls.

**Decision**: drop the Voice Profile dropdown from the UI entirely. The backend still receives a profile name (the API still requires one), so we resolve it implicitly from the user's selected language: `female-vi-natural` for Vietnamese, `female-en-natural` for English. If the user wants male voices, they pick the `Wavenet-B` or `Wavenet-D` voice — the profile name is now an internal identifier, not a user-facing choice.

This is a meaningful simplification (one less dropdown to explain). The backend already accepts `voice` as an override that beats the profile's voice, so this works out of the box.

### TypeScript / file size impact

Estimated diff: ~400 lines deleted from `DownloadTranscribe.tsx`, ~150 lines added. Final file size around 650 lines (from 897).

## Part 2 — Dubsync as Default Subtitle

### Current state

- `src/processor/subtitle.py::select_subtitle_for_platform` (line 508 — burn-in path) already prefers `{video_id}_{lang}.dubsync.srt`. ✓
- `GET /api/videos/{id}/srt?language=vi` (`src/api/routers/transcribe.py:81`) — hardcoded to `{video_id}_{language}.srt`. ✗
- `GET /api/videos/{id}/srt/download?language=vi` — same. ✗
- `PUT /api/videos/{id}/srt` (`src/api/routers/editor.py:130`) — writes to `{video_id}_{language}.srt`. ✗

### Required changes

**`src/api/routers/transcribe.py`** — both GET endpoints add a helper that picks dubsync when present:

```python
def _resolve_srt_path(video_id: str, language: str) -> Path:
    """Return dubsync.srt if it exists for this language, else the legacy SRT."""
    srt_dir = Path("data/srt")
    dubsync = srt_dir / f"{video_id}_{language}.dubsync.srt"
    if dubsync.exists():
        return dubsync
    return srt_dir / f"{video_id}_{language}.srt"
```

Both `get_srt` and `download_srt` use this helper. The download endpoint preserves the *download filename* as `{video_id}_{language}.srt` (without the `.dubsync` infix) so the user sees a clean filename — but the contents are from the dubsync file when present.

**`src/api/routers/editor.py::PUT /api/videos/{id}/srt`** — apply the same resolver. If a dubsync file exists, editor saves write there. Otherwise the legacy SRT.

**Response shape** — `SrtResponse` already exists. Add an optional field `is_dubsync: bool` so the UI can render the editor warning banner only when applicable.

```python
class SrtResponse(BaseModel):
    video_id: str
    segments: list[SubtitleSegment]
    language: str
    is_dubsync: bool = False   # NEW — true when the served file is the dubsync derivative
```

The endpoint sets `is_dubsync=True` when `_resolve_srt_path` returned the dubsync file.

**`ui-app/src/pages/SubtitleEditor.tsx`** — when `srt.is_dubsync` is true, render an amber warning banner at the top:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ⚠  You're editing the dub-synced subtitle. Re-running TTS will         │
│    regenerate this file and lose your manual edits. Edit the original  │
│    translated subtitle (data/srt/{id}_{lang}.srt) for changes that     │
│    survive re-runs.                                                     │
└─────────────────────────────────────────────────────────────────────────┘
```

**API client typing** — the TS `SrtResponse` type in `ui-app/src/api/client.ts` (or wherever it lives) gains an `is_dubsync?: boolean` field.

## Tests

### Pipeline page redesign

UI changes; no automated tests in this repo for React components. Manual verification:

- All previous configuration values still flow to the pipeline POST body (compare network tab before/after).
- Advanced panel collapse / expand works.
- Missing-API-key warning shows when the selected provider's key is unset.
- ElevenLabs Voice ID input only renders when provider is ElevenLabs.
- Running a pipeline replaces the configuration card with the slim progress strip.
- Pipeline completes — configuration card returns.
- Batch mode (>1 URL) shows the concurrency slider in the URL card; the configuration card stays the same.

### Dubsync default

`tests/test_api.py` (or wherever transcribe / editor tests live — grep `pytest tests/test_*.py -k srt`):

```python
def test_get_srt_prefers_dubsync(tmp_path, ...):
    # Create both files in data/srt/
    # GET /api/videos/{id}/srt?language=vi
    # Assert response.json()["is_dubsync"] is True
    # Assert segments came from the dubsync file (distinct text)

def test_get_srt_falls_back_to_legacy(tmp_path, ...):
    # Create only the legacy SRT (no dubsync)
    # GET /api/videos/{id}/srt?language=vi
    # Assert response.json()["is_dubsync"] is False
    # Assert segments came from the legacy SRT

def test_download_srt_serves_dubsync_with_clean_filename(tmp_path, ...):
    # Create both files
    # GET /api/videos/{id}/srt/download?language=vi
    # Assert Content-Disposition filename is "{id}_vi.srt" (NOT "{id}_vi.dubsync.srt")
    # Assert body matches the dubsync file contents

def test_put_srt_writes_to_dubsync_when_present(tmp_path, ...):
    # Create both files
    # PUT /api/videos/{id}/srt with new segments
    # Assert dubsync.srt was overwritten
    # Assert legacy SRT is unchanged
```

## Migration

- No backend data migration needed. Existing `data/srt/{id}_{lang}.dubsync.srt` files from prior runs are automatically picked up by the new endpoints.
- No frontend localStorage migration needed.
- Anyone with `expandedStep` state saved in sessionStorage / localStorage from the deleted stepper UI will have a dead key; not worth a migration since the state was per-session anyway.

## Open Questions

None at draft time. Voice profile dropdown removal was decided in the design discussion above (effectively redundant after Task 5 + Task 3 of the providers cleanup).
