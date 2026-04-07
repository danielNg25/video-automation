"""Subtitle replacement router: region detection, blur preview, manual override."""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse, Response

from src.api.deps import get_data_dir, get_task_manager
from src.api.models import PreviewBlurRequest, SubtitleRegionResponse

router = APIRouter()


@router.get("/api/videos/{video_id}/subtitle-region", response_model=SubtitleRegionResponse)
async def get_subtitle_region(video_id: str):
    """Get auto-detected subtitle region from OCR metadata."""
    data_dir = get_data_dir()
    meta_path = data_dir / "srt" / f"{video_id}_ocr_meta.json"

    if not meta_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No OCR metadata found — video was not transcribed via OCR",
        )

    with open(meta_path) as f:
        meta = json.load(f)

    region = meta.get("subtitle_region")
    if not region:
        raise HTTPException(status_code=404, detail="No subtitle region detected in OCR metadata")

    return SubtitleRegionResponse(
        x=region["x"],
        y=region["y"],
        width=region["width"],
        height=region["height"],
        confidence=1.0,
        video_width=meta.get("video_width", 0),
        video_height=meta.get("video_height", 0),
    )


@router.post("/api/videos/{video_id}/subtitle-region", response_model=SubtitleRegionResponse)
async def set_subtitle_region(video_id: str, region: SubtitleRegionResponse):
    """Set manual region override (saved to OCR metadata)."""
    data_dir = get_data_dir()
    meta_path = data_dir / "srt" / f"{video_id}_ocr_meta.json"

    # Load existing or create new
    if meta_path.exists():
        with open(meta_path) as f:
            meta = json.load(f)
    else:
        meta = {"video_id": video_id}

    meta["subtitle_region"] = {
        "x": region.x,
        "y": region.y,
        "width": region.width,
        "height": region.height,
    }
    if region.video_width:
        meta["video_width"] = region.video_width
    if region.video_height:
        meta["video_height"] = region.video_height

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return region


@router.post("/api/videos/{video_id}/preview-blur")
async def preview_blur(video_id: str, request: PreviewBlurRequest):
    """Render a single frame with blur applied — returns JPEG."""
    from src.processor.ffmpeg import FFmpegProcessor
    from src.processor.region_detector import SubtitleRegion

    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    # Get region: from request or auto-detect
    if request.region:
        region = SubtitleRegion(
            x=request.region.x,
            y=request.region.y,
            width=request.region.width,
            height=request.region.height,
        )
    else:
        data_dir = get_data_dir()
        meta_path = data_dir / "srt" / f"{video_id}_ocr_meta.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="No region available for blur preview")
        with open(meta_path) as f:
            meta = json.load(f)
        r = meta.get("subtitle_region")
        if not r:
            raise HTTPException(status_code=404, detail="No subtitle region in OCR metadata")
        region = SubtitleRegion(x=r["x"], y=r["y"], width=r["width"], height=r["height"])

    video_path = Path(video.file_path)
    processor = FFmpegProcessor()

    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = Path(tmpdir) / "preview.jpg"
        await asyncio.to_thread(
            processor.apply_blur_to_frame,
            video_path,
            output_path,
            region,
            request.timestamp,
            request.blur_settings.strength,
            request.blur_settings.mode,
            request.blur_settings.fill_color,
        )

        if not output_path.exists():
            raise HTTPException(status_code=500, detail="Blur preview generation failed")

        # Read and return as JPEG
        content = output_path.read_bytes()

    return Response(content=content, media_type="image/jpeg")
