"""Tests for the SRT-serving endpoints — preference for dubsync.srt over the
legacy SRT when both exist."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _write_srt(path: Path, text: str) -> None:
    """Write a one-segment SRT containing the given text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"1\n00:00:00,000 --> 00:00:01,000\n{text}\n\n",
        encoding="utf-8",
    )


def _make_client(tmp_path, monkeypatch):
    """Build a FastAPI TestClient with data_dir pointing into tmp_path."""
    monkeypatch.chdir(tmp_path)
    from src.api import create_app
    from src.api.deps import get_task_manager

    app = create_app()
    tm = get_task_manager()
    from src.api.models import VideoResponse
    tm.video_index["vid001"] = VideoResponse(
        video_id="vid001",
        title="t", duration=0.0, source_url="",
        thumbnail="", has_srt=True, srt_languages=["vi"],
        status="done",
    )
    return TestClient(app)


class TestGetSrtDubsyncPreference:
    def test_get_srt_prefers_dubsync_when_present(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "original text")
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt", "dubsync text")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_dubsync"] is True
        assert any("dubsync" in seg["text"] for seg in body["segments"])

    def test_get_srt_falls_back_to_legacy_when_no_dubsync(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy only")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 200
        body = resp.json()
        assert body["is_dubsync"] is False
        assert any("legacy" in seg["text"] for seg in body["segments"])

    def test_get_srt_404_when_neither_file_exists(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        resp = client.get("/api/videos/vid001/srt?language=vi")
        assert resp.status_code == 404


class TestDownloadSrtDubsyncPreference:
    def test_download_serves_dubsync_with_clean_filename(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "original text")
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.dubsync.srt", "dubsync text")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt/download?language=vi")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        assert "vid001_vi.srt" in cd
        assert "dubsync" not in cd
        assert "dubsync text" in resp.text

    def test_download_falls_back_to_legacy_when_no_dubsync(self, tmp_path, monkeypatch):
        _write_srt(tmp_path / "data" / "srt" / "vid001_vi.srt", "legacy only")
        client = _make_client(tmp_path, monkeypatch)

        resp = client.get("/api/videos/vid001/srt/download?language=vi")
        assert resp.status_code == 200
        assert "legacy only" in resp.text
