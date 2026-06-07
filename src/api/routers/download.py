"""Download and video listing endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException

from src.api.deps import get_config, get_task_manager
from src.api.models import (
    BatchDownloadRequest,
    DashboardStats,
    DownloadRequest,
    TaskResponse,
    UpdateVideoRequest,
    VideoListResponse,
    VideoResponse,
)

router = APIRouter()


@router.post("/api/download", response_model=TaskResponse)
async def start_download(request: DownloadRequest):
    tm = get_task_manager()
    config = get_config()
    task = tm.create_task("download")
    task._asyncio_task = asyncio.create_task(tm.run_download(task.task_id, request.url, config))
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.post("/api/download/batch")
async def start_batch_download(request: BatchDownloadRequest):
    """Download many URLs concurrently — no transcribe / translate / TTS.

    Mirrors `/api/pipeline/batch`'s shape (parent batch task + child
    download tasks, concurrency via semaphore, progress emitted on the
    batch task's SSE channel) so the FE can poll the same way.
    """
    tm = get_task_manager()
    config = get_config()

    if not request.urls:
        raise HTTPException(status_code=400, detail="urls must not be empty")

    batch_task = tm.create_task("batch_download")
    batch_id = batch_task.task_id

    task_ids: list[str] = []
    for _ in request.urls:
        child = tm.create_task("download")
        task_ids.append(child.task_id)

    batch_task.result = {"task_ids": task_ids, "urls": request.urls}

    semaphore = asyncio.Semaphore(max(1, request.concurrency))
    completed = 0
    errors: list[dict] = []

    async def process_one(url: str, child_id: str):
        nonlocal completed
        async with semaphore:
            await tm.run_download(child_id, url, config)
            child = tm.tasks.get(child_id)
            if child and child.status == "failed":
                errors.append({"url": url, "error": child.error or "Unknown error"})
            completed += 1
            batch_task.progress = completed / len(request.urls)
            tm._emit(batch_id, "progress", {
                "completed": completed,
                "total": len(request.urls),
                "progress": batch_task.progress,
                "errors": errors,
            })

    async def run_batch():
        batch_task.status = "running"
        child_tasks = []
        for url, tid in zip(request.urls, task_ids):
            child = tm.tasks[tid]
            child._asyncio_task = asyncio.create_task(process_one(url, tid))
            batch_task._child_task_ids.append(tid)
            child_tasks.append(child._asyncio_task)
        await asyncio.gather(*child_tasks, return_exceptions=True)

        succeeded = sum(
            1 for tid in task_ids
            if tm.tasks.get(tid) and tm.tasks[tid].status == "completed"
        )
        failed = len(task_ids) - succeeded
        batch_task.status = "completed" if failed == 0 else (
            "failed" if succeeded == 0 else "completed"
        )
        batch_task.result = {
            **(batch_task.result or {}),
            "total": len(request.urls),
            "succeeded": succeeded,
            "failed": failed,
            "errors": errors,
        }
        tm._emit(batch_id, "complete", batch_task.result)

    batch_task._asyncio_task = asyncio.create_task(run_batch())

    return {
        "batch_id": batch_id,
        "task_ids": task_ids,
        "total": len(request.urls),
    }


@router.get("/api/videos", response_model=VideoListResponse)
async def list_videos(status: str | None = None):
    tm = get_task_manager()
    videos = list(tm.video_index.values())
    if status:
        videos = [v for v in videos if v.status == status]
    # Sort by most recent first (by file path mtime, fallback to video_id)
    videos.sort(key=lambda v: v.video_id, reverse=True)
    return VideoListResponse(videos=videos, total=len(videos))


@router.get("/api/videos/{video_id}", response_model=VideoResponse)
async def get_video(video_id: str):
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    return video


@router.patch("/api/videos/{video_id}", response_model=VideoResponse)
async def update_video(video_id: str, request: UpdateVideoRequest):
    tm = get_task_manager()
    updated = tm.update_video_title(video_id, request.title)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    return updated


@router.delete("/api/videos/{video_id}")
async def delete_video(video_id: str):
    tm = get_task_manager()
    if not tm.delete_video(video_id):
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    return {"deleted": True}


@router.get("/api/stats", response_model=DashboardStats)
async def get_stats():
    tm = get_task_manager()
    return DashboardStats(**tm.get_stats())
