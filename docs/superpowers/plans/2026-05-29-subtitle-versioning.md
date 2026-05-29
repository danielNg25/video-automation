# Subtitle Versioning + Dub-Version Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace today's implicit diff-based "Sync Dub" mechanism with explicit user-managed subtitle versions: a mutable working draft plus auto-numbered immutable snapshots, picked per-dub in the DubTab.

**Architecture:** Storage stays flat under `data/srt/` and `data/tts/`, with the version id embedded in filenames (`{id}_{lang}.v1.srt`, `{id}_{lang}_v1_{provider}_{voice}.wav`). A new per-(video,language) `versions.json` indexes the snapshots. The whole `sync_runner` / `dub_meta` / `dubsync.srt` / per-segment-cache machinery is deleted; every dub is a clean full regen against the chosen version. Migration is silent on first read — legacy `.dubsync.srt` becomes `v1`, existing dub WAVs get a `_v1_` infix, `dub_meta_*.json` and the segment cache directory are deleted.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic v2 (BE), React 19 + TypeScript + Tailwind 4 + Vite + vitest (FE).

---

## Context the implementer needs

**Spec:** [docs/superpowers/specs/2026-05-29-subtitle-versioning-design.md](docs/superpowers/specs/2026-05-29-subtitle-versioning-design.md) — read the full spec before starting; the tasks below are the *how*, the spec is the *what* and *why*.

**Files at HEAD (read these before starting):**
- [src/api/routers/transcribe.py:19-126](src/api/routers/transcribe.py#L19-L126) — `_resolve_srt_path` + `GET /api/videos/{id}/srt`
- [src/api/routers/editor.py:181-325](src/api/routers/editor.py#L181-L325) — `PUT /api/videos/{id}/srt` + `_check_dub_sync_against_meta`
- [src/api/routers/tts.py](src/api/routers/tts.py) — `POST /api/tts` + the soon-to-be-deleted `POST /api/videos/{id}/dub/sync`
- [src/api/task_manager.py:742-793](src/api/task_manager.py#L742-L793) — `run_tts` method
- [src/tts/assembler.py:418-770](src/tts/assembler.py#L418-L770) — `generate_full_track` (Stages 6, 7, and the per-segment cache write at Stage 1.5)
- [src/tts/sync_runner.py](src/tts/sync_runner.py), [src/tts/dub_meta.py](src/tts/dub_meta.py), [src/tts/dubsync_srt.py](src/tts/dubsync_srt.py), [src/tts/segment_cache.py](src/tts/segment_cache.py) — all four go away in Task 6
- [ui-app/src/api/client.ts:73-525](ui-app/src/api/client.ts#L73-L525) — `getSrt`, `postTTS`, `postDubSync`
- [ui-app/src/pages/videoDetail/EditorTab.tsx:302-698](ui-app/src/pages/videoDetail/EditorTab.tsx#L302-L698) — Save button, Sync Dub banner, `handleSyncDub`
- [ui-app/src/pages/videoDetail/DubTab.tsx](ui-app/src/pages/videoDetail/DubTab.tsx) — dub UI + audio library
- [ui-app/src/pages/VideoDetail.tsx](ui-app/src/pages/VideoDetail.tsx) — where the dub generation actually fires (`onGenerate` prop drilled down)
- [ui-app/src/components/editor/__tests__/SegmentList.test.tsx](ui-app/src/components/editor/__tests__/SegmentList.test.tsx) — repo's vitest precedent; match its style for the new component tests

**Commands you'll use:**
- BE tests (single file): `python -m pytest tests/test_versions.py -v`
- BE full suite: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py`
- FE tests: `cd ui-app && npx vitest run`
- BE lint: `ruff check src/ tests/`
- FE lint: `cd ui-app && npm run lint`
- FE build: `cd ui-app && npm run build`

**Repo rules to follow (from `CLAUDE.md`):**
- Branch: `feature/subtitle-versioning` is already created from main with the spec commit `75abf2a`. Stay on it.
- Every commit updates `CHANGELOG.md` (`Changed` for behavior changes that aren't pure bug fixes — this is a behavior change) and the progress section in `README.md`. Bundle CHANGELOG + README into the final Task 13 commit so the per-task diffs stay focused.
- **No AI mentions** in commit messages or code comments.
- No trailing summaries in code; the diff is the summary.

---

## File structure

| Path | Action | Responsibility |
|------|--------|---------------|
| `src/api/versions.py` | Create | `VersionEntry` Pydantic model, load/save `versions.json`, `ensure_migrated`, `next_version_id`, `snapshot_working_draft`, `delete_version` (cascades to SRT + dub WAVs) |
| `src/api/routers/versions.py` | Create | The four CRUD routes |
| `src/api/__init__.py` | Modify | Register the new versions router |
| `src/api/routers/transcribe.py` | Modify | `_resolve_srt_path` becomes version-aware; `GET /api/videos/{id}/srt` accepts `version` query param; calls `ensure_migrated` |
| `src/api/routers/editor.py` | Modify | `PUT /api/videos/{id}/srt` writes only to working draft; remove the `_check_dub_sync_against_meta` call and its return-field plumbing |
| `src/api/routers/tts.py` | Modify | `POST /api/tts` accepts `version`; output filename includes version. `POST /api/videos/{id}/dub/sync` route **deleted** |
| `src/api/task_manager.py` | Modify | `run_tts` accepts and forwards `version` |
| `src/tts/runner.py` | Modify | Output filename includes version (extract `dub_output_filename` helper for testing) |
| `src/tts/assembler.py` | Modify | `generate_full_track` accepts `version` (used in any logging only — output path is computed by the caller). Remove Stage 1.5 segment cache, Stage 6 dubsync.srt write, Stage 7 dub_meta write. `run_partial` method **deleted** |
| `src/tts/sync_runner.py` | **Delete** | |
| `src/tts/dub_meta.py` | **Delete** | |
| `src/tts/dubsync_srt.py` | **Delete** | |
| `src/tts/segment_cache.py` | **Delete** | |
| `tests/test_versions.py` | Create | Version CRUD round-trip |
| `tests/test_migration.py` | Create | `ensure_migrated` scenarios |
| `tests/test_tts_versioned.py` | Create | Versioned dub WAV filename test |
| `tests/test_tts_dub_sync_detection.py` | **Delete** | tests `sync_runner` which is deleted |
| `tests/test_tts_segment_cache.py` | **Delete** | tests `segment_cache` which is deleted |
| `tests/test_tts.py` | Modify | Drop any tests touching the removed stages (`TestDubsyncSrtWriter`, dub_meta integrations) |
| `ui-app/src/api/versions.ts` | Create | `getVersions`, `createVersion`, `renameVersion`, `deleteVersion`, `VersionEntry` type |
| `ui-app/src/hooks/useVersions.ts` | Create | Wraps the four versions API calls with local state + `refresh()` |
| `ui-app/src/api/client.ts` | Modify | `getSrt` and `postTTS` accept optional `version: string = 'draft'`. Delete `postDubSync` |
| `ui-app/src/api/types.ts` | Modify | `TTSAudioFile` gains `version: string` field |
| `ui-app/src/components/dub/VersionPicker.tsx` | Create | The DubTab top-of-panel dropdown |
| `ui-app/src/components/editor/VersionPanel.tsx` | Create | The EditorTab footer "Saved versions" panel |
| `ui-app/src/components/dub/__tests__/VersionPicker.test.tsx` | Create | vitest |
| `ui-app/src/components/editor/__tests__/VersionPanel.test.tsx` | Create | vitest |
| `ui-app/src/pages/videoDetail/EditorTab.tsx` | Modify | Add "Save as version" button + render `VersionPanel`. Remove Sync Dub banner + `handleSyncDub` + `isOutOfSync` / `isSyncing` / `syncError` state |
| `ui-app/src/pages/videoDetail/DubTab.tsx` | Modify | Add `VersionPicker` at top; library entries display version chip |
| `ui-app/src/pages/VideoDetail.tsx` | Modify | Pass version through to `postTTS` |
| `CHANGELOG.md` | Modify | One `Changed` entry under `[Unreleased]` |
| `README.md` | Modify | Add a "Subtitle Versioning + Dub-Version Picker (2026-05-29)" progress section |

---

### Task 1: `src/api/versions.py` — model + load/save + helpers

The pure-IO module. No FastAPI routing here; that lives in Task 3.

**Files:**
- Create: `src/api/versions.py`
- Create: `tests/test_versions.py`

- [ ] **Step 1.1: Write the failing test**

Create `tests/test_versions.py`:

```python
"""Tests for the subtitle versions module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def srt_dir(tmp_path, monkeypatch):
    """Redirect data/srt to a tmp dir for the duration of the test."""
    d = tmp_path / "srt"
    d.mkdir()
    monkeypatch.setattr("src.api.versions.SRT_DIR", d)
    return d


class TestVersionEntry:
    def test_default_fields(self):
        from src.api.versions import VersionEntry

        e = VersionEntry(
            id="v1",
            name="polished",
            created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc),
        )
        assert e.id == "v1"
        assert e.name == "polished"
        assert e.created_at.isoformat() == "2026-05-29T10:00:00+00:00"

    def test_name_can_be_none(self):
        from src.api.versions import VersionEntry

        e = VersionEntry(
            id="v3",
            name=None,
            created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc),
        )
        assert e.name is None


class TestLoadSaveVersions:
    def test_load_returns_empty_when_file_missing(self, srt_dir):
        from src.api.versions import load_versions

        assert load_versions("vid1", "vi") == []

    def test_save_then_load_round_trip(self, srt_dir):
        from src.api.versions import VersionEntry, load_versions, save_versions

        entries = [
            VersionEntry(
                id="v1",
                name="migrated",
                created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc),
            ),
        ]
        save_versions("vid1", "vi", entries)
        out = load_versions("vid1", "vi")
        assert len(out) == 1
        assert out[0].id == "v1"
        assert out[0].name == "migrated"

    def test_save_writes_to_expected_path(self, srt_dir):
        from src.api.versions import VersionEntry, save_versions

        save_versions("vid1", "vi", [
            VersionEntry(id="v1", name=None,
                created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)),
        ])
        expected = srt_dir / "vid1_vi.versions.json"
        assert expected.exists()
        loaded = json.loads(expected.read_text())
        assert loaded[0]["id"] == "v1"


class TestNextVersionId:
    def test_empty_list_returns_v1(self):
        from src.api.versions import next_version_id

        assert next_version_id([]) == "v1"

    def test_returns_one_more_than_highest_v_number(self):
        from src.api.versions import VersionEntry, next_version_id

        existing = [
            VersionEntry(id="v1", name=None,
                created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)),
            VersionEntry(id="v3", name=None,
                created_at=datetime(2026, 5, 29, 11, 0, 0, tzinfo=timezone.utc)),
        ]
        # Highest is v3 → next is v4 (gaps are tolerated; we never reuse ids).
        assert next_version_id(existing) == "v4"

    def test_ignores_non_v_prefixed_ids(self):
        from src.api.versions import VersionEntry, next_version_id

        existing = [
            VersionEntry(id="custom", name=None,
                created_at=datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)),
        ]
        assert next_version_id(existing) == "v1"
```

- [ ] **Step 1.2: Run — confirm tests fail**

Run: `python -m pytest tests/test_versions.py -v 2>&1 | tail -10`

Expected: all tests FAIL with `ImportError: cannot import name 'VersionEntry' from 'src.api.versions'`.

- [ ] **Step 1.3: Implement `src/api/versions.py`**

Create `src/api/versions.py`:

```python
"""Subtitle version model + on-disk IO.

Versions are immutable snapshots of a (video_id, language) working draft.
The working draft itself is NOT a version — it's the unsuffixed
`{video_id}_{language}.srt` file. Versions live next to it as
`{video_id}_{language}.v{N}.srt` and are indexed in a per-(video, language)
`{video_id}_{language}.versions.json`.

Migration from the legacy dubsync.srt / dub_meta layout lives in
`migration.py`; this module is pure version-set bookkeeping.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

SRT_DIR = Path("data/srt")
_VERSION_ID_RE = re.compile(r"^v(\d+)$")


class VersionEntry(BaseModel):
    """One immutable snapshot of a (video, language) working draft."""

    id: str
    name: str | None
    created_at: datetime


def _versions_path(video_id: str, language: str) -> Path:
    return SRT_DIR / f"{video_id}_{language}.versions.json"


def load_versions(video_id: str, language: str) -> list[VersionEntry]:
    """Return the sorted-by-creation-time list of snapshots, or [] if none."""
    path = _versions_path(video_id, language)
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [VersionEntry(**entry) for entry in raw]


def save_versions(
    video_id: str, language: str, entries: list[VersionEntry]
) -> None:
    """Write the entries to disk. Caller is responsible for ordering."""
    path = _versions_path(video_id, language)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": e.id,
            "name": e.name,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
    path.write_text(json.dumps(payload, indent=2))


def next_version_id(existing: list[VersionEntry]) -> str:
    """Return the next id of the form 'v{N}'.

    N is one more than the highest existing N (gaps are tolerated; we
    never reuse ids). When no entries match the `v{N}` pattern, returns
    `v1`.
    """
    max_n = 0
    for entry in existing:
        m = _VERSION_ID_RE.match(entry.id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"v{max_n + 1}"


def snapshot_working_draft(
    video_id: str, language: str, name: str | None = None
) -> VersionEntry:
    """Copy the current working-draft SRT to a new snapshot path and append
    an entry to versions.json. Raises FileNotFoundError if the working
    draft doesn't exist (caller should ensure_migrated first)."""
    import shutil

    working_draft = SRT_DIR / f"{video_id}_{language}.srt"
    if not working_draft.exists():
        raise FileNotFoundError(
            f"Working draft missing for {video_id}/{language}: {working_draft}"
        )
    entries = load_versions(video_id, language)
    new_id = next_version_id(entries)
    snap_path = SRT_DIR / f"{video_id}_{language}.{new_id}.srt"
    shutil.copy(working_draft, snap_path)
    entry = VersionEntry(
        id=new_id, name=name, created_at=datetime.now(timezone.utc)
    )
    entries.append(entry)
    save_versions(video_id, language, entries)
    return entry


def delete_version(video_id: str, language: str, version_id: str) -> bool:
    """Delete the snapshot SRT and any dub WAVs for that version. Removes
    the entry from versions.json. Returns False if the version_id isn't in
    the list."""
    entries = load_versions(video_id, language)
    found = next((e for e in entries if e.id == version_id), None)
    if found is None:
        return False
    # Delete SRT.
    snap_path = SRT_DIR / f"{video_id}_{language}.{version_id}.srt"
    if snap_path.exists():
        snap_path.unlink()
    # Delete every dub WAV that names this version.
    tts_dir = Path("data/tts")
    for wav in tts_dir.glob(
        f"{video_id}_{language}_{version_id}_*.wav"
    ):
        wav.unlink()
    # Drop from versions.json.
    save_versions(
        video_id, language, [e for e in entries if e.id != version_id]
    )
    return True
```

- [ ] **Step 1.4: Run — confirm all 8 tests pass**

Run: `python -m pytest tests/test_versions.py -v 2>&1 | tail -15`

Expected: 8 passed.

- [ ] **Step 1.5: Commit**

```bash
git add src/api/versions.py tests/test_versions.py
git commit -m "feat(versions): subtitle version model + on-disk IO

VersionEntry Pydantic model with id/name/created_at. load_versions and
save_versions round-trip a per-(video, language) versions.json. The
working draft is implicit (the unsuffixed SRT); only snapshots live in
versions.json.

snapshot_working_draft copies the working-draft SRT to
{id}_{lang}.v{N}.srt and appends an entry. delete_version cascades to
the snapshot SRT, every dub WAV named with that version, and the entry.

next_version_id is monotonically increasing — gaps are tolerated, ids
are never reused. 8 unit tests cover the model, IO round-trip,
next-id picker, and the empty-list path."
```

---

### Task 2: `ensure_migrated` — silent legacy migration

Lazily migrates `{id}_{lang}.dubsync.srt` → `v1`, renames existing dub WAVs to include `_v1_`, deletes `dub_meta_*.json` and the per-segment cache directory, and writes a fresh `versions.json`. Runs on the first read of a video's versions, then no-ops on every subsequent call.

**Files:**
- Modify: `src/api/versions.py` (add `ensure_migrated`)
- Create: `tests/test_migration.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_migration.py`:

```python
"""Tests for ensure_migrated — legacy dub-sync layout → versions layout."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    """Tmp data/srt and data/tts directories with helpers to seed files."""
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir()
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
    monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)

    def seed_srt(name: str, content: str = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"):
        (srt_dir / name).write_text(content)

    def seed_dub_wav(name: str):
        (tts_dir / name).write_bytes(b"RIFFfake")

    def seed_dub_meta(video_id: str, language: str):
        d = tts_dir / video_id
        d.mkdir(exist_ok=True)
        (d / f"dub_meta_{language}.json").write_text(
            json.dumps({"video_id": video_id, "language": language, "segment_texts": ["hi"]})
        )

    def seed_segments(video_id: str):
        d = tts_dir / video_id / "segments"
        d.mkdir(parents=True, exist_ok=True)
        (d / "0_google_voice.wav").write_bytes(b"RIFFseg")

    return {
        "srt_dir": srt_dir,
        "tts_dir": tts_dir,
        "seed_srt": seed_srt,
        "seed_dub_wav": seed_dub_wav,
        "seed_dub_meta": seed_dub_meta,
        "seed_segments": seed_segments,
    }


class TestEnsureMigrated:
    def test_brand_new_video_writes_empty_versions(self, fake_layout):
        """No SRT files at all → versions.json is [] and nothing else
        happens. Subsequent calls are a no-op."""
        from src.api.versions import ensure_migrated, load_versions

        ensure_migrated("newvid", "vi")
        assert load_versions("newvid", "vi") == []
        assert (fake_layout["srt_dir"] / "newvid_vi.versions.json").exists()

    def test_legacy_srt_only_becomes_v1(self, fake_layout):
        """{id}_{lang}.srt with no dubsync → v1 snapshot copies it."""
        from src.api.versions import ensure_migrated, load_versions

        fake_layout["seed_srt"]("vid1_vi.srt", "1\n00:00:00,000 --> 00:00:01,000\nA\n")
        ensure_migrated("vid1", "vi")
        entries = load_versions("vid1", "vi")
        assert len(entries) == 1
        assert entries[0].id == "v1"
        assert entries[0].name == "migrated"
        # v1 SRT exists with the same content.
        v1 = fake_layout["srt_dir"] / "vid1_vi.v1.srt"
        assert v1.exists()
        assert "A" in v1.read_text()
        # Working draft is unchanged.
        wd = fake_layout["srt_dir"] / "vid1_vi.srt"
        assert wd.exists()
        assert "A" in wd.read_text()

    def test_dubsync_present_becomes_v1_and_working_draft(self, fake_layout):
        """When dubsync.srt exists, it is the source of truth — v1 AND the
        working draft come from it. The legacy .srt (if any) is overwritten.
        The dubsync.srt is deleted."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid2_vi.srt", "OLD legacy timings")
        fake_layout["seed_srt"]("vid2_vi.dubsync.srt", "NEW dubsync timings")
        ensure_migrated("vid2", "vi")
        v1 = fake_layout["srt_dir"] / "vid2_vi.v1.srt"
        wd = fake_layout["srt_dir"] / "vid2_vi.srt"
        dubsync = fake_layout["srt_dir"] / "vid2_vi.dubsync.srt"
        assert "NEW dubsync timings" in v1.read_text()
        assert "NEW dubsync timings" in wd.read_text()
        assert not dubsync.exists()

    def test_existing_dub_wavs_get_v1_infix(self, fake_layout):
        """{id}_{lang}_{provider}_{voice}.wav → {id}_{lang}_v1_{provider}_{voice}.wav."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid3_vi.srt", "x")
        fake_layout["seed_dub_wav"]("vid3_vi_google_wavenet-A.wav")
        ensure_migrated("vid3", "vi")
        tts = fake_layout["tts_dir"]
        assert (tts / "vid3_vi_v1_google_wavenet-A.wav").exists()
        assert not (tts / "vid3_vi_google_wavenet-A.wav").exists()

    def test_already_versioned_wavs_are_left_alone(self, fake_layout):
        """A WAV that already has v{N} or 'draft' in the version slot is
        not double-prefixed."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid4_vi.srt", "x")
        fake_layout["seed_dub_wav"]("vid4_vi_v2_google_wavenet-A.wav")
        ensure_migrated("vid4", "vi")
        tts = fake_layout["tts_dir"]
        assert (tts / "vid4_vi_v2_google_wavenet-A.wav").exists()
        # Should NOT have been turned into vid4_vi_v1_v2_google_wavenet-A.wav.
        assert not (tts / "vid4_vi_v1_v2_google_wavenet-A.wav").exists()

    def test_dub_meta_and_segments_directory_are_deleted(self, fake_layout):
        """dub_meta_{lang}.json and {id}/segments/ both go away."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid5_vi.srt", "x")
        fake_layout["seed_dub_meta"]("vid5", "vi")
        fake_layout["seed_segments"]("vid5")
        ensure_migrated("vid5", "vi")
        tts = fake_layout["tts_dir"]
        assert not (tts / "vid5" / "dub_meta_vi.json").exists()
        assert not (tts / "vid5" / "segments").exists()

    def test_idempotent_second_call_is_noop(self, fake_layout):
        """Once versions.json exists, ensure_migrated returns without doing
        anything (even if other legacy files remain)."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid6_vi.srt", "x")
        ensure_migrated("vid6", "vi")
        # Manually create a dubsync.srt AFTER migration to verify it's
        # NOT picked up on the second call.
        (fake_layout["srt_dir"] / "vid6_vi.dubsync.srt").write_text("ghost")
        ensure_migrated("vid6", "vi")
        # The dubsync.srt should still be there — second call didn't touch it.
        assert (fake_layout["srt_dir"] / "vid6_vi.dubsync.srt").exists()
```

- [ ] **Step 2.2: Run — confirm tests fail**

Run: `python -m pytest tests/test_migration.py -v 2>&1 | tail -15`

Expected: 7 tests FAIL with `ImportError: cannot import name 'ensure_migrated'` and `AttributeError: module 'src.api.versions' has no attribute 'TTS_DIR'`.

- [ ] **Step 2.3: Add `ensure_migrated` + `TTS_DIR` to `src/api/versions.py`**

Append to `src/api/versions.py`:

```python
import shutil

TTS_DIR = Path("data/tts")
_VERSION_SLOT_RE = re.compile(r"^v\d+$")


def ensure_migrated(video_id: str, language: str) -> None:
    """Migrate legacy dub-sync layout to the versions layout on first read.

    No-op once `versions.json` exists. Otherwise:
      1. If `{id}_{lang}.dubsync.srt` exists, use it as both the v1 source
         and the new working draft, deleting the dubsync.srt afterwards.
         Else use `{id}_{lang}.srt` as the v1 source (working draft is
         unchanged).
      2. If neither legacy SRT exists, write an empty versions.json and
         return — brand-new videos with no transcript yet.
      3. Rename every `{id}_{lang}_{provider}_{voice}.wav` whose third
         underscore-separated token isn't already `draft` or `v{N}` to
         `{id}_{lang}_v1_{provider}_{voice}.wav`.
      4. Delete `data/tts/{id}/dub_meta_{lang}.json` if present.
      5. Delete `data/tts/{id}/segments/` if present.
      6. Write a single-entry versions.json: id=v1, name="migrated",
         created_at = source SRT mtime.
    """
    versions_path = _versions_path(video_id, language)
    if versions_path.exists():
        return

    legacy_srt = SRT_DIR / f"{video_id}_{language}.srt"
    legacy_dubsync = SRT_DIR / f"{video_id}_{language}.dubsync.srt"

    if not legacy_srt.exists() and not legacy_dubsync.exists():
        save_versions(video_id, language, [])
        return

    source = legacy_dubsync if legacy_dubsync.exists() else legacy_srt
    v1_path = SRT_DIR / f"{video_id}_{language}.v1.srt"
    shutil.copy(source, v1_path)
    if source == legacy_dubsync:
        shutil.copy(legacy_dubsync, legacy_srt)
        legacy_dubsync.unlink()

    for wav in TTS_DIR.glob(f"{video_id}_{language}_*.wav"):
        stem_parts = wav.stem.split("_")
        if len(stem_parts) >= 3:
            third = stem_parts[2]
            if third == "draft" or _VERSION_SLOT_RE.match(third):
                continue
        new_name = (
            f"{stem_parts[0]}_{stem_parts[1]}_v1_"
            f"{'_'.join(stem_parts[2:])}.wav"
        )
        wav.rename(TTS_DIR / new_name)

    meta_json = TTS_DIR / video_id / f"dub_meta_{language}.json"
    if meta_json.exists():
        meta_json.unlink()
    seg_dir = TTS_DIR / video_id / "segments"
    if seg_dir.exists():
        shutil.rmtree(seg_dir)

    save_versions(video_id, language, [
        VersionEntry(
            id="v1",
            name="migrated",
            created_at=datetime.fromtimestamp(
                source.stat().st_mtime, tz=timezone.utc
            ),
        )
    ])
```

- [ ] **Step 2.4: Run — confirm 7 tests pass + Task 1's 8 still pass**

Run: `python -m pytest tests/test_versions.py tests/test_migration.py -v 2>&1 | tail -20`

Expected: 15 passed.

- [ ] **Step 2.5: Commit**

```bash
git add src/api/versions.py tests/test_migration.py
git commit -m "feat(versions): lazy migration from legacy dub-sync layout

ensure_migrated runs once per (video, language) the first time anything
reads versions.json. It folds the legacy dubsync.srt (or plain .srt if
no dubsync) into a v1 snapshot, renames existing dub WAVs to include
_v1_, deletes dub_meta_{lang}.json and the per-segment cache directory,
and writes a single-entry versions.json with name='migrated' and
created_at from the source SRT's mtime.

WAVs that already carry a v{N} or 'draft' version slot are left alone.
Brand-new videos with no SRT yet get an empty versions.json so the
no-op short-circuit fires on subsequent calls.

7 unit tests cover all branches: brand new, legacy SRT only, dubsync
takeover, WAV renames, already-versioned WAVs, dub_meta + segments
cleanup, and idempotence."
```

---

### Task 3: Versions CRUD router

The four routes: list, snapshot, rename, delete.

**Files:**
- Create: `src/api/routers/versions.py`
- Modify: `src/api/__init__.py` (register the router)
- Modify: `tests/test_versions.py` (add `TestVersionsRouter` class)

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_versions.py`:

```python
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI test client with data dirs redirected to tmp."""
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir()
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
    monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
    # Seed a working draft so snapshot can succeed.
    (srt_dir / "vidA_vi.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhello\n"
    )

    from src.api import app  # noqa
    return TestClient(app), srt_dir, tts_dir


class TestVersionsRouter:
    def test_list_returns_empty_for_fresh_video(self, client):
        c, _, _ = client
        # Working draft exists but no versions yet.
        r = c.get("/api/videos/vidA/versions?language=vi")
        assert r.status_code == 200
        assert r.json() == []

    def test_post_creates_v1(self, client):
        c, srt_dir, _ = client
        r = c.post(
            "/api/videos/vidA/versions?language=vi",
            json={"name": "first"},
        )
        assert r.status_code == 201
        body = r.json()
        assert body["id"] == "v1"
        assert body["name"] == "first"
        # SRT was actually written.
        assert (srt_dir / "vidA_vi.v1.srt").exists()

    def test_post_with_no_name_is_anonymous(self, client):
        c, _, _ = client
        r = c.post(
            "/api/videos/vidA/versions?language=vi",
            json={"name": None},
        )
        assert r.status_code == 201
        assert r.json()["name"] is None

    def test_patch_renames_an_existing_version(self, client):
        c, _, _ = client
        c.post("/api/videos/vidA/versions?language=vi", json={"name": "old"})
        r = c.patch(
            "/api/videos/vidA/versions/v1?language=vi",
            json={"name": "new"},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "new"
        # GET reflects the rename.
        listing = c.get("/api/videos/vidA/versions?language=vi").json()
        assert listing[0]["name"] == "new"

    def test_patch_unknown_version_returns_404(self, client):
        c, _, _ = client
        r = c.patch(
            "/api/videos/vidA/versions/v99?language=vi",
            json={"name": "ghost"},
        )
        assert r.status_code == 404

    def test_delete_removes_snapshot_srt_and_entry(self, client):
        c, srt_dir, _ = client
        c.post("/api/videos/vidA/versions?language=vi", json={"name": None})
        r = c.delete("/api/videos/vidA/versions/v1?language=vi")
        assert r.status_code == 204
        assert not (srt_dir / "vidA_vi.v1.srt").exists()
        listing = c.get("/api/videos/vidA/versions?language=vi").json()
        assert listing == []

    def test_delete_cascades_to_dub_wavs(self, client):
        c, _, tts_dir = client
        c.post("/api/videos/vidA/versions?language=vi", json={"name": None})
        # Seed a dub WAV for v1.
        (tts_dir / "vidA_vi_v1_google_wavenet-A.wav").write_bytes(b"RIFF")
        c.delete("/api/videos/vidA/versions/v1?language=vi")
        assert not (tts_dir / "vidA_vi_v1_google_wavenet-A.wav").exists()

    def test_delete_unknown_version_returns_404(self, client):
        c, _, _ = client
        r = c.delete("/api/videos/vidA/versions/v99?language=vi")
        assert r.status_code == 404
```

- [ ] **Step 3.2: Run — confirm tests fail**

Run: `python -m pytest tests/test_versions.py::TestVersionsRouter -v 2>&1 | tail -15`

Expected: 8 tests FAIL with 404 (route doesn't exist yet).

- [ ] **Step 3.3: Create `src/api/routers/versions.py`**

Create `src/api/routers/versions.py`:

```python
"""Subtitle versions CRUD routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api import versions as versions_mod

router = APIRouter()


class CreateVersionRequest(BaseModel):
    name: str | None = None


class RenameVersionRequest(BaseModel):
    name: str | None


@router.get(
    "/api/videos/{video_id}/versions",
    response_model=list[versions_mod.VersionEntry],
)
async def list_versions(video_id: str, language: str):
    versions_mod.ensure_migrated(video_id, language)
    return versions_mod.load_versions(video_id, language)


@router.post(
    "/api/videos/{video_id}/versions",
    response_model=versions_mod.VersionEntry,
    status_code=201,
)
async def create_version(
    video_id: str, language: str, request: CreateVersionRequest
):
    versions_mod.ensure_migrated(video_id, language)
    try:
        return versions_mod.snapshot_working_draft(
            video_id, language, request.name
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch(
    "/api/videos/{video_id}/versions/{version_id}",
    response_model=versions_mod.VersionEntry,
)
async def rename_version(
    video_id: str, language: str, version_id: str,
    request: RenameVersionRequest,
):
    versions_mod.ensure_migrated(video_id, language)
    entries = versions_mod.load_versions(video_id, language)
    found = next((e for e in entries if e.id == version_id), None)
    if found is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_id} not found",
        )
    found.name = request.name
    versions_mod.save_versions(video_id, language, entries)
    return found


@router.delete(
    "/api/videos/{video_id}/versions/{version_id}",
    status_code=204,
)
async def delete_version(
    video_id: str, language: str, version_id: str
):
    versions_mod.ensure_migrated(video_id, language)
    deleted = versions_mod.delete_version(video_id, language, version_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Version {version_id} not found",
        )
    return None
```

- [ ] **Step 3.4: Register the router in `src/api/__init__.py`**

Read [src/api/__init__.py](src/api/__init__.py) and locate the existing `app.include_router(...)` block. Add an import and an include:

```python
from src.api.routers import versions as versions_router
# ...
app.include_router(versions_router.router)
```

Keep ordering consistent with the surrounding routers (alphabetical or by feature, whichever the file uses).

- [ ] **Step 3.5: Run — confirm 8 router tests pass + previous 15 still pass**

Run: `python -m pytest tests/test_versions.py tests/test_migration.py -v 2>&1 | tail -20`

Expected: 23 passed.

- [ ] **Step 3.6: Commit**

```bash
git add src/api/routers/versions.py src/api/__init__.py tests/test_versions.py
git commit -m "feat(versions): CRUD router under /api/videos/{id}/versions

Four routes: GET list, POST snapshot, PATCH rename, DELETE.

POST body accepts an optional name. DELETE cascades to the snapshot SRT
and any dub WAVs matching the version_id glob. PATCH and DELETE return
404 for an unknown version_id. Every route calls ensure_migrated up
front so the legacy layout is transparently upgraded on first touch.

8 endpoint tests via FastAPI TestClient with tmp data dirs cover the
list/create/rename/delete paths, the 404 cases, and the dub-WAV
cascade."
```

---

### Task 4: SRT routes accept `version` parameter

Today the editor reads/writes the post-dub `.dubsync.srt` when it exists. With versions, reads accept an optional `version` (defaulting to the working draft); writes always go to the working draft.

**Files:**
- Modify: `src/api/routers/transcribe.py` — `_resolve_srt_path` becomes version-aware; `GET /api/videos/{id}/srt` accepts `version`
- Modify: `src/api/routers/editor.py` — `PUT /api/videos/{id}/srt` ignores any incoming version (writes only to draft)
- Create: `tests/test_srt_versioned.py`

- [ ] **Step 4.1: Write the failing tests**

Create `tests/test_srt_versioned.py`:

```python
"""Tests for version-aware SRT read/write."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir()
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
    monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
    # Patch the transcribe router's data dir too.
    monkeypatch.setattr(
        "src.api.routers.transcribe.SRT_DIR_OVERRIDE", srt_dir, raising=False,
    )
    from src.api import app
    from src.api.deps import get_task_manager

    tm = get_task_manager()
    tm.video_index["vidX"] = type("V", (), {
        "video_id": "vidX",
        "file_path": str(tmp_path / "vidX.mp4"),
        "title": "x",
        "status": "ready",
    })()
    return TestClient(app), srt_dir


def _seed_srt(srt_dir, name: str, body: str):
    (srt_dir / name).write_text(body)


_SAMPLE_SRT = (
    "1\n00:00:00,000 --> 00:00:01,000\nworking draft\n\n"
)
_V1_SRT = (
    "1\n00:00:00,000 --> 00:00:01,000\nv1 snapshot\n\n"
)


class TestGetSrtAcceptsVersion:
    def test_get_without_version_reads_working_draft(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        r = c.get("/api/videos/vidX/srt?language=vi")
        assert r.status_code == 200
        assert "working draft" in r.json()["segments"][0]["text"]

    def test_get_with_version_v1_reads_snapshot(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        _seed_srt(srt_dir, "vidX_vi.v1.srt", _V1_SRT)
        r = c.get("/api/videos/vidX/srt?language=vi&version=v1")
        assert r.status_code == 200
        assert "v1 snapshot" in r.json()["segments"][0]["text"]

    def test_get_with_unknown_version_returns_404(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        r = c.get("/api/videos/vidX/srt?language=vi&version=v99")
        assert r.status_code == 404

    def test_get_with_version_draft_explicitly_reads_working_draft(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        _seed_srt(srt_dir, "vidX_vi.v1.srt", _V1_SRT)
        r = c.get("/api/videos/vidX/srt?language=vi&version=draft")
        assert "working draft" in r.json()["segments"][0]["text"]


class TestPutSrtWritesWorkingDraftOnly:
    def test_put_writes_working_draft_even_when_v1_exists(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        _seed_srt(srt_dir, "vidX_vi.v1.srt", _V1_SRT)
        r = c.put(
            "/api/videos/vidX/srt",
            json={
                "language": "vi",
                "segments": [{
                    "id": 1,
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:02,000",
                    "text": "edited",
                }],
            },
        )
        assert r.status_code == 200
        # Working draft updated.
        assert "edited" in (srt_dir / "vidX_vi.srt").read_text()
        # v1 snapshot still has its original content.
        assert "v1 snapshot" in (srt_dir / "vidX_vi.v1.srt").read_text()
```

- [ ] **Step 4.2: Run — confirm the version-aware tests fail**

Run: `python -m pytest tests/test_srt_versioned.py -v 2>&1 | tail -15`

Expected: at least the `?version=v1` and `?version=v99` tests fail (404 or wrong content) because the route ignores `version` today. The 404 case might pass spuriously; check by inspection.

- [ ] **Step 4.3: Modify `_resolve_srt_path` in `src/api/routers/transcribe.py`**

Read the current `_resolve_srt_path` ([transcribe.py:19-35](src/api/routers/transcribe.py#L19-L35)). Replace it with:

```python
def _resolve_srt_path(
    video_id: str,
    language: str,
    version: str = "draft",
) -> Path:
    """Return the SRT path for the given (video, language, version).

    `version='draft'` (default) → the unsuffixed working-draft SRT.
    `version='v1'`, `'v2'`, ... → the corresponding snapshot SRT.

    Caller must check `.exists()` — this function does not.
    """
    from src.api.versions import SRT_DIR

    if version == "draft":
        return SRT_DIR / f"{video_id}_{language}.srt"
    return SRT_DIR / f"{video_id}_{language}.{version}.srt"
```

Note: the return type changed from `tuple[Path, bool]` to `Path`. Update every caller in `transcribe.py` and `editor.py` to drop the `is_dubsync` unpacking.

- [ ] **Step 4.4: Update `GET /api/videos/{id}/srt` to accept `version`**

Find the route handler (around [transcribe.py:100-126](src/api/routers/transcribe.py#L100-L126)). Replace:

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

with:

```python
@router.get("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def get_srt(
    video_id: str, language: str = "zh", version: str = "draft",
):
    from src.api.versions import ensure_migrated

    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    ensure_migrated(video_id, language)
    srt_path = _resolve_srt_path(video_id, language, version)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"SRT file not found for {video_id} ({language}, version={version})",
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
        language=language, is_dubsync=False,
    )
```

`is_dubsync` is hard-coded `False` for now — its caller in the FE is irrelevant after Task 12 drops the Sync Dub banner. The field stays on `SrtResponse` for back-compat with `GET /api/videos/{id}/srt/download` (which still serves the working draft). If the response model rejects extra/missing fields, leave the field in place.

Also locate the `GET /api/videos/{id}/srt/download` handler (around [transcribe.py:129-148](src/api/routers/transcribe.py#L129-L148)) and update its `_resolve_srt_path` call to the new single-Path return. It can stay version-unaware (always serves the working draft).

- [ ] **Step 4.5: Update `PUT /api/videos/{id}/srt` in `editor.py`**

Read [editor.py:253-325](src/api/routers/editor.py#L253-L325). The handler currently:
1. Calls `_resolve_srt_path(video_id, request.language)` (now returns a single path)
2. Writes segments to that path
3. Calls `_check_dub_sync_against_meta` — **delete this block and the import** (the helper is gone in Task 6 too, but pre-empt it here)

Replace the relevant section with this minimal version that just writes the working draft:

```python
@router.put("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def save_srt(video_id: str, request: SaveSrtRequest):
    """Overwrite the working-draft SRT for this (video, language).

    Snapshots are immutable — the editor never writes them. The DubTab's
    'Save as version' button uses POST /api/videos/{id}/versions to
    create a snapshot from the current working draft.
    """
    from src.api.versions import ensure_migrated

    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    ensure_migrated(video_id, request.language)
    srt_path = _resolve_srt_path(video_id, request.language, "draft")
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    segments = [
        {
            "index": seg.id,
            "start": srt_timestamp_to_seconds(seg.startTime),
            "end": srt_timestamp_to_seconds(seg.endTime),
            "text": seg.text,
        }
        for seg in request.segments
    ]
    write_srt(segments, srt_path)

    return SrtResponse(
        video_id=video_id,
        segments=request.segments,
        language=request.language,
        is_dubsync=False,
    )
```

Drop the `_check_dub_sync_against_meta` function definition AND its `from src.tts.dub_meta import load_dub_meta` import while you're in the file. Any other code in `editor.py` referencing them must also go. Some response fields (e.g. `dub_out_of_sync`) may have to be removed from `SrtResponse` in `src/api/models.py` — do that as part of this task too. If you find downstream callers that read `dub_out_of_sync`, leave them returning `False` from the static value for now; their UI usages disappear in Task 12.

- [ ] **Step 4.6: Run the SRT tests + the BE suite**

Run: `python -m pytest tests/test_srt_versioned.py tests/test_versions.py tests/test_migration.py -v 2>&1 | tail -15`

Expected: all green (4 + 8 + 15 = 27 tests for this and prior tasks).

Then run the full BE suite to flush regressions from removing `_check_dub_sync_against_meta`:

`python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -15`

Expected: passes, with possibly a small number of `_check_dub_sync_against_meta` tests in `tests/test_editor.py` (or similar) failing — those tests are stale and should be deleted. If you find some, delete them in this commit (their feature is gone).

- [ ] **Step 4.7: Commit**

```bash
git add src/api/routers/transcribe.py src/api/routers/editor.py src/api/models.py tests/test_srt_versioned.py
# Plus any test deletions for _check_dub_sync_against_meta:
# git add tests/test_editor.py (if you deleted tests there)

git commit -m "feat(srt): version-aware GET; PUT writes working draft only

_resolve_srt_path now takes a version: str = 'draft' parameter and
returns a single Path. 'draft' resolves to the unsuffixed working-draft
SRT; 'v1'/'v2'/... resolves to the corresponding snapshot. The return
type changed from tuple[Path, bool] to Path — every caller was updated.

GET /api/videos/{id}/srt accepts the version query parameter, calls
ensure_migrated, and returns the requested version's segments. Unknown
versions return 404. The is_dubsync field stays in SrtResponse for
back-compat but is always False now — the FE consumer disappears in
the DubTab refactor task.

PUT /api/videos/{id}/srt unconditionally writes to the working draft.
The _check_dub_sync_against_meta helper, the dub_meta import, and the
dub_out_of_sync response plumbing are deleted — saving subtitles is
now just saving, no implicit dub state."
```

---

### Task 5: TTS + assembler accept version; output filename includes version; remove dub-sync writes

`POST /api/tts` accepts `version`. The dub WAV filename grows a `_{version}_` infix. The assembler's Stage 1.5 (per-segment cache), Stage 6 (dubsync.srt write), and Stage 7 (dub_meta write) are removed; `run_partial` goes too.

**Files:**
- Modify: `src/api/routers/tts.py` — add `version: str = "draft"` to `TTSRequest`, forward it
- Modify: `src/api/task_manager.py` — `run_tts` accepts `version`, forwards to the runner
- Modify: `src/tts/runner.py` — extract `dub_output_filename(video_id, language, version, provider, voice) -> Path` helper; use it in the runner
- Modify: `src/tts/assembler.py` — `generate_full_track` accepts `version` (used in log lines), drops Stages 1.5/6/7; delete `run_partial`
- Modify: `tests/test_tts.py` — drop `TestDubsyncSrtWriter`, any assertions on dubsync.srt or dub_meta writes (without breaking the existing iterative-shortening tests)
- Create: `tests/test_tts_versioned.py` — assert filename includes version

- [ ] **Step 5.1: Write the failing test for the output filename**

Create `tests/test_tts_versioned.py`:

```python
"""Tests for version-aware dub WAV output naming."""

from __future__ import annotations

from pathlib import Path


class TestDubOutputFilename:
    def test_draft_omits_version_prefix(self):
        from src.tts.runner import dub_output_filename

        out = dub_output_filename("vid1", "vi", "draft", "google", "wavenet-A")
        assert out == Path("data/tts/vid1_vi_draft_google_wavenet-A.wav")

    def test_v1_includes_version(self):
        from src.tts.runner import dub_output_filename

        out = dub_output_filename("vid1", "vi", "v1", "google", "wavenet-A")
        assert out == Path("data/tts/vid1_vi_v1_google_wavenet-A.wav")

    def test_voice_with_slashes_is_escaped(self):
        """Some Google voice ids contain '/' which would break the path."""
        from src.tts.runner import dub_output_filename

        out = dub_output_filename(
            "vid1", "vi", "v2", "google", "vi-VN/Wavenet-A"
        )
        # '/' must be replaced (not preserved) so Path stays one segment.
        assert "/" not in out.name
        assert out.name.endswith(".wav")
        assert "v2" in out.name
```

- [ ] **Step 5.2: Run — confirm fail (ImportError)**

Run: `python -m pytest tests/test_tts_versioned.py -v 2>&1 | tail -10`

Expected: 3 tests FAIL with `ImportError: cannot import name 'dub_output_filename'`.

- [ ] **Step 5.3: Implement `dub_output_filename` in `src/tts/runner.py`**

Read [src/tts/runner.py](src/tts/runner.py) and find where the output path is constructed today (search for `data/tts` or `_{provider}_{voice}.wav`). Add a module-level helper near the top:

```python
import re
from pathlib import Path

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def dub_output_filename(
    video_id: str,
    language: str,
    version: str,
    provider: str,
    voice: str,
) -> Path:
    """Canonical path for a dub WAV.

    Layout: data/tts/{video_id}_{language}_{version}_{provider}_{voice}.wav.

    `voice` may contain characters that aren't safe in a filename (Google
    voice ids historically include '/'); they are replaced with '-'.
    """
    safe_voice = _FILENAME_SAFE.sub("-", voice)
    safe_provider = _FILENAME_SAFE.sub("-", provider)
    return Path(
        f"data/tts/{video_id}_{language}_{version}_{safe_provider}_{safe_voice}.wav"
    )
```

Find every existing construction of the dub output path in `runner.py` and replace it with a call to `dub_output_filename(video_id, language, version, provider, voice)`. The `version` argument needs to be threaded through — add it to `run_tts_track`'s signature (default `"draft"`).

- [ ] **Step 5.4: Thread `version` through `task_manager.run_tts` and `POST /api/tts`**

In [task_manager.py:742-754](src/api/task_manager.py#L742-L754), add `version: str = "draft"` to `run_tts`'s signature (after `playback_speed`). Forward it to `run_tts_track`.

In `src/api/models.py`, add `version: str = "draft"` to the `TTSRequest` model.

In [src/api/routers/tts.py:23-48](src/api/routers/tts.py#L23-L48), forward `request.version` into `tm.run_tts(...)`.

- [ ] **Step 5.5: Run the new filename tests**

Run: `python -m pytest tests/test_tts_versioned.py -v 2>&1 | tail -10`

Expected: 3 passed.

- [ ] **Step 5.6: Strip dub-sync writes from the assembler**

In [src/tts/assembler.py](src/tts/assembler.py):

1. Add `version: str = "draft"` to `generate_full_track`'s signature (after `underlay_db`). Use it only in a log line (`logger.info(f"Generating dub for version={version} ...")`). The output path is constructed by the caller now.

2. **Delete** lines 575-596 (Stage 1.5 segment cache write). Also delete the `from src.tts.segment_cache import save_segment_clip` import if it's the only use.

3. **Delete** lines 722-739 (Stage 6 dubsync.srt write).

4. **Delete** lines 741-763 (Stage 7 dub_meta write).

5. **Delete** the entire `run_partial` method ([src/tts/assembler.py:772-1114](src/tts/assembler.py#L772-L1114)). It's only called by `sync_runner.run_dub_sync`, which gets deleted in Task 6.

6. Remove now-unused imports at the top of the file (`from src.tts.dubsync_srt import write_dubsync_srt`, `from src.tts.dub_meta import DubMeta, save_dub_meta`, `from src.tts.segment_cache import save_segment_clip`). Pylance/lint will surface any survivors.

- [ ] **Step 5.7: Drop assembler tests that referenced the deleted stages**

In `tests/test_tts.py`, locate and DELETE these test classes/methods (they assert behavior that no longer exists):

- `TestDubsyncSrtWriter` (all three tests; the dubsync_srt module is gone in Task 6).
- Any assertion in other tests that mentions `dubsync.srt`, `dub_meta_*.json`, or `segment_cache` (skim each test method for the strings — usually one or two assertions can just be deleted).

Keep `TestIterativeShortening`, `TestSentenceMergerGapSplit`, `TestNaturalSpeedAnchoring`, `TestShortenTextsBatchFloor`, `TestRunTtsTrack`, `TestFFmpegAudioMix`, `TestBatchProcessorTTS`, and the `TestCleanText`/`TestBaseTTSProvider`/`TestTTSFactory` blocks — those still apply.

- [ ] **Step 5.8: Run the BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -15`

Expected: green. If `tests/test_tts_dub_sync_detection.py` or `tests/test_tts_segment_cache.py` fail because their imports are broken, that's fine — they get deleted entirely in Task 6.

If those two are the only failures, temporarily skip them with `--ignore=tests/test_tts_dub_sync_detection.py --ignore=tests/test_tts_segment_cache.py` for this task's verification only.

- [ ] **Step 5.9: Commit**

```bash
git add src/tts/runner.py src/tts/assembler.py src/api/routers/tts.py src/api/task_manager.py src/api/models.py tests/test_tts_versioned.py tests/test_tts.py
git commit -m "feat(tts): version-aware dub output; strip dub-sync writes

POST /api/tts accepts a version field (default 'draft'). The output WAV
lives at data/tts/{id}_{lang}_{ver}_{provider}_{voice}.wav, constructed
by the new dub_output_filename helper in src/tts/runner.py. The helper
escapes filename-unsafe characters in the provider/voice strings.

generate_full_track loses three stages: per-segment cache writes
(Stage 1.5), dubsync.srt emission (Stage 6), and dub_meta persistence
(Stage 7). It accepts a version parameter purely for log clarity.
run_partial is deleted entirely — its only caller (sync_runner) goes
away in the next commit.

TestDubsyncSrtWriter is removed from tests/test_tts.py along with
isolated assertions on the deleted side-effects. dub_output_filename
gains three unit tests."
```

---

### Task 6: Delete the dub-sync system

`POST /api/videos/{id}/dub/sync` route, `sync_runner.py`, `dub_meta.py`, `dubsync_srt.py`, `segment_cache.py`, and their dedicated tests all go.

**Files:**
- Modify: `src/api/routers/tts.py` — delete the `/dub/sync` route + its imports
- Delete: `src/tts/sync_runner.py`
- Delete: `src/tts/dub_meta.py`
- Delete: `src/tts/dubsync_srt.py`
- Delete: `src/tts/segment_cache.py`
- Delete: `tests/test_tts_dub_sync_detection.py`
- Delete: `tests/test_tts_segment_cache.py`
- Modify: any router init / __init__.py that imports the deleted modules

- [ ] **Step 6.1: Delete the `/dub/sync` route in `src/api/routers/tts.py`**

Locate the handler around [tts.py:51-150](src/api/routers/tts.py#L51-L150). Delete the entire `@router.post("/api/videos/{video_id}/dub/sync", ...)` block including its imports and helper functions if any. Also delete the `from src.api.routers.transcribe import _resolve_srt_path` and `from src.processor.subtitle import parse_srt` imports if they're now unused.

- [ ] **Step 6.2: Delete the four module files**

```bash
git rm src/tts/sync_runner.py src/tts/dub_meta.py src/tts/dubsync_srt.py src/tts/segment_cache.py
```

If `src/tts/__init__.py` re-exports any of those, drop the lines (run `grep -n "sync_runner\|dub_meta\|dubsync_srt\|segment_cache" src/tts/__init__.py`).

- [ ] **Step 6.3: Delete the dead test files**

```bash
git rm tests/test_tts_dub_sync_detection.py tests/test_tts_segment_cache.py
```

- [ ] **Step 6.4: Hunt for stragglers**

Run `grep -rln "sync_runner\|dub_meta\|dubsync_srt\|segment_cache" src/ tests/ ui-app/src/ 2>&1`. Every hit must be resolved — delete the line or the file. The FE will still have `postDubSync` references; **leave them for Task 11**, which removes them as part of the EditorTab rewrite.

- [ ] **Step 6.5: Run the full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -15`

Expected: all green.

- [ ] **Step 6.6: Lint**

Run: `ruff check src/ tests/ 2>&1 | tail -10`

Expected: no new errors (pre-existing lint debt in unrelated files is fine).

- [ ] **Step 6.7: Commit**

```bash
git add -A
git commit -m "feat(tts): remove the dub-sync system

Deletes:
- POST /api/videos/{id}/dub/sync route and its imports in tts.py
- src/tts/sync_runner.py, dub_meta.py, dubsync_srt.py, segment_cache.py
- tests/test_tts_dub_sync_detection.py
- tests/test_tts_segment_cache.py

With explicit per-version dub generation, the diff-based dirty-segment
detection and partial-resynth machinery is dead code. Every dub is now
a clean full regen against the user-chosen subtitle version, with the
per-segment WAV cache no longer needed (re-synth cost is cents per
video at typical segment counts).

The FE's postDubSync client and the Sync Dub banner in EditorTab are
removed in the editor refactor task to keep that diff focused."
```

---

### Task 7: FE API client + types + useVersions hook

**Files:**
- Create: `ui-app/src/api/versions.ts`
- Create: `ui-app/src/hooks/useVersions.ts`
- Modify: `ui-app/src/api/types.ts` (add `VersionEntry`; extend `TTSAudioFile` with `version`)

- [ ] **Step 7.1: Write the failing test for `useVersions`**

Create `ui-app/src/hooks/__tests__/useVersions.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { useVersions } from '../useVersions';

vi.mock('../../api/versions', () => ({
  getVersions: vi.fn(),
  createVersion: vi.fn(),
  renameVersion: vi.fn(),
  deleteVersion: vi.fn(),
}));

describe('useVersions', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches versions on mount and exposes them', async () => {
    const { getVersions } = await import('../../api/versions');
    (getVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'v1', name: 'first', created_at: '2026-05-29T10:00:00Z' },
    ]);
    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));
    expect(result.current.versions[0].id).toBe('v1');
  });

  it('createSnapshot calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    (api.createVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z',
    });
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toEqual([]));

    await act(async () => {
      await result.current.createSnapshot(null);
    });

    expect(api.createVersion).toHaveBeenCalledWith('vid1', 'vi', null);
    await waitFor(() => expect(result.current.versions).toHaveLength(1));
  });

  it('rename calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValue([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);
    (api.renameVersion as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 'v1', name: 'polished', created_at: '2026-05-29T10:00:00Z',
    });

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));

    await act(async () => {
      await result.current.rename('v1', 'polished');
    });

    expect(api.renameVersion).toHaveBeenCalledWith('vid1', 'vi', 'v1', 'polished');
  });

  it('remove calls the API and refreshes', async () => {
    const api = await import('../../api/versions');
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
    ]);
    (api.getVersions as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    (api.deleteVersion as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    const { result } = renderHook(() => useVersions('vid1', 'vi'));
    await waitFor(() => expect(result.current.versions).toHaveLength(1));

    await act(async () => {
      await result.current.remove('v1');
    });

    expect(api.deleteVersion).toHaveBeenCalledWith('vid1', 'vi', 'v1');
    await waitFor(() => expect(result.current.versions).toHaveLength(0));
  });
});
```

- [ ] **Step 7.2: Run — confirm fail**

Run: `cd ui-app && npx vitest run src/hooks/__tests__/useVersions.test.tsx 2>&1 | tail -10`

Expected: tests fail — `useVersions` and the API module don't exist yet.

- [ ] **Step 7.3: Implement `ui-app/src/api/versions.ts`**

Create `ui-app/src/api/versions.ts`:

```ts
import type { VersionEntry } from './types';

const BASE = '/api';

function request(path: string, init?: RequestInit) {
  return fetch(`${BASE}${path}`, init).then(async (r) => {
    if (!r.ok) {
      const body = await r.text().catch(() => '');
      throw new Error(`${r.status} ${body}`);
    }
    if (r.status === 204) return undefined;
    return r.json();
  });
}

export async function getVersions(
  videoId: string,
  language: string,
): Promise<VersionEntry[]> {
  return request(`/videos/${videoId}/versions?language=${language}`);
}

export async function createVersion(
  videoId: string,
  language: string,
  name: string | null,
): Promise<VersionEntry> {
  return request(`/videos/${videoId}/versions?language=${language}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
}

export async function renameVersion(
  videoId: string,
  language: string,
  versionId: string,
  name: string | null,
): Promise<VersionEntry> {
  return request(
    `/videos/${videoId}/versions/${versionId}?language=${language}`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    },
  );
}

export async function deleteVersion(
  videoId: string,
  language: string,
  versionId: string,
): Promise<void> {
  await request(
    `/videos/${videoId}/versions/${versionId}?language=${language}`,
    { method: 'DELETE' },
  );
}
```

- [ ] **Step 7.4: Add `VersionEntry` type + extend `TTSAudioFile`**

Open `ui-app/src/api/types.ts`. Add:

```ts
export interface VersionEntry {
  id: string;
  name: string | null;
  created_at: string;
}
```

Find the existing `TTSAudioFile` interface (or whatever the audio library type is called) and add:

```ts
export interface TTSAudioFile {
  // ...existing fields...
  version: string;  // 'draft' or 'v1'/'v2'/... — derived by the BE from the filename
}
```

- [ ] **Step 7.5: Implement `useVersions` hook**

Create `ui-app/src/hooks/useVersions.ts`:

```ts
import { useCallback, useEffect, useState } from 'react';
import {
  getVersions,
  createVersion,
  renameVersion,
  deleteVersion,
} from '../api/versions';
import type { VersionEntry } from '../api/types';

export function useVersions(videoId: string | undefined, language: string) {
  const [versions, setVersions] = useState<VersionEntry[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!videoId) return;
    setLoading(true);
    try {
      const list = await getVersions(videoId, language);
      setVersions(list);
    } finally {
      setLoading(false);
    }
  }, [videoId, language]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const createSnapshot = useCallback(
    async (name: string | null) => {
      if (!videoId) return;
      await createVersion(videoId, language, name);
      await refresh();
    },
    [videoId, language, refresh],
  );

  const rename = useCallback(
    async (versionId: string, name: string | null) => {
      if (!videoId) return;
      await renameVersion(videoId, language, versionId, name);
      await refresh();
    },
    [videoId, language, refresh],
  );

  const remove = useCallback(
    async (versionId: string) => {
      if (!videoId) return;
      await deleteVersion(videoId, language, versionId);
      await refresh();
    },
    [videoId, language, refresh],
  );

  return { versions, loading, createSnapshot, rename, remove, refresh };
}
```

- [ ] **Step 7.6: Run — confirm tests pass**

Run: `cd ui-app && npx vitest run src/hooks/__tests__/useVersions.test.tsx 2>&1 | tail -10`

Expected: 4 passed.

- [ ] **Step 7.7: Commit**

```bash
git add ui-app/src/api/versions.ts ui-app/src/api/types.ts ui-app/src/hooks/useVersions.ts ui-app/src/hooks/__tests__/useVersions.test.tsx
git commit -m "feat(fe): versions API client + useVersions hook

Adds GET/POST/PATCH/DELETE wrappers in ui-app/src/api/versions.ts and a
useVersions(videoId, language) hook that loads on mount, exposes the
list, and offers createSnapshot/rename/remove operations that auto-
refresh on success.

types.ts gains the VersionEntry interface and the TTSAudioFile gets a
version: string field (the BE will populate it from the filename).

Four vitest tests cover the hook's lifecycle: initial fetch, snapshot
+ refresh, rename + refresh, delete + refresh."
```

---

### Task 8: Update `getSrt` and `postTTS` to accept `version`; delete `postDubSync`

**Files:**
- Modify: `ui-app/src/api/client.ts`

- [ ] **Step 8.1: Modify `getSrt`**

Locate `getSrt` at [ui-app/src/api/client.ts:73-75](ui-app/src/api/client.ts#L73-L75). Replace with:

```ts
export function getSrt(
  videoId: string,
  language: string = 'zh',
  version: string = 'draft',
): Promise<SrtResponse> {
  return request(
    `/videos/${videoId}/srt?language=${language}&version=${version}`,
  );
}
```

- [ ] **Step 8.2: Modify `postTTS`**

Locate `postTTS` at [ui-app/src/api/client.ts:285-311](ui-app/src/api/client.ts#L285-L311). Add a `version` parameter (with default `'draft'`) and include it in the JSON body:

```ts
export function postTTS(
  videoId: string,
  language: string,
  provider: string,
  voice: string,
  version: string = 'draft',
  apiKey?: string,
  llmApiKey?: string,
  llmBackend?: string,
  playbackSpeed?: number,
  underlayDb?: number,
): Promise<TaskResponse> {
  return request('/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      video_id: videoId,
      language,
      provider,
      voice,
      version,
      api_key: apiKey ?? null,
      llm_api_key: llmApiKey ?? null,
      llm_backend: llmBackend ?? null,
      playback_speed: playbackSpeed ?? null,
      underlay_db: underlayDb ?? null,
    }),
  });
}
```

- [ ] **Step 8.3: Delete `postDubSync` + related types**

Find `postDubSync` at [ui-app/src/api/client.ts:514-525](ui-app/src/api/client.ts#L514-L525). Delete the function. Also delete the `SyncDubBody` type if it's defined in the same file (or in `types.ts`).

- [ ] **Step 8.4: Run lint**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -10`

Expected: TypeScript surfaces the now-broken call sites in `EditorTab.tsx` (lines 407-459: `postDubSync` import, `handleSyncDub`, `isSyncing`, `syncError`, etc.). Those are repaired in Task 11. For this commit, you can either:

- (a) Add a temporary stub `export const postDubSync = () => { throw new Error('removed'); };` to silence TypeScript until Task 11. **Cleaner alternative**: comment out the broken import in EditorTab.tsx for now with a `// REMOVED IN TASK 12` marker — it's clearer than a stub.
- (b) Roll up the EditorTab cleanup into this same commit.

Pick (a) to keep diffs small. Verify the FE build still succeeds:

`cd ui-app && npm run build 2>&1 | tail -10`

Expected: build succeeds. The Sync Dub banner will be broken at runtime, but it's about to be deleted in Task 11.

- [ ] **Step 8.5: Commit**

```bash
git add ui-app/src/api/client.ts ui-app/src/pages/videoDetail/EditorTab.tsx
git commit -m "feat(fe): getSrt/postTTS accept version; postDubSync deleted

getSrt and postTTS gain a version: string = 'draft' parameter wired
into the URL or request body.

postDubSync is deleted entirely along with SyncDubBody. The Sync Dub
banner in EditorTab is commented out behind a TASK 12 marker until the
editor refactor lands — it stays compilable but inert."
```

---

### Task 9: `VersionPicker` component

**Files:**
- Create: `ui-app/src/components/dub/VersionPicker.tsx`
- Create: `ui-app/src/components/dub/__tests__/VersionPicker.test.tsx`

- [ ] **Step 9.1: Write the failing tests**

Create `ui-app/src/components/dub/__tests__/VersionPicker.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VersionPicker } from '../VersionPicker';
import type { VersionEntry } from '../../../api/types';

const versions: VersionEntry[] = [
  { id: 'v2', name: 'polished', created_at: '2026-05-29T11:00:00Z' },
  { id: 'v1', name: 'migrated', created_at: '2026-05-29T10:00:00Z' },
];

describe('VersionPicker', () => {
  it('always renders the Working Draft option first', () => {
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    const options = screen.getAllByRole('option');
    expect(options[0].textContent).toMatch(/working draft/i);
  });

  it('renders each snapshot below the working draft', () => {
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/polished/i)).toBeInTheDocument();
    expect(screen.getByText(/migrated/i)).toBeInTheDocument();
  });

  it('falls back to the id when a snapshot has no name', () => {
    render(
      <VersionPicker
        versions={[
          { id: 'v3', name: null, created_at: '2026-05-29T12:00:00Z' },
        ]}
        value="draft"
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText(/v3/)).toBeInTheDocument();
  });

  it('calls onChange with the selected version id', () => {
    const onChange = vi.fn();
    render(
      <VersionPicker
        versions={versions}
        value="draft"
        onChange={onChange}
      />,
    );
    const select = screen.getByRole('combobox') as HTMLSelectElement;
    fireEvent.change(select, { target: { value: 'v2' } });
    expect(onChange).toHaveBeenCalledWith('v2');
  });
});
```

- [ ] **Step 9.2: Run — confirm fail**

Run: `cd ui-app && npx vitest run src/components/dub/__tests__/VersionPicker.test.tsx 2>&1 | tail -10`

Expected: tests fail with "Cannot find module '../VersionPicker'".

- [ ] **Step 9.3: Implement `VersionPicker`**

Create `ui-app/src/components/dub/VersionPicker.tsx`:

```tsx
import type { VersionEntry } from '../../api/types';

interface VersionPickerProps {
  versions: VersionEntry[];
  /** The selected version id: 'draft' or one of the entries' ids. */
  value: string;
  onChange: (next: string) => void;
}

export function VersionPicker({ versions, value, onChange }: VersionPickerProps) {
  return (
    <div className="rounded-lg border border-primary/30 bg-primary/5 px-3 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] uppercase tracking-wider text-on-surface-variant">
          Subtitle version
        </span>
        <span className="text-[9px] text-on-surface-variant">
          edited in Editor tab
        </span>
      </div>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-surface border border-outline-variant/20 rounded px-2 py-1.5 text-xs text-on-surface focus:border-primary focus:outline-none"
      >
        <option value="draft">📝 Working Draft (latest edits)</option>
        {versions.map((v) => (
          <option key={v.id} value={v.id}>
            📌 {v.id} — {v.name ?? '(no name)'}
          </option>
        ))}
      </select>
    </div>
  );
}
```

- [ ] **Step 9.4: Run — confirm pass**

Run: `cd ui-app && npx vitest run src/components/dub/__tests__/VersionPicker.test.tsx 2>&1 | tail -10`

Expected: 4 passed.

- [ ] **Step 9.5: Commit**

```bash
git add ui-app/src/components/dub/VersionPicker.tsx ui-app/src/components/dub/__tests__/VersionPicker.test.tsx
git commit -m "feat(fe): VersionPicker dropdown for DubTab

A controlled <select> with 'Working Draft' always at the top and one
entry per snapshot below. Falls back to the version id when the entry
has no name. Wrapped in a primary-tinted card so it visually anchors
the top of the DubTab panel.

4 vitest tests cover always-having-working-draft-first, listing all
snapshots, the no-name fallback, and the onChange contract."
```

---

### Task 10: `VersionPanel` component for EditorTab

A list of saved versions with inline rename + delete. Hidden when versions is empty.

**Files:**
- Create: `ui-app/src/components/editor/VersionPanel.tsx`
- Create: `ui-app/src/components/editor/__tests__/VersionPanel.test.tsx`

- [ ] **Step 10.1: Write the failing tests**

Create `ui-app/src/components/editor/__tests__/VersionPanel.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { VersionPanel } from '../VersionPanel';
import type { VersionEntry } from '../../../api/types';

const versions: VersionEntry[] = [
  { id: 'v2', name: 'polished', created_at: '2026-05-29T11:00:00Z' },
  { id: 'v1', name: null, created_at: '2026-05-29T10:00:00Z' },
];

describe('VersionPanel', () => {
  it('renders nothing when versions is empty', () => {
    const { container } = render(
      <VersionPanel versions={[]} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders one row per version', () => {
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(screen.getByText(/v2/)).toBeInTheDocument();
    expect(screen.getByText(/v1/)).toBeInTheDocument();
  });

  it('inline-edit triggers onRename on blur with the new name', () => {
    const onRename = vi.fn();
    render(
      <VersionPanel versions={versions} onRename={onRename} onDelete={vi.fn()} />,
    );
    // Click the v2 name to enter edit mode.
    fireEvent.click(screen.getByText(/polished/i));
    const input = screen.getByDisplayValue('polished') as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'final' } });
    fireEvent.blur(input);
    expect(onRename).toHaveBeenCalledWith('v2', 'final');
  });

  it('delete button calls onDelete with the version id', () => {
    const onDelete = vi.fn();
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={onDelete} />,
    );
    const deleteButtons = screen.getAllByTitle(/delete/i);
    fireEvent.click(deleteButtons[0]); // first row = v2
    expect(onDelete).toHaveBeenCalledWith('v2');
  });

  it('shows (no name) placeholder for entries without a name', () => {
    render(
      <VersionPanel versions={versions} onRename={vi.fn()} onDelete={vi.fn()} />,
    );
    expect(screen.getByText(/\(no name\)/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 10.2: Run — confirm fail**

Run: `cd ui-app && npx vitest run src/components/editor/__tests__/VersionPanel.test.tsx 2>&1 | tail -10`

Expected: tests fail with "Cannot find module '../VersionPanel'".

- [ ] **Step 10.3: Implement `VersionPanel`**

Create `ui-app/src/components/editor/VersionPanel.tsx`:

```tsx
import { useState } from 'react';
import type { VersionEntry } from '../../api/types';

interface VersionPanelProps {
  versions: VersionEntry[];
  onRename: (versionId: string, name: string | null) => void;
  onDelete: (versionId: string) => void;
}

export function VersionPanel({ versions, onRename, onDelete }: VersionPanelProps) {
  const [editingId, setEditingId] = useState<string | null>(null);

  if (versions.length === 0) {
    return null;
  }

  return (
    <div className="pt-3 mt-3 border-t border-outline-variant/10">
      <div className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-2">
        Saved versions
      </div>
      <div className="flex flex-col gap-1">
        {versions.map((v) => (
          <div
            key={v.id}
            className="flex items-center gap-2 px-2 py-1.5 rounded bg-surface-container-lowest"
          >
            <span className="text-[10px] font-mono font-semibold text-primary bg-primary/15 px-1.5 py-0.5 rounded">
              {v.id}
            </span>
            {editingId === v.id ? (
              <input
                autoFocus
                defaultValue={v.name ?? ''}
                onBlur={(e) => {
                  setEditingId(null);
                  const next = e.target.value.trim();
                  onRename(v.id, next === '' ? null : next);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === 'Escape') {
                    (e.target as HTMLInputElement).blur();
                  }
                }}
                className="flex-1 bg-transparent text-xs text-on-surface border-b border-primary/40 focus:outline-none"
              />
            ) : (
              <span
                onClick={() => setEditingId(v.id)}
                className="flex-1 text-xs text-on-surface cursor-text hover:bg-primary/5 px-1 rounded"
              >
                {v.name ?? '(no name)'}
              </span>
            )}
            <button
              onClick={() => onDelete(v.id)}
              title="Delete version"
              className="p-1 rounded text-on-surface-variant hover:text-red-400 hover:bg-red-500/10"
            >
              <span className="material-symbols-outlined text-[14px]">delete</span>
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 10.4: Run — confirm pass**

Run: `cd ui-app && npx vitest run src/components/editor/__tests__/VersionPanel.test.tsx 2>&1 | tail -10`

Expected: 5 passed.

- [ ] **Step 10.5: Commit**

```bash
git add ui-app/src/components/editor/VersionPanel.tsx ui-app/src/components/editor/__tests__/VersionPanel.test.tsx
git commit -m "feat(fe): VersionPanel — saved-versions list in EditorTab

A compact list of immutable snapshots. Returns null when there are
zero versions so the editor footer stays minimal until the user takes
the first snapshot.

Each row: a chip with the version id, an inline-editable name
(click-to-edit, blur/Enter to commit, Esc to cancel), and a delete
icon. Names default to '(no name)' when null. Rename emits the cleaned
name (whitespace-trimmed); empty strings become null.

5 vitest tests cover the empty-state null, row rendering, inline
rename + blur, delete button, and the no-name fallback."
```

---

### Task 11: Wire DubTab — version picker + per-version dub generation

Now plumb everything together. The DubTab consumes `useVersions`, renders `VersionPicker`, and passes the selected version into `postTTS`. Audio library entries gain a version chip.

**Files:**
- Modify: `ui-app/src/pages/videoDetail/DubTab.tsx`
- Modify: `ui-app/src/pages/VideoDetail.tsx` (the actual `postTTS` caller)
- Modify: BE — `GET /api/videos/{id}/tts` to include `version` per entry (extract it from the filename)

- [ ] **Step 11.1: BE — extend the audio listing**

Open `src/api/routers/tts.py` and find the `list_tts_audio` handler (or similar — anywhere `GET /api/videos/{id}/tts` is defined; around line 182 per the survey). For each `.wav` file in the listing, parse the version from the filename:

```python
import re

_FNAME_RE = re.compile(
    r"^(?P<video_id>[^_]+)_(?P<lang>[^_]+)_(?P<version>v\d+|draft)_(?P<provider>[^_]+)_(?P<voice>.+)\.wav$"
)

def _parse_dub_filename(name: str) -> dict | None:
    m = _FNAME_RE.match(name)
    return m.groupdict() if m else None
```

Use this to populate a new `version: str` field on each `TTSAudioFile` response entry. Files that don't match the regex (legacy ones that escaped migration) fall back to `version="v1"` so the UI shows them as belonging to v1.

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10`

Expected: passes. No new test required — the FE smoke test covers this in Step 11.4.

- [ ] **Step 11.2: FE — DubTab integration**

Open [ui-app/src/pages/videoDetail/DubTab.tsx](ui-app/src/pages/videoDetail/DubTab.tsx). Find the component's prop interface and add `versions: VersionEntry[]`, `selectedVersion: string`, `onVersionChange: (v: string) => void`. Inside the component, render the `<VersionPicker>` at the top of the panel (before the existing provider/language/voice controls). In every audio-library row, render a colored chip with the row's `version` (Tailwind: `bg-primary/15 text-primary text-[9px] font-semibold px-1.5 py-0.5 rounded`).

- [ ] **Step 11.3: FE — VideoDetail wiring**

Open `ui-app/src/pages/VideoDetail.tsx`. Add:

```ts
import { useVersions } from '../hooks/useVersions';
// ...inside the component...
const { versions, createSnapshot, rename, remove } = useVersions(videoId, ttsLanguage);
const [selectedVersion, setSelectedVersion] = useState('draft');
```

Pass `versions`, `selectedVersion`, and `setSelectedVersion` into both `<EditorTab>` (for the VersionPanel + Save as version) and `<DubTab>`. Update the `postTTS` call site to include `selectedVersion`.

- [ ] **Step 11.4: Smoke test the FE build**

Run: `cd ui-app && npm run build 2>&1 | tail -10`

Expected: build succeeds. Vitest tests still pass:

`cd ui-app && npx vitest run 2>&1 | tail -10`

Expected: all green.

- [ ] **Step 11.5: Commit**

```bash
git add src/api/routers/tts.py ui-app/src/pages/videoDetail/DubTab.tsx ui-app/src/pages/VideoDetail.tsx
git commit -m "feat(dub): version-aware DubTab + audio library

DubTab renders the new VersionPicker at the top of the panel; selected
version is passed into postTTS so each (version + provider + voice)
gets its own WAV. Audio library rows show a colored chip with the
version id parsed from the filename.

BE: GET /api/videos/{id}/tts now populates a version field on each
entry by regex-matching the canonical
{id}_{lang}_{ver}_{provider}_{voice}.wav layout. Unmatched legacy files
fall back to 'v1' so the UI still shows them grouped under v1.

VideoDetail owns the selectedVersion state and the useVersions hook;
both EditorTab and DubTab consume from it for cross-tab consistency."
```

---

### Task 12: Wire EditorTab — Save as version + VersionPanel + remove Sync Dub banner

**Files:**
- Modify: `ui-app/src/pages/videoDetail/EditorTab.tsx`

- [ ] **Step 12.1: Drop the Sync Dub state and handler**

Locate and DELETE all of:
- The `handleSyncDub` callback ([EditorTab.tsx:407-459](ui-app/src/pages/videoDetail/EditorTab.tsx#L407-L459))
- The `isOutOfSync` / `isSyncing` / `syncError` state and their setters
- The Sync Dub banner JSX ([EditorTab.tsx:660-698](ui-app/src/pages/videoDetail/EditorTab.tsx#L660-L698))
- The `postDubSync` import and the TASK 12 marker comment from Task 8
- Any SSE subscription wired to dub-sync progress (`useSyncDubProgress` or similar)

- [ ] **Step 12.2: Add new props**

Update the `EditorTab` interface to accept:

```ts
interface EditorTabProps {
  // ...existing...
  versions: VersionEntry[];
  onCreateSnapshot: (name: string | null) => Promise<void>;
  onRenameVersion: (id: string, name: string | null) => Promise<void>;
  onDeleteVersion: (id: string) => Promise<void>;
}
```

- [ ] **Step 12.3: Add the "Save as version" button next to "Save"**

In the footer JSX where the Save button lives ([EditorTab.tsx:585-598](ui-app/src/pages/videoDetail/EditorTab.tsx#L585-L598)), add a sibling button:

```tsx
<button
  onClick={async () => {
    if (isDirty && saving) return;
    if (isDirty) {
      // Ensure the working draft is up to date before snapshotting.
      await handleSave();
    }
    await onCreateSnapshot(null);
  }}
  disabled={saving || segments.length === 0}
  className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-medium bg-secondary/20 text-secondary hover:bg-secondary/30 transition-colors"
  title="Save current draft as the next auto-numbered version"
>
  <span className="material-symbols-outlined text-sm">bookmark_add</span>
  Save as version
</button>
```

Above it, the existing Save button stays untouched (it already writes the working draft only after Task 4).

- [ ] **Step 12.4: Render the `VersionPanel`**

Just below the footer buttons row (still inside the editor pane), render:

```tsx
<VersionPanel
  versions={versions}
  onRename={(id, name) => onRenameVersion(id, name)}
  onDelete={(id) => {
    if (confirm(`Delete ${id}? This also deletes any dub WAVs generated from this version.`)) {
      onDeleteVersion(id);
    }
  }}
/>
```

Add the import: `import { VersionPanel } from '../../components/editor/VersionPanel';` and `import type { VersionEntry } from '../../api/types';`.

- [ ] **Step 12.5: Run the FE suite + build**

Run: `cd ui-app && npx vitest run && npm run build 2>&1 | tail -15`

Expected: all green; build succeeds.

- [ ] **Step 12.6: Commit**

```bash
git add ui-app/src/pages/videoDetail/EditorTab.tsx
git commit -m "feat(editor): Save as version button + VersionPanel; drop Sync Dub

The Sync Dub banner, handleSyncDub, isOutOfSync / isSyncing / syncError
state, and the SSE subscription for dub-sync progress are all removed.
Saving subtitles is now just saving — there's no implicit dub state to
care about.

A new 'Save as version' button sits next to 'Save' in the footer. If
there are unsaved edits it saves the working draft first, then calls
onCreateSnapshot(null). The VersionPanel renders below the buttons
when at least one snapshot exists.

Delete uses native confirm() since the deletion is destructive (it
cascades to all dub WAVs for the version). Rename and delete are
plumbed via props from VideoDetail's useVersions hook."
```

---

### Task 13: CHANGELOG + README

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 13.1: Add CHANGELOG entry**

In `CHANGELOG.md`, find the `## [Unreleased]` block. Add a `### Changed` subsection at the top (above existing `### Fixed` and `### Added` blocks):

```markdown
### Changed
- **Subtitle versioning + dub picks a version (replaces the implicit Sync Dub flow).** The editor saves to a mutable working draft; a new "Save as version" button snapshots it as the next auto-numbered immutable version (v1, v2, …) with an optional friendly name. DubTab gains a "Subtitle version" picker; each (version + provider + voice) gets its own dub WAV in the audio library. Per-(video, language) `versions.json` indexes snapshots. Migration is silent on first read: legacy `.dubsync.srt` becomes `v1`, existing dub WAVs gain a `_v1_` infix, `dub_meta_*.json` and the per-segment WAV cache are deleted. **Deleted:** `src/tts/sync_runner.py`, `src/tts/dub_meta.py`, `src/tts/dubsync_srt.py`, `src/tts/segment_cache.py`, `assembler.run_partial`, `POST /api/videos/{id}/dub/sync`, the Sync Dub banner in EditorTab, `_check_dub_sync_against_meta`, `postDubSync` FE client. **Added:** `src/api/versions.py` + `src/api/routers/versions.py` (CRUD), `ui-app/src/api/versions.ts`, `useVersions` hook, `VersionPicker`, `VersionPanel`. 27 new BE tests (`tests/test_versions.py`, `tests/test_migration.py`, `tests/test_srt_versioned.py`, `tests/test_tts_versioned.py`) + 13 new FE vitest tests.
```

- [ ] **Step 13.2: Add README progress section**

In `README.md`, find the "Subtitle Editor Bug Fixes (2026-05-29)" subsection. Insert this new subsection immediately after it (before "One-Time Setup Checklist"):

```markdown
### Subtitle Versioning + Dub-Version Picker (2026-05-29)

> Sub-project 2 of 3 in the dub-sync rebuild. See [`docs/superpowers/specs/2026-05-29-subtitle-versioning-design.md`](docs/superpowers/specs/2026-05-29-subtitle-versioning-design.md) and [`docs/superpowers/plans/2026-05-29-subtitle-versioning.md`](docs/superpowers/plans/2026-05-29-subtitle-versioning.md).

- [x] **Task 1** — `src/api/versions.py`: VersionEntry Pydantic model, load/save versions.json, next_version_id, snapshot_working_draft, delete_version (cascades to SRT + dub WAVs)
- [x] **Task 2** — `ensure_migrated` lazily folds legacy `.dubsync.srt`/dub_meta/segment-cache into the new layout on first read
- [x] **Task 3** — `/api/videos/{id}/versions` CRUD router (GET / POST / PATCH / DELETE)
- [x] **Task 4** — `GET /api/videos/{id}/srt` accepts `version` query param; `PUT` writes the working draft only; `_check_dub_sync_against_meta` removed
- [x] **Task 5** — `POST /api/tts` accepts `version`; output filename includes the version; assembler drops Stages 1.5/6/7 + `run_partial`
- [x] **Task 6** — Deleted `sync_runner.py`, `dub_meta.py`, `dubsync_srt.py`, `segment_cache.py`, their tests, and the `POST /api/videos/{id}/dub/sync` route
- [x] **Task 7** — FE versions API client + `useVersions` hook (4 vitest)
- [x] **Task 8** — `getSrt`/`postTTS` accept `version`; `postDubSync` deleted
- [x] **Task 9** — `VersionPicker` dropdown for DubTab (4 vitest)
- [x] **Task 10** — `VersionPanel` for EditorTab footer (5 vitest)
- [x] **Task 11** — DubTab + VideoDetail wired to the picker; audio library rows show version chips
- [x] **Task 12** — EditorTab grows "Save as version", renders VersionPanel, drops the Sync Dub banner and SSE subscription
- [x] **Task 13** — CHANGELOG + README updates

**Not in this PR:** standalone text→voice tool (sub-project 3) — separate spec + PR.

---
```

- [ ] **Step 13.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(versions): CHANGELOG + README rollup for subtitle versioning"
```

---

## Final verification (run before opening the PR)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10`

Expected: green. Roughly 370+ tests (343 from prior + 27 new).

- [ ] **Step F.2: Full FE vitest**

Run: `cd ui-app && npx vitest run 2>&1 | tail -10`

Expected: green. ~33 tests (20 from prior + 13 new).

- [ ] **Step F.3: FE build + lint**

Run: `cd ui-app && npm run build && npm run lint 2>&1 | tail -10`

Expected: build succeeds; only pre-existing lint debt remains.

- [ ] **Step F.4: BE lint**

Run: `ruff check src/ tests/ 2>&1 | tail -10`

Expected: only pre-existing lint debt remains.

- [ ] **Step F.5: Manual smoke (after merge)**

1. Open an existing video that has prior dub/SRT data → versions panel shows `v1 (migrated)`; DubTab dropdown lists `Working Draft` + `v1`; existing dub WAVs in the library show a `v1` chip.
2. Edit some subtitles → Save → click "Save as version" → `v2` appears in the panel.
3. DubTab → select `v2` → Generate → new WAV with `v2` chip; the v1 WAV is untouched.
4. Click v2's name in the panel → type "polished" → blur → label updates everywhere (DubTab dropdown reflects without reload).
5. Delete v1 from the panel → confirm → v1's SRT and any v1 WAVs disappear from the library.
6. Open a brand-new video with no prior subtitles → versions panel is hidden; "Save as version" disabled.

- [ ] **Step F.6: Push and open the PR**

```bash
git push -u origin feature/subtitle-versioning
gh pr create --base main --title "Subtitle versioning + dub picks a version (sub-project 2 of 3)" --body "$(cat <<'EOF'
## Summary
Replaces today's implicit diff-based Sync Dub flow with explicit user-managed subtitle versions. Sub-project **2 of 3** in the dub-sync rebuild — follows PR #17 (editor bug fixes) and precedes the standalone text→voice tool.

- **Working draft + immutable snapshots.** Existing "Save" overwrites the working draft. New "Save as version" snapshots it as v1, v2, … with an optional name.
- **DubTab version picker.** A "Subtitle version" dropdown at the top of DubTab. Each (version + provider + voice) gets its own dub WAV.
- **Silent migration.** Legacy `.dubsync.srt` becomes v1; existing dub WAVs get `_v1_` infix; `dub_meta_*.json` and per-segment cache deleted.
- **Deleted:** `sync_runner.py`, `dub_meta.py`, `dubsync_srt.py`, `segment_cache.py`, `assembler.run_partial`, `POST /api/videos/{id}/dub/sync`, the Sync Dub banner, `postDubSync` FE client.

## Test plan
- [x] `python -m pytest tests/ -x` — all green
- [x] `cd ui-app && npx vitest run` — all green (13 new tests)
- [x] `cd ui-app && npm run build && npm run lint` — clean
- [ ] Manual smoke: migrate an existing video; create + rename + delete a version; dub the working draft and v1 separately

## Sub-project context
Design: `docs/superpowers/specs/2026-05-29-subtitle-versioning-design.md`
Plan: `docs/superpowers/plans/2026-05-29-subtitle-versioning.md`
EOF
)"
```

---

## Self-review checklist (for the implementer)

- [ ] Every required item from the spec maps to a task: model (T1), migration (T2), CRUD router (T3), version-aware SRT routes (T4), version-aware TTS (T5), dub-sync deletion (T6), FE API + hook (T7), client params (T8), VersionPicker (T9), VersionPanel (T10), DubTab wiring (T11), EditorTab refactor (T12), docs (T13).
- [ ] No "TBD" / "implement later" / "similar to Task N" in any step.
- [ ] Type names are consistent: `VersionEntry` everywhere (FE + BE), `version` field on `TTSAudioFile`, `'draft'` sentinel for the working draft.
- [ ] No AI-attribution strings in any commit message.
- [ ] Branch stays `feature/subtitle-versioning`; no new branches.
