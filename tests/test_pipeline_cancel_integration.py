"""Integration: cancelling a running task kills the subprocess + cleans up."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest


@pytest.mark.integration
async def test_cancel_kills_running_subprocess():
    """run_subprocess_tracked + cancel_task end-to-end with a real sleep."""
    from src.api.task_manager import TaskManager
    tm = TaskManager()
    task = tm.create_task("test")

    async def long_subprocess():
        # `sleep 30` simulates a long ffmpeg encode.
        await tm.run_subprocess_tracked(task.task_id, ["sleep", "30"])
        return "completed"

    task._asyncio_task = asyncio.create_task(long_subprocess())
    await asyncio.sleep(0.2)  # let the subprocess actually start
    assert task._running_subprocess is not None
    assert task._running_subprocess.poll() is None  # still running

    # Cancel — should take well under 5s.
    start = time.monotonic()
    result = await tm.cancel_task(task.task_id)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"cancel took {elapsed:.2f}s — too slow"
    assert result["status"] == "cancelled"
    assert task.status == "cancelled"


@pytest.mark.integration
async def test_cancel_with_video_id_runs_delete_video(tmp_path, monkeypatch):
    """End-to-end: cancel a task with a video_id → delete_video fires →
    per-video files are removed."""
    from src.api.task_manager import TaskManager
    tm = TaskManager()

    # Lay out a fake video to verify it gets cleaned up. delete_video reads
    # from cwd-relative paths (data/raw, data/srt, ...), so chdir tmp_path.
    raw_dir = tmp_path / "data" / "raw"; raw_dir.mkdir(parents=True)
    srt_dir = tmp_path / "data" / "srt"; srt_dir.mkdir(parents=True)
    video_id = "test_cancel_vid"
    (raw_dir / f"{video_id}.mp4").write_bytes(b"fake mp4")
    (srt_dir / f"{video_id}_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n")

    monkeypatch.chdir(tmp_path)

    # delete_video also calls is_duplicate / state operations that hit
    # data/logs — make sure that exists too.
    (tmp_path / "data" / "logs").mkdir(parents=True, exist_ok=True)

    # delete_video also bumps tm.video_index, but the index check is a
    # short-circuit guard — we need the video to be registered or the
    # function returns False early. Register a minimal entry.
    from src.api.models import VideoResponse
    tm.video_index[video_id] = VideoResponse(
        video_id=video_id,
        title="test",
        author="",
        duration=0.0,
        resolution="",
        size="",
        codec="",
        description="",
        hashtags=[],
        source_url="",
        file_path=str(raw_dir / f"{video_id}.mp4"),
        thumbnail="",
        has_srt=True,
        status="downloaded",
    )

    task = tm.create_task("full_pipeline")
    task.video_id = video_id

    async def sleeper():
        await asyncio.sleep(5)
    task._asyncio_task = asyncio.create_task(sleeper())

    result = await tm.cancel_task(task.task_id)

    assert result["cleaned"] is True
    assert not (raw_dir / f"{video_id}.mp4").exists()
    assert not (srt_dir / f"{video_id}_vi.srt").exists()
