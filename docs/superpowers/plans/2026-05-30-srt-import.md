# SRT Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user upload an edited SRT from the per-video page; it lands as the next auto-numbered version snapshot, skipping the working draft entirely.

**Architecture:** Sibling helper to `snapshot_working_draft` in `src/api/versions.py` — `import_as_version` validates uploaded bytes via `parse_srt`, writes them verbatim to `{video_id}_{lang}.v{N}.srt`, appends to `versions.json`. A new multipart `POST /api/videos/{id}/versions/import` exposes it. FE adds a hidden `<input type="file">` paired with an "Import SRT" button in the EditorTab toolbar; `useVersions` gains an `importFile` method that wraps the API call and refreshes the list.

**Tech Stack:** FastAPI + Pydantic v2 (BE), React 19 + TypeScript + Tailwind 4 + Vite + vitest (FE).

---

## Context the implementer needs

**Spec:** [docs/superpowers/specs/2026-05-30-srt-import-design.md](docs/superpowers/specs/2026-05-30-srt-import-design.md) — read first.

**Files at HEAD (read before starting):**
- [src/api/versions.py:83-103](src/api/versions.py#L83-L103) — `snapshot_working_draft` (the helper to mirror)
- [src/api/versions.py:106-170](src/api/versions.py#L106-L170) — `ensure_migrated` (called by every router handler)
- [src/api/routers/versions.py](src/api/routers/versions.py) — entire file; current routes use JSON bodies via Pydantic `BaseModel`. We're adding the first multipart endpoint.
- [src/processor/subtitle.py](src/processor/subtitle.py) — `parse_srt` is what we use to validate uploads
- [tests/test_versions.py:105-202](tests/test_versions.py#L105-L202) — `TestSnapshotWorkingDraft` and `TestDeleteVersion` are the mirror templates for the new test classes
- [tests/test_versions.py:225+](tests/test_versions.py#L225) — `TestVersionsRouter` shows the TestClient + monkeypatch fixture pattern
- [ui-app/src/api/versions.ts](ui-app/src/api/versions.ts) — existing CRUD wrappers (`getVersions`, `createVersion`, `renameVersion`, `deleteVersion`); these use JSON. We add `importVersion` using `FormData`.
- [ui-app/src/hooks/useVersions.ts](ui-app/src/hooks/useVersions.ts) — wraps API calls + auto-refreshes. Existing methods: `createSnapshot`, `rename`, `remove`, `refresh`. Add `importFile`.
- [ui-app/src/hooks/__tests__/useVersions.test.tsx](ui-app/src/hooks/__tests__/useVersions.test.tsx) — existing tests for the hook; one more test added at the end.
- [ui-app/src/pages/videoDetail/EditorTab.tsx](ui-app/src/pages/videoDetail/EditorTab.tsx) — toolbar layout. Existing imports at line 12 include `getSrtDownloadUrl`. The toolbar JSX is around line 340 (where `getSrtDownloadUrl` is referenced). `saveStatus` state is on line 45; the save-status flash is around lines 321-326.
- [ui-app/src/pages/VideoDetail.tsx](ui-app/src/pages/VideoDetail.tsx) — destructures `useVersions(...)` and passes its members into `<EditorTab>`.

**Commands you'll use:**
- BE tests (file): `python -m pytest tests/test_versions.py -v`
- BE tests (full): `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py`
- FE tests: `cd ui-app && npx vitest run`
- FE build: `cd ui-app && npm run build`
- BE lint: `ruff check src/ tests/`

**Repo rules to follow (from CLAUDE.md):**
- Branch: `feature/srt-import` already exists with the spec commit `99a4cd4`. Stay on it.
- Bundle CHANGELOG + README into Task 5.
- No "Co-Authored-By", no AI mentions in commits or code comments.

---

## File structure

| Path | Action | Responsibility |
|------|--------|---------------|
| `src/api/versions.py` | Modify | Add `import_as_version(video_id, language, srt_content, name) -> VersionEntry` after `snapshot_working_draft` |
| `src/api/routers/versions.py` | Modify | Add `POST /api/videos/{id}/versions/import` endpoint; import `UploadFile`, `File`, `Form` from fastapi |
| `tests/test_versions.py` | Modify | Append `TestImportAsVersion` (4 tests) and `TestImportRouter` (3 tests) |
| `ui-app/src/api/versions.ts` | Modify | Add `importVersion(videoId, language, file, name?) -> Promise<VersionEntry>` |
| `ui-app/src/hooks/useVersions.ts` | Modify | Add `importFile(file, name)` method to the returned object |
| `ui-app/src/hooks/__tests__/useVersions.test.tsx` | Modify | Append `importFile calls the API and refreshes` test |
| `ui-app/src/pages/videoDetail/EditorTab.tsx` | Modify | Add hidden file input + "Import SRT" button to toolbar; new `onImportVersion` prop |
| `ui-app/src/pages/VideoDetail.tsx` | Modify | Destructure `importFile` from `useVersions`; pass as `onImportVersion` to EditorTab |
| `CHANGELOG.md` | Modify | One `Added` entry under `[Unreleased]` |
| `README.md` | Modify | Progress section for this feature |

---

### Task 1: BE — `import_as_version` helper

Pure-function helper sibling of `snapshot_working_draft`. Validates uploaded bytes by parsing through `parse_srt`, then writes them verbatim to the snapshot path and appends to `versions.json`.

**Files:**
- Modify: `src/api/versions.py`
- Modify: `tests/test_versions.py`

- [ ] **Step 1.1: Write the failing tests**

Append after the existing `TestDeleteVersion` class (around line 200 of `tests/test_versions.py`):

```python
_VALID_SRT_BYTES = (
    b"1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
    b"2\n00:00:02,000 --> 00:00:03,000\nworld\n\n"
)


class TestImportAsVersion:
    def test_import_creates_next_version(self, srt_dir):
        from src.api.versions import import_as_version, load_versions, save_versions

        # Empty versions.json so ensure_migrated is a no-op (none here anyway —
        # the function doesn't call ensure_migrated).
        save_versions("vid1", "vi", [])

        entry = import_as_version("vid1", "vi", _VALID_SRT_BYTES, name=None)
        assert entry.id == "v1"
        assert entry.name is None

        snap = srt_dir / "vid1_vi.v1.srt"
        assert snap.exists()
        assert snap.read_bytes() == _VALID_SRT_BYTES

        listing = load_versions("vid1", "vi")
        assert len(listing) == 1
        assert listing[0].id == "v1"

    def test_import_with_existing_versions_increments(self, srt_dir):
        from datetime import datetime, timezone
        from src.api.versions import (
            VersionEntry,
            import_as_version,
            save_versions,
        )

        save_versions("vid1", "vi", [
            VersionEntry(id="v1", name=None,
                created_at=datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc)),
            VersionEntry(id="v2", name="polished",
                created_at=datetime(2026, 5, 30, 11, 0, 0, tzinfo=timezone.utc)),
        ])

        entry = import_as_version("vid1", "vi", _VALID_SRT_BYTES, name=None)
        assert entry.id == "v3"

    def test_import_with_name_sets_name(self, srt_dir):
        from src.api.versions import import_as_version, save_versions

        save_versions("vid1", "vi", [])
        entry = import_as_version("vid1", "vi", _VALID_SRT_BYTES, name="from-aegisub")
        assert entry.name == "from-aegisub"

    def test_import_invalid_srt_raises_value_error(self, srt_dir):
        import pytest
        from src.api.versions import import_as_version, save_versions

        save_versions("vid1", "vi", [])
        with pytest.raises(ValueError):
            import_as_version("vid1", "vi", b"this is not an srt file", name=None)

    def test_import_empty_srt_raises_value_error(self, srt_dir):
        import pytest
        from src.api.versions import import_as_version, save_versions

        save_versions("vid1", "vi", [])
        with pytest.raises(ValueError):
            import_as_version("vid1", "vi", b"", name=None)
```

Note: the test count is 5 (4 in the spec + 1 extra `with_name_sets_name` — covers the name parameter path; cheap to add).

- [ ] **Step 1.2: Run — confirm fail**

Run: `python -m pytest tests/test_versions.py::TestImportAsVersion -v 2>&1 | tail -15`

Expected: 5 tests FAIL with `ImportError: cannot import name 'import_as_version' from 'src.api.versions'`.

- [ ] **Step 1.3: Implement `import_as_version`**

Open `src/api/versions.py`. Find `snapshot_working_draft` (around line 83-103). Insert this function immediately after it (before `ensure_migrated`):

```python
def import_as_version(
    video_id: str,
    language: str,
    srt_content: bytes,
    name: str | None = None,
) -> VersionEntry:
    """Validate uploaded SRT bytes and write them as the next snapshot.

    Validates by parsing via ``processor.subtitle.parse_srt`` against a temp
    file. Raises ValueError on parse failure or zero-segment content
    (caller should map to HTTP 400).

    Unlike ``snapshot_working_draft``, this does NOT touch the working draft —
    imports are always new immutable snapshots. The working draft stays
    whatever the user last saved in the editor.

    The bytes are written verbatim (no re-serialisation), preserving the
    user's original formatting.
    """
    import tempfile
    from src.processor.subtitle import parse_srt

    # Validate by parsing. Use a NamedTemporaryFile so parse_srt's
    # Path-based API works without changes. Reject empty content first
    # (parse_srt would return [] but the error message is clearer up front).
    if not srt_content.strip():
        raise ValueError("Invalid or empty SRT")

    with tempfile.NamedTemporaryFile(suffix=".srt", delete=False) as tmp:
        tmp.write(srt_content)
        tmp_path = Path(tmp.name)
    try:
        try:
            segments = parse_srt(tmp_path)
        except Exception as e:
            raise ValueError(f"Invalid SRT: {e}") from e
        if not segments:
            raise ValueError("Invalid or empty SRT")
    finally:
        tmp_path.unlink(missing_ok=True)

    entries = load_versions(video_id, language)
    new_id = next_version_id(entries)
    snap_path = SRT_DIR / f"{video_id}_{language}.{new_id}.srt"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_bytes(srt_content)
    entry = VersionEntry(
        id=new_id, name=name, created_at=datetime.now(timezone.utc)
    )
    entries.append(entry)
    save_versions(video_id, language, entries)
    return entry
```

The `tempfile` + `from src.processor.subtitle import parse_srt` imports are inlined to keep them next to their only use (matches the pattern of other lazy imports already in this file).

- [ ] **Step 1.4: Run — confirm 5 pass**

Run: `python -m pytest tests/test_versions.py::TestImportAsVersion -v 2>&1 | tail -15`

Expected: 5 passed.

- [ ] **Step 1.5: Run the whole versions test file**

Run: `python -m pytest tests/test_versions.py -v 2>&1 | tail -10`

Expected: all previous tests still pass + the 5 new ones.

- [ ] **Step 1.6: Commit**

```bash
git add src/api/versions.py tests/test_versions.py
git commit -m "feat(versions): import_as_version helper

Sibling of snapshot_working_draft. Takes raw SRT bytes, validates by
parsing through parse_srt (via a temp file), and writes them verbatim
to the next snapshot path. Appends a VersionEntry with name and
created_at=now to versions.json.

Empty or unparseable content raises ValueError (caller maps to HTTP
400). The bytes are written verbatim — no re-serialisation — so
user-formatted SRTs preserve their original byte layout (line endings,
spacing inside cue text, etc.).

5 new tests in TestImportAsVersion cover: first-version creation,
gap-tolerant increment over existing entries, name parameter pass-
through, garbage bytes rejection, empty content rejection."
```

---

### Task 2: BE — POST `/api/videos/{id}/versions/import` endpoint

Multipart endpoint that reads the uploaded file, calls `import_as_version`, returns the new `VersionEntry`.

**Files:**
- Modify: `src/api/routers/versions.py`
- Modify: `tests/test_versions.py`

- [ ] **Step 2.1: Write the failing tests**

Append after `TestVersionsRouter` in `tests/test_versions.py` (the class ends around line 320):

```python
class TestImportRouter:
    def test_post_import_returns_201_with_entry(self, client):
        from io import BytesIO

        valid_srt = (
            b"1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        )
        c, _, _ = client
        r = c.post(
            "/api/videos/vidA/versions/import?language=vi",
            files={"file": ("uploaded.srt", BytesIO(valid_srt), "text/plain")},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == "v1"
        assert body["name"] is None
        assert "created_at" in body

    def test_post_import_with_name_sets_name(self, client):
        from io import BytesIO

        valid_srt = (
            b"1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
        )
        c, _, _ = client
        r = c.post(
            "/api/videos/vidA/versions/import?language=vi",
            files={"file": ("uploaded.srt", BytesIO(valid_srt), "text/plain")},
            data={"name": "polished"},
        )
        assert r.status_code == 201
        assert r.json()["name"] == "polished"

    def test_post_import_rejects_invalid_srt(self, client):
        from io import BytesIO

        c, _, _ = client
        r = c.post(
            "/api/videos/vidA/versions/import?language=vi",
            files={"file": ("garbage.srt", BytesIO(b"not an srt at all"), "text/plain")},
        )
        assert r.status_code == 400
```

The `client` fixture is defined earlier in the file (around line 205) — it gives `(TestClient, srt_dir, tts_dir)` with `vidA` pre-seeded in `video_index` and an empty `versions.json` written. The existing `TestVersionsRouter` uses the same fixture.

- [ ] **Step 2.2: Run — confirm fail**

Run: `python -m pytest tests/test_versions.py::TestImportRouter -v 2>&1 | tail -15`

Expected: 3 FAIL with `404 Not Found` (the route doesn't exist yet).

- [ ] **Step 2.3: Add the endpoint to `src/api/routers/versions.py`**

Open `src/api/routers/versions.py`. Update the imports at the top:

```python
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from src.api import versions as versions_mod
```

(Add `File`, `Form`, `UploadFile` to the existing `fastapi` import.)

Append this handler after the existing `delete_version` handler (after the closing line ~84):

```python
@router.post(
    "/api/videos/{video_id}/versions/import",
    response_model=versions_mod.VersionEntry,
    status_code=201,
)
async def import_version(
    video_id: str,
    language: str,
    file: UploadFile = File(...),
    name: str | None = Form(None),
):
    """Upload an edited SRT and snapshot it as the next version.

    Skips the working draft. The uploaded bytes become
    {video_id}_{language}.v{N+1}.srt. Rejects parse-failed or empty SRTs
    with 400.
    """
    versions_mod.ensure_migrated(video_id, language)
    content = await file.read()
    try:
        return versions_mod.import_as_version(video_id, language, content, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 2.4: Run — confirm 3 pass**

Run: `python -m pytest tests/test_versions.py::TestImportRouter -v 2>&1 | tail -15`

Expected: 3 passed.

- [ ] **Step 2.5: Run the full versions test file**

Run: `python -m pytest tests/test_versions.py -v 2>&1 | tail -10`

Expected: all previous + 8 new (5 from Task 1 + 3 from Task 2) all pass.

- [ ] **Step 2.6: Lint**

Run: `ruff check src/api/routers/versions.py src/api/versions.py 2>&1 | tail -5`

Expected: no new errors.

- [ ] **Step 2.7: Commit**

```bash
git add src/api/routers/versions.py tests/test_versions.py
git commit -m "feat(versions): POST /api/videos/{id}/versions/import endpoint

Multipart form endpoint that wraps import_as_version. Accepts a file
field (the SRT) and an optional name form field. Calls ensure_migrated
first so legacy videos get upgraded transparently. Returns 201 with the
new VersionEntry on success; 400 with the ValueError message on
parse failure.

3 new endpoint tests in TestImportRouter: success path, name=field
pass-through, invalid-SRT rejection."
```

---

### Task 3: FE — `importVersion` client + `useVersions.importFile` method

**Files:**
- Modify: `ui-app/src/api/versions.ts`
- Modify: `ui-app/src/hooks/useVersions.ts`
- Modify: `ui-app/src/hooks/__tests__/useVersions.test.tsx`

- [ ] **Step 3.1: Write the failing test**

Append inside the existing `describe('useVersions', ...)` block in `ui-app/src/hooks/__tests__/useVersions.test.tsx` (after the last `it(...)`):

```ts
it('importFile calls the API and refreshes', async () => {
  const api = await import('../../api/versions');
  (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
  (api.importVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
    id: 'v1', name: null, created_at: '2026-05-30T10:00:00Z',
  });
  (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
    { id: 'v1', name: null, created_at: '2026-05-30T10:00:00Z' },
  ]);

  const { result } = renderHook(() => useVersions('vid1', 'vi'));
  await waitFor(() => expect(result.current.versions).toEqual([]));

  const file = new File(['srt content'], 'test.srt', { type: 'text/plain' });
  await act(async () => {
    await result.current.importFile(file, null);
  });

  expect(api.importVersion).toHaveBeenCalledWith('vid1', 'vi', file, null);
  await waitFor(() => expect(result.current.versions).toHaveLength(1));
});
```

Also update the top-of-file `vi.mock` block to include `importVersion`:

```ts
vi.mock('../../api/versions', () => ({
  getVersions: vi.fn(),
  createVersion: vi.fn(),
  renameVersion: vi.fn(),
  deleteVersion: vi.fn(),
  importVersion: vi.fn(),
}));
```

(Add the `importVersion: vi.fn()` line — don't remove the existing entries.)

- [ ] **Step 3.2: Run — confirm fail**

Run: `cd ui-app && npx vitest run src/hooks/__tests__/useVersions.test.tsx 2>&1 | tail -10`

Expected: the new test FAILs with `result.current.importFile is not a function` (or similar).

- [ ] **Step 3.3: Add `importVersion` to `ui-app/src/api/versions.ts`**

Append to `ui-app/src/api/versions.ts` (after `deleteVersion`):

```ts
export async function importVersion(
  videoId: string,
  language: string,
  file: File,
  name?: string | null,
): Promise<VersionEntry> {
  const formData = new FormData();
  formData.append('file', file);
  if (name) formData.append('name', name);
  const r = await fetch(
    `/api${`/videos/${videoId}/versions/import?language=${language}`}`,
    { method: 'POST', body: formData },
  );
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    throw new Error(`${r.status} ${body}`);
  }
  return r.json();
}
```

Note: we bypass the file's existing `request` helper because that helper sets `Content-Type: application/json` by default (or some equivalent) — `FormData` needs the browser to set its own `multipart/form-data; boundary=...` header, which only works when no `Content-Type` is provided. Using raw `fetch` here keeps the multipart contract correct.

If the existing `request` helper in this file already handles `FormData` correctly (no JSON-content-type assumption), then reuse it instead — read the file once to check. The body of the helper above is the fallback that's guaranteed to work.

- [ ] **Step 3.4: Add `importFile` to `useVersions` hook**

Open `ui-app/src/hooks/useVersions.ts`. Update the imports at the top:

```ts
import {
  getVersions,
  createVersion,
  renameVersion,
  deleteVersion,
  importVersion,
} from '../api/versions';
```

(Add `importVersion`.)

After the `remove` method (and before the `return` statement), add:

```ts
const importFile = useCallback(
  async (file: File, name: string | null) => {
    if (!videoId) return;
    await importVersion(videoId, language, file, name);
    await refresh();
  },
  [videoId, language, refresh],
);
```

Update the return object:

```ts
return { versions, loading, createSnapshot, rename, remove, refresh, importFile };
```

(Add `importFile` to the returned values.)

- [ ] **Step 3.5: Run — confirm all hook tests pass**

Run: `cd ui-app && npx vitest run src/hooks/__tests__/useVersions.test.tsx 2>&1 | tail -10`

Expected: 5 passed (4 existing + 1 new).

- [ ] **Step 3.6: Commit**

```bash
git add ui-app/src/api/versions.ts ui-app/src/hooks/useVersions.ts ui-app/src/hooks/__tests__/useVersions.test.tsx
git commit -m "feat(fe): importVersion client + useVersions.importFile

importVersion wraps POST /api/videos/{id}/versions/import as a
multipart upload (FormData, no Content-Type override — the browser
picks the right boundary). The hook's importFile method calls it and
refreshes the versions list on success.

One new vitest covers the lifecycle: mounted with []; import a File;
importVersion called with (videoId, language, file, null); refresh
fires; versions has 1 entry."
```

---

### Task 4: FE — "Import SRT" button in EditorTab

Hidden file input triggered by a button next to the SRT-download anchor.

**Files:**
- Modify: `ui-app/src/pages/videoDetail/EditorTab.tsx`
- Modify: `ui-app/src/pages/VideoDetail.tsx`

- [ ] **Step 4.1: Wire `importFile` in VideoDetail**

In `ui-app/src/pages/VideoDetail.tsx`, find the line that destructures `useVersions(...)`:

```tsx
const { versions, createSnapshot, rename, remove } = useVersions(videoId, activeLang);
```

Add `importFile`:

```tsx
const { versions, createSnapshot, rename, remove, importFile } = useVersions(videoId, activeLang);
```

Find the `<EditorTab>` JSX render. The existing version props are passed as `onCreateSnapshot={createSnapshot}` etc. Add `onImportVersion={importFile}`:

```tsx
<EditorTab
  /* ...existing props including onCreateSnapshot/onRenameVersion/onDeleteVersion... */
  onImportVersion={importFile}
/>
```

- [ ] **Step 4.2: Add the prop type + button to EditorTab**

Open `ui-app/src/pages/videoDetail/EditorTab.tsx`. Add the new prop to the `Props` interface (find the interface — it has `versions`, `onCreateSnapshot`, etc.):

```ts
interface Props {
  // ...existing...
  onImportVersion: (file: File, name: string | null) => Promise<void>;
}
```

Destructure `onImportVersion` from props at the top of the component body.

Add the `useRef` import at the top of the file if it isn't already imported (`import { useRef, useState, useCallback, useMemo, useEffect } from 'react';` — `useRef` may or may not already be present).

Inside the component body, near the existing `saving` / `saveStatus` state, add:

```ts
const fileInputRef = useRef<HTMLInputElement>(null);
const [importing, setImporting] = useState(false);

const handleImport = useCallback(async (file: File) => {
  setImporting(true);
  setSaveStatus('idle');
  try {
    await onImportVersion(file, null);
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 3000);
  } catch {
    setSaveStatus('error');
  } finally {
    setImporting(false);
  }
}, [onImportVersion]);
```

In the toolbar JSX (search for `getSrtDownloadUrl` at line ~340 — that's the existing SRT download anchor), add this block right after the SRT download anchor's closing tag and before the Save button:

```tsx
<input
  ref={fileInputRef}
  type="file"
  accept=".srt"
  className="hidden"
  onChange={(e) => {
    const file = e.target.files?.[0];
    if (file) {
      handleImport(file);
    }
    e.target.value = '';
  }}
/>
<button
  onClick={() => fileInputRef.current?.click()}
  disabled={importing || !activeLang}
  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-highest text-on-surface-variant hover:bg-surface-container-high disabled:opacity-50 transition-colors"
  title={activeLang ? `Upload an edited ${activeLang.toUpperCase()} SRT as the next version` : 'Pick a language first'}
>
  <span className="material-symbols-outlined text-sm">
    {importing ? 'progress_activity' : 'upload'}
  </span>
  {importing ? 'Importing...' : 'Import SRT'}
</button>
```

The button is disabled when `importing` is true (avoid double-submit while the upload is in flight) or when `activeLang` is empty (matches the existing SRT-download anchor's gating).

- [ ] **Step 4.3: Run FE tests + build**

Run: `cd ui-app && npx vitest run 2>&1 | tail -10`

Expected: 39 passed (38 prior + 1 new from Task 3).

Run: `cd ui-app && npm run build 2>&1 | tail -10`

Expected: build succeeds. The two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may still be there — not in scope.

Run: `cd ui-app && npx eslint src/pages/videoDetail/EditorTab.tsx src/pages/VideoDetail.tsx 2>&1 | tail -5`

Expected: no new errors.

- [ ] **Step 4.4: Commit**

```bash
git add ui-app/src/pages/videoDetail/EditorTab.tsx ui-app/src/pages/VideoDetail.tsx
git commit -m "feat(editor): Import SRT button in toolbar

A hidden <input type=\"file\" accept=\".srt\"> paired with an
'Import SRT' button between the SRT-download anchor and Save. On file
selection the button calls onImportVersion (wired to
useVersions.importFile in VideoDetail), which creates the next
version snapshot via POST /api/videos/{id}/versions/import.

Success state piggybacks on saveStatus ('saved' green flash for 3s).
Failure flashes 'error'. The button shows a spinner + 'Importing...'
text while in flight and is disabled until the active editor language
is set."
```

---

### Task 5: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 5.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find the `## [Unreleased]` section. Find the existing `### Added` subsection (or create one above any `### Changed` / `### Removed` blocks). Add this entry at the top of `Added`:

```markdown
### Added
- **Import SRT in the video editor.** New "Import SRT" button in the EditorTab toolbar (between the SRT download anchor and Save). Uploads a `.srt` file as the next auto-numbered version snapshot — skips the working draft entirely; imports are immutable from the start. Auto-numbered `v{N+1}`, optional name (set blank by default; user can rename via the VersionPanel afterward). BE: new `POST /api/videos/{id}/versions/import?language=…` multipart endpoint that validates the upload via `parse_srt` and writes the bytes verbatim to `{video_id}_{language}.v{N+1}.srt`. Returns 400 on unparseable or empty content. FE: new `importVersion` API client + `useVersions.importFile` hook method. Success flashes the same green save-status as Save. 8 new BE tests (5 helper + 3 endpoint) + 1 new FE vitest. Sub-project 2 of 3 in the refocused app (closes the download-edit-import loop the refocus opened).
```

If the existing `Added` block has other entries, keep them — just add the new bullet at the top.

- [ ] **Step 5.2: README progress section**

Open `README.md`. Find the "App Refocus — Drop Export Pipeline (2026-05-30)" subsection. Insert this new subsection immediately after its `---` separator (before the next section):

```markdown
### SRT Import in Video Flow (2026-05-30)

> Sub-project 2 of 3 in the refocused app. See [`docs/superpowers/specs/2026-05-30-srt-import-design.md`](docs/superpowers/specs/2026-05-30-srt-import-design.md) and [`docs/superpowers/plans/2026-05-30-srt-import.md`](docs/superpowers/plans/2026-05-30-srt-import.md).

- [x] **Task 1** — BE `import_as_version` helper in `src/api/versions.py`: validates bytes via `parse_srt`, writes verbatim to `{id}_{lang}.v{N+1}.srt`, appends entry. 5 unit tests.
- [x] **Task 2** — BE `POST /api/videos/{id}/versions/import` multipart endpoint. Calls `ensure_migrated` + the helper. 400 on parse failure. 3 endpoint tests.
- [x] **Task 3** — FE `importVersion` client + `useVersions.importFile` method. 1 vitest.
- [x] **Task 4** — FE "Import SRT" button in EditorTab toolbar (hidden file input + button between the SRT download anchor and Save).
- [x] **Task 5** — CHANGELOG + README updates.

**Not in this PR:** sub-project 3 (standalone SRT → Dub tool). Separate spec + PR.

---
```

- [ ] **Step 5.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(srt-import): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10`

Expected: green. Test count = baseline + 8.

- [ ] **Step F.2: Full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -10`

Expected: green. Test count = baseline + 1.

- [ ] **Step F.3: FE build is clean**

Run: `cd ui-app && npm run build 2>&1 | tail -10`

Expected: succeeds (modulo the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).

- [ ] **Step F.4: BE lint**

Run: `ruff check src/ tests/ 2>&1 | tail -5`

Expected: no new errors.

- [ ] **Step F.5: Manual smoke (after merge)**

1. Open a video → Subtitle tab → click "Import SRT".
2. Pick an existing SRT from disk (e.g. one previously downloaded via the SRT button) → "saved" green flash; the new version appears in VersionPanel.
3. DubTab dropdown also shows the new version. Pick it → Generate dub → confirm the dub timing matches the imported SRT.
4. Rename it in VersionPanel → name persists across reloads.
5. Drop a `.txt` file with garbage content saved as `.srt` → red error flash; no new version created.
6. Set EditorTab language to `zh` → click Import SRT → uploaded file lands as the next Chinese version (the import is scoped to whichever language the editor is on).

---

## Self-review checklist (for the implementer)

- [ ] Each spec requirement maps to a task: `import_as_version` (T1), endpoint (T2), FE client + hook (T3), EditorTab button + VideoDetail wiring (T4), docs (T5).
- [ ] No "TBD" / "implement later" / "similar to Task N".
- [ ] Type/method names consistent: `import_as_version` (BE), `importVersion` (FE client), `importFile` (hook method), `onImportVersion` (EditorTab prop).
- [ ] No AI-attribution strings in commit messages or code comments.
- [ ] Branch stays `feature/srt-import`; no new branches.
