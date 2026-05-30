"""Editor router: save edited subtitles, serve proxy/raw video."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_data_dir, get_task_manager
from src.api.models import (
    SaveSrtRequest,
    SrtResponse,
)
from src.api.routers.transcribe import _resolve_srt_path
from src.processor.subtitle import (
    _timestamp_to_seconds,
    write_srt,
)

router = APIRouter()


@router.get("/api/videos/{video_id}/raw")
async def serve_raw_video(video_id: str):
    """Serve the full-resolution raw video file."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"{video_id}.mp4",
        headers={"Content-Disposition": f'attachment; filename="{video_id}.mp4"'},
    )


@router.get("/api/videos/{video_id}/proxy")
async def serve_proxy_video(video_id: str):
    """Serve a cached 480p proxy video, generating on first request."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    data_dir = get_data_dir()
    proxy_path = data_dir / "proxy" / f"{video_id}_360p.mp4"

    if not proxy_path.exists():
        from src.processor.ffmpeg import FFmpegProcessor

        proc = FFmpegProcessor()
        try:
            await asyncio.to_thread(proc.generate_proxy, video_path, proxy_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Proxy generation failed: {e}")

    return FileResponse(
        path=str(proxy_path),
        media_type="video/mp4",
        filename=f"{video_id}_360p.mp4",
    )


@router.put("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def save_srt(video_id: str, request: SaveSrtRequest):
    """Overwrite the working-draft SRT for this (video, language).

    Snapshots are immutable — the editor never writes them. The DubTab's
    'Save as version' button uses POST /api/videos/{id}/versions to
    create a snapshot from the current working draft.
    """
    from src.api.versions import ensure_migrated

    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    ensure_migrated(video_id, request.language)
    srt_path = _resolve_srt_path(video_id, request.language, "draft")
    srt_path.parent.mkdir(parents=True, exist_ok=True)

    segments = [
        {
            "index": seg.id,
            "start": _timestamp_to_seconds(seg.startTime),
            "end": _timestamp_to_seconds(seg.endTime),
            "text": seg.text,
        }
        for seg in request.segments
    ]
    write_srt(segments, srt_path)

    return SrtResponse(
        video_id=video_id,
        segments=request.segments,
        language=request.language,
        is_dubsync=False,
    )
