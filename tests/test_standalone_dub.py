"""Tests for the standalone-dub module."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def standalone_dir(tmp_path, monkeypatch):
    """Redirect data/standalone_dubs to a tmp dir for the test."""
    d = tmp_path / "standalone_dubs"
    d.mkdir()
    monkeypatch.setattr("src.api.standalone_dub.STANDALONE_DIR", d)
    return d


def _seed_entry(
    standalone_dir,
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
