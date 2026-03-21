"""Editor router: save edited subtitles, preview frame/clip with burn-in."""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import (
    PreviewClipRequest,
    PreviewFrameRequest,
    SaveSrtRequest,
    SrtResponse,
    SubtitleSegment,
    TaskResponse,
)
from src.processor.subtitle import (
    _timestamp_to_seconds,
    parse_srt,
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
    """Save edited subtitle segments back to SRT file."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"

    # Convert SubtitleSegment timestamps (HH:MM:SS,mmm) to seconds
    segments = []
    for seg in request.segments:
        segments.append(
            {
                "start": _timestamp_to_seconds(seg.startTime),
                "end": _timestamp_to_seconds(seg.endTime),
                "text": seg.text,
            }
        )

    write_srt(segments, srt_path)

    # Update video index srt_languages
    if request.language not in video.srt_languages:
        video.srt_languages.append(request.language)
        video.srt_languages.sort()
        video.has_srt = True

    # Re-parse to return fresh data
    parsed = parse_srt(srt_path)
    response_segments = []
    for i, seg in enumerate(parsed, start=1):
        from src.processor.subtitle import _seconds_to_srt_timestamp

        response_segments.append(
            SubtitleSegment(
                id=i,
                startTime=_seconds_to_srt_timestamp(seg["start"]),
                endTime=_seconds_to_srt_timestamp(seg["end"]),
                text=seg["text"],
            )
        )

    return SrtResponse(
        video_id=video_id,
        segments=response_segments,
        language=request.language,
    )


@router.post("/api/videos/{video_id}/preview-frame")
async def preview_frame(video_id: str, request: PreviewFrameRequest):
    """Render a single frame with burned-in subtitle, returns JPEG."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"SRT file not found: {video_id}_{request.language}.srt",
        )

    video_path = Path(video.file_path)

    # Build subtitle filter
    from src.processor.ffmpeg import FFmpegProcessor

    proc = FFmpegProcessor()
    escaped_sub = proc._escape_filter_path(srt_path)

    if request.subtitle_style:
        style_str = proc._build_style_string(request.subtitle_style)
        vf = f"subtitles='{escaped_sub}':force_style='{style_str}'"
    else:
        vf = f"subtitles='{escaped_sub}'"

    # Render single frame
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        out_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                str(request.timestamp),
                "-i",
                str(video_path),
                "-vf",
                vf,
                "-frames:v",
                "1",
                "-q:v",
                "2",
                out_path,
            ],
            capture_output=True,
            check=True,
            timeout=30,
        )
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode()[-200:]
        raise HTTPException(status_code=500, detail=f"ffmpeg failed: {stderr}")

    return FileResponse(
        path=out_path,
        media_type="image/jpeg",
        filename=f"{video_id}_frame_{request.timestamp:.1f}s.jpg",
    )


@router.post("/api/videos/{video_id}/preview-clip", response_model=TaskResponse)
async def preview_clip(video_id: str, request: PreviewClipRequest):
    """Render a short clip with burned-in subtitles (background task + SSE)."""
    tm = get_task_manager()
    config = get_config()

    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"SRT file not found: {video_id}_{request.language}.srt",
        )

    task = tm.create_task("preview_clip")

    async def run_preview():
        task_obj = tm.tasks[task.task_id]
        task_obj.status = "running"
        task_obj.message = "Rendering preview clip..."
        tm._emit(
            task.task_id,
            "progress",
            {"progress": 0.3, "message": "Rendering preview clip..."},
        )

        try:
            from src.processor.ffmpeg import FFmpegProcessor

            proc = FFmpegProcessor()
            escaped_sub = proc._escape_filter_path(srt_path)

            if request.subtitle_style:
                style_str = proc._build_style_string(request.subtitle_style)
                vf = f"subtitles='{escaped_sub}':force_style='{style_str}'"
            else:
                vf = f"subtitles='{escaped_sub}'"

            output_dir = data_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            clip_path = output_dir / f"{video_id}_preview.mp4"

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(request.start),
                "-i",
                str(Path(video.file_path)),
                "-t",
                str(request.duration),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "23",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(clip_path),
            ]

            await asyncio.to_thread(
                subprocess.run,
                cmd,
                capture_output=True,
                check=True,
                timeout=120,
            )

            task_obj.status = "completed"
            task_obj.progress = 1.0
            task_obj.result = {
                "video_id": video_id,
                "clip_url": f"/api/videos/{video_id}/output/preview",
            }
            tm._emit(task.task_id, "complete", task_obj.result)

        except Exception as e:
            task_obj.status = "failed"
            task_obj.error = str(e)
            tm._emit(task.task_id, "error", {"message": str(e)})

    asyncio.create_task(run_preview())
    return TaskResponse(task_id=task.task_id, status=task.status)
