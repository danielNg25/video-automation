"""Shared TTS-track runner used by both the per-video API and the full pipeline.

This is the single place where voice profile resolution, TTS provider/API-key
plumbing, LLM-translator setup (with backend-aware default model and per-request
override priority), SRT loading, video-duration fallback, output filename, and
the final `TTSAssembler.generate_full_track` invocation live. Both callers
(`tm.run_tts` and `Pipeline.process_single`) must route through this so they
produce byte-identical output for identical inputs.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


# Backend → default model. Used when no explicit model is provided in config.
# Matches what the per-video API has historically used.
_DEFAULT_LLM_MODELS = {
    "deepseek": "deepseek-chat",
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o-mini",
}


def _build_llm_translator(
    config: dict,
    *,
    llm_api_key: str | None,
    llm_backend: str | None,
):
    """Resolve the LLM translator used for sentence detection + text shortening.

    Priority for each parameter: per-request override → config → environment.
    Returns the constructed LLMTranslator or None if no key is available.
    """
    try:
        from src.translator.llm import LLMTranslator
    except Exception as e:  # pragma: no cover — only fires if the module is broken
        logger.warning(f"Could not import LLMTranslator: {e}")
        return None

    trans_cfg = config.get("translation", {})
    backend = llm_backend or trans_cfg.get("backend", "deepseek")
    api_key = (
        llm_api_key
        or trans_cfg.get("api_key")
        or os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
    )
    base_url = trans_cfg.get("base_url")
    if backend == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com/v1"

    logger.info(
        f"TTS shortening init: llm_api_key={'yes' if llm_api_key else 'no'}, "
        f"llm_backend={llm_backend}, "
        f"env_deepseek={'yes' if os.environ.get('DEEPSEEK_API_KEY') else 'no'}"
    )

    if not api_key:
        logger.info("TTS text shortening disabled (no API key found)")
        return None

    # Use the backend-aware default model — config["translation"]["model"] is
    # often set for the *translate* stage and may be wrong for this backend.
    model = _DEFAULT_LLM_MODELS.get(backend, trans_cfg.get("model"))
    try:
        translator = LLMTranslator(
            backend=backend,
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )
        logger.info(
            f"TTS LLM enabled (backend={backend}, model={model}, base_url={base_url})"
        )
        return translator
    except Exception as e:
        logger.warning(f"Could not init translator for TTS shortening: {e}")
        return None


def tts_output_path(
    tts_dir: Path,
    video_id: str,
    language: str,
    provider_name: str,
    voice_profile_name: str,
) -> Path:
    """Canonical output filename used by both flows."""
    safe_profile = voice_profile_name.replace("/", "-").replace(" ", "-")
    return tts_dir / f"{video_id}_{language}_{provider_name}_{safe_profile}.wav"


async def run_tts_track(
    *,
    video_id: str,
    video_path: Path,
    language: str,
    voice_profile_name: str,
    config: dict,
    canonical_duration: float | None = None,
    provider_override: str | None = None,
    voice_override: str | None = None,
    api_key_override: str | None = None,
    llm_api_key: str | None = None,
    llm_backend: str | None = None,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Generate the TTS track for a video and return result metadata.

    Args:
        video_id: Video identifier (used for SRT path and output filename).
        video_path: Path to the source MP4 (used as a duration fallback).
        language: Subtitle language code; the SRT must exist at
            data/srt/{video_id}_{language}.srt.
        voice_profile_name: Key into the voice profiles config.
        config: Full app config dict.
        canonical_duration: Trusted duration (e.g. from the video index).
            If provided and > 0 it is used directly; otherwise we fall back to
            ffprobe on `video_path`.
        provider_override: Override the profile's TTS provider (e.g. elevenlabs).
        voice_override: Override the profile's voice ID.
        api_key_override: Per-request TTS provider API key (elevenlabs/openai/google).
        llm_api_key: Per-request LLM API key for sentence detection + shortening.
        llm_backend: deepseek | anthropic | openai.
        on_progress: (current, total, message) callback for SSE.

    Returns:
        {"audio_path": str, "duration": float, "segment_count": int, "language": str}
    """
    from src.processor.subtitle import parse_srt
    from src.tts import get_tts_provider, load_voice_profiles
    from src.tts.assembler import TTSAssembler
    from src.utils.metadata import extract_metadata_from_file

    # ── Voice profile ────────────────────────────────────────────────
    profiles_data = load_voice_profiles(config)
    profiles = profiles_data.get("profiles", {})
    if voice_profile_name not in profiles:
        raise ValueError(
            f"Voice profile '{voice_profile_name}' not found. "
            f"Available: {list(profiles.keys())}"
        )
    voice_profile = profiles[voice_profile_name]
    if voice_override:
        voice_profile = {**voice_profile, "voice": voice_override}

    # ── SRT segments ─────────────────────────────────────────────────
    srt_dir = Path("data/srt")
    srt_path = srt_dir / f"{video_id}_{language}.srt"
    if not srt_path.exists():
        raise FileNotFoundError(
            f"SRT not found: {srt_path}. Translate to '{language}' first."
        )
    segments = parse_srt(srt_path)
    if not segments:
        raise ValueError(f"SRT file is empty: {srt_path}")

    # ── Video duration: trusted source first, ffprobe fallback ──────
    if canonical_duration and canonical_duration > 0:
        video_duration = canonical_duration
    else:
        file_meta = extract_metadata_from_file(video_path) if video_path.exists() else {}
        video_duration = float(file_meta.get("duration", 0.0))
    if video_duration <= 0:
        raise ValueError(
            f"Could not determine duration for {video_path}; cannot lay out TTS track"
        )

    # ── TTS provider with per-request API-key injection ─────────────
    provider_name = provider_override or voice_profile.get("provider", "edge")
    effective_config = config
    if api_key_override:
        tts_section = dict(config.get("tts", {}))
        if provider_name == "elevenlabs":
            tts_section["elevenlabs_api_key"] = api_key_override
        elif provider_name == "openai":
            tts_section["openai_api_key"] = api_key_override
        elif provider_name == "google":
            tts_section["google_api_key"] = api_key_override
        effective_config = {**config, "tts": tts_section}
    tts_provider = get_tts_provider(effective_config, provider=provider_name)

    # ── LLM translator (sentence detection + text shortening) ──────
    translator = _build_llm_translator(
        config, llm_api_key=llm_api_key, llm_backend=llm_backend
    )
    llm_caller = translator._call_llm if translator else None

    # ── Output path (canonical, shared by both callers) ────────────
    tts_dir = Path("data/tts")
    tts_dir.mkdir(parents=True, exist_ok=True)
    output_path = tts_output_path(
        tts_dir, video_id, language, provider_name, voice_profile_name
    )

    # ── Assemble ────────────────────────────────────────────────────
    assembler = TTSAssembler(translator=translator)
    await assembler.generate_full_track(
        provider=tts_provider,
        segments=segments,
        voice_profile=voice_profile,
        video_duration=video_duration,
        output_path=output_path,
        on_progress=on_progress,
        merge_sentences=True,
        llm_caller=llm_caller,
        srt_path=srt_path,
    )

    # ── Output duration via ffprobe (informational) ────────────────
    out_duration = 0.0
    try:
        import json
        import subprocess

        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(output_path)],
            capture_output=True, text=True, timeout=10,
        )
        out_duration = float(
            json.loads(probe.stdout).get("format", {}).get("duration", 0)
        )
    except Exception:  # noqa: BLE001 — informational only
        out_duration = 0.0

    return {
        "audio_path": str(output_path),
        "duration": out_duration,
        "segment_count": len(segments),
        "language": language,
    }
