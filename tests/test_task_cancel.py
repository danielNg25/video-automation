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
