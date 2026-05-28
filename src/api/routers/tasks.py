"""Task lifecycle endpoints — currently just cancel.

Future home for `GET /api/tasks/{id}` consolidation if multiple routers
ever drift on the status shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import get_task_manager

router = APIRouter()


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running task, kill its subprocess, delete_video its output."""
    tm = get_task_manager()
    try:
        return await tm.cancel_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
