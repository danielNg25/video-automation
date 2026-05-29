# Subtitle Versioning + Dub-Version Picker

> **Sub-project 2 of 3** in the dub-sync rebuild. Sub-project 1 ([editor bug fixes](2026-05-29-subtitle-editor-bug-fixes-design.md), merged as PR #17) shipped the typable editor. Sub-project 3 (standalone text→voice tool) gets its own spec and PR after this lands.

## Goal

Replace today's implicit, diff-based "Sync Dub" mechanism with explicit user-managed subtitle versions. The editor saves edits to a mutable working draft; an explicit "Save as version" button snapshots the draft as an immutable, auto-numbered version. The DubTab gains a "Subtitle version" picker so the user chooses which version to dub from. Each (version + provider + voice) gets its own dub WAV in the audio library.

## Why now

The existing `sync_runner.py` / `dub_meta` flow tries to keep the dub WAV in sync with whatever's currently in the SRT by diffing segment texts, conditionally re-synthesising "dirty" segments and falling back to full re-synth on parameter changes or >50% dirty. In practice this is:

- **Opaque** — the user can't tell what the dub corresponds to.
- **Lossy** — once you re-dub, the previous version of the SRT (and its dub) is gone.
- **Confusing** — the "Sync Dub" banner triggers on small typo fixes that don't actually need re-synth.

The user has asked to rebuild it. Explicit versions are the simpler, more inspectable model.

## Non-goals

- **No backward compatibility with the sync-dub API.** `POST /api/videos/{id}/dub/sync`, the banner, and the dirty-segment logic are removed.
- **No per-segment cache.** Each dub is a clean full regen from the chosen SRT. At ~30 segments per video, full re-synth is a few cents per dub on Google TTS — not worth the cache complexity.
- **No version diff UI.** Comparing two SRT versions visually is a nice-to-have; defer.
- **No "production" / "for-export" tagging.** The chosen-for-dub state is implicit in which version the user picks in DubTab.
- **No multi-language version locking.** Versions are per (video, language). Editing the Chinese OCR creates Chinese versions independently of Vietnamese versions.
- **Sub-project 3 (standalone text→voice tool)** stays out of scope.

## Architecture

### Storage layout

Files live in `data/srt/` and `data/tts/` with version IDs embedded in filenames so a `glob` lists everything cheaply.

```
data/srt/
  {video_id}_zh.srt               # OCR (Chinese), untouched
  {video_id}_vi.srt                # Vietnamese working draft (mutable)
  {video_id}_vi.v1.srt             # snapshot v1 (immutable)
  {video_id}_vi.v2.srt             # snapshot v2 (immutable)
  {video_id}_vi.versions.json      # [{id, name, created_at}, …]

data/tts/
  {video_id}_vi_draft_{provider}_{voice}.wav   # dub generated from working draft
  {video_id}_vi_v1_{provider}_{voice}.wav      # dub generated from v1
  {video_id}_vi_v2_{provider}_{voice}.wav
```

Gone after this PR:

```
data/srt/{video_id}_vi.dubsync.srt            # deleted (folded into working draft on migration)
data/tts/{video_id}/dub_meta_*.json           # deleted on migration
data/tts/{video_id}/segments/                 # deleted on migration (per-segment cache)
src/tts/sync_runner.py                        # deleted
src/tts/dub_meta.py                           # deleted
src/tts/segment_cache.py                      # deleted (if it exists)
POST /api/videos/{id}/dub/sync                # endpoint removed
"Sync Dub" banner in EditorTab                # removed
```

### `versions.json` schema

Per-language list of immutable snapshots, sorted by `created_at`. Version IDs are strings like `"v1"`, `"v2"`, ascending. Names are optional user-typed labels.

```json
[
  {
    "id": "v1",
    "name": "migrated",
    "created_at": "2026-05-29T10:00:00Z"
  },
  {
    "id": "v2",
    "name": "polished",
    "created_at": "2026-05-29T11:30:00Z"
  }
]
```

The working draft is **not** an entry in this file. It's implicit (always the unsuffixed `{id}_{lang}.srt`). The DubTab picker constructs the displayed list as `[{id: "draft", name: "Working Draft"}, …versions]`.

### Backend API

The endpoint shapes preserve the existing SRT/TTS routes where possible; version is a new query/body parameter.

```
GET    /api/videos/{id}/srt?language=vi&version=draft|v1|v2
       → returns SubtitleSegment[] for that version. version=draft (default) reads the working draft.

PUT    /api/videos/{id}/srt?language=vi
       → overwrites the working draft. body: {segments: SubtitleSegment[]}
       → version is ignored / rejected (the editor only ever writes the working draft).

GET    /api/videos/{id}/versions?language=vi
       → [{id, name, created_at}, …] from versions.json. Working draft is NOT returned here.

POST   /api/videos/{id}/versions?language=vi   body: {name?: string|null}
       → snapshot the current working draft as the next auto-numbered version.
       → response: {id, name, created_at}

PATCH  /api/videos/{id}/versions/{ver}?language=vi   body: {name: string|null}
       → rename a snapshot. Returns the updated entry.

DELETE /api/videos/{id}/versions/{ver}?language=vi
       → delete the snapshot's SRT, all dub WAVs derived from it
         (glob {id}_{lang}_{ver}_*.wav), and the versions.json entry.

POST   /api/tts   body: {video_id, version: "draft"|"v1"|…, language, provider, voice, …}
       → generate a dub from the named version. Output filename:
         data/tts/{video_id}_{lang}_{ver}_{provider}_{voice}.wav

GET    /api/videos/{id}/tts
       → existing endpoint. Response gains a `version: string` field on each entry,
         parsed out of the filename.

DELETE /api/videos/{id}/dub/sync                   # ROUTE DELETED
```

### Frontend

**EditorTab** changes:

- Footer save area grows a second button "Save as version" next to "Save". Clicking it calls `POST /api/videos/{id}/versions`, on success the new version appears in a small "Saved versions" panel that lives in the editor footer (collapsible, default collapsed when there are 0 versions).
- The "Saved versions" panel lists every version with: id chip, name (inline-editable), created_at relative time, delete button. The panel is **hidden** when there are 0 versions and shown otherwise. Clicking the id chip switches the editor to read-only view of that version's SRT (informational only — promoting it back to the working draft is a follow-up; not in scope for this PR).
- The "Sync Dub" banner that today appears when the dub is out of sync with the SRT is **removed**. The editor's Save button no longer cares about dub state — saving is just saving.

**DubTab** changes:

- A new "Subtitle version" picker at the top of the panel, above the existing provider/language/voice controls. Default selection: working draft. Other options: every entry in `versions.json` for the current language, in `created_at` descending order (newest first under the working draft).
- The audio library entries gain a colored chip showing which version each dub was generated from. The chip text is the version id (`draft`, `v1`, `v2`).
- The "Generate Dub" button passes the chosen version to `POST /api/tts`. If a dub already exists for the current (version + provider + voice) tuple it's overwritten silently.

**VideoDetail / SWR keys:**

- `getSrt(videoId, language)` becomes `getSrt(videoId, language, version)`. The default `version=draft` preserves today's behaviour for code paths that haven't migrated.
- A new SWR-style hook `useVersions(videoId, language)` returns `{versions, refresh}` and is consumed by both tabs.

### Migration (lazy, on first read)

The first time the BE reads `versions.json` for a given `(video_id, language)` and finds it missing, it runs a one-shot migration:

```python
def migrate_to_versions(video_id: str, language: str) -> None:
    srt_dir = Path("data/srt")
    versions_path = srt_dir / f"{video_id}_{language}.versions.json"
    if versions_path.exists():
        return  # already migrated

    legacy_srt = srt_dir / f"{video_id}_{language}.srt"
    legacy_dubsync = srt_dir / f"{video_id}_{language}.dubsync.srt"

    if not legacy_srt.exists() and not legacy_dubsync.exists():
        # Brand-new video with no SRT yet. Write an empty versions.json so
        # we don't repeat this check on every read.
        versions_path.write_text("[]")
        return

    # Prefer dubsync.srt as the source of truth (it has the post-dub timings).
    source = legacy_dubsync if legacy_dubsync.exists() else legacy_srt
    v1_path = srt_dir / f"{video_id}_{language}.v1.srt"
    shutil.copy(source, v1_path)
    if source == legacy_dubsync:
        # Working draft starts identical to v1 (legacy_srt may have older
        # timings; the user has been editing dubsync.srt). Overwrite legacy_srt.
        shutil.copy(legacy_dubsync, legacy_srt)
        legacy_dubsync.unlink()

    # Rename existing dub WAVs from {id}_{lang}_{provider}_{voice}.wav to
    # {id}_{lang}_v1_{provider}_{voice}.wav so the audio library shows them
    # as belonging to v1.
    tts_dir = Path("data/tts")
    legacy_wavs = list(tts_dir.glob(f"{video_id}_{language}_*.wav"))
    for wav in legacy_wavs:
        # Skip already-versioned files.
        stem_parts = wav.stem.split("_")
        # Pattern: {id}_{lang}_{provider}_{voice}. After fix:
        # {id}_{lang}_v1_{provider}_{voice}. We insert "v1" at the third slot.
        # Detect by checking if the part after lang is already a version slot.
        if len(stem_parts) >= 3:
            third = stem_parts[2]
            if third == "draft" or re.fullmatch(r"v\d+", third):
                continue
        new_name = f"{stem_parts[0]}_{stem_parts[1]}_v1_{'_'.join(stem_parts[2:])}.wav"
        wav.rename(tts_dir / new_name)

    # Delete obsolete dub_meta JSON if present.
    meta_dir = tts_dir / video_id
    meta_json = meta_dir / f"dub_meta_{language}.json"
    if meta_json.exists():
        meta_json.unlink()
    # Delete the per-segment cache directory if present.
    seg_dir = meta_dir / "segments"
    if seg_dir.exists():
        shutil.rmtree(seg_dir)

    # Stamp versions.json.
    versions_path.write_text(json.dumps([{
        "id": "v1",
        "name": "migrated",
        "created_at": datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat(),
    }], indent=2))
```

Edge cases:

- **No SRT at all** (brand-new video, transcribe hasn't run): write `versions.json = []` to short-circuit future migrations.
- **dubsync.srt exists but `_vi.srt` doesn't** (shouldn't happen in practice): treat dubsync as the source and create `_vi.srt` from it.
- **Multiple dub WAVs** for different (provider, voice) combos: all rename to `v1`.
- **Concurrency:** the migration is fast (file copies). Wrap the whole function in `fcntl.flock` on `versions.json` to make it safe under concurrent reads.

Migration runs the first time any API endpoint reads versions for that (video_id, language). All read endpoints (`GET /api/videos/{id}/srt`, `GET /api/videos/{id}/versions`) call `ensure_migrated(video_id, language)` before their main logic.

### Files (BE)

- **New:** `src/api/versions.py` — `VersionEntry` Pydantic model, `load_versions(video_id, language)`, `save_versions(video_id, language, list)`, `ensure_migrated(video_id, language)`, `next_version_id(existing)`, `snapshot_working_draft(video_id, language, name)`, `delete_version(video_id, language, ver)`.
- **New:** `src/api/routers/versions.py` — the four CRUD routes (`GET`/`POST`/`PATCH`/`DELETE`).
- **Modify:** `src/api/routers/transcribe.py` — `_resolve_srt_path` becomes version-aware. Accept a `version: str = "draft"` parameter on `GET /api/videos/{id}/srt`. `PUT` writes only to the working draft.
- **Modify:** `src/api/routers/tts.py` — `POST /api/tts` accepts a `version: str = "draft"` parameter. The output filename includes the version. Delete `POST /api/videos/{id}/dub/sync` and the `_check_dub_sync_against_meta` helper.
- **Delete:** `src/tts/sync_runner.py`, `src/tts/dub_meta.py`, `src/tts/segment_cache.py` (if present), `src/tts/dubsync_srt.py`.
- **Modify:** `src/tts/assembler.py` — `generate_full_track` accepts `version: str` (used to name the output file) and no longer writes `dubsync.srt` or `dub_meta`. `run_partial` is deleted (the partial-resynth flow is gone).
- **Modify:** `src/api/task_manager.py` — `run_tts` accepts and forwards `version`.

### Files (FE)

- **New:** `ui-app/src/api/versions.ts` — `getVersions(videoId, language)`, `createVersion(videoId, language, name?)`, `renameVersion(videoId, language, ver, name)`, `deleteVersion(videoId, language, ver)`. Each returns a `VersionEntry`.
- **New:** `ui-app/src/hooks/useVersions.ts` — small hook wrapping the four CRUD calls with a local state cache and a `refresh()`.
- **Modify:** `ui-app/src/api/client.ts` — `getSrt` accepts an optional `version: string = 'draft'`. `postTts` accepts and forwards `version`.
- **Modify:** `ui-app/src/pages/videoDetail/EditorTab.tsx` — footer gains "Save as version" button and a collapsible "Saved versions" panel. Remove the "Sync Dub" banner and its `postDubSync` call. The Save button still writes only the working draft.
- **Modify:** `ui-app/src/pages/videoDetail/DubTab.tsx` — adds the "Subtitle version" dropdown at the top. Library entries display a version chip. The generate-dub call passes `version`.
- **Modify:** `ui-app/src/lib/pipelineStatus.tsx` — if SSE events reference dub-sync, drop those branches.
- **New:** `ui-app/src/components/editor/VersionPanel.tsx` — the saved-versions list with rename/delete actions.
- **New:** `ui-app/src/components/dub/VersionPicker.tsx` — the DubTab dropdown.

### Tests

**BE (pytest):**

- `tests/test_versions.py` — version CRUD round-trip: snapshot a working draft, list it, rename it, delete it (asserting SRT + WAV cleanup). 6 tests minimum.
- `tests/test_migration.py` — fixture-based: create a fake `_vi.dubsync.srt` + `_vi_google_voice.wav` + `dub_meta_vi.json` on disk, call `ensure_migrated`, assert the post-migration layout. Cases: dubsync-present, dubsync-absent, brand-new video, already-migrated (no-op).
- `tests/test_tts_versioned.py` — `generate_full_track` writes its WAV to `{id}_{lang}_{ver}_{provider}_{voice}.wav` and the file shows up in `GET /api/videos/{id}/tts` with the right `version` field.

**FE (vitest):**

- `ui-app/src/components/editor/__tests__/VersionPanel.test.tsx` — list renders, rename calls API, delete confirms and calls API.
- `ui-app/src/components/dub/__tests__/VersionPicker.test.tsx` — dropdown lists working draft + all versions, defaults to draft, changing selection calls the parent callback.

## Verification

1. `python -m pytest tests/test_versions.py tests/test_migration.py tests/test_tts_versioned.py -v` — all green.
2. `python -m pytest tests/ -x` — full BE suite passes (we expect deletions of old `test_sync_runner.py` etc. to clean up).
3. `cd ui-app && npm run test` — FE suite green.
4. `cd ui-app && npm run lint && npm run build` — clean.
5. **Manual smoke** (after merge):
   - Open an existing video. Editor footer shows "Saved versions: v1 (migrated)". DubTab dropdown shows "Working Draft" + "v1". Existing dub WAVs in the library show a `v1` chip.
   - Edit a few subtitles. Click "Save as version" → "v2" appears in the panel.
   - DubTab → pick v2 → Generate → new WAV appears in the library with a `v2` chip; library is sorted draft → v2 → v1.
   - Rename v2 to "polished" via the version panel → both EditorTab panel and DubTab dropdown reflect the name without reload (SWR/refresh).
   - Delete v1 → its SRT and any v1 dub WAVs vanish; library list updates.
   - Brand-new video (no prior SRT) → versions panel is empty; "Save as version" disabled until the editor has segments.

## Out of scope

- Standalone text→voice tool (sub-project 3).
- Visual diff between two versions.
- Sharing a version between videos (template versions).
- Per-version style overrides — `_style.json` still applies to all versions for now.
- "Open version as new draft" — the design includes a view-only mode for saved versions; promoting one back to the working draft is a follow-up (low risk, easy to add later).

## Critical files

- New BE: `src/api/versions.py`, `src/api/routers/versions.py`, `tests/test_versions.py`, `tests/test_migration.py`.
- Modified BE: `src/api/routers/transcribe.py`, `src/api/routers/tts.py`, `src/api/task_manager.py`, `src/tts/assembler.py`.
- Deleted BE: `src/tts/sync_runner.py`, `src/tts/dub_meta.py`, `src/tts/dubsync_srt.py`, plus their tests.
- New FE: `ui-app/src/api/versions.ts`, `ui-app/src/hooks/useVersions.ts`, `ui-app/src/components/editor/VersionPanel.tsx`, `ui-app/src/components/dub/VersionPicker.tsx`.
- Modified FE: `ui-app/src/pages/videoDetail/EditorTab.tsx`, `ui-app/src/pages/videoDetail/DubTab.tsx`, `ui-app/src/api/client.ts`.
- Docs: `CHANGELOG.md` (`Changed` entry — this is behavior change, not pure bug fix), `README.md` (progress section).
