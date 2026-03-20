"""Transcription and SRT endpoints."""

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException

from src.api.deps import get_config, get_task_manager
from src.api.models import SrtResponse, SubtitleSegment, TaskResponse, TranscribeRequest
from src.processor.subtitle import parse_srt
from src.transcriber.base import BaseTranscriber

router = APIRouter()


@router.post("/api/transcribe", response_model=TaskResponse)
async def start_transcribe(request: TranscribeRequest):
    tm = get_task_manager()
    config = get_config()

    if request.video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    task = tm.create_task("transcribe")
    asyncio.create_task(
        tm.run_transcribe(task.task_id, request.video_id, request.language, request.task, config)
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def get_srt(video_id: str, language: str = "zh"):
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    srt_path = Path("data/srt") / f"{video_id}_{language}.srt"
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

    return SrtResponse(video_id=video_id, segments=segments, language=language)
