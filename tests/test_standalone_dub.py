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
