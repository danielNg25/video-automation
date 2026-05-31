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
    from src.api import create_app
    from src.api.deps import get_task_manager

    app = create_app()
    tm = get_task_manager()
    tm.video_index["vidX"] = type("V", (), {
        "video_id": "vidX",
        "file_path": str(tmp_path / "vidX.mp4"),
        "title": "x",
        "status": "ready",
    })()
    # Seed an already-migrated versions.json so ensure_migrated is a no-op.
    (srt_dir / "vidX_vi.versions.json").write_text("[]")
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


class TestPutSrtAcceptsVersion:
    def test_put_without_version_writes_working_draft(self, client):
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

    def test_put_with_version_v1_overwrites_snapshot_in_place(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        _seed_srt(srt_dir, "vidX_vi.v1.srt", _V1_SRT)
        r = c.put(
            "/api/videos/vidX/srt",
            json={
                "language": "vi",
                "version": "v1",
                "segments": [{
                    "id": 1,
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:02,000",
                    "text": "edited v1",
                }],
            },
        )
        assert r.status_code == 200
        # v1 was rewritten.
        assert "edited v1" in (srt_dir / "vidX_vi.v1.srt").read_text()
        # Working draft untouched.
        assert "working draft" in (srt_dir / "vidX_vi.srt").read_text()

    def test_put_with_unknown_version_returns_404(self, client):
        c, srt_dir = client
        _seed_srt(srt_dir, "vidX_vi.srt", _SAMPLE_SRT)
        # No v99 file exists.
        r = c.put(
            "/api/videos/vidX/srt",
            json={
                "language": "vi",
                "version": "v99",
                "segments": [{
                    "id": 1,
                    "startTime": "00:00:00,000",
                    "endTime": "00:00:02,000",
                    "text": "should not land",
                }],
            },
        )
        assert r.status_code == 404
        # Nothing was created (the endpoint refused before write).
        assert not (srt_dir / "vidX_vi.v99.srt").exists()
