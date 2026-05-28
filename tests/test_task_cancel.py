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
