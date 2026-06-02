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
    # Pre-seed an empty versions.json so ensure_migrated treats this as a
    # fresh (already-migrated) video, not a legacy one to auto-snapshot.
    (srt_dir / "vidA_vi.versions.json").write_text("[]")

    from src.api import create_app  # noqa
    return TestClient(create_app()), srt_dir, tts_dir


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


_VALID_SRT_BYTES = (
    b"1\n00:00:00,000 --> 00:00:01,000\nhello\n\n"
    b"2\n00:00:02,000 --> 00:00:03,000\nworld\n\n"
)


class TestImportAsVersion:
    def test_import_creates_next_version(self, srt_dir):
        from src.api.versions import import_as_version, load_versions, save_versions

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


class TestImportSegmentsAsVersion:
    """import_segments_as_version skips the bytes round-trip — useful for
    in-process callers (like the TTS runner) that already have parsed
    segments in hand."""

    def test_creates_next_version_from_segments(self, tmp_path, monkeypatch):
        """A 2-segment list lands as v1 with the expected file content + entry."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        # Seed an already-migrated versions.json so ensure_migrated is no-op.
        (srt_dir / "vidA_vi.versions.json").write_text("[]")

        from src.api.versions import import_segments_as_version, load_versions

        segments = [
            {"index": 1, "start": 0.0, "end": 1.5, "text": "first"},
            {"index": 2, "start": 1.5, "end": 3.0, "text": "second"},
        ]
        entry = import_segments_as_version(
            "vidA", "vi", segments, name="dub: google/voiceA"
        )

        assert entry.id == "v1"
        assert entry.name == "dub: google/voiceA"

        # File exists with the expected SRT content.
        v1_path = srt_dir / "vidA_vi.v1.srt"
        assert v1_path.exists()
        body = v1_path.read_text(encoding="utf-8")
        assert "first" in body
        assert "second" in body
        assert "00:00:00,000 --> 00:00:01,500" in body
        assert "00:00:01,500 --> 00:00:03,000" in body

        # versions.json has the entry.
        loaded = load_versions("vidA", "vi")
        assert len(loaded) == 1
        assert loaded[0].id == "v1"

    def test_increments_when_versions_already_exist(self, tmp_path, monkeypatch):
        """Existing v1/v2 → new entry is v3."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        import json
        (srt_dir / "vidB_en.versions.json").write_text(json.dumps([
            {"id": "v1", "name": None, "created_at": "2026-05-30T00:00:00+00:00"},
            {"id": "v2", "name": "edit-1", "created_at": "2026-05-30T01:00:00+00:00"},
        ]))

        from src.api.versions import import_segments_as_version

        entry = import_segments_as_version(
            "vidB", "en",
            [{"index": 1, "start": 0.0, "end": 1.0, "text": "hi"}],
            name=None,
        )
        assert entry.id == "v3"
        assert entry.name is None

    def test_calls_ensure_migrated_if_versions_json_missing(
        self, tmp_path, monkeypatch
    ):
        """With no versions.json and no legacy SRTs, ensure_migrated writes
        an empty versions.json — then the new entry lands as v1."""
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        tts_dir = tmp_path / "tts"
        tts_dir.mkdir()
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)

        from src.api.versions import import_segments_as_version

        entry = import_segments_as_version(
            "vidC", "vi",
            [{"index": 1, "start": 0.0, "end": 1.0, "text": "ok"}],
            name="dub: x/y",
        )
        assert entry.id == "v1"
        assert (srt_dir / "vidC_vi.versions.json").exists()
        assert (srt_dir / "vidC_vi.v1.srt").exists()
