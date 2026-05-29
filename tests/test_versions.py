"""Tests for the subtitle versions module."""

from __future__ import annotations

import json
from datetime import datetime, timezone

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

        created = datetime(2026, 5, 29, 10, 0, 0, tzinfo=timezone.utc)
        entries = [
            VersionEntry(id="v1", name="migrated", created_at=created),
        ]
        save_versions("vid1", "vi", entries)
        out = load_versions("vid1", "vi")
        assert len(out) == 1
        assert out[0].id == "v1"
        assert out[0].name == "migrated"
        assert out[0].created_at == created  # timezone-aware round trip

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


class TestSnapshotWorkingDraft:
    def test_happy_path_creates_v1(self, srt_dir):
        """Working draft exists; snapshot copies it to v1 and appends entry."""
        from src.api.versions import (
            load_versions,
            snapshot_working_draft,
        )

        # Seed working draft.
        wd = srt_dir / "vid1_vi.srt"
        wd.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n")

        entry = snapshot_working_draft("vid1", "vi", name="first")
        assert entry.id == "v1"
        assert entry.name == "first"
        # Snapshot SRT exists with same content.
        snap = srt_dir / "vid1_vi.v1.srt"
        assert snap.exists()
        assert snap.read_text() == wd.read_text()
        # versions.json has the new entry.
        listing = load_versions("vid1", "vi")
        assert len(listing) == 1
        assert listing[0].id == "v1"

    def test_subsequent_call_allocates_v2(self, srt_dir):
        from src.api.versions import snapshot_working_draft

        (srt_dir / "vid1_vi.srt").write_text("x")
        snapshot_working_draft("vid1", "vi", None)
        entry = snapshot_working_draft("vid1", "vi", None)
        assert entry.id == "v2"

    def test_name_can_be_none(self, srt_dir):
        from src.api.versions import snapshot_working_draft

        (srt_dir / "vid1_vi.srt").write_text("x")
        entry = snapshot_working_draft("vid1", "vi", None)
        assert entry.name is None

    def test_raises_when_working_draft_missing(self, srt_dir):
        from src.api.versions import snapshot_working_draft

        with pytest.raises(FileNotFoundError):
            snapshot_working_draft("ghost", "vi", None)


@pytest.fixture
def tts_dir(tmp_path, monkeypatch):
    d = tmp_path / "tts"
    d.mkdir()
    monkeypatch.setattr("src.api.versions.TTS_DIR", d)
    return d


class TestDeleteVersion:
    def test_deletes_snapshot_srt_and_entry(self, srt_dir, tts_dir):
        from src.api.versions import (
            delete_version,
            load_versions,
            snapshot_working_draft,
        )

        (srt_dir / "vid1_vi.srt").write_text("x")
        snapshot_working_draft("vid1", "vi", None)
        snap = srt_dir / "vid1_vi.v1.srt"
        assert snap.exists()

        ok = delete_version("vid1", "vi", "v1")
        assert ok is True
        assert not snap.exists()
        assert load_versions("vid1", "vi") == []

    def test_cascades_to_dub_wavs_for_that_version(self, srt_dir, tts_dir):
        from src.api.versions import delete_version, snapshot_working_draft

        (srt_dir / "vid1_vi.srt").write_text("x")
        snapshot_working_draft("vid1", "vi", None)
        # Seed dub WAVs.
        (tts_dir / "vid1_vi_v1_google_wavenet-A.wav").write_bytes(b"RIFF")
        (tts_dir / "vid1_vi_v1_openai_alloy.wav").write_bytes(b"RIFF")
        # Seed an unrelated WAV that must NOT be deleted.
        (tts_dir / "vid1_vi_v2_google_wavenet-A.wav").write_bytes(b"RIFF")

        delete_version("vid1", "vi", "v1")
        assert not (tts_dir / "vid1_vi_v1_google_wavenet-A.wav").exists()
        assert not (tts_dir / "vid1_vi_v1_openai_alloy.wav").exists()
        # v2 file untouched.
        assert (tts_dir / "vid1_vi_v2_google_wavenet-A.wav").exists()

    def test_returns_false_for_unknown_version(self, srt_dir, tts_dir):
        from src.api.versions import delete_version

        # No versions.json at all → False.
        assert delete_version("ghost", "vi", "v1") is False
