# Pipeline Page Cleanup + Dubsync Default Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two user-facing changes: (1) backend SRT endpoints prefer `{id}_{lang}.dubsync.srt` over the legacy SRT when present, and the editor warns when editing it; (2) the pipeline launcher's 5-step expandable stepper is replaced by a flat compact form with an Advanced toggle.

**Architecture:** Backend changes are minimal — one helper function in `transcribe.py` shared between GET endpoints, the editor's PUT endpoint adopts the same helper, `SrtResponse` gains `is_dubsync: bool`. Frontend changes split into two: SubtitleEditor adds a one-time warning banner driven by the new field; DownloadTranscribe gets a major rewrite — the stepper UI block (~365 lines) is deleted and replaced with a `Configuration` card containing a top row (Translation Profile + LLM Backend), middle row (TTS Provider + Voice + Preview), and a single inline-expandable "Advanced" panel for the less-common settings. Voice Profile dropdown is removed; the UI resolves the profile name implicitly from the selected translation language.

**Tech Stack:** Python 3.11, pytest with pytest-asyncio (auto mode), ruff, FastAPI, Pydantic v2, React 19 + TypeScript, Tailwind 4.

**Source spec:** [docs/superpowers/specs/2026-05-21-pipeline-page-cleanup-and-dubsync-default.md](../specs/2026-05-21-pipeline-page-cleanup-and-dubsync-default.md). All design decisions are locked in there.

**Branch:** `feature/phase4-dubbing-redesign-spec` (HEAD = fcf4632 — spec already committed).

---

## File Structure

**Files to create:**
- `tests/test_srt_endpoints.py` — new test module covering the dubsync-resolver behavior on GET / download / PUT endpoints.

**Files to modify:**
- `src/api/models.py` — `SrtResponse` gains `is_dubsync: bool = False`.
- `src/api/routers/transcribe.py` — add `_resolve_srt_path(video_id, language)` helper; both GET endpoints use it.
- `src/api/routers/editor.py` — `save_srt` uses the same resolver for writes.
- `ui-app/src/api/types.ts` — TS `SrtResponse` gains `is_dubsync?: boolean`.
- `ui-app/src/pages/SubtitleEditor.tsx` — render an amber warning banner when `srt.is_dubsync === true`.
- `ui-app/src/pages/DownloadTranscribe.tsx` — large rewrite: delete the stepper block, add the compact Configuration card and running progress strip.
- `CHANGELOG.md` — `### Added` / `### Changed` entries per task.

---

## Task 1: Backend — dubsync resolver + `is_dubsync` on response

**Files:**
- Modify: `src/api/models.py` (`SrtResponse` class)
- Modify: `src/api/routers/transcribe.py` (add helper, update both GET endpoints)
- Create: `tests/test_srt_endpoints.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_srt_endpoints.py` with:

```python
"""Tests for the SRT-serving endpoints — preference for dubsync.srt over the
legacy SRT when both exist."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _write_srt(path: Path, text: str) -> None:
    """Write a one-segment SRT containing the given text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n",
        encoding="utf-8",
    )


def _make_client(tmp_path, monkeypatch):
    """Build a FastAPI TestClient with data_dir pointing into tmp_path."""
    # Point cwd at tmp_path so the routers' hardcoded data/srt path lands there.
    monkeypatch.chdir(tmp_path)
    # Make sure the video_index has our test video so the 404 guards pass.
    from src.api import create_app
    from src.api.deps import get_task_manager

    app = create_app()
    tm = get_task_manager()
    # Inject a stub video entry into the task manager's index.
    from src.api.models import VideoResponse
    tm.video_index["vid001"] = VideoResponse(
        video_id="vid001",
        title="t", duration=0.0, source_url="",
        thumbnail="", has_srt=True, srt_languages=["vi"],
        download_status="done",
    )
    return TestClient(app)


class TestGetSrtDubsyncPreference:
    def test_get_srt_prefers_dubsync_when_present(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "original text")
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt", "dubsync text")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_dubsync"] is True
        # Segments came from the dubsync file
        assert any("dubsync" in seg["text"] for seg in body["segments"])

    def test_get_srt_falls_back_to_legacy_when_no_dubsync(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy only")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_dubsync"] is False
        assert any("legacy" in seg["text"] for seg in body["segments"])

    def test_get_srt_404_when_neither_file_exists(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 404


class TestDownloadSrtDubsyncPreference:
    def test_download_serves_dubsync_with_clean_filename(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "original text")
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt", "dubsync text")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt/download?language=vi")
        assert resp.status_code == 200
        # Filename in Content-Disposition is the clean name, NOT .dubsync.srt
        cd = resp.headers.get("content-disposition", "")
        assert "vid001_vi.srt" in cd
        assert "dubsync" not in cd
        # Body is the dubsync content
        assert "dubsync text" in resp.text

    def test_download_falls_back_to_legacy_when_no_dubsync(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy only")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt/download?language=vi")
        assert resp.status_code == 200
        assert "legacy only" in resp.text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_srt_endpoints.py -v
```

Expected: 5 failures. The GET tests fail because `is_dubsync` doesn't exist on the response. The download tests fail because the endpoint always serves the legacy SRT regardless of dubsync presence.

- [ ] **Step 3: Add `is_dubsync` to `SrtResponse`**

In `src/api/models.py`, find `class SrtResponse(BaseModel):` (around line 193). Update:

```python
class SrtResponse(BaseModel):
    video_id: str
    segments: list[SubtitleSegment]
    language: str
    is_dubsync: bool = False
```

- [ ] **Step 4: Add the resolver helper in `transcribe.py`**

In `src/api/routers/transcribe.py`, add this helper near the top of the file (after the imports, before the route functions):

```python
def _resolve_srt_path(video_id: str, language: str) -> tuple[Path, bool]:
    """Return the SRT path to read for this video+language plus whether it
    is the dub-synced derivative.

    Prefers `{video_id}_{language}.dubsync.srt` when present. Falls back to
    the legacy `{video_id}_{language}.srt`. The dubsync file is written by
    the TTS assembler at Stage 6 with text and timings synced to the actual
    dub; consumers should prefer it whenever available.

    Returns (path, is_dubsync). The returned path is NOT guaranteed to
    exist — callers must check with `.exists()`.
    """
    srt_dir = Path("data/srt")
    dubsync = srt_dir / f"{video_id}_{language}.dubsync.srt"
    if dubsync.exists():
        return dubsync, True
    return srt_dir / f"{video_id}_{language}.srt", False
```

Make sure `from pathlib import Path` is imported (likely already is).

- [ ] **Step 5: Update `get_srt` to use the resolver**

In `src/api/routers/transcribe.py::get_srt` (around line 82), replace the body so the early-section reads:

```python
@router.get("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def get_srt(video_id: str, language: str = "zh"):
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    srt_path, is_dubsync = _resolve_srt_path(video_id, language)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404, detail=f"SRT file not found for {video_id} ({language})"
        )

    parsed = parse_srt(srt_path)
    segments = [
        SubtitleSegment(
            id=seg["index"],
            startTime=BaseTranscriber._format_timestamp(seg["start"]),
            endTime=BaseTranscriber._format_timestamp(seg["end"]),
            text=seg["text"],
        )
        for seg in parsed
    ]

    return SrtResponse(
        video_id=video_id, segments=segments,
        language=language, is_dubsync=is_dubsync,
    )
```

- [ ] **Step 6: Update `download_srt` to use the resolver**

In `src/api/routers/transcribe.py::download_srt` (around line 108), replace the body:

```python
@router.get("/api/videos/{video_id}/srt/download")
async def download_srt(video_id: str, language: str = "zh"):
    """Download SRT file as attachment.

    Serves the dub-synced SRT when present (with a clean `{id}_{lang}.srt`
    download filename — no `.dubsync` infix in the filename the user sees),
    falling back to the legacy SRT otherwise."""
    srt_path, _is_dubsync = _resolve_srt_path(video_id, language)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404, detail=f"SRT file not found for {video_id} ({language})"
        )

    download_name = f"{video_id}_{language}.srt"
    return FileResponse(
        path=str(srt_path),
        media_type="text/plain",
        filename=download_name,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/test_srt_endpoints.py -v
```

Expected: 5 passes (3 in `TestGetSrtDubsyncPreference`, 2 in `TestDownloadSrtDubsyncPreference`).

- [ ] **Step 8: Run the full test suite to confirm no regression**

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all pre-existing tests still pass.

- [ ] **Step 9: Lint**

```bash
ruff check src/api/models.py src/api/routers/transcribe.py tests/test_srt_endpoints.py
```

Expected: no NEW errors. Pre-existing warnings in other files may persist.

- [ ] **Step 10: Update CHANGELOG**

Append to existing `### Added` block under `[Unreleased]` in `CHANGELOG.md`:

```
- `is_dubsync: bool` field on `SrtResponse`. The GET `/api/videos/{id}/srt` endpoint sets it to `true` when the served file is the dub-synced derivative; the editor banner uses this to warn users that re-running TTS overwrites the file.
```

And to existing `### Changed`:

```
- GET `/api/videos/{id}/srt` and GET `/api/videos/{id}/srt/download` now prefer `{video_id}_{language}.dubsync.srt` over `{video_id}_{language}.srt` when both exist. The download endpoint preserves the clean filename `{id}_{lang}.srt` (no `.dubsync` infix) for UX. Adds the shared `_resolve_srt_path(video_id, language)` helper in `src/api/routers/transcribe.py`.
```

- [ ] **Step 11: Commit**

```bash
git add src/api/models.py src/api/routers/transcribe.py tests/test_srt_endpoints.py CHANGELOG.md
git commit -m "Prefer dubsync.srt in GET/download endpoints

GET /api/videos/{id}/srt and the download endpoint now resolve the
SRT path via _resolve_srt_path(video_id, language), which prefers
{id}_{lang}.dubsync.srt when present and falls back to the legacy
{id}_{lang}.srt otherwise. The download filename stays clean as
{id}_{lang}.srt regardless of which file actually backs it.

SrtResponse gains is_dubsync: bool so the editor UI can warn users
that they are editing the dub-synced derivative.

5 new tests in tests/test_srt_endpoints.py cover both endpoints
against (dubsync only, legacy only, both present, neither)."
```

No AI mentions, no Co-Authored-By.

---

## Task 2: Backend — PUT endpoint writes to dubsync when present

**Files:**
- Modify: `src/api/routers/editor.py` (`save_srt`)
- Modify: `tests/test_srt_endpoints.py` (append PUT tests)

- [ ] **Step 1: Append failing tests**

Add to `tests/test_srt_endpoints.py`:

```python
class TestPutSrtDubsyncPreference:
    def test_put_writes_to_dubsync_when_present(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy text")
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt", "dubsync text")
        client = _make_client(tmp_path, monkeypatch)

        body = {
            "language": "vi",
            "segments": [
                {
                    "id": 1,
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:01,000",
                    "text": "edited text",
                }
            ],
        }
        resp = client.put("/api/videos/vid001/srt", json=body)
        assert resp.status_code == 200
        # Editor saves went to the dubsync file (since it existed)
        dubsync_contents = (tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt").read_text(encoding="utf-8")
        assert "edited text" in dubsync_contents
        # Legacy SRT was NOT touched
        legacy_contents = (tmp_path / "data" / "srt" / "vid001_vi.srt").read_text(encoding="utf-8")
        assert "legacy text" in legacy_contents
        assert "edited" not in legacy_contents
        # Response reflects is_dubsync
        assert resp.json()["is_dubsync"] is True

    def test_put_writes_to_legacy_when_no_dubsync(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy text")
        client = _make_client(tmp_path, monkeypatch)

        body = {
            "language": "vi",
            "segments": [
                {
                    "id": 1,
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:01,000",
                    "text": "edited text",
                }
            ],
        }
        resp = client.put("/api/videos/vid001/srt", json=body)
        assert resp.status_code == 200
        legacy_contents = (tmp_path / "data" / "srt" / "vid001_vi.srt").read_text(encoding="utf-8")
        assert "edited text" in legacy_contents
        assert resp.json()["is_dubsync"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/test_srt_endpoints.py::TestPutSrtDubsyncPreference -v
```

Expected: 2 failures. The PUT endpoint writes to the legacy SRT unconditionally.

- [ ] **Step 3: Update `save_srt` in `src/api/routers/editor.py`**

In `src/api/routers/editor.py`, at the top of the file, add the import (if not already present):

```python
from src.api.routers.transcribe import _resolve_srt_path
```

Then in `save_srt` (around line 130), replace the SRT-path-resolution block. Find:

```python
    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"
```

Replace with:

```python
    # Resolve where to write: dubsync.srt when present, legacy otherwise.
    srt_path, is_dubsync = _resolve_srt_path(video_id, request.language)
```

(The `data_dir` local is no longer needed in this function for the SRT path. Check whether it's used elsewhere in the function — grep `data_dir` within `save_srt` — and remove the unused variable if so. If `data_dir` is used for the style path or anything else in this function, keep the variable, just don't use it for the SRT path.)

Then at the end of `save_srt`, where the response is built, pass `is_dubsync` through:

```python
    return SrtResponse(
        video_id=video_id,
        segments=response_segments,
        language=request.language,
        is_dubsync=is_dubsync,
    )
```

(If the existing return statement uses a different builder shape, update it to include the new field. Read the existing function body to confirm.)

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_srt_endpoints.py -v
```

Expected: 7 passes (5 from Task 1 + 2 new).

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all pass.

- [ ] **Step 6: Lint**

```bash
ruff check src/api/routers/editor.py tests/test_srt_endpoints.py
```

Expected: no NEW errors.

- [ ] **Step 7: Update CHANGELOG**

Append to existing `### Changed` block:

```
- PUT `/api/videos/{id}/srt` (editor save) now writes to `{id}_{lang}.dubsync.srt` when it exists, falling back to the legacy SRT. The response includes `is_dubsync` so the editor can render the warning banner.
```

- [ ] **Step 8: Commit**

```bash
git add src/api/routers/editor.py tests/test_srt_endpoints.py CHANGELOG.md
git commit -m "Editor PUT writes to dubsync.srt when present

save_srt now resolves the write target via _resolve_srt_path,
matching the GET/download endpoints from Task 1. When a dubsync
file exists, the editor's saves go there; otherwise they go to
the legacy SRT.

Response carries is_dubsync so the UI knows whether to render the
're-running TTS will overwrite these edits' banner.

2 new tests cover the both-present and legacy-only cases."
```

No AI mentions, no Co-Authored-By.

---

## Task 3: Frontend — TS type + editor warning banner

**Files:**
- Modify: `ui-app/src/api/types.ts`
- Modify: `ui-app/src/pages/SubtitleEditor.tsx`

- [ ] **Step 1: Add `is_dubsync?: boolean` to TS `SrtResponse`**

In `ui-app/src/api/types.ts`, line 37-41, update:

```ts
export interface SrtResponse {
  video_id: string;
  segments: SubtitleSegment[];
  language: string;
  is_dubsync?: boolean;
}
```

The `?` keeps the field optional for backward compatibility with any cached responses.

- [ ] **Step 2: Inspect `SubtitleEditor.tsx` for the SRT-fetch site**

```bash
grep -n "getSrt\|srt\.is_dubsync\|setSrtSegments\|SrtResponse" ui-app/src/pages/SubtitleEditor.tsx | head
```

Find where the editor calls `getSrt()` and stores the response. You'll likely see something like:

```tsx
const data = await getSrt(videoId, language);
setSrtSegments(data.segments);
```

- [ ] **Step 3: Add `isDubsync` state**

Near the other state declarations in `SubtitleEditor.tsx`:

```tsx
const [isDubsync, setIsDubsync] = useState(false);
```

- [ ] **Step 4: Set `isDubsync` from each successful `getSrt` response**

Wherever the editor calls `getSrt(...)` and stores the segments, also set `isDubsync`:

```tsx
const data = await getSrt(videoId, language);
setSrtSegments(data.segments);
setIsDubsync(Boolean(data.is_dubsync));
```

If the editor refetches on language change, save, or other events, apply the same setter at each fetch site.

- [ ] **Step 5: Render the warning banner**

In the JSX, near the top of the editor body (before the segment list), add the conditional banner:

```tsx
{isDubsync && (
  <div className="bg-amber-500/10 border border-amber-500/30 text-amber-400 text-xs p-3 rounded-lg flex items-start gap-2 mb-3">
    <span className="material-symbols-outlined text-sm mt-0.5">warning</span>
    <div className="flex-1">
      <p className="font-semibold">You're editing the dub-synced subtitle.</p>
      <p className="mt-1 text-amber-300/80">
        Re-running TTS will regenerate <code className="text-[10px] bg-amber-900/30 px-1 rounded">{`{video_id}_{lang}.dubsync.srt`}</code> and lose your manual edits.
        For changes that survive re-runs, edit the original translated subtitle (<code className="text-[10px] bg-amber-900/30 px-1 rounded">{`data/srt/{id}_{lang}.srt`}</code>) instead.
      </p>
    </div>
  </div>
)}
```

Place this banner just inside the main editor container, before the segment list.

- [ ] **Step 6: Verify build**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -10
cd ui-app && npm run lint 2>&1 | tail -10
```

Expected: TS clean. Lint may have pre-existing warnings — confirm no NEW errors.

- [ ] **Step 7: Update CHANGELOG**

Append to existing `### Added` block:

```
- Subtitle Editor warning banner: when the editor is displaying the dub-synced SRT (the new default served by GET `/api/videos/{id}/srt`), an amber banner at the top of the editor warns that re-running TTS will overwrite manual edits. Driven by the new `is_dubsync` field on `SrtResponse`.
```

- [ ] **Step 8: Commit**

```bash
git add ui-app/src/api/types.ts ui-app/src/pages/SubtitleEditor.tsx CHANGELOG.md
git commit -m "Subtitle editor: warn when editing dubsync SRT

When GET /api/videos/{id}/srt returns is_dubsync=true, the editor
renders an amber banner explaining that re-running TTS will
regenerate the dubsync file and lose the user's manual edits.

The banner points to the original translated SRT
(data/srt/{id}_{lang}.srt) as the path for edits that should
survive future TTS runs."
```

No AI mentions, no Co-Authored-By.

---

## Task 4: Pipeline page rewrite — compact form layout

**Files:**
- Modify: `ui-app/src/pages/DownloadTranscribe.tsx` (large rewrite)
- Modify: `CHANGELOG.md`

This is the biggest task. The page is being restructured: the 5-step expandable stepper (current lines ~462-827) is deleted entirely; a flat `Configuration` card replaces it with an inline "Advanced" panel for the less-common settings. During a pipeline run, the card is hidden and replaced by a slim progress strip.

- [ ] **Step 1: Inspect the current file structure**

```bash
wc -l ui-app/src/pages/DownloadTranscribe.tsx
grep -n "^  const\|^  function\|^  const handle\|^    const steps\|expandedStep\|getStepState\|steps.map\|Pipeline Stepper\|Pipeline Steps" ui-app/src/pages/DownloadTranscribe.tsx | head -30
```

You'll see the file is ~900 lines. The deletions target the stepper block; the additions are the new Configuration card.

- [ ] **Step 2: Delete the stepper state + helpers**

Search the file for these symbols and delete the related state + functions:

```bash
grep -n "expandedStep\|toggleStep\|getStepState\|const steps" ui-app/src/pages/DownloadTranscribe.tsx
```

Delete:
- `const [expandedStep, setExpandedStep] = useState<...>(...)` declaration
- `const toggleStep = (...) => { ... }` definition
- `const getStepState = (...) => { ... }` definition
- `const steps = [...]` array (currently around line 350)

Keep all other state untouched: URL, pipeline status, batch results, translation profile, LLM backend/model, TTS provider/voice/preview, playback speed, underlay, blur enabled, etc.

- [ ] **Step 3: Add the "Advanced" panel toggle state**

Near the other UI state (e.g. just below the existing pipeline-status state), add:

```tsx
const [showAdvanced, setShowAdvanced] = useState(false);
```

- [ ] **Step 4: Delete the Pipeline Stepper JSX block**

Find the opening `<div>` for the Pipeline Stepper card (look for the `account_tree` icon and the heading "Pipeline Steps"). The block spans roughly lines 462-827 in the current file. Delete from:

```tsx
{/* Pipeline Stepper */}
<div className="bg-surface-container-low rounded-xl overflow-hidden border border-outline-variant/10">
  ...
```

through the matching closing `</div>` (just before the Video Library section).

After deletion, the JSX flow should be:

```tsx
{/* URL Input */}
<div ...>...</div>

{/* Error Banner */}
{error && (...)}

// ← Configuration card and running progress strip go HERE (next step)

{/* Video Library */}
<div ...>...</div>
```

- [ ] **Step 5: Insert the running progress strip + Configuration card**

In the place where the stepper used to live, add:

```tsx
{/* Running progress strip — visible only during a single-URL pipeline run */}
{isPipeline && !isBatchMode && (
  <div className="bg-surface-container-low rounded-xl p-4 flex items-center gap-4">
    <div className="flex-1 space-y-1.5">
      <div className="flex justify-between text-[10px] font-mono">
        <span className="text-primary uppercase tracking-widest font-bold">
          {pipelineStage || 'Starting'}
        </span>
        <span className="text-zinc-500">{Math.round(pipelineProgress)}%</span>
      </div>
      <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
        <div
          className="h-full bg-primary transition-all duration-300"
          style={{ width: `${pipelineProgress}%` }}
        />
      </div>
      {pipelineMessage && (
        <p className="text-[10px] font-mono text-on-surface-variant whitespace-pre-line mt-1">
          {pipelineMessage}
        </p>
      )}
    </div>
  </div>
)}

{/* Configuration card — hidden during a pipeline run */}
{!isPipeline && (
  <div className="bg-surface-container-low rounded-xl p-5 space-y-4">
    <div className="flex items-center gap-2">
      <span className="material-symbols-outlined text-primary text-lg">tune</span>
      <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">
        Configuration
      </span>
    </div>

    {/* Top row: Translation Profile + LLM Backend */}
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">
          Translation Profile
        </label>
        <select
          value={selectedProfile}
          onChange={(e) => setSelectedProfile(e.target.value)}
          className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary"
        >
          <option value="">Skip translation</option>
          {profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name} ({p.target_language})
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">
          LLM Backend
        </label>
        <select
          value={llmBackend}
          onChange={(e) => {
            const val = e.target.value;
            setLlmBackend(val);
            const m = MODEL_OPTIONS[val];
            if (m?.length) {
              setLlmModel(m[0].value);
              saveLLMPrefs(val, m[0].value);
            }
          }}
          className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary"
        >
          <option value="deepseek">DeepSeek</option>
          <option value="anthropic">Anthropic</option>
          <option value="openai">OpenAI</option>
        </select>
      </div>
    </div>

    {/* Middle row: TTS Provider + Voice + Preview */}
    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
      <div>
        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">
          TTS Provider
        </label>
        <select
          value={selectedTtsProvider}
          onChange={(e) => {
            setSelectedTtsProvider(e.target.value);
            storageSet('tts_selected_provider', e.target.value);
          }}
          className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary"
        >
          {ttsProviders.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}{p.free ? ' (Free)' : ''}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block mb-1.5">
          Voice
        </label>
        {selectedTtsProvider === 'elevenlabs' ? (
          <div className="flex items-center h-10 px-3 bg-surface-container rounded-lg text-xs text-on-surface-variant">
            {selectedVoiceId ? (
              <span className="font-mono truncate">{selectedVoiceId}</span>
            ) : (
              <span className="text-zinc-500 italic">Configure in Advanced → Voice ID</span>
            )}
          </div>
        ) : (
          <select
            value={selectedVoiceId}
            onChange={(e) => {
              setSelectedVoiceId(e.target.value);
              storageSet(`tts_voice_id_${selectedTtsProvider}`, e.target.value);
            }}
            className="w-full bg-surface-container border-none text-xs text-on-surface h-10 px-3 rounded-lg focus:ring-1 focus:ring-primary"
          >
            {ttsVoices.length === 0 && <option value="">No voices loaded (check API key)</option>}
            {ttsVoices.map((v) => (
              <option key={v.name} value={v.name}>
                {v.friendly_name || v.name} ({v.gender}) — {v.language}
              </option>
            ))}
          </select>
        )}
      </div>
    </div>

    {/* Inline voice preview, when a voice is selected */}
    {selectedVoiceId && (
      <div className="flex items-center gap-3">
        <TTSPreview
          voice={selectedVoiceId}
          provider={selectedTtsProvider}
          speed="+0%"
          pitch="+0Hz"
          apiKey={ttsApiKey || undefined}
          playbackSpeed={playbackSpeed}
          sampleText={
            profiles.find((p) => p.name === selectedProfile)?.target_language === 'en'
              ? 'Hello everyone, today we will talk about a very interesting topic.'
              : 'Xin chào các bạn, hôm nay chúng ta sẽ nói về một chủ đề rất thú vị.'
          }
        />
        <span className="font-mono text-[9px] text-on-surface-variant truncate">
          {selectedVoiceId}
        </span>
      </div>
    )}

    {/* Advanced toggle */}
    <button
      onClick={() => setShowAdvanced(!showAdvanced)}
      className="flex items-center gap-2 text-xs text-on-surface-variant hover:text-on-surface transition-colors"
    >
      <span className="material-symbols-outlined text-sm">settings</span>
      <span>Advanced settings</span>
      <span className="material-symbols-outlined text-sm">
        {showAdvanced ? 'expand_less' : 'expand_more'}
      </span>
    </button>

    {/* Advanced panel */}
    {showAdvanced && (
      <div className="bg-surface-container rounded-lg p-4 space-y-3">
        {/* Playback Speed */}
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-sm text-on-surface-variant">speed</span>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">
            Dub Playback Speed
          </label>
          <input
            type="number"
            min={1.0}
            max={2.0}
            step={0.1}
            value={playbackSpeed}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              if (Number.isFinite(v) && v >= 1.0 && v <= 2.0) {
                setPlaybackSpeed(v);
                storageSet('tts_playback_speed', String(v));
              }
            }}
            className="w-16 px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
          />
          <span className="text-[10px] text-on-surface-variant font-mono">×</span>
        </div>

        {/* Original Underlay */}
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-sm text-on-surface-variant">graphic_eq</span>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">
            Original Underlay
          </label>
          <select
            value={String(underlayDb)}
            onChange={(e) => {
              const v = parseFloat(e.target.value);
              setUnderlayDb(v);
              storageSet('tts_underlay_db', String(v));
            }}
            className="px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
          >
            <option value="0">Off</option>
            <option value="-24">-24</option>
            <option value="-18">-18</option>
            <option value="-12">-12</option>
            <option value="-6">-6</option>
          </select>
          <span className="text-[10px] text-on-surface-variant font-mono">dB</span>
        </div>

        {/* LLM Model */}
        <div className="flex items-center gap-3">
          <span className="material-symbols-outlined text-sm text-on-surface-variant">model_training</span>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">
            LLM Model
          </label>
          <select
            value={llmModel}
            onChange={(e) => {
              setLlmModel(e.target.value);
              saveLLMPrefs(llmBackend, e.target.value);
            }}
            className="px-2 py-1 text-xs font-mono text-on-surface bg-surface-container-low border border-outline-variant/30 rounded focus:outline-none focus:border-primary"
          >
            {(MODEL_OPTIONS[llmBackend] || []).map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {/* Blur toggle */}
        <div className="flex items-center gap-3 pt-1">
          <span className="material-symbols-outlined text-sm text-primary">blur_on</span>
          <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold flex-1">
            Blur Original Subtitles
          </label>
          <button
            onClick={() => setBlurEnabled(!blurEnabled)}
            className={`w-8 h-4 rounded-full relative cursor-pointer transition-colors ${
              blurEnabled ? 'bg-primary' : 'bg-surface-container-highest'
            }`}
          >
            <div
              className={`absolute top-0.5 w-3 h-3 bg-white rounded-full transition-all ${
                blurEnabled ? 'right-0.5' : 'left-0.5'
              }`}
            />
          </button>
        </div>

        {/* ElevenLabs Voice ID — only when EL provider is selected */}
        {selectedTtsProvider === 'elevenlabs' && (
          <div className="space-y-2 pt-2 border-t border-outline-variant/10">
            <label className="text-[10px] text-zinc-500 uppercase tracking-tighter font-bold block">
              ElevenLabs Voice ID
            </label>
            <div className="flex gap-2">
              <input
                type="text"
                value={voiceIdInput}
                onChange={(e) => {
                  setVoiceIdInput(e.target.value);
                  setVoiceIdSaved(false);
                }}
                placeholder="Paste ElevenLabs voice ID"
                className="flex-1 bg-surface-container-low border-none text-xs text-on-surface py-2 px-3 rounded focus:ring-1 focus:ring-primary placeholder:text-zinc-600 font-mono"
              />
              <button
                onClick={() => {
                  setSelectedVoiceId(voiceIdInput);
                  storageSet('tts_voice_id_elevenlabs', voiceIdInput);
                  setVoiceIdSaved(true);
                  setTimeout(() => setVoiceIdSaved(false), 2000);
                }}
                disabled={!voiceIdInput}
                className="px-3 py-2 rounded text-[10px] font-bold uppercase bg-primary/20 text-primary hover:bg-primary/30 disabled:opacity-50 transition-colors"
              >
                {voiceIdSaved ? 'Saved' : 'Save'}
              </button>
            </div>
          </div>
        )}
      </div>
    )}

    {/* Missing API key warning */}
    {ttsProviders.find((p) => p.id === selectedTtsProvider)?.requires_key && !ttsApiKey && (
      <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs p-3 rounded-lg flex items-center gap-2">
        <span className="material-symbols-outlined text-sm">warning</span>
        <span>
          No API key configured for <strong>{selectedTtsProvider}</strong>.
        </span>
        <button
          onClick={() => navigate('/settings#apikeys')}
          className="ml-auto text-[10px] font-bold uppercase tracking-wider text-amber-300 hover:text-amber-200 flex items-center gap-1 whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-xs">settings</span>
          Configure
        </button>
      </div>
    )}

    {/* LLM API key warning (when translation profile is selected) */}
    {selectedProfile && !llmApiKey && (
      <div className="bg-amber-500/10 border border-amber-500/20 text-amber-400 text-xs p-3 rounded-lg flex items-center gap-2">
        <span className="material-symbols-outlined text-sm">warning</span>
        <span>
          No <strong>{llmBackend}</strong> API key configured for translation.
        </span>
        <button
          onClick={() => navigate('/settings#apikeys')}
          className="ml-auto text-[10px] font-bold uppercase tracking-wider text-amber-300 hover:text-amber-200 flex items-center gap-1 whitespace-nowrap"
        >
          <span className="material-symbols-outlined text-xs">settings</span>
          Configure
        </button>
      </div>
    )}
  </div>
)}
```

This block uses every state variable that was previously bound inside the deleted stepper panels. No new state is introduced beyond `showAdvanced` (Step 3).

- [ ] **Step 6: Resolve the implicit Voice Profile name in the pipeline POST**

The backend still expects `tts_voice_profile` in the request body. The UI used to send `selectedTtsProfile` (the dropdown value). With the dropdown removed, derive the profile name from the selected translation profile's target language.

Find where `handlePipeline` builds the request body (search for `playback_speed: playbackSpeed,` or `ttsOverrides`):

```bash
grep -n "ttsOverrides\|tts_voice_profile\|selectedTtsProfile" ui-app/src/pages/DownloadTranscribe.tsx | head
```

Where `selectedTtsProfile` is used in the POST body, replace it with a derived value:

```tsx
// Derive the voice profile name from the translation profile's target language.
// female-vi-natural for Vietnamese, female-en-natural for English.
const targetLang = profiles.find((p) => p.name === selectedProfile)?.target_language ?? 'vi';
const ttsVoiceProfile = targetLang === 'en' ? 'female-en-natural' : 'female-vi-natural';
```

Then use `ttsVoiceProfile` everywhere `selectedTtsProfile` was used in the request payload. Keep the `selectedTtsProfile` STATE for now if any other code reads it — but if nothing else does, remove the state and the related setter.

Run:

```bash
grep -n "selectedTtsProfile" ui-app/src/pages/DownloadTranscribe.tsx
```

If the only remaining reference is the (now dead) state declaration, delete it.

- [ ] **Step 7: Confirm Voice Profile state is gone**

```bash
grep -n "selectedTtsProfile\|setSelectedTtsProfile" ui-app/src/pages/DownloadTranscribe.tsx
```

Expected: no output, OR only the now-orphan state declaration. If the only reference is the orphan declaration, delete it. If there are still consumers (e.g. the now-deleted stepper logic), they should already be gone — check carefully.

- [ ] **Step 8: TypeScript + lint**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -10
cd ui-app && npm run lint 2>&1 | tail -10
```

Expected: zero TS errors. Lint may have pre-existing warnings — confirm no NEW errors.

Common issues to look for if TS fails:
- Unused imports from the deleted stepper logic (`steps`, `getStepState`, etc.).
- Unused state variables (`expandedStep`).
- Stale `selectedTtsProfile` reference where the POST body is built.

Fix any genuine errors before proceeding.

- [ ] **Step 9: Spot-check the file structure**

```bash
wc -l ui-app/src/pages/DownloadTranscribe.tsx
```

Expected: roughly 600-650 lines (down from 897). If the line count didn't drop noticeably, the stepper block may not have been fully deleted — go back to Step 4.

- [ ] **Step 10: Update CHANGELOG**

Append to existing `### Changed` block:

```
- Pipeline launcher (DownloadTranscribe) page: dropped the 5-step expandable stepper UI. Replaced with a flat Configuration card containing two main rows (Translation Profile + LLM Backend; TTS Provider + Voice + Preview) and an Advanced toggle that expands to show playback speed, original underlay, LLM model, blur toggle, and the ElevenLabs Voice ID input. Voice Profile dropdown removed — the backend profile name is derived implicitly from the selected translation profile's target language (`female-vi-natural` for vi, `female-en-natural` for en). During a pipeline run, the Configuration card is hidden; a slim progress strip shows the current stage + percent + message. File size: ~900 → ~650 lines.
```

- [ ] **Step 11: Commit**

```bash
git add ui-app/src/pages/DownloadTranscribe.tsx CHANGELOG.md
git commit -m "Pipeline page: replace stepper with compact form

DownloadTranscribe.tsx now uses a flat Configuration card instead
of the 5-step expandable stepper. Layout:

  Translation Profile [select]    LLM Backend [select]
  TTS Provider        [select]    Voice       [select]    [Preview]
  ⚙ Advanced settings ▾                                              
    └─ Playback Speed · Underlay · LLM Model · Blur · ElevenLabs ID

Voice Profile dropdown removed; the backend profile name is derived
implicitly from the translation profile's target_language. Per-run
voice override (added in the providers cleanup) still wins over the
profile's voice.

During a pipeline run the Configuration card is hidden; a slim
progress strip shows the current stage + percent. URL input card,
error banner, and Video Library are unchanged.

File: 897 → ~650 lines."
```

No AI mentions, no Co-Authored-By.

---

## Task 5: Manual QA + finalize

**Files:**
- No code changes — manual verification only.
- Modify: `CHANGELOG.md` for any final consolidation.

This task verifies the full set of changes against a real pipeline run, then pushes the branch.

- [ ] **Step 1: Run full automated test suite**

```bash
make test
```

Or:

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all pass. New tests in `tests/test_srt_endpoints.py` (7 total) pass.

- [ ] **Step 2: Rebuild Docker and start the app**

```bash
make docker-up
```

Wait for the build to finish, then tail logs:

```bash
make docker-logs
```

Expected: app starts cleanly; no import errors, no startup exceptions.

- [ ] **Step 3: UI smoke — pipeline launcher**

In a browser at `http://localhost:8000`:

- Open the Pipeline launcher (DownloadTranscribe).
- Confirm: no 5-step stepper, no numbered circles. Just a `Configuration` card.
- Confirm rows: Translation Profile + LLM Backend (row 1), TTS Provider + Voice (row 2), Voice Preview button below.
- Click "⚙ Advanced settings". Verify the panel expands showing: Playback Speed, Original Underlay, LLM Model, Blur Original Subtitles, ElevenLabs Voice ID (only if EL is selected).
- Click again to collapse.
- Pick an unsupported provider configuration to confirm the amber API-key warning appears at the bottom of the card.
- Open DevTools → Network. Start a pipeline. Inspect the POST body to `/api/pipeline/full`:
  - `tts_voice_profile` is `female-vi-natural` (or `female-en-natural` if you chose English translation).
  - `tts_voice` is the selected voice from the dropdown / ElevenLabs ID input.
  - `tts_provider`, `tts_api_key`, `playback_speed`, `underlay_db` are all present.

- [ ] **Step 4: UI smoke — running state**

Watch a single-URL pipeline run after submitting:

- Configuration card disappears.
- A slim progress strip appears showing the current stage, percent, and message.
- When the pipeline completes, Configuration card reappears.

- [ ] **Step 5: UI smoke — Subtitle Editor warning**

- Run a full pipeline that produces both `{id}_vi.srt` and `{id}_vi.dubsync.srt`.
- Open the Subtitle Editor on that video, language Vietnamese.
- Confirm the amber warning banner shows at the top: "You're editing the dub-synced subtitle. Re-running TTS will regenerate this file and lose your manual edits."
- Make a small edit; save.
- Confirm the dubsync file (`data/srt/{id}_vi.dubsync.srt`) has your edit; the legacy SRT (`data/srt/{id}_vi.srt`) is untouched.

- [ ] **Step 6: UI smoke — SRT download**

- On the Video List or VideoDetail page, click "Download SRT" for the same video (Vietnamese).
- Confirm the downloaded file's contents match the dubsync file, but the filename is `{id}_vi.srt` (no `.dubsync` infix).

- [ ] **Step 7: Push the branch**

```bash
git push origin feature/phase4-dubbing-redesign-spec
```

- [ ] **Step 8: Provide a PR link**

If you haven't yet opened a PR, do so:

```bash
gh pr view feature/phase4-dubbing-redesign-spec 2>/dev/null || gh pr create \
  --title "TTS dubbing redesign + providers cleanup + pipeline UI cleanup" \
  --body "$(cat <<'EOF'
## Summary

Long-running branch covering the full TTS dubbing arc:

1. Dubbing redesign (planner + assembler + Chinese underlay → routed to processor).
2. TTS providers cleanup (drop edge/gtts/piper; keep google/elevenlabs/openai).
3. Pipeline page UI cleanup (flat Configuration card; drop the 5-step stepper).
4. Dubsync default (GET/PUT SRT endpoints prefer the dub-synced file; editor warns when editing it).

See `docs/superpowers/specs/2026-05-2*-*.md` for the full design history.

## Test plan
- [ ] All automated tests pass (`make test`)
- [ ] Full pipeline runs end-to-end against a testurl.txt video with Google TTS
- [ ] Subtitle Editor shows the dubsync warning banner on videos that have a dubsync file
- [ ] Pipeline launcher hides the Configuration card during a run and shows a slim progress strip
EOF
)"
```

If the PR already exists, just push.

- [ ] **Step 9: Report state**

Return:
- Total commits on this branch since `main`: `git rev-list --count main..HEAD`
- Files changed: `git diff --stat main..HEAD | tail -1`
- Test counts from Step 1
- PR URL

---

## Self-Review Checklist

**Spec coverage:**

- ✅ §Part 1 (Configuration card layout, deleted stepper, retained fields) — Task 4
- ✅ §Part 1 (Voice Profile dropdown removal + implicit mapping) — Task 4 Steps 6-7
- ✅ §Part 1 (Running progress strip replaces card during run) — Task 4 Step 5
- ✅ §Part 1 (URL card, error banner, video library unchanged) — Tasks 4 (verified via line counts + smoke test)
- ✅ §Part 2 (Backend dubsync resolver on GET / download endpoints) — Task 1
- ✅ §Part 2 (PUT endpoint writes to dubsync when present) — Task 2
- ✅ §Part 2 (SrtResponse.is_dubsync new field) — Task 1
- ✅ §Part 2 (Editor warning banner driven by is_dubsync) — Task 3
- ✅ §Tests (new tests in test_srt_endpoints.py covering 4 scenarios for GET + 2 for PUT) — Tasks 1, 2

**Placeholder scan:**

- No "TBD" / "TODO" / "fill in details" — checked.
- No "Add appropriate error handling" — concrete handling shown.
- No "Similar to Task N" — JSX code blocks are explicit in each task.
- No references to undefined types or functions — `getSrt`, `TTSPreview`, `loadApiKeys`, `storageGet`, `storageSet`, `navigate`, `useNavigate` are confirmed present in the existing file (verified via grep at file-structure review).

**Type consistency:**

- Backend: `_resolve_srt_path` returns `tuple[Path, bool]` — used identically in `get_srt`, `download_srt`, `save_srt`.
- Backend: `SrtResponse.is_dubsync: bool` — set in `get_srt` (Task 1 Step 5) and `save_srt` (Task 2 Step 3), defaulted to `False` on the model so existing tests don't break.
- Frontend: `SrtResponse.is_dubsync?: boolean` — used in `SubtitleEditor.tsx` (Task 3 Step 4) as `data.is_dubsync`. Optional with `Boolean(...)` coercion so undefined → false.
- Frontend: `showAdvanced: boolean` — only used in Task 4 Step 3 + Step 5.
- Frontend: Voice profile string derivation (`female-vi-natural` / `female-en-natural`) — consistent in Task 4 Step 6 and the spec.

**Known minor risks (call out but no plan change):**

- Task 1 Step 1 — `_make_client` instantiates the full FastAPI app. If the app's startup includes side effects (e.g. PaddleOCR model load), the tests will be slow. If they take more than ~5s, consider mocking the task manager. The pattern works in the existing test suite; adjust if needed.
- Task 4 Step 6 — if `selectedTtsProfile` is referenced in places I didn't identify (e.g. an SSE handler, a status displayer), TS may complain after Step 7. Resolution: grep for any remaining usage and either remove or keep the orphan state declaration.
- Task 5 Step 5 — manual QA against the dubsync warning requires having generated both files. Run a full pipeline first.

**Note on existing `tests/test_processor.py`:**

That file already tests the burn-in `select_subtitle_for_platform`'s dubsync preference. The new `tests/test_srt_endpoints.py` is for the GET/PUT/download endpoints specifically — different code path, different file. They don't overlap.
