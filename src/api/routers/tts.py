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


@router.get("/api/videos/{video_id}/tts/{language}")
async def get_tts_audio(video_id: str, language: str):
    """Stream generated TTS audio file."""
    data_dir = get_data_dir()
    audio_path = data_dir / "tts" / f"{video_id}_{language}.wav"
    if not audio_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"TTS audio not found: {video_id}_{language}.wav",
        )
    return FileResponse(
        path=str(audio_path),
        media_type="audio/wav",
        filename=f"{video_id}_{language}.wav",
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
    except Exception as e:
        msg = str(e)
        if "402" in msg or "Payment Required" in msg:
            raise HTTPException(status_code=402, detail="ElevenLabs: no credits remaining (free tier is 10k chars/month)")
        if "401" in msg or "Unauthorized" in msg or "Invalid" in msg:
            raise HTTPException(status_code=401, detail="Invalid API key")
        raise HTTPException(status_code=500, detail=msg)
    return Response(content=audio_bytes, media_type="audio/mpeg")
