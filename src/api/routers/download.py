"""Download and video listing endpoints."""

import asyncio

from fastapi import APIRouter, HTTPException

from src.api.deps import get_config, get_task_manager
from src.api.models import (
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
