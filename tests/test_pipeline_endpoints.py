"""Tests for /api/pipeline/{task_id} stage_progress derivation."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_client(monkeypatch, tmp_path):
    """Build a TestClient and inject a stub task into the task manager."""
    monkeypatch.chdir(tmp_path)
    from src.api import create_app
    from src.api.deps import get_task_manager

    app = create_app()
    tm = get_task_manager()
    # Inject a stub task — minimum fields needed for the GET handler.
    from src.api.task_manager import Task
    task = Task(task_id="t1", task_type="full_pipeline")
    task.status = "running"
    task.current_stage = "transcribe"
    task.progress = 0.325        # halfway through transcribe (0.20-0.45 range)
    task.message = "Running OCR on frame 100/200"
    task.video_id = None         # skip the on-disk PipelineState enrich path
    tm.tasks["t1"] = task
    return TestClient(app)


class TestStageProgressDerivation:
    def test_transcribe_midpoint_maps_to_half(self):
        from src.api.routers.pipeline import _stage_progress
        result = _stage_progress("transcribe", 0.325)
        assert abs(result - 0.5) < 1e-6

    def test_tts_midpoint_maps_to_half(self):
        from src.api.routers.pipeline import _stage_progress
        result = _stage_progress("tts", 0.65)
        assert abs(result - 0.5) < 1e-6

    def test_overall_at_stage_lo_maps_to_zero(self):
        from src.api.routers.pipeline import _stage_progress
        assert _stage_progress("transcribe", 0.20) == 0.0

    def test_overall_at_stage_hi_maps_to_one(self):
        from src.api.routers.pipeline import _stage_progress
        assert _stage_progress("transcribe", 0.45) == 1.0

    def test_clamps_overshoot_to_one(self):
        """If overall exceeds the stage's hi (unexpected but defensive),
        the returned per-stage value clamps at 1.0."""
        from src.api.routers.pipeline import _stage_progress
        assert _stage_progress("download", 0.50) == 1.0

    def test_clamps_undershoot_to_zero(self):
        from src.api.routers.pipeline import _stage_progress
        assert _stage_progress("process", 0.50) == 0.0

    def test_unknown_stage_returns_zero(self):
        from src.api.routers.pipeline import _stage_progress
        assert _stage_progress("skip", 0.5) == 0.0
        assert _stage_progress("", 0.5) == 0.0


class TestGetPipelineStatusIncludesStageProgress:
    def test_stage_progress_field_present(self, tmp_path, monkeypatch):
        client = _make_client(monkeypatch, tmp_path)
        resp = client.get("/api/pipeline/t1")
        assert resp.status_code == 200
        body = resp.json()
        assert "stage_progress" in body, f"response body missing stage_progress: {body!r}"
        # Stub task has current_stage='transcribe', progress=0.325 → stage_progress ≈ 0.5
        assert abs(body["stage_progress"] - 0.5) < 1e-6


class TestVideoResponseIncludesDubStatus:
    def test_video_response_includes_dub_status_field(self, tmp_path, monkeypatch):
        """GET /api/videos response always includes dub_status (may be empty)."""
        monkeypatch.chdir(tmp_path)

        # Create a minimal raw video entry so the index scan finds something
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True)
        # Write a stub mp4 (content doesn't matter for the index scan path —
        # extract_metadata_from_file is mocked out by the fake file size check)
        mp4 = raw_dir / "testvid001.mp4"
        mp4.write_bytes(b"\x00" * 1024)

        from src.api import create_app
        from src.api.deps import get_task_manager

        app = create_app()
        tm = get_task_manager()

        from src.api.models import VideoResponse
        tm.video_index["testvid001"] = VideoResponse(
            video_id="testvid001",
            title="Test Video",
            file_path=str(mp4),
            dub_status=[],
        )

        client = TestClient(app)
        r = client.get("/api/videos")
        assert r.status_code == 200
        body = r.json()
        assert body.get("videos"), "Expected at least one video in response"
        for video in body["videos"]:
            assert "dub_status" in video, f"dub_status missing from video: {video!r}"
            assert isinstance(video["dub_status"], list)


class TestSrtLangsDeduplicatesDubsyncFiles:
    async def test_dubsync_srt_not_listed_as_separate_language(self, tmp_path, monkeypatch):
        """srt_languages deduplicates: vi.srt + vi.dubsync.srt → only 'vi' in list."""
        monkeypatch.chdir(tmp_path)

        # Set up a raw video so scan_existing_videos picks it up
        raw_dir = tmp_path / "data" / "raw"
        raw_dir.mkdir(parents=True)
        (raw_dir / "myvid.mp4").write_bytes(b"\x00" * 1024)

        # Two SRT files for the same language: plain + dubsync variant
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        (srt_dir / "myvid_vi.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nhello\n", encoding="utf-8"
        )
        (srt_dir / "myvid_vi.dubsync.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nhello dubsync\n", encoding="utf-8"
        )
        (srt_dir / "myvid_zh.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\n你好\n", encoding="utf-8"
        )

        from src.api.task_manager import TaskManager

        tm = TaskManager()
        await tm.scan_existing_videos()

        video = tm.video_index.get("myvid")
        assert video is not None, "scan_existing_videos should have indexed myvid"
        assert video.srt_languages == ["vi", "zh"], (
            f"Expected deduped ['vi', 'zh'], got {video.srt_languages}"
        )
