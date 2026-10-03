"""Tests for Task model + cancel_task + run_subprocess_tracked."""

from __future__ import annotations

import asyncio
import subprocess
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _fast_cancel_grace(monkeypatch):
    # Keep the graceful-cancel wait tiny so tests with hung sleepers don't
    # block for the full production grace period before the hard-cancel.
    import src.api.task_manager as tm_mod
    monkeypatch.setattr(tm_mod, "_CANCEL_GRACE_SECONDS", 0.05)


class TestTaskFields:
    def test_task_has_cancellation_fields(self):
        from src.api.task_manager import Task
        t = Task(task_id="t1", task_type="full_pipeline")
        assert t._asyncio_task is None
        assert t._running_subprocess is None
        assert t._child_task_ids == []

    def test_task_status_can_be_cancelling_or_cancelled(self):
        from src.api.task_manager import Task
        t = Task(task_id="t1", task_type="full_pipeline")
        # The dataclass doesn't constrain status, but document the union.
        t.status = "cancelling"
        assert t.status == "cancelling"
        t.status = "cancelled"
        assert t.status == "cancelled"


class TestRunSubprocessTracked:
    async def test_returns_completed_process(self, tmp_path):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")
        result = await tm.run_subprocess_tracked(
            task.task_id, ["echo", "hello"],
        )
        assert result.returncode == 0
        assert b"hello" in result.stdout

    async def test_clears_running_subprocess_on_completion(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")
        await tm.run_subprocess_tracked(task.task_id, ["true"])
        assert task._running_subprocess is None

    async def test_stores_subprocess_during_execution(self):
        """During the await, _running_subprocess should be the live Popen."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")

        async def kill_after_delay():
            await asyncio.sleep(0.05)
            assert task._running_subprocess is not None
            assert isinstance(task._running_subprocess, subprocess.Popen)
            task._running_subprocess.kill()

        killer = asyncio.create_task(kill_after_delay())
        # `sleep 5` should be killed by the killer task in ~50ms
        result = await tm.run_subprocess_tracked(task.task_id, ["sleep", "5"])
        await killer
        assert result.returncode != 0  # killed


class TestCancelTask:
    async def test_cancel_queued_task_no_subprocess_no_video(self):
        """Queued tasks cancel cleanly, no video_id, no subprocess to kill."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("download")
        # Simulate a real asyncio task so cancel() has something to act on
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "cancelled"
        assert result["cleaned"] is False  # no video_id
        assert result["video_id"] is None
        assert task.status == "cancelled"

    async def test_cancel_kills_running_subprocess(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("export")
        mock_proc = MagicMock(spec=subprocess.Popen)
        task._running_subprocess = mock_proc
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        await tm.cancel_task(task.task_id)
        mock_proc.kill.assert_called_once()

    async def test_cancel_deletes_owned_video(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid123"
        task._owns_video_cleanup = True  # this run created the video
        deleted = []
        monkeypatch.setattr(tm, "delete_video", lambda vid: deleted.append(vid) or True)
        # Worker finishes within grace → cleanup runs (not deferred).
        async def done():
            return
        task._asyncio_task = asyncio.create_task(done())
        result = await tm.cancel_task(task.task_id)
        assert deleted == ["vid123"]
        assert result["cleaned"] is True
        assert result["cleanup_deferred"] is False
        assert result["video_id"] == "vid123"

    async def test_cancel_defers_cleanup_when_worker_does_not_stop(self, monkeypatch):
        """If the worker doesn't stop within the grace window, cleanup is
        deferred (not run) to avoid racing a live to_thread worker."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid123"
        task._owns_video_cleanup = True
        deleted = []
        monkeypatch.setattr(tm, "delete_video", lambda vid: deleted.append(vid) or True)
        async def sleeper():
            await asyncio.sleep(10)  # never finishes within the (0.05s) grace
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert deleted == []  # cleanup deferred, not run
        assert result["cleaned"] is False
        assert result["cleanup_deferred"] is True
        assert task.status == "cancelled"

    async def test_cancel_does_not_delete_unowned_video(self, monkeypatch):
        """A cancel must NOT wipe a video this run didn't create."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "preexisting"
        task._owns_video_cleanup = False  # video pre-existed this run
        deleted = []
        monkeypatch.setattr(tm, "delete_video", lambda vid: deleted.append(vid) or True)
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert deleted == []  # existing video preserved
        assert result["cleaned"] is False

    async def test_cancel_reports_false_when_delete_returns_false(self, monkeypatch):
        """cleaned reflects the real delete_video result (video not in index)."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid123"
        task._owns_video_cleanup = True
        monkeypatch.setattr(tm, "delete_video", lambda vid: False)  # not in index
        async def done():
            return
        task._asyncio_task = asyncio.create_task(done())
        result = await tm.cancel_task(task.task_id)
        assert result["cleaned"] is False
        assert result["cleanup_deferred"] is False  # delete ran, just returned False

    async def test_cancel_completed_task_is_noop(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("export")
        task.status = "completed"
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "completed"
        assert result["cleaned"] is False

    async def test_cancel_already_cancelling_returns_noop(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.status = "cancelling"
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "cancelling"

    async def test_cancel_unknown_task_raises_keyerror(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        with pytest.raises(KeyError):
            await tm.cancel_task("no-such-id")

    async def test_cancelled_before_start_aborts_worker(self):
        """A queued worker cancelled before it starts must not run (and must
        not flip itself back to 'running')."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("transcribe")
        task.status = "cancelling"
        # Bails via _cancelled_before_start before touching video_index, so a
        # missing video_id raises nothing.
        await tm.run_transcribe(task.task_id, "nonexistent", "zh", "transcribe", {"ocr": {}})
        assert task.status == "cancelled"

    async def test_cancel_batch_parent_cancels_children(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        parent = tm.create_task("batch_pipeline")
        child_a = tm.create_task("full_pipeline")
        child_b = tm.create_task("full_pipeline")
        parent._child_task_ids = [child_a.task_id, child_b.task_id]
        async def sleeper():
            await asyncio.sleep(10)
        parent._asyncio_task = asyncio.create_task(sleeper())
        child_a._asyncio_task = asyncio.create_task(sleeper())
        child_b._asyncio_task = asyncio.create_task(sleeper())
        await tm.cancel_task(parent.task_id)
        assert child_a.status == "cancelled"
        assert child_b.status == "cancelled"
        assert parent.status == "cancelled"

    async def test_cancel_continues_when_delete_video_raises(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid"
        task._owns_video_cleanup = True
        def boom(vid): raise RuntimeError("disk full")
        monkeypatch.setattr(tm, "delete_video", boom)
        async def done(): return
        task._asyncio_task = asyncio.create_task(done())
        result = await tm.cancel_task(task.task_id)
        assert task.status == "cancelled"
        assert result["cleaned"] is False


def test_no_destructible_artifacts(tmp_path, monkeypatch):
    """Ownership is positively established: a lone raw mp4 is fine, but an
    existing SRT means the id pre-existed and must not be owned/cleaned."""
    from src.api.task_manager import TaskManager
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "srt").mkdir(parents=True)
    tm = TaskManager()
    assert tm._no_destructible_artifacts("fresh") is True
    (tmp_path / "data" / "srt" / "existing_vi.srt").write_text("x")
    assert tm._no_destructible_artifacts("existing") is False
