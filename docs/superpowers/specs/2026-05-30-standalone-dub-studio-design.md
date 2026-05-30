# Standalone SRT → Dub Studio

> **Sub-project 3 of 3** — the final piece of the post-refocus app. Sub-projects 1 (drop export pipeline, PR #20) and 2 (SRT import in video flow, PR #21) merged.

## Goal

Add a standalone "Dub Studio" page where the user uploads an SRT file (no video, no project binding), picks TTS provider/voice/language/speed/shorten-toggle, generates a dub, and downloads the WAV. Recent dubs persist on disk with a small metadata sidecar so the user can come back and re-download.

## Why

The refocused app's promise is: **bring your own video, get a SRT + dub WAV, assemble elsewhere**. But sometimes the user already has an SRT from another source (a different video, a hand-written script, a translation done outside the app) and just wants a dub from it. The standalone tool serves that case without forcing them to create a fake "video" first.

## Non-goals

- No per-segment voice overrides (one voice for the whole track).
- No custom voice cloning — uses existing TTS providers (Google / OpenAI / ElevenLabs).
- No batch uploads (one SRT at a time).
- No editing the SRT in the UI — it's one-shot. To retry, re-upload.
- No version snapshots — each generation is a one-shot artifact.
- No quota / no automatic cleanup. User manages disk; delete buttons available per row.

## Architecture

A new top-level page at `/dub-studio`, served by `ui-app/src/pages/DubStudio.tsx`, lists recent dubs and offers an upload+configure form. A new BE module `src/api/standalone_dub.py` owns IO + a thin wrapper around the existing `assembler.generate_full_track` (already capable of running without a source video — `video_id` and `underlay_db` are kept-for-back-compat parameters, no source-video coupling). A new router `src/api/routers/standalone_dub.py` exposes `POST` / `GET` / `DELETE` plus a download endpoint. SSE progress reuses the existing `subscribe(task_id)` machinery on `TaskManager`.

```
Browser → POST /api/standalone-dub (multipart: srt file + tts params)
        → returns {task_id}
        → SSE /api/tasks/{task_id} (existing) streams progress
        → on complete, GET /api/standalone-dub lists the new entry
        → download via /api/standalone-dub/{uuid}.wav
        → optional DELETE /api/standalone-dub/{uuid}
```

Storage:

```
data/standalone_dubs/
    {uuid}.wav             # generated audio
    {uuid}.json            # {provider, voice, language, original_filename,
                           #  created_at, duration_seconds, playback_speed,
                           #  enable_shortening, file_size_bytes}
```

The `assembler.generate_full_track` runs identically to the video-flow case: parses segments, runs Stage 0 (LLM sentence merge if `llm_caller` provided), Stage 1 (synth per sentence), Stage 2 (planner), Stage 3 (`_apply_shortening` if `enable_shortening=True`), Stage 4 (atempo), Stage 5 (concat onto silence base). The underlay step is already a no-op in the current assembler — no source video, no underlay.

Video duration for the silence track: `max(segment.end for segment in segments) + 1.0` (1-second tail buffer so the last word doesn't get clipped).

## Backend

### `src/api/standalone_dub.py` (new)

```python
"""Standalone SRT → Dub orchestration.

Wraps the TTS assembler to produce a dub WAV from an uploaded SRT alone —
no source video, no project binding. Each invocation produces a single
{uuid}.wav + {uuid}.json metadata sidecar in data/standalone_dubs/.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

STANDALONE_DIR = Path("data/standalone_dubs")


@dataclass
class StandaloneDubEntry:
    """One generated dub's metadata sidecar."""
    uuid: str
    original_filename: str
    provider: str
    voice: str
    language: str
    playback_speed: float
    enable_shortening: bool
    duration_seconds: float
    created_at: datetime
    file_size_bytes: int


def list_dubs() -> list[StandaloneDubEntry]:
    """Return recent dubs newest-first by created_at. Scans every {uuid}.json
    in STANDALONE_DIR. Skips entries whose .wav has been deleted out of band."""


def delete_dub(dub_uuid: str) -> bool:
    """Remove both {uuid}.wav and {uuid}.json. Returns True on success,
    False if neither file existed."""


def wav_path(dub_uuid: str) -> Path:
    """Resolve the WAV path; caller checks exists()."""
    return STANDALONE_DIR / f"{dub_uuid}.wav"


def _meta_path(dub_uuid: str) -> Path:
    return STANDALONE_DIR / f"{dub_uuid}.json"
```

The orchestrator function that actually runs the dub lives on `TaskManager` (new method `run_standalone_dub`) since it needs the task lifecycle (`_emit`, `cancel_task`, the asyncio task handle pattern). Mirrors the existing `run_tts` shape.

`TaskManager.run_standalone_dub(task_id, srt_content, original_filename, provider, voice, language, playback_speed, enable_shortening, config, api_key_override, llm_api_key, llm_backend)`:

1. Generate `dub_uuid = uuid.uuid4().hex`.
2. Parse `srt_content` via `parse_srt` (write to temp file first, mirror `import_as_version`). Reject empty / unparseable with `ValueError` → task fails with `error_message`.
3. Compute `video_duration = max(seg["end"] for seg in segments) + 1.0`.
4. Build the TTS provider via existing `get_tts_provider`. Build the LLM translator via existing `_build_llm_translator` for Stage 0 sentence merging + Stage 3 shortening.
5. Call `assembler.generate_full_track(provider, segments, voice_profile, video_duration, output_path=STANDALONE_DIR / f"{dub_uuid}.wav", playback_speed=playback_speed, enable_shortening=enable_shortening, video_id=dub_uuid, language=language)`.
6. After success, write `{uuid}.json` with metadata.
7. Emit `complete` event via the existing SSE machinery.

The synthetic `video_id=dub_uuid` is passed only so the assembler's internal logging has something to print — it doesn't drive any file paths (we pass `output_path` directly).

### `src/api/routers/standalone_dub.py` (new)

```python
from __future__ import annotations

import asyncio
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from src.api import standalone_dub as standalone_mod
from src.api.deps import get_config, get_task_manager
from src.api.models import TaskResponse

router = APIRouter()


@router.post("/api/standalone-dub", response_model=TaskResponse, status_code=201)
async def start_standalone_dub(
    file: UploadFile = File(...),
    provider: str = Form(...),
    voice: str = Form(...),
    language: str = Form(...),
    playback_speed: float = Form(1.5),
    enable_shortening: bool = Form(True),
    api_key: str | None = Form(None),
    llm_api_key: str | None = Form(None),
    llm_backend: str | None = Form(None),
):
    """Generate a dub from an uploaded SRT. Returns the task_id; subscribe
    to the existing /api/tasks/{task_id} SSE stream for progress."""

@router.get("/api/standalone-dub", response_model=list[StandaloneDubEntry])
async def list_standalone_dubs():
    """Return recent dubs newest-first."""

@router.delete("/api/standalone-dub/{dub_uuid}", status_code=204)
async def delete_standalone_dub(dub_uuid: str):
    """Remove the WAV + metadata sidecar."""

@router.get("/api/standalone-dub/{dub_uuid}.wav")
async def download_standalone_dub(dub_uuid: str):
    """Serve the WAV with Content-Disposition: attachment for browser
    download."""
```

The `POST` handler creates a task, fires `tm.run_standalone_dub(...)` on `asyncio.create_task(...)`, captures the handle on `task._asyncio_task` (matches the cancel-pipeline pattern from PR #15), returns `TaskResponse(task_id, status)`.

The `GET /api/standalone-dub/{uuid}.wav` handler uses `FileResponse` with `media_type="audio/wav"` and `filename=f"{uuid}.wav"` so the browser triggers a download.

Register the new router in `src/api/__init__.py`:

```python
from src.api.routers import standalone_dub as standalone_router
# ...
app.include_router(standalone_router.router)
```

## Frontend

### `ui-app/src/api/standaloneDub.ts` (new)

```ts
import type { TaskResponse } from './types';

export interface StandaloneDubEntry {
  uuid: string;
  original_filename: string;
  provider: string;
  voice: string;
  language: string;
  playback_speed: number;
  enable_shortening: boolean;
  duration_seconds: number;
  created_at: string;
  file_size_bytes: number;
}

export async function postStandaloneDub(opts: {
  file: File;
  provider: string;
  voice: string;
  language: string;
  playbackSpeed: number;
  enableShortening: boolean;
  apiKey?: string;
  llmApiKey?: string;
  llmBackend?: string;
}): Promise<TaskResponse> { /* multipart POST */ }

export async function getStandaloneDubs(): Promise<StandaloneDubEntry[]>;
export async function deleteStandaloneDub(dubUuid: string): Promise<void>;
export function getStandaloneDubUrl(dubUuid: string): string;
```

The `postStandaloneDub` uses raw `fetch` + `FormData` (same pattern as `importVersion` from sub-project 2 — bypasses the `request` helper's JSON Content-Type assumption).

### `ui-app/src/pages/DubStudio.tsx` (new)

Page structure (top to bottom):

1. **Header**: title "Dub Studio" + one-line description ("Generate a dub WAV from any SRT file. No video required.")
2. **Generate form** (`<form>` element so Enter submits):
   - File picker (`<input type="file" accept=".srt">`) with a selected-file chip showing the filename
   - Provider dropdown (uses existing `getTTSProviders` API)
   - Language dropdown (limited list: `vi`, `en`, `zh`, `ja`, `ko`, `es`, `fr`, `de`, `ru`, `pt`, `it`, `th`, `id` — same as the existing DubTab)
   - Voice dropdown (uses existing `getTTSVoices` filtered by provider + language)
   - Playback Speed slider (1.0× – 2.0×, default 1.5×)
   - "Shorten dub to fit timeline" checkbox (default ON, matches DubTab)
   - **Generate** button (disabled until file + voice are selected)
3. **Progress** strip (shown while a generation is running): linear progress bar + current stage message ("Synthesising sentence 4/12…")
4. **Recent dubs** section: same row layout as the existing DubTab audio library —
   - Play button → inline `<audio>` playback
   - Filename chip (uses `original_filename` instead of a version id)
   - Provider · Voice · Language · Duration · File size
   - Created-at relative time ("3m ago")
   - Download icon (always visible — anchor with `download` attribute, `href={getStandaloneDubUrl(uuid)}`)
   - Delete icon (hover-only) with `confirm()` guard

State management mirrors VideoDetail's pattern:
- `selectedFile: File | null`, `selectedProvider`, `selectedVoiceId`, `selectedLanguage`, `playbackSpeed`, `enableShortening`
- Persist all picker settings to localStorage (`dub_studio_provider`, `dub_studio_voice_id_{provider}`, `dub_studio_language`, etc.) — independent of the video-flow keys so changing here doesn't pollute the video DubTab and vice versa
- API keys + LLM prefs loaded from the same shared `loadApiKeys()` / `loadLLMPrefs()` helpers
- Recent dubs list refreshed on mount, after a successful generation, and after a delete

SSE wiring: on submit, call `postStandaloneDub` → take the `task_id` → call existing `subscribeSSE(task_id, eventType => …)` from `api/client.ts`. On `progress` events, update the progress bar; on `complete`, refetch the recent-dubs list and reset the form's "generating" flag; on `error`, show an error inline.

### Nav entry

Edit `ui-app/src/data/mockData.ts`:

```ts
export const navItems: readonly NavItem[] = [
  { icon: 'rocket_launch', label: 'Pipeline', path: '/' },
  { icon: 'movie_edit', label: 'Video Studio', path: '/videos' },
  { icon: 'graphic_eq', label: 'Dub Studio', path: '/dub-studio' },
  { icon: 'translate', label: 'Translation Profiles', path: '/profiles' },
  { icon: 'settings', label: 'Settings', path: '/settings' },
];
```

Position: between "Video Studio" and "Translation Profiles" — TTS-related, so it sits near video work in the nav order.

### Route

Edit `ui-app/src/App.tsx`:

```tsx
import { DubStudioPage } from './pages/DubStudio';
// ...
<Route path="/dub-studio" element={<DubStudioPage />} />
```

## Tests

### Backend — `tests/test_standalone_dub.py`

**`TestStandaloneDubHelpers`** (synchronous IO helpers):
- `test_list_dubs_empty_returns_empty_list` — fresh dir → `[]`
- `test_list_dubs_returns_newest_first` — seed two JSON files with different `created_at` → list sorted descending
- `test_list_dubs_skips_orphan_metadata` — JSON exists but corresponding WAV doesn't → entry filtered out
- `test_delete_dub_removes_both_files` — seed `.wav` + `.json`, call `delete_dub`, both gone, returns True
- `test_delete_dub_missing_returns_false` — unknown uuid → False (idempotent)

**`TestStandaloneDubRouter`** (FastAPI TestClient):
- `test_post_returns_task_id` — multipart POST with a valid SRT → 201 + body has `task_id`
- `test_post_rejects_missing_file` → 422
- `test_get_lists_dubs` — seed two metadata files → 200 + array of 2
- `test_delete_removes_files` — seed, DELETE, GET shows 0 entries
- `test_get_wav_serves_file` — seed wav, GET returns 200 + `audio/wav` content-type
- `test_get_wav_unknown_returns_404`

`TestManagerRunStandaloneDub` (async, mocks the assembler):
- `test_run_writes_wav_and_metadata` — mock `generate_full_track` to write a fake WAV byte; assert metadata sidecar created with correct fields
- `test_run_with_invalid_srt_marks_task_failed` — pass garbage bytes → task ends with `status='failed'`

### Frontend — `ui-app/src/pages/__tests__/DubStudio.test.tsx`

- `test_renders_with_empty_recent_list` — mock `getStandaloneDubs` returning `[]` → "No recent dubs" placeholder shown
- `test_file_selection_enables_generate_button` — initially disabled; after change event with a File, button enabled (requires voice too — mock voices and pre-select one)
- `test_generate_posts_and_refreshes` — click Generate → `postStandaloneDub` called with all fields → `getStandaloneDubs` called again after `complete` SSE event
- `test_delete_removes_row` — render with one entry → click delete (confirm yes) → `deleteStandaloneDub` called

## Verification

1. `python -m pytest tests/test_standalone_dub.py -v` — all green.
2. `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py` — full BE suite green.
3. `cd ui-app && npx vitest run` — full FE suite green, +4 new tests.
4. `cd ui-app && npm run build` — succeeds (modulo the 2 pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).
5. `ruff check src/ tests/` — no new errors.

**Manual smoke** (after merge):
- Click "Dub Studio" in the sidebar → page loads with empty "Recent dubs" placeholder.
- Pick a `.srt` file from disk → filename chip shows; Generate button enables once a voice is picked.
- Click Generate → progress bar appears → completes in ~30s for a short SRT → new entry shows up in Recent.
- Click play on the new entry → audio plays inline. Click download → browser downloads the WAV.
- Refresh the page → entry persists.
- Click delete → confirm → row disappears; files gone from `data/standalone_dubs/`.

## Out of scope

- Per-segment voice overrides.
- Voice cloning.
- Batch uploads.
- In-page SRT editing (re-upload to retry).
- Long-term storage management (TTL, quotas).

## Critical files

- New BE: `src/api/standalone_dub.py`, `src/api/routers/standalone_dub.py`, `tests/test_standalone_dub.py`
- Modify BE: `src/api/__init__.py` (router registration), `src/api/task_manager.py` (`run_standalone_dub` method)
- New FE: `ui-app/src/api/standaloneDub.ts`, `ui-app/src/pages/DubStudio.tsx`, `ui-app/src/pages/__tests__/DubStudio.test.tsx`
- Modify FE: `ui-app/src/App.tsx` (route), `ui-app/src/data/mockData.ts` (nav item)
- Docs: `CHANGELOG.md`, `README.md`
