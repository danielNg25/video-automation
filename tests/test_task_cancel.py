"""Tests for Task model + cancel_task + run_subprocess_tracked."""

from __future__ import annotations

import asyncio
import subprocess
import pytest
from unittest.mock import MagicMock


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

    async def test_cancel_calls_delete_video_when_video_id_set(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid123"
        deleted = []
        monkeypatch.setattr(tm, "delete_video", lambda vid: deleted.append(vid) or True)
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert deleted == ["vid123"]
        assert result["cleaned"] is True
        assert result["video_id"] == "vid123"

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
        def boom(vid): raise RuntimeError("disk full")
        monkeypatch.setattr(tm, "delete_video", boom)
        async def sleeper(): await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert task.status == "cancelled"
        assert result["cleaned"] is False
