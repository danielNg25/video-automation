"""Integration tests for POST /api/tasks/{task_id}/cancel."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api import create_app
    return TestClient(create_app())


class TestCancelEndpoint:
    def test_cancel_unknown_task_returns_404(self, client):
        r = client.post("/api/tasks/no-such-id/cancel")
        assert r.status_code == 404

    def test_cancel_running_task_returns_cancelled(self, client):
        from src.api.deps import get_task_manager
        tm = get_task_manager()
        task = tm.create_task("download")

        # Simulate a running task without an asyncio task handle
        # (cancel_task skips the wait_for block when _asyncio_task is None)
        task.status = "running"
        r = client.post(f"/api/tasks/{task.task_id}/cancel")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == task.task_id
        assert body["status"] == "cancelled"

    def test_cancel_completed_task_returns_terminal_status(self, client):
        from src.api.deps import get_task_manager
        tm = get_task_manager()
        task = tm.create_task("export")
        task.status = "completed"
        r = client.post(f"/api/tasks/{task.task_id}/cancel")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        assert body["cleaned"] is False
