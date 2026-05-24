"""TTS router: text-to-speech generation and voice management endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse, Response

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import (
    SyncDubRequest,
    TaskResponse,
    TTSPreviewRequest,
    TTSRequest,
    VoiceInfo,
)

router = APIRouter()


@router.post("/api/tts", response_model=TaskResponse)
async def start_tts(request: TTSRequest):
    """Generate TTS audio track for a video."""
    tm = get_task_manager()
    config = get_config()

    video = tm.video_index.get(request.video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    task = tm.create_task("tts")
    asyncio.create_task(
        tm.run_tts(
            task.task_id,
            request.video_id,
            request.language,
            request.voice,
            request.provider,
            config,
            api_key_override=request.api_key,
            llm_api_key=request.llm_api_key,
            llm_backend=request.llm_backend,
            playback_speed=request.playback_speed,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.post("/api/videos/{video_id}/dub/sync", response_model=TaskResponse)
async def sync_dub(video_id: str, request: SyncDubRequest):
    """Re-sync the dub for a single language after subtitle edits.

    Kicks off a background task that loads `dub_meta_{language}.json`,
    diffs each segment's text against the saved record, and either:
      - re-synthesises only the changed segments (partial path), or
      - falls back to a full regen when > 50% of segments are dirty,
        the segment count changed, or any of provider / voice_id /
        playback_speed / underlay_db do not match dub_meta.
    """
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    from src.api.routers.transcribe import _resolve_srt_path
    from src.processor.subtitle import parse_srt

    srt_path, _ = _resolve_srt_path(video_id, request.language)
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"No SRT for {video_id}/{request.language} to sync against",
        )
    parsed = parse_srt(srt_path)
    new_texts = [seg["text"] for seg in parsed]

    current_params = {
        "provider": request.provider,
        "voice_id": request.voice_id,
        "playback_speed": request.playback_speed,
        "underlay_db": request.underlay_db,
        "api_key": request.api_key,
        "llm_api_key": request.llm_api_key,
        "llm_backend": request.llm_backend,
    }

    task = tm.create_task("dub_sync")
    task.video_id = video_id

    async def _runner():
        from src.tts.sync_runner import run_dub_sync

        task_obj = tm.tasks[task.task_id]
        task_obj.status = "running"
        task_obj.message = "Starting dub sync..."
        tm._emit(
            task.task_id,
            "progress",
            {"progress": 0.0, "message": "Starting dub sync..."},
        )

        def on_progress(current: int, total: int, message: str):
            pct = current / total if total > 0 else 0.0
            task_obj.progress = pct
            task_obj.message = message
            tm._emit(
                task.task_id,
                "progress",
                {"progress": pct, "message": message},
            )

        try:
            result = await run_dub_sync(
                video_id=video_id,
                language=request.language,
                new_texts=new_texts,
                current_params=current_params,
                on_progress=on_progress,
            )

            # Clear the dub_out_of_sync flag for this language since the
            # dub now matches the SRT.
            try:
                from src.utils.state import PipelineState

                state = PipelineState.load(video_id)
                if request.language in state.dub_out_of_sync_languages:
                    state.dub_out_of_sync_languages.remove(request.language)
                    state.save()
            except Exception:  # noqa: BLE001 — state update is best-effort
                pass

            task_obj.status = "completed"
            task_obj.progress = 1.0
            task_obj.message = (
                f"Dub sync complete ({result.get('mode')}, "
                f"{result.get('dirty_count', 0)} dirty)"
            )
            task_obj.result = {"video_id": video_id, **result}
            tm._emit(task.task_id, "complete", task_obj.result)
        except Exception as e:  # noqa: BLE001 — surface failure via SSE
            task_obj.status = "failed"
            task_obj.error = str(e)
            task_obj.message = f"Dub sync failed: {e}"
            tm._emit(task.task_id, "error", {"message": str(e)})

    asyncio.create_task(_runner())
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/tts/voices", response_model=list[VoiceInfo])
async def list_voices(language: str | None = None, provider: str = "google", api_key: str | None = None):  # noqa: E501
    """List available TTS voices, optionally filtered by language."""
    config = get_config()

    from src.tts import get_tts_provider

    # Inject per-request API key for paid providers
    effective_config = config
    if api_key:
        tts_section = dict(config.get("tts", {}))
        tts_section[f"{provider}_api_key"] = api_key
        effective_config = {**config, "tts": tts_section}

    tts = get_tts_provider(effective_config, provider=provider)
    voices = await tts.list_voices(language=language)
    return [VoiceInfo(**v) for v in voices]


@router.get("/api/tts/providers")
async def list_providers():
    """List available TTS providers."""
    return [
        {"id": "google", "name": "Google Cloud TTS", "free": False, "requires_key": True},
        {"id": "elevenlabs", "name": "ElevenLabs", "free": False, "requires_key": True},
        {"id": "openai", "name": "OpenAI TTS", "free": False, "requires_key": True},
    ]


@router.get("/api/videos/{video_id}/tts")
async def list_tts_audio(video_id: str):
    """List all generated TTS audio files for a video."""
    import os

    data_dir = get_data_dir()
    tts_dir = data_dir / "tts"
    if not tts_dir.exists():
        return []

    results = []
    for f in tts_dir.glob(f"{video_id}_*.wav"):
        # Parse filename: {video_id}_{lang}_{provider}_{voice}.wav
        # or legacy: {video_id}_{lang}.wav
        stem = f.stem  # without .wav
        parts = stem[len(video_id) + 1:]  # remove "{video_id}_"
        segments = parts.split("_", 2)  # lang, provider, voice
        language = segments[0] if len(segments) >= 1 else "unknown"
        provider = segments[1] if len(segments) >= 2 else "unknown"
        voice = segments[2] if len(segments) >= 3 else ""

        stat = f.stat()
        results.append({
            "filename": f.name,
            "language": language,
            "provider": provider,
            "voice": voice,
            "size": stat.st_size,
            "created_at": os.path.getmtime(f),
        })

    # Sort by most recent first
    results.sort(key=lambda r: r["created_at"], reverse=True)
    return results


@router.delete("/api/videos/{video_id}/tts/{filename}")
async def delete_tts_audio(video_id: str, filename: str):
    """Delete a specific TTS audio file."""
    data_dir = get_data_dir()
    # Prevent path traversal
    safe_name = Path(filename).name
    if not safe_name.startswith(video_id):
        raise HTTPException(status_code=400, detail="Filename does not match video_id")
    audio_path = data_dir / "tts" / safe_name
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"TTS file not found: {safe_name}")
    audio_path.unlink()
    # Also remove .sentences.srt if it exists
    sentences_srt = audio_path.with_suffix(".sentences.srt")
    if sentences_srt.exists():
        sentences_srt.unlink()
    return {"status": "deleted", "filename": safe_name}


@router.get("/api/videos/{video_id}/tts/{language}")
async def get_tts_audio(video_id: str, language: str, file: str | None = None):
    """Stream generated TTS audio file. Optionally specify exact filename."""
    data_dir = get_data_dir()
    tts_dir = data_dir / "tts"

    if file:
        # Serve specific file (prevent path traversal)
        safe_file = Path(file).name
        audio_path = tts_dir / safe_file
    else:
        # Serve most recent file matching video_id + language
        matches = sorted(
            tts_dir.glob(f"{video_id}_{language}*.wav"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        audio_path = matches[0] if matches else tts_dir / f"{video_id}_{language}.wav"

    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"TTS audio not found for {video_id}/{language}",
        )
    return FileResponse(
        path=str(audio_path),
        media_type="audio/wav",
        filename=audio_path.name,
    )


@router.post("/api/tts/preview")
async def preview_tts(request: TTSPreviewRequest):
    """Generate a quick TTS preview for a text snippet."""
    config = get_config()

    from src.tts import get_tts_provider

    # Inject per-request API key for paid providers
    effective_config = config
    if request.api_key:
        tts_section = dict(config.get("tts", {}))
        tts_section[f"{request.provider}_api_key"] = request.api_key
        effective_config = {**config, "tts": tts_section}

    tts = get_tts_provider(effective_config, provider=request.provider)
    try:
        audio_bytes = await tts.synthesize(
            request.text,
            request.voice,
            speed=request.speed,
            pitch=request.pitch,
        )
    except HTTPException:
        raise
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg or "Invalid API key" in msg:
            raise HTTPException(status_code=401, detail=msg)
        raise HTTPException(status_code=502, detail=msg)

    # Apply the user's chosen playback speed so the preview sounds the same
    # as the final dub will. Skip the trivial ~1.0 case to avoid a useless
    # ffmpeg round-trip.
    if request.playback_speed and abs(request.playback_speed - 1.0) > 0.01:
        import subprocess
        import tempfile
        from src.tts.assembler import _build_atempo_filter

        try:
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as in_f:
                in_f.write(audio_bytes)
                in_path = in_f.name
            out_path = in_path + ".out.mp3"
            atempo = _build_atempo_filter(request.playback_speed)
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", in_path, "-af", atempo,
                 "-c:a", "libmp3lame", "-q:a", "4", out_path],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                with open(out_path, "rb") as f:
                    audio_bytes = f.read()
            import os
            os.unlink(in_path)
            if os.path.exists(out_path):
                os.unlink(out_path)
        except Exception:
            # Fall back to natural-speed audio if atempo fails — the preview
            # still plays, just not at the requested speed.
            pass

    return Response(content=audio_bytes, media_type="audio/mpeg")
