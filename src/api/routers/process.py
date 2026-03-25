"""Process router: subtitle burn-in + platform reformatting endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import ProcessRequest, ProcessResult, TaskResponse

router = APIRouter()


@router.post("/api/process", response_model=TaskResponse)
async def start_process(request: ProcessRequest):
    """Start video processing for selected platforms."""
    tm = get_task_manager()
    config = get_config()

    video = tm.video_index.get(request.video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    valid_platforms = {"tiktok", "youtube", "facebook", "x"}
    invalid = set(request.platforms) - valid_platforms
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid platforms: {invalid}")

    task = tm.create_task("process")
    asyncio.create_task(
        tm.run_process(
            task.task_id,
            request.video_id,
            request.platforms,
            request.subtitle_style,
            request.subtitle_language_overrides,
            config,
            enable_tts=request.enable_tts,
            tts_mix_settings=request.tts_mix_settings,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/process/{task_id}", response_model=ProcessResult)
async def get_process_result(task_id: str):
    """Get processing result for a completed task."""
    tm = get_task_manager()
    task = tm.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status == "failed":
        raise HTTPException(status_code=500, detail=task.error or "Processing failed")
    if task.status != "completed":
        raise HTTPException(status_code=202, detail="Processing still in progress")
    return ProcessResult(**(task.result or {}))


@router.get("/api/subtitle-styles")
async def get_subtitle_styles():
    """Return subtitle style configuration."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")
    with open(config_path) as f:
        return yaml.safe_load(f)


@router.put("/api/subtitle-styles")
async def update_default_subtitle_style(style: dict):
    """Update the default subtitle style."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")

    with open(config_path) as f:
        styles = yaml.safe_load(f)

    styles["default"] = {**styles.get("default", {}), **style}

    with open(config_path, "w") as f:
        yaml.safe_dump(styles, f, default_flow_style=False)

    return styles


@router.put("/api/subtitle-styles/{platform}")
async def update_subtitle_style(platform: str, style: dict):
    """Update platform-specific subtitle style."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")

    with open(config_path) as f:
        styles = yaml.safe_load(f)

    if "platforms" not in styles:
        styles["platforms"] = {}
    styles["platforms"][platform] = style

    with open(config_path, "w") as f:
        yaml.safe_dump(styles, f, default_flow_style=False)

    return styles


@router.get("/api/platforms")
async def get_platforms():
    """Return platform specifications."""
    config_path = Path("config/platforms.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Platform config not found")
    with open(config_path) as f:
        return yaml.safe_load(f)


@router.get("/api/videos/{video_id}/output/{platform}")
async def get_processed_video(video_id: str, platform: str):
    """Stream a processed video file."""
    data_dir = get_data_dir()
    output_path = data_dir / "output" / f"{video_id}_{platform}.mp4"
    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Processed video not found: {video_id}_{platform}.mp4",
        )
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"{video_id}_{platform}.mp4",
    )
