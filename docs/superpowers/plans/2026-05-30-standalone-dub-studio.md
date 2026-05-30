# Standalone SRT → Dub Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New `/dub-studio` page where the user uploads any SRT (no video, no project binding), picks TTS provider/voice/language/speed/shorten-toggle, generates a dub WAV, and downloads it. Recent dubs persist on disk with a small metadata sidecar.

**Architecture:** New module `src/api/standalone_dub.py` owns IO + a thin `StandaloneDubEntry` dataclass. New `TaskManager.run_standalone_dub` orchestrates the dub run via the existing `assembler.generate_full_track` (whose `video_id` / `underlay_db` params are already kept-for-back-compat no-ops since the refocus). New router exposes 4 endpoints; FE is a new top-level page that reuses `subscribeSSE` for progress + the multipart `FormData` upload pattern from sub-project 2.

**Tech Stack:** Python 3.11 + FastAPI + Pydantic v2 (BE), React 19 + TypeScript + Tailwind 4 + Vite + vitest (FE), `python-multipart` (already added in sub-project 2).

---

## Context the implementer needs

**Spec:** [docs/superpowers/specs/2026-05-30-standalone-dub-studio-design.md](docs/superpowers/specs/2026-05-30-standalone-dub-studio-design.md) — read first.

**Files at HEAD (read before starting):**
- [src/api/task_manager.py:658-727](src/api/task_manager.py#L658-L727) — `run_tts` (the orchestrator pattern to mirror; `run_standalone_dub` follows the same shape)
- [src/api/task_manager.py:255-260](src/api/task_manager.py#L255-L260) — `create_task` (used by the router to register a task before dispatch)
- [src/api/task_manager.py:260-268](src/api/task_manager.py#L260-L268) — `_emit` (SSE event push)
- [src/api/task_manager.py:376-405](src/api/task_manager.py#L376-L405) — `subscribe` (read side of SSE; the existing `/api/tasks/{id}` route uses this)
- [src/tts/runner.py:33-90](src/tts/runner.py#L33-L90) — `_build_llm_translator` (reuse for Stage 0 + 3 LLM work)
- [src/tts/runner.py:120-180](src/tts/runner.py#L120-L180) — `run_tts_track` shape (we duplicate ~20 lines of provider+translator setup in standalone instead of forcing this path to accept "no video")
- [src/tts/assembler.py:418-434](src/tts/assembler.py#L418-L434) — `generate_full_track` signature
- [src/api/routers/versions.py](src/api/routers/versions.py) — sub-project 2's multipart import endpoint (the pattern to mirror for our POST)
- [src/api/routers/transcribe.py:135-149](src/api/routers/transcribe.py#L135-L149) — SRT download via `FileResponse` (pattern for our WAV download)
- [src/api/routers/tasks.py](src/api/routers/tasks.py) — `cancel_task` route; also shows the `task._asyncio_task` capture pattern
- [src/api/__init__.py:46-54](src/api/__init__.py#L46-L54) — router registration; we add `standalone_dub` here
- [ui-app/src/api/versions.ts](ui-app/src/api/versions.ts) — `importVersion` is the multipart `FormData` template
- [ui-app/src/api/client.ts:379+](ui-app/src/api/client.ts#L379) — `subscribeSSE` (reuse on the page)
- [ui-app/src/pages/videoDetail/DubTab.tsx](ui-app/src/pages/videoDetail/DubTab.tsx) — picker controls + audio library row layout (we mirror its row shape on the standalone page)
- [ui-app/src/data/mockData.ts](ui-app/src/data/mockData.ts) — `navItems` array (add the Dub Studio entry here)
- [ui-app/src/App.tsx:25-35](ui-app/src/App.tsx#L25-L35) — Routes block (add the new route here)
- [tests/test_versions.py:205-230](tests/test_versions.py#L205-L230) — `client` fixture pattern with `tmp_path` + `monkeypatch` (mirror for our router tests)

**Commands you'll use:**
- BE tests (file): `python -m pytest tests/test_standalone_dub.py -v`
- BE tests (full): `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py`
- FE tests: `cd ui-app && npx vitest run`
- FE build: `cd ui-app && npm run build`
- BE lint: `ruff check src/ tests/`

**Repo rules to follow (from CLAUDE.md):**
- Branch: `feature/standalone-dub-studio` already exists with the spec commit `d4cdb4f`. Stay on it.
- Bundle CHANGELOG + README into Task 6.
- No "Co-Authored-By", no AI mentions in commits or code comments.

---

## File structure

| Path | Action | Responsibility |
|------|--------|---------------|
| `src/api/standalone_dub.py` | Create | `StandaloneDubEntry` dataclass + IO helpers: `list_dubs`, `delete_dub`, `wav_path`, `_meta_path`, `STANDALONE_DIR` |
| `src/api/routers/standalone_dub.py` | Create | 4 routes: POST (multipart), GET list, DELETE, GET WAV |
| `src/api/task_manager.py` | Modify | Add `run_standalone_dub` async method that wraps `assembler.generate_full_track` |
| `src/api/__init__.py` | Modify | Register the new router |
| `tests/test_standalone_dub.py` | Create | 3 test classes: `TestStandaloneDubHelpers` (5), `TestStandaloneDubRouter` (6), `TestManagerRunStandaloneDub` (2) |
| `ui-app/src/api/standaloneDub.ts` | Create | `StandaloneDubEntry` interface + 4 API functions |
| `ui-app/src/pages/DubStudio.tsx` | Create | The page component |
| `ui-app/src/pages/__tests__/DubStudio.test.tsx` | Create | 4 vitest tests |
| `ui-app/src/App.tsx` | Modify | Add the `<Route path="/dub-studio" />` |
| `ui-app/src/data/mockData.ts` | Modify | Add `Dub Studio` nav item |
| `CHANGELOG.md` | Modify | `Added` entry |
| `README.md` | Modify | Progress section |

---

### Task 1: BE — `standalone_dub.py` helpers + tests

Pure-IO module: dataclass + load/save/delete. No FastAPI imports.

**Files:**
- Create: `src/api/standalone_dub.py`
- Create: `tests/test_standalone_dub.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_standalone_dub.py`:

```python
"""Tests for the standalone-dub module."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest


@pytest.fixture
def standalone_dir(tmp_path, monkeypatch):
    """Redirect data/standalone_dubs to a tmp dir for the test."""
    d = tmp_path / "standalone_dubs"
    d.mkdir()
    monkeypatch.setattr("src.api.standalone_dub.STANDALONE_DIR", d)
    return d


def _seed_entry(
    standalone_dir: Path,
    dub_uuid: str,
    *,
    original_filename: str = "test.srt",
    provider: str = "google",
    voice: str = "vi-VN-Wavenet-A",
    language: str = "vi",
    created_at: str = "2026-05-30T10:00:00+00:00",
    duration_seconds: float = 30.0,
    file_size_bytes: int = 1024,
    playback_speed: float = 1.5,
    enable_shortening: bool = True,
) -> None:
    """Write a fake .wav + .json sidecar pair."""
    (standalone_dir / f"{dub_uuid}.wav").write_bytes(b"RIFFfake-audio")
    (standalone_dir / f"{dub_uuid}.json").write_text(json.dumps({
        "uuid": dub_uuid,
        "original_filename": original_filename,
        "provider": provider,
        "voice": voice,
        "language": language,
        "playback_speed": playback_speed,
        "enable_shortening": enable_shortening,
        "duration_seconds": duration_seconds,
        "created_at": created_at,
        "file_size_bytes": file_size_bytes,
    }))


class TestStandaloneDubHelpers:
    def test_list_dubs_empty_returns_empty_list(self, standalone_dir):
        from src.api.standalone_dub import list_dubs

        assert list_dubs() == []

    def test_list_dubs_returns_newest_first(self, standalone_dir):
        from src.api.standalone_dub import list_dubs

        _seed_entry(standalone_dir, "older", created_at="2026-05-30T09:00:00+00:00")
        _seed_entry(standalone_dir, "newer", created_at="2026-05-30T11:00:00+00:00")

        out = list_dubs()
        assert len(out) == 2
        assert out[0].uuid == "newer"
        assert out[1].uuid == "older"

    def test_list_dubs_skips_orphan_metadata(self, standalone_dir):
        """A .json file with no corresponding .wav is filtered out."""
        from src.api.standalone_dub import list_dubs

        _seed_entry(standalone_dir, "complete")
        # Orphan: write JSON but no WAV
        (standalone_dir / "orphan.json").write_text(json.dumps({
            "uuid": "orphan",
            "original_filename": "orphan.srt",
            "provider": "google",
            "voice": "v",
            "language": "vi",
            "playback_speed": 1.5,
            "enable_shortening": True,
            "duration_seconds": 30.0,
            "created_at": "2026-05-30T10:00:00+00:00",
            "file_size_bytes": 0,
        }))

        out = list_dubs()
        uuids = [e.uuid for e in out]
        assert "complete" in uuids
        assert "orphan" not in uuids

    def test_delete_dub_removes_both_files(self, standalone_dir):
        from src.api.standalone_dub import delete_dub

        _seed_entry(standalone_dir, "tobedeleted")
        assert (standalone_dir / "tobedeleted.wav").exists()
        assert (standalone_dir / "tobedeleted.json").exists()

        ok = delete_dub("tobedeleted")
        assert ok is True
        assert not (standalone_dir / "tobedeleted.wav").exists()
        assert not (standalone_dir / "tobedeleted.json").exists()

    def test_delete_dub_missing_returns_false(self, standalone_dir):
        from src.api.standalone_dub import delete_dub

        assert delete_dub("does-not-exist") is False

    def test_wav_path_returns_expected_location(self, standalone_dir):
        from src.api.standalone_dub import wav_path

        p = wav_path("abc123")
        assert p == standalone_dir / "abc123.wav"
```

- [ ] **Step 1.2: Run — confirm fail**

Run: `python -m pytest tests/test_standalone_dub.py -v 2>&1 | tail -15`

Expected: 6 tests FAIL with `ImportError: cannot import name 'list_dubs' from 'src.api.standalone_dub'`.

- [ ] **Step 1.3: Implement `src/api/standalone_dub.py`**

Create the new module:

```python
"""Standalone SRT → Dub IO module.

Pure-IO helpers for the data/standalone_dubs/ directory. Each generated
dub is one {uuid}.wav + one {uuid}.json sidecar with metadata. This
module owns the dataclass shape, the list/delete/path helpers, and the
on-disk schema.

The orchestration that actually runs the assembler lives on
TaskManager.run_standalone_dub — this module is pure IO and stays
FastAPI-free for clean unit testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
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


def wav_path(dub_uuid: str) -> Path:
    """Resolve the WAV path for a uuid. Caller must check `.exists()`."""
    return STANDALONE_DIR / f"{dub_uuid}.wav"


def _meta_path(dub_uuid: str) -> Path:
    return STANDALONE_DIR / f"{dub_uuid}.json"


def list_dubs() -> list[StandaloneDubEntry]:
    """Return recent dubs newest-first by created_at.

    Scans every {uuid}.json in STANDALONE_DIR. Skips entries whose
    corresponding .wav file has been deleted out of band — only "complete"
    pairs (.wav + .json both present) are surfaced.
    """
    if not STANDALONE_DIR.exists():
        return []

    entries: list[StandaloneDubEntry] = []
    for json_path in STANDALONE_DIR.glob("*.json"):
        wav = json_path.with_suffix(".wav")
        if not wav.exists():
            continue
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        try:
            entries.append(StandaloneDubEntry(
                uuid=data["uuid"],
                original_filename=data["original_filename"],
                provider=data["provider"],
                voice=data["voice"],
                language=data["language"],
                playback_speed=float(data["playback_speed"]),
                enable_shortening=bool(data["enable_shortening"]),
                duration_seconds=float(data["duration_seconds"]),
                created_at=datetime.fromisoformat(data["created_at"]),
                file_size_bytes=int(data["file_size_bytes"]),
            ))
        except (KeyError, ValueError, TypeError):
            # Malformed metadata — skip silently.
            continue

    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def delete_dub(dub_uuid: str) -> bool:
    """Remove both {uuid}.wav and {uuid}.json. Returns True if at least
    one file was removed; False if neither existed."""
    wav = wav_path(dub_uuid)
    meta = _meta_path(dub_uuid)
    deleted_any = False
    if wav.exists():
        wav.unlink()
        deleted_any = True
    if meta.exists():
        meta.unlink()
        deleted_any = True
    return deleted_any


def save_meta(entry: StandaloneDubEntry) -> None:
    """Write the sidecar JSON for an entry."""
    STANDALONE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "uuid": entry.uuid,
        "original_filename": entry.original_filename,
        "provider": entry.provider,
        "voice": entry.voice,
        "language": entry.language,
        "playback_speed": entry.playback_speed,
        "enable_shortening": entry.enable_shortening,
        "duration_seconds": entry.duration_seconds,
        "created_at": entry.created_at.isoformat(),
        "file_size_bytes": entry.file_size_bytes,
    }
    _meta_path(entry.uuid).write_text(json.dumps(payload, indent=2))
```

- [ ] **Step 1.4: Run — confirm all 6 pass**

Run: `python -m pytest tests/test_standalone_dub.py::TestStandaloneDubHelpers -v 2>&1 | tail -15`

Expected: 6 passed.

- [ ] **Step 1.5: Lint**

Run: `ruff check src/api/standalone_dub.py tests/test_standalone_dub.py 2>&1 | tail -5`

Expected: clean.

- [ ] **Step 1.6: Commit**

```bash
git add src/api/standalone_dub.py tests/test_standalone_dub.py
git commit -m "feat(standalone-dub): IO module + dataclass

src/api/standalone_dub.py exposes:
- STANDALONE_DIR = data/standalone_dubs
- StandaloneDubEntry dataclass (the on-disk metadata shape)
- list_dubs(): scan {uuid}.json sidecars, return newest-first; skip
  orphans whose .wav was deleted out of band
- delete_dub(uuid): remove both .wav + .json, returns True if removed
- wav_path(uuid), save_meta(entry): small helpers

Pure IO. No FastAPI imports. 6 unit tests cover empty-dir, sort order,
orphan-filtering, delete happy path, delete missing, and wav_path."
```

---

### Task 2: BE — `TaskManager.run_standalone_dub` + tests

The orchestrator. Parses the uploaded SRT bytes via `parse_srt`, derives video_duration from segments, builds the provider + translator (mirrors `run_tts_track`'s ~20 lines), calls `assembler.generate_full_track` directly, writes the metadata sidecar.

**Files:**
- Modify: `src/api/task_manager.py`
- Modify: `tests/test_standalone_dub.py`

- [ ] **Step 2.1: Write the failing tests**

Append to `tests/test_standalone_dub.py`:

```python
class TestManagerRunStandaloneDub:
    @pytest.mark.asyncio
    async def test_run_writes_wav_and_metadata(self, standalone_dir, monkeypatch):
        """The orchestrator parses SRT, calls the assembler, and writes
        both the WAV (from assembler) and the JSON sidecar."""
        from unittest.mock import AsyncMock, patch
        from src.api.task_manager import TaskManager

        tm = TaskManager()
        task = tm.create_task("standalone_dub")
        task_id = task.task_id

        valid_srt = (
            b"1\n00:00:00,000 --> 00:00:02,000\nhello\n\n"
            b"2\n00:00:03,000 --> 00:00:05,000\nworld\n\n"
        )

        async def fake_generate(*args, **kwargs):
            # The assembler writes the WAV at output_path
            kwargs["output_path"].write_bytes(b"RIFFfake-audio")
            return (kwargs["output_path"], [])

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            side_effect=fake_generate,
        ), patch(
            "src.tts.runner.get_tts_provider", return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator", return_value=None,
        ):
            await tm.run_standalone_dub(
                task_id=task_id,
                srt_content=valid_srt,
                original_filename="episode-5.srt",
                provider="google",
                voice="vi-VN-Wavenet-A",
                language="vi",
                playback_speed=1.5,
                enable_shortening=True,
                config={},
            )

        assert task.status == "completed"

        # WAV + JSON both present in the standalone dir
        wavs = list(standalone_dir.glob("*.wav"))
        metas = list(standalone_dir.glob("*.json"))
        assert len(wavs) == 1
        assert len(metas) == 1

        meta = json.loads(metas[0].read_text())
        assert meta["original_filename"] == "episode-5.srt"
        assert meta["provider"] == "google"
        assert meta["voice"] == "vi-VN-Wavenet-A"
        assert meta["language"] == "vi"
        assert meta["playback_speed"] == 1.5
        assert meta["enable_shortening"] is True
        # video_duration = max(end) + 1.0 = 5.0 + 1.0 = 6.0
        # The assembler is mocked, so duration_seconds reflects what we
        # computed before calling it (the planned duration).
        assert meta["duration_seconds"] == 6.0
        assert meta["file_size_bytes"] > 0  # the fake WAV bytes
        assert "uuid" in meta
        assert "created_at" in meta

    @pytest.mark.asyncio
    async def test_run_with_invalid_srt_marks_task_failed(self, standalone_dir):
        """Garbage bytes → task ends with status='failed'."""
        from src.api.task_manager import TaskManager

        tm = TaskManager()
        task = tm.create_task("standalone_dub")
        task_id = task.task_id

        await tm.run_standalone_dub(
            task_id=task_id,
            srt_content=b"not an srt at all",
            original_filename="garbage.srt",
            provider="google",
            voice="v",
            language="vi",
            playback_speed=1.5,
            enable_shortening=True,
            config={},
        )

        assert task.status == "failed"
        assert task.error  # some non-empty error message
        # No partial output left behind
        assert list(standalone_dir.glob("*.wav")) == []
        assert list(standalone_dir.glob("*.json")) == []
```

- [ ] **Step 2.2: Run — confirm fail**

Run: `python -m pytest tests/test_standalone_dub.py::TestManagerRunStandaloneDub -v 2>&1 | tail -15`

Expected: 2 FAIL with `AttributeError: 'TaskManager' object has no attribute 'run_standalone_dub'`.

- [ ] **Step 2.3: Add `run_standalone_dub` to `TaskManager`**

Open `src/api/task_manager.py`. Find the end of `run_tts` (around line 727). Add this new method immediately after:

```python
    async def run_standalone_dub(
        self,
        task_id: str,
        srt_content: bytes,
        original_filename: str,
        provider: str,
        voice: str,
        language: str,
        playback_speed: float,
        enable_shortening: bool,
        config: dict,
        api_key_override: str | None = None,
        llm_api_key: str | None = None,
        llm_backend: str | None = None,
    ):
        """Generate a dub WAV from uploaded SRT bytes alone.

        Unlike run_tts, there's no video binding: SRT bytes are passed
        directly, video_duration is derived from the last segment's end +
        1s buffer, output lands in data/standalone_dubs/{uuid}.wav with a
        {uuid}.json metadata sidecar.
        """
        import tempfile
        import uuid as uuid_lib
        from datetime import datetime, timezone

        from src.api import standalone_dub as standalone_mod
        from src.processor.subtitle import parse_srt
        from src.tts import get_tts_provider
        from src.tts.assembler import TTSAssembler
        from src.tts.runner import _build_llm_translator

        task = self.tasks[task_id]
        task.status = "running"
        task.message = "Preparing standalone dub..."
        self._emit(task_id, "progress", {"progress": 0.0, "message": "Preparing standalone dub..."})

        try:
            # 1. Parse SRT via temp file (parse_srt is path-based).
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

            # 2. Derive duration: last segment end + 1s buffer.
            video_duration = max(seg["end"] for seg in segments) + 1.0

            # 3. Generate uuid and output path.
            dub_uuid = uuid_lib.uuid4().hex
            standalone_mod.STANDALONE_DIR.mkdir(parents=True, exist_ok=True)
            output_path = standalone_mod.wav_path(dub_uuid)

            # 4. Build effective config with API-key override.
            effective_config = dict(config)
            if api_key_override:
                tts_cfg = dict(effective_config.get("tts", {}))
                tts_cfg[f"{provider}_api_key"] = api_key_override
                effective_config["tts"] = tts_cfg

            # 5. Build provider + translator (translator may be None if
            # no LLM key is configured; that's fine — Stage 0 and 3 fall
            # back to heuristic / no-op respectively).
            tts_provider = get_tts_provider(effective_config, provider=provider)
            translator = _build_llm_translator(
                effective_config,
                llm_api_key=llm_api_key,
                llm_backend_override=llm_backend,
            )

            # 6. Progress callback wires into SSE.
            def on_progress(current: int, total: int, message: str):
                pct = current / total if total > 0 else 0.0
                task.progress = pct
                task.message = message
                self._emit(task_id, "progress", {"progress": pct, "message": message})

            # 7. Build the LLM caller for Stage 0 sentence merging (if
            # the translator is available).
            llm_caller = None
            if translator is not None:
                async def _llm_caller(system: str, user: str, max_tokens: int) -> str:
                    return await translator._call_llm(system, user, max_tokens=max_tokens)
                llm_caller = _llm_caller

            # 8. Build the voice_profile dict the assembler expects.
            voice_profile = {"voice": voice, "language": language}

            # 9. Run the assembler.
            assembler = TTSAssembler(translator=translator)
            await assembler.generate_full_track(
                provider=tts_provider,
                segments=segments,
                voice_profile=voice_profile,
                video_duration=video_duration,
                output_path=output_path,
                on_progress=on_progress,
                llm_caller=llm_caller,
                playback_speed=playback_speed,
                video_id=dub_uuid,
                language=language,
                provider_name=provider,
                enable_shortening=enable_shortening,
            )

            # 10. Write metadata sidecar.
            file_size = output_path.stat().st_size if output_path.exists() else 0
            entry = standalone_mod.StandaloneDubEntry(
                uuid=dub_uuid,
                original_filename=original_filename,
                provider=provider,
                voice=voice,
                language=language,
                playback_speed=playback_speed,
                enable_shortening=enable_shortening,
                duration_seconds=video_duration,
                created_at=datetime.now(timezone.utc),
                file_size_bytes=file_size,
            )
            standalone_mod.save_meta(entry)

            task.status = "completed"
            task.progress = 1.0
            task.message = "Dub generation complete"
            task.result = {"uuid": dub_uuid, "file_size_bytes": file_size}
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Standalone dub failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Standalone dub task {task_id} failed: {e}")
```

- [ ] **Step 2.4: Run — confirm 2 new tests pass**

Run: `python -m pytest tests/test_standalone_dub.py::TestManagerRunStandaloneDub -v 2>&1 | tail -15`

Expected: 2 passed.

- [ ] **Step 2.5: Run the full standalone test file**

Run: `python -m pytest tests/test_standalone_dub.py -v 2>&1 | tail -10`

Expected: 8 passed (6 from Task 1 + 2 from Task 2).

- [ ] **Step 2.6: Commit**

```bash
git add src/api/task_manager.py tests/test_standalone_dub.py
git commit -m "feat(standalone-dub): TaskManager.run_standalone_dub orchestrator

Parses uploaded SRT via parse_srt + temp file (mirrors import_as_version
from sub-project 2). Derives video_duration from max(segment.end) + 1s.
Generates a uuid, builds the TTS provider + LLM translator, calls
assembler.generate_full_track directly. Writes the metadata sidecar
on success.

Failure path: any ValueError (parse failure, empty SRT) or assembler
exception sets task.status='failed' and emits an error SSE event. No
partial WAV/sidecar is left behind because the assembler writes
straight to output_path which only exists after a successful run.

2 new tests in TestManagerRunStandaloneDub: happy path with mocked
assembler verifying the JSON metadata matches inputs; invalid-SRT
path verifying task failure with no orphan files."
```

---

### Task 3: BE — router (POST, GET list, DELETE, WAV download) + tests

**Files:**
- Create: `src/api/routers/standalone_dub.py`
- Modify: `src/api/__init__.py` (register the router)
- Modify: `tests/test_standalone_dub.py`

- [ ] **Step 3.1: Write the failing tests**

Append to `tests/test_standalone_dub.py`:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    """FastAPI TestClient with data dirs redirected to tmp."""
    standalone_dir = tmp_path / "standalone_dubs"
    standalone_dir.mkdir()
    monkeypatch.setattr("src.api.standalone_dub.STANDALONE_DIR", standalone_dir)

    from fastapi.testclient import TestClient
    from src.api import create_app

    app = create_app()
    return TestClient(app), standalone_dir


class TestStandaloneDubRouter:
    def test_get_lists_empty_initially(self, client):
        c, _ = client
        r = c.get("/api/standalone-dub")
        assert r.status_code == 200
        assert r.json() == []

    def test_get_lists_seeded_dubs(self, client):
        c, standalone_dir = client
        _seed_entry(standalone_dir, "first", created_at="2026-05-30T10:00:00+00:00")
        _seed_entry(standalone_dir, "second", created_at="2026-05-30T11:00:00+00:00")

        r = c.get("/api/standalone-dub")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        # Newest first.
        assert body[0]["uuid"] == "second"

    def test_delete_removes_files(self, client):
        c, standalone_dir = client
        _seed_entry(standalone_dir, "tobedeleted")

        r = c.delete("/api/standalone-dub/tobedeleted")
        assert r.status_code == 204
        assert not (standalone_dir / "tobedeleted.wav").exists()
        assert not (standalone_dir / "tobedeleted.json").exists()

    def test_delete_unknown_returns_404(self, client):
        c, _ = client
        r = c.delete("/api/standalone-dub/does-not-exist")
        assert r.status_code == 404

    def test_get_wav_serves_file(self, client):
        c, standalone_dir = client
        _seed_entry(standalone_dir, "wav-test")

        r = c.get("/api/standalone-dub/wav-test.wav")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("audio/")
        assert r.content == b"RIFFfake-audio"

    def test_get_wav_unknown_returns_404(self, client):
        c, _ = client
        r = c.get("/api/standalone-dub/unknown.wav")
        assert r.status_code == 404
```

The POST endpoint is exercised indirectly via `TestManagerRunStandaloneDub` (the orchestrator is what does the work). A separate POST-route test would add an asyncio + mock-heavy test for ~no extra coverage; skip it.

- [ ] **Step 3.2: Run — confirm fail**

Run: `python -m pytest tests/test_standalone_dub.py::TestStandaloneDubRouter -v 2>&1 | tail -15`

Expected: 6 FAIL with `404 Not Found` (the route doesn't exist).

- [ ] **Step 3.3: Create `src/api/routers/standalone_dub.py`**

```python
"""Standalone SRT → Dub CRUD routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from starlette.responses import FileResponse

from src.api import standalone_dub as standalone_mod
from src.api.deps import get_config, get_task_manager
from src.api.models import TaskResponse

router = APIRouter()


class StandaloneDubEntryResponse(BaseModel):
    uuid: str
    original_filename: str
    provider: str
    voice: str
    language: str
    playback_speed: float
    enable_shortening: bool
    duration_seconds: float
    created_at: str  # iso-format
    file_size_bytes: int


@router.post(
    "/api/standalone-dub",
    response_model=TaskResponse,
    status_code=201,
)
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
    """Generate a dub from an uploaded SRT. Returns task_id; subscribe
    to the existing /api/tasks/{task_id} SSE for progress."""
    tm = get_task_manager()
    config = get_config()

    content = await file.read()
    task = tm.create_task("standalone_dub")
    task._asyncio_task = asyncio.create_task(
        tm.run_standalone_dub(
            task_id=task.task_id,
            srt_content=content,
            original_filename=file.filename or "uploaded.srt",
            provider=provider,
            voice=voice,
            language=language,
            playback_speed=playback_speed,
            enable_shortening=enable_shortening,
            config=config,
            api_key_override=api_key,
            llm_api_key=llm_api_key,
            llm_backend=llm_backend,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get(
    "/api/standalone-dub",
    response_model=list[StandaloneDubEntryResponse],
)
async def list_standalone_dubs():
    """Recent dubs, newest first."""
    return [
        StandaloneDubEntryResponse(
            uuid=e.uuid,
            original_filename=e.original_filename,
            provider=e.provider,
            voice=e.voice,
            language=e.language,
            playback_speed=e.playback_speed,
            enable_shortening=e.enable_shortening,
            duration_seconds=e.duration_seconds,
            created_at=e.created_at.isoformat(),
            file_size_bytes=e.file_size_bytes,
        )
        for e in standalone_mod.list_dubs()
    ]


@router.delete("/api/standalone-dub/{dub_uuid}", status_code=204)
async def delete_standalone_dub(dub_uuid: str):
    """Remove the WAV + metadata sidecar."""
    ok = standalone_mod.delete_dub(dub_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Dub {dub_uuid} not found")
    return None


@router.get("/api/standalone-dub/{dub_uuid}.wav")
async def download_standalone_dub(dub_uuid: str):
    """Serve the WAV with Content-Disposition: attachment for download."""
    wav = standalone_mod.wav_path(dub_uuid)
    if not wav.exists():
        raise HTTPException(status_code=404, detail=f"Dub {dub_uuid} not found")
    return FileResponse(
        path=str(wav),
        media_type="audio/wav",
        filename=f"{dub_uuid}.wav",
        headers={"Content-Disposition": f'attachment; filename="{dub_uuid}.wav"'},
    )
```

- [ ] **Step 3.4: Register the router in `src/api/__init__.py`**

Open `src/api/__init__.py`. In the import block (around line 17), add `standalone_dub` to the routers import:

```python
from src.api.routers import (
    download, transcribe, translate, editor, settings, pipeline,
    tts, versions, tasks, standalone_dub,
)
```

(Add `standalone_dub` to the end of the list; keep ordering consistent with the rest.)

In the `app.include_router(...)` block (around lines 46-54), add:

```python
app.include_router(standalone_dub.router)
```

(Place it next to the other content routers — order doesn't matter functionally.)

- [ ] **Step 3.5: Run — confirm 6 router tests pass**

Run: `python -m pytest tests/test_standalone_dub.py::TestStandaloneDubRouter -v 2>&1 | tail -15`

Expected: 6 passed.

- [ ] **Step 3.6: Run the full standalone test file + the wider BE suite**

```bash
python -m pytest tests/test_standalone_dub.py -v 2>&1 | tail -5
python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5
```

Expected: standalone file = 14 passed; full BE suite = green.

- [ ] **Step 3.7: Lint**

Run: `ruff check src/api/routers/standalone_dub.py src/api/__init__.py 2>&1 | tail -5`

Expected: no new errors.

- [ ] **Step 3.8: Commit**

```bash
git add src/api/routers/standalone_dub.py src/api/__init__.py tests/test_standalone_dub.py
git commit -m "feat(standalone-dub): POST/GET/DELETE/WAV-download routes

Four endpoints under /api/standalone-dub:
- POST: multipart (file + provider/voice/language/playback_speed/
  enable_shortening + optional api_key/llm_api_key/llm_backend).
  Creates a task; returns task_id. Run in background via
  asyncio.create_task captured on task._asyncio_task (matches the
  cancel-pipeline pattern).
- GET: lists recent dubs, newest first.
- DELETE /{uuid}: removes WAV + metadata sidecar. 404 if neither
  exists.
- GET /{uuid}.wav: FileResponse with Content-Disposition: attachment.

6 endpoint tests via FastAPI TestClient with monkeypatched
STANDALONE_DIR. Router registered in src/api/__init__.py."
```

---

### Task 4: FE — `standaloneDub.ts` API client

**Files:**
- Create: `ui-app/src/api/standaloneDub.ts`

- [ ] **Step 4.1: Implement the client**

Create `ui-app/src/api/standaloneDub.ts`:

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

export interface PostStandaloneDubOpts {
  file: File;
  provider: string;
  voice: string;
  language: string;
  playbackSpeed: number;
  enableShortening: boolean;
  apiKey?: string;
  llmApiKey?: string;
  llmBackend?: string;
}

export async function postStandaloneDub(
  opts: PostStandaloneDubOpts,
): Promise<TaskResponse> {
  const formData = new FormData();
  formData.append('file', opts.file);
  formData.append('provider', opts.provider);
  formData.append('voice', opts.voice);
  formData.append('language', opts.language);
  formData.append('playback_speed', String(opts.playbackSpeed));
  formData.append('enable_shortening', String(opts.enableShortening));
  if (opts.apiKey) formData.append('api_key', opts.apiKey);
  if (opts.llmApiKey) formData.append('llm_api_key', opts.llmApiKey);
  if (opts.llmBackend) formData.append('llm_backend', opts.llmBackend);

  const r = await fetch('/api/standalone-dub', {
    method: 'POST',
    body: formData,
  });
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    throw new Error(`${r.status} ${body}`);
  }
  return r.json();
}

export async function getStandaloneDubs(): Promise<StandaloneDubEntry[]> {
  const r = await fetch('/api/standalone-dub');
  if (!r.ok) {
    throw new Error(`${r.status}`);
  }
  return r.json();
}

export async function deleteStandaloneDub(dubUuid: string): Promise<void> {
  const r = await fetch(`/api/standalone-dub/${dubUuid}`, { method: 'DELETE' });
  if (!r.ok && r.status !== 204) {
    throw new Error(`${r.status}`);
  }
}

export function getStandaloneDubUrl(dubUuid: string): string {
  return `/api/standalone-dub/${dubUuid}.wav`;
}
```

The `postStandaloneDub` uses raw `fetch` + `FormData` (same pattern as `importVersion` — don't set Content-Type, let the browser set the multipart boundary).

- [ ] **Step 4.2: Verify TypeScript compiles**

Run: `cd ui-app && npx tsc --noEmit 2>&1 | tail -10`

Expected: no new errors. (The two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may still be there.)

- [ ] **Step 4.3: Commit**

```bash
git add ui-app/src/api/standaloneDub.ts
git commit -m "feat(fe): standaloneDub API client

Four exports:
- StandaloneDubEntry: interface mirroring the BE Pydantic response
- postStandaloneDub: multipart upload (FormData, no Content-Type
  override — matches the importVersion pattern from sub-project 2)
- getStandaloneDubs / deleteStandaloneDub: list + delete
- getStandaloneDubUrl: helper for <a href=...> download anchors"
```

---

### Task 5: FE — DubStudio page + nav entry + route + tests

**Files:**
- Create: `ui-app/src/pages/DubStudio.tsx`
- Create: `ui-app/src/pages/__tests__/DubStudio.test.tsx`
- Modify: `ui-app/src/data/mockData.ts` (nav)
- Modify: `ui-app/src/App.tsx` (route)

- [ ] **Step 5.1: Add the nav entry**

Open `ui-app/src/data/mockData.ts`. Replace the `navItems` array:

```ts
export const navItems: readonly NavItem[] = [
  { icon: 'rocket_launch', label: 'Pipeline', path: '/' },
  { icon: 'movie_edit', label: 'Video Studio', path: '/videos' },
  { icon: 'graphic_eq', label: 'Dub Studio', path: '/dub-studio' },
  { icon: 'translate', label: 'Translation Profiles', path: '/profiles' },
  { icon: 'settings', label: 'Settings', path: '/settings' },
];
```

- [ ] **Step 5.2: Add the route**

Open `ui-app/src/App.tsx`. In the existing `<Routes>` block, add the new route after the `/videos/:videoId` entry:

```tsx
<Route path="/dub-studio" element={<DubStudioPage />} />
```

Add the matching import at the top of the file:

```tsx
import { DubStudioPage } from './pages/DubStudio';
```

- [ ] **Step 5.3: Write the failing tests for the page**

Create `ui-app/src/pages/__tests__/DubStudio.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { DubStudioPage } from '../DubStudio';

vi.mock('../../api/standaloneDub', () => ({
  postStandaloneDub: vi.fn(),
  getStandaloneDubs: vi.fn(),
  deleteStandaloneDub: vi.fn(),
  getStandaloneDubUrl: vi.fn((uuid: string) => `/api/standalone-dub/${uuid}.wav`),
}));

vi.mock('../../api/client', () => ({
  getTTSProviders: vi.fn().mockResolvedValue([{ id: 'google', name: 'Google' }]),
  getTTSVoices: vi.fn().mockResolvedValue([
    { name: 'vi-VN-Wavenet-A', language: 'vi', gender: 'female', provider: 'google' },
  ]),
  subscribeSSE: vi.fn(() => ({ close: vi.fn() })),
}));

vi.mock('../../utils/storage', () => ({
  loadApiKeys: vi.fn(() => ({ google: '', openai: '', anthropic: '', deepseek: '', elevenlabs: '' })),
  loadLLMPrefs: vi.fn(() => ({ backend: 'anthropic', model: 'claude-sonnet-4-20250514' })),
  storageGet: vi.fn(() => null),
  storageSet: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter>
      <DubStudioPage />
    </MemoryRouter>,
  );
}

describe('DubStudio', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders with empty recent list', async () => {
    const api = await import('../../api/standaloneDub');
    (api.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no recent dubs/i)).toBeInTheDocument();
    });
  });

  it('shows seeded recent rows', async () => {
    const api = await import('../../api/standaloneDub');
    (api.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValue([
      {
        uuid: 'abc',
        original_filename: 'episode-5.srt',
        provider: 'google',
        voice: 'vi-VN-Wavenet-A',
        language: 'vi',
        playback_speed: 1.5,
        enable_shortening: true,
        duration_seconds: 30,
        created_at: '2026-05-30T10:00:00+00:00',
        file_size_bytes: 1024,
      },
    ]);

    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/episode-5\.srt/i)).toBeInTheDocument();
    });
  });

  it('disables Generate until a file is picked', async () => {
    const api = await import('../../api/standaloneDub');
    (api.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValue([]);

    renderPage();
    await waitFor(() => {
      const btn = screen.getByRole('button', { name: /generate/i }) as HTMLButtonElement;
      expect(btn.disabled).toBe(true);
    });
  });

  it('deletes a row and refreshes the list', async () => {
    const api = await import('../../api/standaloneDub');
    (api.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      {
        uuid: 'todelete',
        original_filename: 'gone.srt',
        provider: 'google',
        voice: 'vi-VN-Wavenet-A',
        language: 'vi',
        playback_speed: 1.5,
        enable_shortening: true,
        duration_seconds: 30,
        created_at: '2026-05-30T10:00:00+00:00',
        file_size_bytes: 1024,
      },
    ]);
    (api.deleteStandaloneDub as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    (api.getStandaloneDubs as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);

    vi.stubGlobal('confirm', vi.fn(() => true));

    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/gone\.srt/i)).toBeInTheDocument();
    });

    const deleteBtn = screen.getByTitle(/delete/i);
    fireEvent.click(deleteBtn);

    await waitFor(() => {
      expect(api.deleteStandaloneDub).toHaveBeenCalledWith('todelete');
    });
  });
});
```

- [ ] **Step 5.4: Run — confirm fail**

Run: `cd ui-app && npx vitest run src/pages/__tests__/DubStudio.test.tsx 2>&1 | tail -10`

Expected: 4 FAIL with `Cannot find module '../DubStudio'`.

- [ ] **Step 5.5: Implement `ui-app/src/pages/DubStudio.tsx`**

Create the page. The layout: header → form → progress → recent dubs list. State management mirrors VideoDetail's TTS state (provider, voice, language, speed, shorten flag, API keys).

```tsx
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  postStandaloneDub,
  getStandaloneDubs,
  deleteStandaloneDub,
  getStandaloneDubUrl,
  type StandaloneDubEntry,
} from '../api/standaloneDub';
import {
  getTTSProviders, getTTSVoices, subscribeSSE,
} from '../api/client';
import type { TTSProviderInfo, VoiceInfo } from '../api/types';
import { loadApiKeys, loadLLMPrefs, storageGet, storageSet } from '../utils/storage';

const LANGUAGES = [
  { code: 'vi', label: 'Vietnamese' },
  { code: 'en', label: 'English' },
  { code: 'zh', label: 'Chinese' },
  { code: 'ja', label: 'Japanese' },
  { code: 'ko', label: 'Korean' },
  { code: 'es', label: 'Spanish' },
  { code: 'fr', label: 'French' },
  { code: 'de', label: 'German' },
  { code: 'ru', label: 'Russian' },
  { code: 'pt', label: 'Portuguese' },
  { code: 'it', label: 'Italian' },
  { code: 'th', label: 'Thai' },
  { code: 'id', label: 'Indonesian' },
];

export function DubStudioPage() {
  // ── Form state ──
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [provider, setProvider] = useState(() => storageGet('dub_studio_provider') || 'google');
  const [voice, setVoice] = useState('');
  const [language, setLanguage] = useState(() => storageGet('dub_studio_language') || 'vi');
  const [playbackSpeed, setPlaybackSpeed] = useState(() => {
    const v = parseFloat(storageGet('dub_studio_playback_speed') || '');
    return Number.isFinite(v) && v >= 1.0 && v <= 2.0 ? v : 1.5;
  });
  const [enableShortening, setEnableShortening] = useState(() => {
    const v = storageGet('dub_studio_enable_shortening');
    return v === null ? true : v === 'true';
  });

  // Persist picker changes
  useEffect(() => storageSet('dub_studio_provider', provider), [provider]);
  useEffect(() => storageSet('dub_studio_language', language), [language]);
  useEffect(() => storageSet('dub_studio_playback_speed', String(playbackSpeed)), [playbackSpeed]);
  useEffect(() => storageSet('dub_studio_enable_shortening', String(enableShortening)), [enableShortening]);

  // ── Providers + voices (lazy load) ──
  const [providers, setProviders] = useState<TTSProviderInfo[]>([]);
  const [voices, setVoices] = useState<VoiceInfo[]>([]);

  useEffect(() => {
    getTTSProviders().then(setProviders).catch(() => setProviders([]));
  }, []);

  useEffect(() => {
    if (!provider) return;
    const apiKey = loadApiKeys()[provider as keyof ReturnType<typeof loadApiKeys>] || undefined;
    getTTSVoices(language, provider, apiKey)
      .then((vs) => {
        setVoices(vs);
        if (vs.length > 0) {
          const saved = storageGet(`dub_studio_voice_id_${provider}`) || '';
          const valid = vs.some((v) => v.name === saved);
          setVoice(valid ? saved : vs[0].name);
        }
      })
      .catch(() => setVoices([]));
  }, [provider, language]);

  useEffect(() => {
    if (voice) storageSet(`dub_studio_voice_id_${provider}`, voice);
  }, [voice, provider]);

  // ── Generation state ──
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState({ pct: 0, message: '' });
  const [error, setError] = useState('');
  const sseRef = useRef<{ close: () => void } | null>(null);

  // ── Recent dubs ──
  const [recent, setRecent] = useState<StandaloneDubEntry[]>([]);
  const [playingUuid, setPlayingUuid] = useState<string | null>(null);

  const refreshRecent = useCallback(async () => {
    try {
      const list = await getStandaloneDubs();
      setRecent(list);
    } catch {
      setRecent([]);
    }
  }, []);

  useEffect(() => { refreshRecent(); }, [refreshRecent]);

  // ── Submit ──
  const handleGenerate = useCallback(async () => {
    if (!selectedFile || !voice || generating) return;
    setGenerating(true);
    setError('');
    setProgress({ pct: 0, message: 'Submitting...' });
    try {
      const apiKey = loadApiKeys()[provider as keyof ReturnType<typeof loadApiKeys>] || undefined;
      const llmPrefs = loadLLMPrefs();
      const llmApiKey = loadApiKeys()[llmPrefs.backend as keyof ReturnType<typeof loadApiKeys>] || undefined;

      const { task_id } = await postStandaloneDub({
        file: selectedFile,
        provider,
        voice,
        language,
        playbackSpeed,
        enableShortening,
        apiKey,
        llmApiKey,
        llmBackend: llmPrefs.backend,
      });

      sseRef.current = subscribeSSE(task_id, (event, data) => {
        if (event === 'progress' && data) {
          setProgress({
            pct: typeof data.progress === 'number' ? data.progress : 0,
            message: typeof data.message === 'string' ? data.message : '',
          });
        } else if (event === 'complete') {
          setGenerating(false);
          setProgress({ pct: 1, message: 'Complete' });
          refreshRecent();
          sseRef.current?.close();
          sseRef.current = null;
        } else if (event === 'error') {
          setGenerating(false);
          setError(typeof data?.message === 'string' ? data.message : 'Generation failed');
          sseRef.current?.close();
          sseRef.current = null;
        }
      });
    } catch (e) {
      setGenerating(false);
      setError(e instanceof Error ? e.message : 'Submit failed');
    }
  }, [selectedFile, voice, generating, provider, language, playbackSpeed, enableShortening, refreshRecent]);

  // ── Delete ──
  const handleDelete = useCallback(async (entry: StandaloneDubEntry) => {
    if (!confirm(`Delete "${entry.original_filename}"?`)) return;
    try {
      await deleteStandaloneDub(entry.uuid);
      refreshRecent();
    } catch { /* silent */ }
  }, [refreshRecent]);

  // ── Render ──
  const canGenerate = !!selectedFile && !!voice && !generating;
  const generateLabel = generating ? `Generating... ${Math.round(progress.pct * 100)}%` : 'Generate Dub';

  return (
    <div className="flex-1 overflow-y-auto p-6 max-w-3xl mx-auto">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-on-surface mb-1">Dub Studio</h1>
        <p className="text-xs text-on-surface-variant">
          Generate a dub WAV from any SRT file. No video required.
        </p>
      </div>

      {/* Generate form */}
      <div className="bg-surface-container-lowest border border-outline-variant/15 rounded-xl p-4 space-y-4 mb-6">
        {/* File picker */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-1.5 block">
            SRT file
          </label>
          <input
            type="file"
            accept=".srt"
            onChange={(e) => setSelectedFile(e.target.files?.[0] ?? null)}
            className="text-xs file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border-0 file:bg-surface-container-highest file:text-on-surface file:cursor-pointer hover:file:bg-surface-container-high"
          />
          {selectedFile && (
            <div className="mt-2 inline-flex items-center gap-1.5 px-2 py-1 bg-primary/10 text-primary text-[11px] rounded">
              <span className="material-symbols-outlined text-xs">description</span>
              {selectedFile.name}
            </div>
          )}
        </div>

        {/* Provider + Language + Voice */}
        <div className="grid grid-cols-3 gap-3">
          <div>
            <label className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-1 block">Provider</label>
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              className="w-full text-xs bg-surface-container-highest border border-outline-variant/20 rounded px-2 py-1.5 text-on-surface"
            >
              {providers.length === 0 && <option value={provider}>{provider}</option>}
              {providers.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-1 block">Language</label>
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              className="w-full text-xs bg-surface-container-highest border border-outline-variant/20 rounded px-2 py-1.5 text-on-surface"
            >
              {LANGUAGES.map((l) => (
                <option key={l.code} value={l.code}>{l.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-1 block">Voice</label>
            <select
              value={voice}
              onChange={(e) => setVoice(e.target.value)}
              disabled={voices.length === 0}
              className="w-full text-xs bg-surface-container-highest border border-outline-variant/20 rounded px-2 py-1.5 text-on-surface disabled:opacity-50"
            >
              {voices.length === 0 && <option>Loading...</option>}
              {voices.map((v) => (
                <option key={v.name} value={v.name}>{v.name}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Playback speed */}
        <div>
          <label className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-1 block">
            Playback Speed: {playbackSpeed.toFixed(2)}×
          </label>
          <input
            type="range"
            min={1.0}
            max={2.0}
            step={0.05}
            value={playbackSpeed}
            onChange={(e) => setPlaybackSpeed(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>

        {/* Shorten toggle */}
        <label className="flex items-start gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={enableShortening}
            onChange={(e) => setEnableShortening(e.target.checked)}
            className="mt-0.5 accent-primary"
          />
          <div className="flex-1">
            <div className="text-xs font-medium text-on-surface">Shorten dub to fit timeline</div>
            <div className="text-[10px] text-on-surface-variant mt-0.5 leading-snug">
              Uses the LLM to compress text when a sentence would overrun. Uncheck to keep
              the original text — clips may overrun.
            </div>
          </div>
        </label>

        {/* Generate */}
        <button
          onClick={handleGenerate}
          disabled={!canGenerate}
          className="w-full px-4 py-2.5 rounded-lg bg-primary text-on-primary text-sm font-medium hover:shadow-lg disabled:opacity-50 disabled:cursor-not-allowed transition-all"
        >
          {generateLabel}
        </button>

        {generating && progress.message && (
          <div className="text-[11px] text-on-surface-variant text-center">{progress.message}</div>
        )}
        {error && (
          <div className="text-[11px] text-red-400 text-center">{error}</div>
        )}
      </div>

      {/* Recent dubs */}
      <div>
        <h2 className="text-[10px] uppercase tracking-wider text-on-surface-variant mb-2">
          Recent dubs ({recent.length})
        </h2>
        {recent.length === 0 ? (
          <div className="text-center text-xs text-on-surface-variant py-8 bg-surface-container-lowest rounded-lg">
            No recent dubs. Generate one above to get started.
          </div>
        ) : (
          <div className="space-y-1.5">
            {recent.map((entry) => {
              const isPlaying = playingUuid === entry.uuid;
              const sizeMb = (entry.file_size_bytes / 1024 / 1024).toFixed(1);
              const ago = (() => {
                const diff = Date.now() / 1000 - new Date(entry.created_at).getTime() / 1000;
                if (diff < 60) return 'just now';
                if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
                if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
                return `${Math.floor(diff / 86400)}d ago`;
              })();
              const downloadUrl = getStandaloneDubUrl(entry.uuid);

              return (
                <div key={entry.uuid} className="flex items-center gap-2 px-3 py-2 bg-surface-container-lowest rounded-lg group">
                  <button
                    onClick={() => setPlayingUuid(isPlaying ? null : entry.uuid)}
                    className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 ${
                      isPlaying ? 'bg-primary text-on-primary' : 'bg-surface-container-high text-on-surface-variant hover:bg-primary/20'
                    }`}
                  >
                    <span className="material-symbols-outlined text-sm">{isPlaying ? 'stop' : 'play_arrow'}</span>
                  </button>
                  {isPlaying && (
                    <audio
                      src={downloadUrl}
                      autoPlay
                      onEnded={() => setPlayingUuid(null)}
                      className="hidden"
                    />
                  )}
                  <div className="flex-1 min-w-0 flex items-center gap-1.5">
                    <span className="shrink-0 bg-primary/15 text-primary text-[9px] font-semibold px-1.5 py-0.5 rounded truncate max-w-[140px]" title={entry.original_filename}>
                      {entry.original_filename}
                    </span>
                    <span className="text-[11px] font-semibold text-on-surface truncate">{entry.voice}</span>
                    <span className="text-[9px] text-zinc-500 shrink-0">
                      {entry.provider} · {entry.language} · {sizeMb}MB
                    </span>
                  </div>
                  <span className="text-[9px] font-mono text-zinc-600">{ago}</span>
                  <a
                    href={downloadUrl}
                    download={entry.original_filename.replace(/\.srt$/i, '.wav')}
                    className="p-1 rounded text-zinc-600 hover:text-primary hover:bg-primary/10"
                    title="Download dub"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <span className="material-symbols-outlined text-sm">download</span>
                  </a>
                  <button
                    onClick={() => handleDelete(entry)}
                    className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-red-500/20 text-zinc-600 hover:text-red-400 transition-all"
                    title="Delete dub"
                  >
                    <span className="material-symbols-outlined text-sm">delete</span>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 5.6: Run — confirm tests pass**

Run: `cd ui-app && npx vitest run src/pages/__tests__/DubStudio.test.tsx 2>&1 | tail -10`

Expected: 4 passed.

- [ ] **Step 5.7: Run full FE suite + build**

```bash
cd ui-app && npx vitest run 2>&1 | tail -5
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: vitest all green (existing + 4 new). Build succeeds (modulo the 2 pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).

- [ ] **Step 5.8: Commit**

```bash
git add ui-app/src/pages/DubStudio.tsx ui-app/src/pages/__tests__/DubStudio.test.tsx ui-app/src/App.tsx ui-app/src/data/mockData.ts
git commit -m "feat(fe): Dub Studio page + nav entry + route

New top-level page at /dub-studio. File picker for the SRT, then the
same TTS picker controls as DubTab (provider/language/voice/playback
speed/shorten-toggle). Generate button submits via postStandaloneDub
and listens on the existing /api/tasks/{task_id} SSE for progress.
Recent dubs section renders the existing audio-library row shape with
per-row play (inline <audio>) + download (<a download>) + delete.

State persistence: dub_studio_* localStorage keys for provider,
language, playback_speed, enable_shortening, voice_id_{provider} —
independent of the video-flow keys so the two surfaces don't collide.

Nav entry inserted between 'Video Studio' and 'Translation Profiles'
with the graphic_eq Material icon. Route registered in App.tsx.

4 vitest tests cover empty recent state, seeded row rendering,
Generate-disabled-without-file guard, and delete flow."
```

---

### Task 6: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 6.1: CHANGELOG entry**

In `CHANGELOG.md`, find `## [Unreleased]`. Find the existing `### Added` subsection. Add this entry at the top of `Added`:

```markdown
### Added
- **Dub Studio: standalone SRT → Dub tool.** New top-level page at `/dub-studio` (nav entry between Video Studio and Translation Profiles). Upload any SRT, pick provider/voice/language/playback-speed/shorten-toggle, generate a dub WAV, download it. Not tied to any video — purely SRT-in, WAV-out. BE: new `src/api/standalone_dub.py` (IO + dataclass), `src/api/routers/standalone_dub.py` (POST multipart + GET list + DELETE + WAV download), `TaskManager.run_standalone_dub` orchestrator. Reuses `assembler.generate_full_track` directly (no source-video dependency). FE: new `DubStudio` page + `standaloneDub` API client. Storage: `data/standalone_dubs/{uuid}.wav` + `{uuid}.json` metadata sidecar. SSE progress via the existing `subscribeSSE` machinery. 14 new BE tests (6 IO helpers + 2 orchestrator + 6 router) + 4 new FE vitest tests. Sub-project 3 of 3 in the refocused app — completes the post-refocus shape.
```

- [ ] **Step 6.2: README progress section**

Open `README.md`. Find the "SRT Import in Video Flow (2026-05-30)" subsection. Insert this new subsection immediately after its `---` separator (before the next section):

```markdown
### Standalone SRT → Dub Studio (2026-05-30)

> Sub-project 3 of 3 in the refocused app. See [`docs/superpowers/specs/2026-05-30-standalone-dub-studio-design.md`](docs/superpowers/specs/2026-05-30-standalone-dub-studio-design.md) and [`docs/superpowers/plans/2026-05-30-standalone-dub-studio.md`](docs/superpowers/plans/2026-05-30-standalone-dub-studio.md).

- [x] **Task 1** — BE `src/api/standalone_dub.py`: `StandaloneDubEntry` dataclass, `list_dubs`, `delete_dub`, `wav_path`, `save_meta`. 6 unit tests.
- [x] **Task 2** — BE `TaskManager.run_standalone_dub` orchestrator. Parses SRT bytes via `parse_srt`, derives `video_duration = max(end) + 1s`, builds provider + LLM translator, calls `assembler.generate_full_track`, writes metadata sidecar on success. 2 tests (happy + invalid SRT).
- [x] **Task 3** — BE router at `/api/standalone-dub`: POST (multipart), GET list, DELETE, GET `{uuid}.wav` download. 6 endpoint tests.
- [x] **Task 4** — FE `standaloneDub.ts` API client. Same multipart `FormData` pattern as sub-project 2's `importVersion`.
- [x] **Task 5** — FE `DubStudio` page + nav entry + `/dub-studio` route. 4 vitest tests covering empty state, seeded rows, Generate gating, and delete flow.
- [x] **Task 6** — CHANGELOG + README updates.

**Refocus complete.** The 3-part post-refocus app: download/transcribe/translate pipeline → per-video editor with SRT export and import + dub generation → standalone SRT→Dub tool for SRTs that don't have a video binding.
```

- [ ] **Step 6.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(standalone-dub): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10`

Expected: green. ~14 more tests than the prior baseline.

- [ ] **Step F.2: Full FE suite**

Run: `cd ui-app && npx vitest run 2>&1 | tail -10`

Expected: green. ~4 more tests than the prior baseline.

- [ ] **Step F.3: FE build**

Run: `cd ui-app && npm run build 2>&1 | tail -10`

Expected: succeeds (modulo the 2 pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).

- [ ] **Step F.4: BE lint**

Run: `ruff check src/ tests/ 2>&1 | tail -5`

Expected: no new errors on the touched files.

- [ ] **Step F.5: Manual smoke (after merge)**

1. Click "Dub Studio" in the sidebar → page loads with empty "Recent dubs" placeholder.
2. Pick a `.srt` file from disk → filename chip shows; Generate button enables once a voice is picked.
3. Click Generate → progress bar updates → completes in ~30s for a short SRT → new entry appears in Recent.
4. Click play on the new entry → audio plays inline. Click download → browser downloads the WAV.
5. Refresh the page → entry persists.
6. Click delete → confirm → row disappears; files gone from `data/standalone_dubs/`.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: each spec section maps to a task — IO module (T1), orchestrator (T2), router (T3), FE client (T4), page + nav + route (T5), docs (T6).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type names consistent: `StandaloneDubEntry` (BE dataclass + FE TS interface), `run_standalone_dub` (BE method), `postStandaloneDub` (FE client), `dub_studio_*` (localStorage key prefix).
- [ ] localStorage key prefix is `dub_studio_*` everywhere — independent of `tts_*` so the video-flow and standalone-flow don't share state.
- [ ] No AI-attribution strings in any commit message.
- [ ] Branch stays `feature/standalone-dub-studio`; no new branches.
- [ ] Router registered in `src/api/__init__.py`.
- [ ] Route + nav entry registered in `App.tsx` and `mockData.ts` respectively.
