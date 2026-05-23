"""Tests for GET /api/videos/{id}/preview-mix.

Full end-to-end coverage requires ffmpeg + real media. These tests pin the
404 paths (missing video / missing dub WAV) — the success path is covered
by manual QA.
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_client(tmp_path, monkeypatch, video_id: str = "vid001", register: bool = True):
    """Build a FastAPI TestClient with data_dir pointing into tmp_path."""
    monkeypatch.chdir(tmp_path)
    from src.api import create_app
    from src.api.deps import get_task_manager
    from src.api.models import VideoResponse

    app = create_app()
    tm = get_task_manager()
    tm.video_index.clear()
    tm.tasks.clear()
    if register:
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{video_id}.mp4"
        raw_path.write_bytes(b"\x00" * 16)  # placeholder; we don't run ffmpeg
        tm.video_index[video_id] = VideoResponse(
            video_id=video_id,
            title="t", duration=10.0, source_url="",
            thumbnail="", has_srt=True, srt_languages=["vi"],
            status="dubbed",
            file_path=str(raw_path),
        )
    return TestClient(app)


class TestPreviewMixEndpoint:
    def test_missing_video_returns_404(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch, register=False)
        r = client.get("/api/videos/nonexistent/preview-mix?language=vi")
        assert r.status_code == 404

    def test_missing_dub_returns_404(self, tmp_path, monkeypatch):
        """Registered video but no dub WAV on disk → 404."""
        client = _make_client(tmp_path, monkeypatch)
        r = client.get("/api/videos/vid001/preview-mix?language=vi")
        assert r.status_code == 404
        assert "dub" in r.json().get("detail", "").lower()
