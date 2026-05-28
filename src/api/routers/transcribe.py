"""Transcription and SRT endpoints."""

import asyncio
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_config, get_task_manager
from src.api.models import SrtResponse, SubtitleSegment, TaskResponse, TranscribeRequest
from src.processor.subtitle import parse_srt
from src.transcriber.base import BaseTranscriber

router = APIRouter()


def _resolve_srt_path(video_id: str, language: str) -> tuple[Path, bool]:
    """Return the SRT path to read for this video+language plus whether it
    is the dub-synced derivative.

    Prefers `{video_id}_{language}.dubsync.srt` when present. Falls back to
    the legacy `{video_id}_{language}.srt`. The dubsync file is written by
    the TTS assembler at Stage 6 with text and timings synced to the actual
    dub; consumers should prefer it whenever available.

    Returns (path, is_dubsync). The returned path is NOT guaranteed to
    exist — callers must check with `.exists()`.
    """
    srt_dir = Path("data/srt")
    dubsync = srt_dir / f"{video_id}_{language}.dubsync.srt"
    if dubsync.exists():
        return dubsync, True
    return srt_dir / f"{video_id}_{language}.srt", False


@router.post("/api/transcribe", response_model=TaskResponse)
async def start_transcribe(request: TranscribeRequest):
    tm = get_task_manager()
    config = get_config()

    if request.video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    task = tm.create_task("transcribe")
    task._asyncio_task = asyncio.create_task(
        tm.run_transcribe(
            task.task_id,
            request.video_id,
            request.language,
            request.task,
            config,
            ocr_region=request.ocr_region,
            ocr_config=request.ocr_config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/videos/{video_id}/sample-frame")
async def get_sample_frame(video_id: str, timestamp: float = 1.0):
    """Extract and return a single JPEG frame at the given timestamp."""
    tm = get_task_manager()
    video_info = tm.video_index.get(video_id)
    if not video_info:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video_info.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(timestamp),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                tmp_path,
            ],
            capture_output=True,
            check=True,
            timeout=15,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        raise HTTPException(status_code=500, detail=f"Frame extraction failed: {e}")

    return FileResponse(
        path=tmp_path,
        media_type="image/jpeg",
        filename=f"{video_id}_frame.jpg",
    )


@router.get("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def get_srt(video_id: str, language: str = "zh"):
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    srt_path, is_dubsync = _resolve_srt_path(video_id, language)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404, detail=f"SRT file not found for {video_id} ({language})"
        )

    parsed = parse_srt(srt_path)
    segments = [
        SubtitleSegment(
            id=seg["index"],
            startTime=BaseTranscriber._format_timestamp(seg["start"]),
            endTime=BaseTranscriber._format_timestamp(seg["end"]),
            text=seg["text"],
        )
        for seg in parsed
    ]

    return SrtResponse(
        video_id=video_id, segments=segments,
        language=language, is_dubsync=is_dubsync,
    )


@router.get("/api/videos/{video_id}/srt/download")
async def download_srt(video_id: str, language: str = "zh"):
    """Download SRT file as attachment.

    Serves the dub-synced SRT when present (with a clean `{id}_{lang}.srt`
    download filename — no `.dubsync` infix in the filename the user sees),
    falling back to the legacy SRT otherwise."""
    srt_path, _is_dubsync = _resolve_srt_path(video_id, language)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404, detail=f"SRT file not found for {video_id} ({language})"
        )

    download_name = f"{video_id}_{language}.srt"
    return FileResponse(
        path=str(srt_path),
        media_type="text/plain",
        filename=download_name,
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )
