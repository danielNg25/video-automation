# SRT Import (in video flow)

> **Sub-project 2 of 3** in the refocused app. Sub-project 1 (PR #20, merged) dropped the per-platform export pipeline. Sub-project 3 (standalone SRT→Dub tool) follows.

## Goal

Let the user upload an edited SRT file from the per-video page; it lands as the next auto-numbered version snapshot. Skips the working draft entirely — imports are immutable snapshots from the start. The user clicks **Import SRT**, picks a file, sees "Imported as v{N}" in the save-status area; the new entry shows up in the `VersionPanel` and is selectable in the `DubTab` version picker.

## Why

The refocused app's intended workflow is **download SRT → edit in your favorite SRT editor (Aegisub, Subtitle Edit, etc.) → bring it back → generate dub**. PR #20 wired the download but left the "bring it back" half missing. This closes the loop.

## Non-goals

- No language auto-detection from the filename. The upload targets the currently-active editor language (mirrors the SRT download button — both are scoped to `activeLang`).
- No name prompt on import. Auto-numbered `v{N+1}`; user can rename via the existing `VersionPanel` (uses the existing `PATCH /api/videos/{id}/versions/{ver}` endpoint).
- No pre-import diff preview against the working draft.
- No bulk import (one file at a time).
- No importing for languages other than the currently-active one. To import a Vietnamese SRT, switch the editor's active language to Vietnamese first.
- No replace-working-draft option. Imports always create a new snapshot.

## Architecture

A new helper `import_as_version` in `src/api/versions.py` mirrors `snapshot_working_draft` but takes raw SRT bytes instead of copying the working draft. A new multipart endpoint accepts the file upload, validates by parsing through `parse_srt`, and returns the new `VersionEntry`. The FE adds a hidden `<input type="file" accept=".srt">` paired with an "Import SRT" button in the EditorTab toolbar; on file selection it calls a new method on the `useVersions` hook, which refreshes the list on success so the new version appears immediately in the VersionPanel + DubTab picker.

```
EditorTab toolbar:  [⬇ Video]  [⬇ SRT]  [⬆ Import SRT]  ...  [Save]  [Save as version]
                                            │
                                            ▼ (hidden file input → file selection)
                                       useVersions.importFile(file, null)
                                            │
                                            ▼ POST /api/videos/{id}/versions/import (multipart)
                                       import_as_version(video_id, language, content, name=null)
                                            │
                                            ▼ write {id}_{lang}.v{N+1}.srt + append versions.json
                                       refresh() → VersionPanel + DubTab picker show the new entry
```

## Backend

### `src/api/versions.py` — new `import_as_version` helper

Add after `snapshot_working_draft`:

```python
def import_as_version(
    video_id: str,
    language: str,
    srt_content: bytes,
    name: str | None = None,
) -> VersionEntry:
    """Validate the uploaded SRT bytes and write them as the next snapshot.

    Validates by parsing via ``processor.subtitle.parse_srt`` against a temp
    file. Raises ValueError on parse failure (caller should map to HTTP 400).

    Unlike ``snapshot_working_draft``, this does NOT touch the working draft —
    imports are always new immutable snapshots. The working draft stays
    whatever the user last saved in the editor.
    """
```

Behaviour:
1. Parse the bytes by writing to `tempfile.NamedTemporaryFile(suffix=".srt")` and calling `parse_srt`. If parsing produces zero segments OR raises an exception, raise `ValueError("Invalid or empty SRT")`.
2. Compute `new_id = next_version_id(load_versions(video_id, language))`.
3. Write the bytes (verbatim, not re-serialized via `write_srt` — preserves user formatting) to `SRT_DIR / f"{video_id}_{language}.{new_id}.srt"`.
4. Append a `VersionEntry(id=new_id, name=name, created_at=datetime.now(timezone.utc))` to `versions.json` via `save_versions`.
5. Return the new entry.

Concurrency: same single-user assumption as `snapshot_working_draft`. No flock.

### `src/api/routers/versions.py` — new POST endpoint

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
    versions_mod.ensure_migrated(video_id, language)
    content = await file.read()
    try:
        return versions_mod.import_as_version(video_id, language, content, name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Imports `from fastapi import File, Form, UploadFile` at the top of the file.

The `language` stays a query parameter to match the other versions routes (`?language=vi`). The `name` field is optional — clients omit it for the common "import, name later" case.

## Frontend

### `ui-app/src/api/versions.ts` — new `importVersion` function

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
  return request(
    `/videos/${videoId}/versions/import?language=${language}`,
    { method: 'POST', body: formData },
  );
}
```

Uses `FormData` (not JSON) since it's multipart. Doesn't set `Content-Type` — the browser picks the right multipart boundary automatically.

### `ui-app/src/hooks/useVersions.ts` — new `importFile` method

Add to the returned object:

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

Import `importVersion` from `../api/versions` at the top.

### `ui-app/src/pages/videoDetail/EditorTab.tsx` — new "Import SRT" button

In the toolbar where "Video" / "SRT" / "Save" / "Save as version" already live, add a new button between the download SRT anchor and the Save button. The button triggers a hidden file input that accepts `.srt` only:

```tsx
const fileInputRef = useRef<HTMLInputElement>(null);
const [importing, setImporting] = useState(false);

const handleImport = async (file: File) => {
  setImporting(true);
  setSaveStatus('idle');
  try {
    await onImportVersion(file, null);  // prop passed from VideoDetail
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 3000);
  } catch {
    setSaveStatus('error');
  } finally {
    setImporting(false);
  }
};

// ... in JSX, between the SRT download anchor and the Save button:
<input
  ref={fileInputRef}
  type="file"
  accept=".srt"
  className="hidden"
  onChange={(e) => {
    const file = e.target.files?.[0];
    if (file) handleImport(file);
    e.target.value = '';  // reset so re-uploading the same filename works
  }}
/>
<button
  onClick={() => fileInputRef.current?.click()}
  disabled={importing || !activeLang}
  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-container-highest text-on-surface-variant hover:bg-surface-container-high disabled:opacity-50 transition-colors"
  title={`Upload an edited ${activeLang.toUpperCase()} SRT as the next version`}
>
  <span className="material-symbols-outlined text-sm">upload</span>
  Import SRT
</button>
```

The success state piggybacks on the existing `saveStatus` ('idle' / 'saved' / 'error') so the user gets the same green-flash feedback they get for Save.

EditorTab gains one new prop: `onImportVersion: (file: File, name: string | null) => Promise<void>`. `VideoDetail.tsx` wires it to `useVersions().importFile`.

### `ui-app/src/pages/VideoDetail.tsx` — pass `importFile` down

The component already destructures `{ versions, createSnapshot, rename, remove }` from `useVersions(videoId, activeLang)`. Add `importFile`:

```tsx
const { versions, createSnapshot, rename, remove, importFile } = useVersions(videoId, activeLang);
```

Pass `onImportVersion={importFile}` to `<EditorTab>` alongside the existing version props.

## Tests

### Backend — `tests/test_versions.py`

Add a new test class `TestImportAsVersion`:

```python
class TestImportAsVersion:
    def test_import_creates_next_version(self, tmp_path, monkeypatch):
        # Set SRT_DIR to tmp_path/srt
        # Write a versions.json so ensure_migrated doesn't fire
        # Call import_as_version with valid SRT bytes
        # Assert: returns VersionEntry with id='v1', name=None
        # Assert: file exists at {id}_{lang}.v1.srt with the exact bytes
        # Assert: versions.json has the new entry

    def test_import_with_existing_versions_increments(self, tmp_path, monkeypatch):
        # Seed versions.json with v1 + v2 entries (no actual files needed)
        # Import → id='v3'

    def test_import_invalid_srt_raises_value_error(self, tmp_path, monkeypatch):
        # Call with b"this is not an srt" → raises ValueError

    def test_import_empty_srt_raises_value_error(self, tmp_path, monkeypatch):
        # Call with b"" → raises ValueError
```

Add a new test class `TestImportRouter` using the existing FastAPI TestClient fixture:

```python
class TestImportRouter:
    def test_post_import_returns_201_with_entry(self, client):
        # Multipart POST with a valid SRT file
        # Assert: 201, body has id/name/created_at

    def test_post_import_rejects_invalid_srt(self, client):
        # Multipart POST with garbage bytes
        # Assert: 400

    def test_post_import_with_name_sets_name(self, client):
        # Multipart POST with file + name="polished"
        # Assert: 201, body.name == "polished"
```

### Frontend — `ui-app/src/hooks/__tests__/useVersions.test.tsx`

Add to the existing describe block:

```ts
it('importFile calls the API and refreshes', async () => {
  // Mock importVersion + getVersions
  // Call result.current.importFile(new File([...], 'test.srt'), null)
  // Assert: importVersion called with (videoId, language, file, null)
  // Assert: getVersions called again (refresh)
});
```

That's 8 new tests total (4 BE helper + 3 BE endpoint + 1 FE hook).

## Verification

1. `python -m pytest tests/test_versions.py -v` — all version tests green.
2. `python -m pytest tests/ -x` — full BE suite green.
3. `cd ui-app && npx vitest run` — full FE suite green (one new test).
4. `cd ui-app && npm run build` — clean (modulo the two pre-existing errors).
5. **Manual smoke** after merge:
   - Open a video → Subtitle tab → click "Import SRT".
   - Pick an existing SRT file from disk → "Imported as v{N}" appears in save-status area.
   - VersionPanel shows the new entry; DubTab dropdown also shows it.
   - Click the entry's name in VersionPanel → rename to "from-aegisub" → reload → name persists.
   - Click DubTab → select that version → Generate dub → confirm the dub uses the imported SRT (inspect the generated WAV's timing vs. the imported SRT).
   - Invalid SRT (try renaming a `.txt` to `.srt` with garbage content) → save-status flashes red.

## Out of scope

- Sub-project 3: standalone SRT → Dub tool (separate page, no video binding).

## Critical files

- New BE: `src/api/versions.py` (`import_as_version` helper), `src/api/routers/versions.py` (POST `/import` endpoint), `tests/test_versions.py` (8 new tests in 2 classes)
- New FE: `ui-app/src/api/versions.ts` (`importVersion` function), `ui-app/src/hooks/useVersions.ts` (`importFile` method), `ui-app/src/pages/videoDetail/EditorTab.tsx` (button + hidden input), `ui-app/src/pages/VideoDetail.tsx` (wire `importFile`), `ui-app/src/hooks/__tests__/useVersions.test.tsx` (1 new test)
- Docs: `CHANGELOG.md` (`Added` entry), `README.md` (progress section)
