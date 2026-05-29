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
