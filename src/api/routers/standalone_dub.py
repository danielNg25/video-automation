"""Standalone SRT → Dub CRUD routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from starlette.responses import FileResponse

from src.api import standalone_dub as standalone_mod
from src.api.deps import get_config, get_task_manager
from src.api.models import TaskResponse

router = APIRouter()


@router.post(
    "/api/standalone-dub",
    response_model=TaskResponse,
    status_code=201,
)
async def start_standalone_dub(
    file: UploadFile = File(...),
    provider: str = Form(...),
    voice: str = Form(...),
    language: str = Form(...),
    playback_speed: float = Form(1.5),
    enable_shortening: bool = Form(True),
    api_key: str | None = Form(None),
    llm_api_key: str | None = Form(None),
    llm_backend: str | None = Form(None),
):
    """Generate a dub from an uploaded SRT. Returns task_id; subscribe
    to the existing /api/tasks/{task_id} SSE for progress."""
    tm = get_task_manager()
    config = get_config()

    content = await file.read()
    task = tm.create_task("standalone_dub")
    task._asyncio_task = asyncio.create_task(
        tm.run_standalone_dub(
            task_id=task.task_id,
            srt_content=content,
            original_filename=file.filename or "uploaded.srt",
            provider=provider,
            voice=voice,
            language=language,
            playback_speed=playback_speed,
            enable_shortening=enable_shortening,
            config=config,
            api_key_override=api_key,
            llm_api_key=llm_api_key,
            llm_backend=llm_backend,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get(
    "/api/standalone-dub",
    response_model=list[standalone_mod.StandaloneDubEntry],
)
async def list_standalone_dubs():
    """Recent dubs, newest first."""
    return standalone_mod.list_dubs()


@router.delete("/api/standalone-dub/{dub_uuid}", status_code=204)
async def delete_standalone_dub(dub_uuid: str):
    """Remove the WAV + metadata sidecar."""
    ok = standalone_mod.delete_dub(dub_uuid)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Dub {dub_uuid} not found")
    return None


@router.get("/api/standalone-dub/{dub_uuid}.wav")
async def download_standalone_dub(dub_uuid: str):
    """Serve the WAV with Content-Disposition: attachment for download."""
    wav = standalone_mod.wav_path(dub_uuid)
    if not wav.exists():
        raise HTTPException(status_code=404, detail=f"Dub {dub_uuid} not found")
    return FileResponse(
        path=str(wav),
        media_type="audio/wav",
        filename=f"{dub_uuid}.wav",
    )
