"""Pipeline endpoint — one-click download + transcribe + translate."""

import asyncio

from fastapi import APIRouter

from src.api.deps import get_config, get_task_manager
from src.api.models import PipelineRequest, TaskResponse

router = APIRouter()


@router.post("/api/pipeline", response_model=TaskResponse)
async def start_pipeline(request: PipelineRequest):
    tm = get_task_manager()
    config = get_config()

    task = tm.create_task("pipeline")
    asyncio.create_task(
        tm.run_pipeline(
            task.task_id,
            url=request.url,
            transcribe_method=request.transcribe_method,
            translate_profile=request.translate_profile,
            source_language=request.source_language,
            config=config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)
