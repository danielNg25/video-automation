"""Pipeline endpoints — single, batch, history, retry, stats."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import get_config, get_task_manager
from src.api.models import (
    BatchPipelineRequest,
    FullPipelineRequest,
    PipelineHistoryEntry,
    PipelineRequest,
    TaskResponse,
)
from src.utils.state import PipelineState, get_all_states

router = APIRouter()


# --- Existing: download → transcribe → translate pipeline ---


@router.post("/api/pipeline", response_model=TaskResponse)
async def start_pipeline(request: PipelineRequest):
    """Run download → transcribe → translate pipeline (existing behavior)."""
    tm = get_task_manager()
    config = get_config()

    task = tm.create_task("pipeline")
    asyncio.create_task(
        tm.run_pipeline(
            task.task_id,
            url=request.url,
            translate_profile=request.translate_profile,
            source_language=request.source_language,
            config=config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


# --- Full pipeline: download → transcribe → translate → process → upload ---


@router.post("/api/pipeline/full", response_model=TaskResponse)
async def start_full_pipeline(request: FullPipelineRequest):
    """Run the full pipeline including process and upload stages."""
    tm = get_task_manager()
    config = get_config()

    task = tm.create_task("full_pipeline")
    asyncio.create_task(
        _run_full_pipeline(
            task_id=task.task_id,
            url=request.url,
            platforms=request.platforms,
            auto_upload=request.auto_upload,
            translate_profile=request.translate_profile,
            source_language=request.source_language,
            force=request.force,
            config=config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


async def _run_full_pipeline(
    task_id: str,
    url: str,
    platforms: list[str],
    auto_upload: bool,
    translate_profile: str | None,
    source_language: str,
    force: bool,
    config: dict,
):
    """Execute the full pipeline as a background task with SSE events."""
    from src.pipeline import Pipeline

    tm = get_task_manager()
    task = tm.tasks[task_id]
    task.status = "running"

    def emit(stage: str, progress: float, message: str):
        task.progress = progress
        task.message = message
        tm._emit(task_id, "progress", {
            "stage": stage,
            "progress": progress,
            "message": message,
        })

    try:
        pipeline = Pipeline(config)
        options = {
            "force": force,
            "subtitle_lang": source_language,
            "translate_profile": translate_profile,
        }

        result = await pipeline.process_single(url, platforms, options, emit)

        if result.get("status") == "done":
            task.status = "completed"
            task.progress = 1.0
            task.video_id = result.get("video_id")
            task.result = result
            tm._emit(task_id, "complete", result)
        elif result.get("status") == "skipped":
            task.status = "completed"
            task.message = result.get("message", "Skipped")
            task.result = result
            tm._emit(task_id, "complete", result)
        else:
            task.status = "failed"
            task.error = result.get("error", "Unknown error")
            tm._emit(task_id, "error", {"message": task.error})

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        tm._emit(task_id, "error", {"message": str(e)})


# --- Batch pipeline ---


@router.post("/api/pipeline/batch")
async def start_batch_pipeline(request: BatchPipelineRequest):
    """Start batch processing of multiple URLs."""
    tm = get_task_manager()
    config = get_config()

    # Create a parent task for the batch
    batch_task = tm.create_task("batch_pipeline")
    batch_id = batch_task.task_id

    # Create individual tasks per URL
    task_ids = []
    for url in request.urls:
        child_task = tm.create_task("full_pipeline")
        task_ids.append(child_task.task_id)

    asyncio.create_task(
        _run_batch_pipeline(
            batch_id=batch_id,
            task_ids=task_ids,
            urls=request.urls,
            platforms=request.platforms,
            concurrency=request.concurrency,
            translate_profile=request.translate_profile,
            source_language=request.source_language,
            force=request.force,
            config=config,
        )
    )

    return {
        "batch_id": batch_id,
        "task_ids": task_ids,
        "total": len(request.urls),
    }


async def _run_batch_pipeline(
    batch_id: str,
    task_ids: list[str],
    urls: list[str],
    platforms: list[str],
    concurrency: int,
    translate_profile: str | None,
    source_language: str,
    force: bool,
    config: dict,
):
    """Execute batch pipeline with concurrency control."""
    from src.pipeline import Pipeline

    tm = get_task_manager()
    batch_task = tm.tasks[batch_id]
    batch_task.status = "running"

    semaphore = asyncio.Semaphore(concurrency)
    completed = 0

    async def process_one(idx: int, url: str, child_task_id: str):
        nonlocal completed
        async with semaphore:
            await _run_full_pipeline(
                task_id=child_task_id,
                url=url,
                platforms=platforms,
                auto_upload=False,
                translate_profile=translate_profile,
                source_language=source_language,
                force=force,
                config=config,
            )
            completed += 1
            batch_task.progress = completed / len(urls)
            tm._emit(batch_id, "progress", {
                "completed": completed,
                "total": len(urls),
                "progress": batch_task.progress,
            })

    tasks = [
        process_one(i, url, tid)
        for i, (url, tid) in enumerate(zip(urls, task_ids))
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Summarize
    succeeded = sum(1 for tid in task_ids if tm.tasks.get(tid, None) and tm.tasks[tid].status == "completed")
    failed = len(task_ids) - succeeded

    batch_task.status = "completed"
    batch_task.progress = 1.0
    batch_task.result = {
        "total": len(urls),
        "succeeded": succeeded,
        "failed": failed,
    }
    tm._emit(batch_id, "complete", batch_task.result)


# --- Pipeline status + history ---


@router.get("/api/pipeline/{task_id}")
async def get_pipeline_status(task_id: str):
    """Get detailed pipeline status for a task."""
    tm = get_task_manager()
    task = tm.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "video_id": task.video_id,
        "progress": task.progress,
        "message": task.message,
        "result": task.result,
        "error": task.error,
    }


@router.get("/api/pipeline/history", response_model=list[PipelineHistoryEntry])
async def get_pipeline_history(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
):
    """List all pipeline runs from state files, optionally filtered by status."""
    states = get_all_states()

    if status:
        states = [s for s in states if s.get("status") == status]

    entries = []
    for s in states[:limit]:
        entries.append(PipelineHistoryEntry(
            video_id=s.get("video_id", ""),
            url=s.get("url", ""),
            status=s.get("status", "unknown"),
            completed_stages=s.get("completed_stages", []),
            platforms=s.get("platforms", []),
            error=s.get("error"),
            created_at=s.get("created_at", ""),
            updated_at=s.get("updated_at", ""),
        ))

    return entries


# --- Retry ---


@router.post("/api/pipeline/{task_id}/retry", response_model=TaskResponse)
async def retry_pipeline(task_id: str):
    """Retry a failed pipeline from the failed stage."""
    tm = get_task_manager()
    old_task = tm.tasks.get(task_id)
    if not old_task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if old_task.status != "failed":
        raise HTTPException(status_code=400, detail="Can only retry failed tasks")

    video_id = old_task.video_id
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id on task — cannot retry")

    # Load the saved state to find the URL and resume point
    state = PipelineState.load(video_id)

    config = get_config()
    new_task = tm.create_task("full_pipeline")

    asyncio.create_task(
        _run_full_pipeline(
            task_id=new_task.task_id,
            url=state.url,
            platforms=state.platforms or ["youtube", "tiktok"],
            auto_upload=False,
            translate_profile=None,
            source_language="zh",
            force=False,
            config=config,
        )
    )

    return TaskResponse(task_id=new_task.task_id, status=new_task.status)


# --- Dashboard stats ---


@router.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """Summary stats: total videos, today's count, success rate, active tasks."""
    tm = get_task_manager()

    # Get stats from task manager (existing videos + tasks)
    base_stats = tm.get_stats()

    # Also count from state files for historical accuracy
    states = get_all_states()
    today_str = date.today().isoformat()

    total_from_states = len(states)
    today_from_states = sum(
        1 for s in states
        if s.get("created_at", "").startswith(today_str)
    )
    done_count = sum(1 for s in states if s.get("status") == "done")
    failed_count = sum(1 for s in states if s.get("status") == "failed")
    total_finished = done_count + failed_count
    success_rate = (done_count / total_finished * 100) if total_finished > 0 else 100.0

    return {
        "total_videos": max(base_stats["totalVideos"], total_from_states),
        "today": max(base_stats["processedToday"], today_from_states),
        "success_rate": round(success_rate / 100, 2),  # 0.0 – 1.0
        "active_tasks": base_stats["activeTasks"],
    }
