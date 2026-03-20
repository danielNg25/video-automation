"""SSE event streaming endpoint."""

import json

from fastapi import APIRouter, HTTPException
from starlette.responses import StreamingResponse

from src.api.deps import get_task_manager

router = APIRouter()


@router.get("/api/events/{task_id}")
async def event_stream(task_id: str):
    tm = get_task_manager()
    task = tm.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    async def generate():
        async for event in tm.subscribe(task_id):
            event_type = event["event"]
            data = json.dumps(event["data"])
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
