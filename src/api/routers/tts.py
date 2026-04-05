"""TTS router: text-to-speech generation and voice management endpoints."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse, Response

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import (
    TaskResponse,
    TTSPreviewRequest,
    TTSRequest,
    VoiceInfo,
    VoiceProfileConfig,
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
            request.voice_profile,
            request.provider,
            config,
            voice_override=request.voice,
            api_key_override=request.api_key,
            llm_api_key=request.llm_api_key,
            llm_backend=request.llm_backend,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/tts/voices", response_model=list[VoiceInfo])
async def list_voices(language: str | None = None, provider: str = "edge", api_key: str | None = None):
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
        {"id": "edge", "name": "Edge TTS", "free": True, "requires_key": False},
        {"id": "gtts", "name": "Google Translate TTS", "free": True, "requires_key": False},
        {"id": "piper", "name": "Piper (Local)", "free": True, "requires_key": False},
        {"id": "elevenlabs", "name": "ElevenLabs", "free": False, "requires_key": True},
        {"id": "openai", "name": "OpenAI TTS", "free": False, "requires_key": True},
        {"id": "google", "name": "Google Cloud TTS", "free": False, "requires_key": True},
    ]


@router.get("/api/tts/profiles")
async def get_profiles():
    """Get all voice profiles from config."""
    from src.tts import load_voice_profiles

    config = get_config()
    profiles_data = load_voice_profiles(config)
    return profiles_data.get("profiles", {})


@router.get("/api/tts/platforms")
async def get_tts_platforms():
    """Get per-platform TTS settings."""
    from src.tts import load_voice_profiles

    config = get_config()
    profiles_data = load_voice_profiles(config)
    return profiles_data.get("platforms", {})


@router.put("/api/tts/profiles/{name}")
async def upsert_profile(name: str, profile: VoiceProfileConfig):
    """Create or update a voice profile."""
    from src.tts import load_voice_profiles, save_voice_profiles

    config = get_config()
    profiles_data = load_voice_profiles(config)

    if "profiles" not in profiles_data:
        profiles_data["profiles"] = {}

    profiles_data["profiles"][name] = profile.model_dump()
    save_voice_profiles(profiles_data, config)
    return profiles_data["profiles"][name]


@router.delete("/api/tts/profiles/{name}")
async def delete_profile(name: str):
    """Delete a voice profile."""
    from src.tts import load_voice_profiles, save_voice_profiles

    config = get_config()
    profiles_data = load_voice_profiles(config)

    if name not in profiles_data.get("profiles", {}):
        raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")

    del profiles_data["profiles"][name]
    save_voice_profiles(profiles_data, config)
    return {"status": "deleted", "name": name}


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
        # Parse filename: {video_id}_{lang}_{provider}_{profile}.wav
        # or legacy: {video_id}_{lang}.wav
        stem = f.stem  # without .wav
        parts = stem[len(video_id) + 1:]  # remove "{video_id}_"
        segments = parts.split("_", 2)  # lang, provider, profile
        language = segments[0] if len(segments) >= 1 else "unknown"
        provider = segments[1] if len(segments) >= 2 else "unknown"
        profile = segments[2] if len(segments) >= 3 else "default"

        stat = f.stat()
        results.append({
            "filename": f.name,
            "language": language,
            "provider": provider,
            "profile": profile,
            "size": stat.st_size,
            "created_at": os.path.getmtime(f),
        })

    # Sort by most recent first
    results.sort(key=lambda r: r["created_at"], reverse=True)
    return results


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
    return Response(content=audio_bytes, media_type="audio/mpeg")
