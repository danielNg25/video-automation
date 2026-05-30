"""Shared TTS-track runner used by both the per-video API and the full pipeline.

This is the single place where voice profile resolution, TTS provider/API-key
plumbing, LLM-translator setup (with backend-aware default model and per-request
override priority), SRT loading, video-duration fallback, output filename, and
the final `TTSAssembler.generate_full_track` invocation live. Both callers
(`tm.run_tts` and `Pipeline.process_single`) must route through this so they
produce byte-identical output for identical inputs.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from src.tts import get_tts_provider  # re-exported for patching in tests
from src.utils.logger import setup_logger

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

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

    Keys come from the request body (Settings UI sends them per request) — the
    server never reads API keys from environment variables or YAML config.
    Returns the constructed LLMTranslator or None if no key is provided.
    """
    try:
        from src.translator.llm import LLMTranslator
    except Exception as e:  # pragma: no cover — only fires if the module is broken
        logger.warning(f"Could not import LLMTranslator: {e}")
        return None

    trans_cfg = config.get("translation", {})
    backend = llm_backend or trans_cfg.get("backend", "deepseek")
    api_key = llm_api_key
    base_url = trans_cfg.get("base_url")
    if backend == "deepseek" and not base_url:
        base_url = "https://api.deepseek.com/v1"

    logger.info(
        f"TTS shortening init: llm_api_key={'yes' if llm_api_key else 'no'}, "
        f"llm_backend={llm_backend}"
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
    voice_id: str,
) -> Path:
    """Canonical output filename used by both flows."""
    safe_voice = voice_id.replace("/", "-").replace(" ", "-")
    return tts_dir / f"{video_id}_{language}_{provider_name}_{safe_voice}.wav"


def dub_output_filename(
    video_id: str,
    language: str,
    version: str,
    provider: str,
    voice: str,
) -> Path:
    """Canonical path for a dub WAV.

    Layout: data/tts/{video_id}_{language}_{version}_{provider}_{voice}.wav.

    `voice` may contain characters that aren't safe in a filename (Google
    voice ids historically include '/'); they are replaced with '-'.
    """
    safe_voice = _FILENAME_SAFE.sub("-", voice)
    safe_provider = _FILENAME_SAFE.sub("-", provider)
    return Path(
        f"data/tts/{video_id}_{language}_{version}_{safe_provider}_{safe_voice}.wav"
    )


async def run_tts_track(
    *,
    video_id: str,
    video_path: Path,
    language: str,
    voice: str,
    provider: str = "google",
    config: dict,
    canonical_duration: float | None = None,
    api_key_override: str | None = None,
    llm_api_key: str | None = None,
    llm_backend: str | None = None,
    playback_speed: float | None = None,
    version: str = "draft",
    enable_shortening: bool = True,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    # Coerce request-supplied playback_speed in case it arrived as a string
    # (e.g. from config.yaml interpolation in some future use, or a misbehaving
    # client). Runner is the boundary where types should be normalised.
    if playback_speed is not None and not isinstance(playback_speed, (int, float)):
        try:
            playback_speed = float(playback_speed)
        except (TypeError, ValueError):
            logger.warning(
                f"playback_speed is not numeric ({playback_speed!r}); "
                f"falling back to assembler default"
            )
            playback_speed = None
    """Generate the TTS track for a video and return result metadata.

    Args:
        video_id: Video identifier (used for SRT path and output filename).
        video_path: Path to the source MP4 (used as a duration fallback).
        language: Subtitle language code; the SRT must exist at
            data/srt/{video_id}_{language}.srt.
        voice: Provider's voice ID (e.g. 'vi-VN-Wavenet-A'). Required.
        provider: TTS provider name ('google' | 'elevenlabs' | 'openai').
        config: Full app config dict.
        canonical_duration: Trusted duration (e.g. from the video index).
            If provided and > 0 it is used directly; otherwise we fall back to
            ffprobe on `video_path`.
        api_key_override: Per-request TTS provider API key (elevenlabs/openai/google).
        llm_api_key: Per-request LLM API key for sentence detection + shortening.
        llm_backend: deepseek | anthropic | openai.
        on_progress: (current, total, message) callback for SSE.

    Returns:
        {"audio_path": str, "duration": float, "segment_count": int, "language": str}
    """
    from src.processor.subtitle import parse_srt
    from src.tts.assembler import TTSAssembler
    from src.utils.metadata import extract_metadata_from_file

    # The voice profile is now a tiny dict built from explicit kwargs; no
    # YAML lookup. Optional speed/pitch could be added later if a future UI
    # exposes them — providers default to no adjustment when absent.
    voice_profile = {"voice": voice}

    # ── SRT segments ─────────────────────────────────────────────────
    srt_dir = Path("data/srt")
    if version == "draft":
        srt_path = srt_dir / f"{video_id}_{language}.srt"
    else:
        srt_path = srt_dir / f"{video_id}_{language}.{version}.srt"
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
    provider_name = provider
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
    output_path = dub_output_filename(video_id, language, version, provider_name, voice)

    # ── Assemble ────────────────────────────────────────────────────
    # Pull the underlay_db default from config so the assembler uses
    # the same value the processor will use when mixing.
    underlay_db_cfg = config.get("tts", {}).get("underlay_db")
    try:
        underlay_db_val = float(underlay_db_cfg) if underlay_db_cfg is not None else None
    except (TypeError, ValueError):
        underlay_db_val = None

    assembler = TTSAssembler(translator=translator)
    _, sentence_plan = await assembler.generate_full_track(
        provider=tts_provider,
        segments=segments,
        voice_profile=voice_profile,
        video_duration=video_duration,
        output_path=output_path,
        on_progress=on_progress,
        merge_sentences=True,
        llm_caller=llm_caller,
        srt_path=srt_path,
        playback_speed=playback_speed,
        video_id=video_id,
        language=language,
        provider_name=provider_name,
        underlay_db=underlay_db_val,
        enable_shortening=enable_shortening,
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

    review_count = sum(1 for s in sentence_plan if s.get("needs_review"))

    # Write a per-sentence plan log alongside the WAV so the user can review
    # final speed_ratio, shortened text, and which sentences hit the cap.
    # JSON for machine use; TSV for quick eyeballing in a terminal.
    plan_log_path = output_path.with_suffix(".plan.json")
    plan_tsv_path = output_path.with_suffix(".plan.tsv")
    try:
        import json as _json

        plan_payload = {
            "video_id": video_id,
            "language": language,
            "provider": provider_name,
            "voice": voice,
            "playback_speed_requested": playback_speed,
            "audio_path": str(output_path),
            "audio_duration": out_duration,
            "video_duration": video_duration,
            "total_sentences": len(sentence_plan),
            "review_count": review_count,
            "sentences": sentence_plan,
        }
        plan_log_path.write_text(_json.dumps(plan_payload, ensure_ascii=False, indent=2))

        # Tab-separated text view for quick review (sortable, greppable).
        # Includes `fitted_duration` (the actual length of audio mixed into
        # the WAV after atempo) so any mismatch between requested speedup
        # and actual sped-up duration is visible.
        lines = [
            "idx\twindow_start\twindow_end\twindow_size\tsynth_dur\tfitted_dur\trequested\tapplied\tneeds_review\treason\ttext"
        ]
        for s in sentence_plan:
            ws = s.get("window_start", 0.0)
            we = s.get("window_end", 0.0)
            text = (s.get("text") or "").replace("\t", " ").replace("\n", " ")[:120]
            lines.append(
                f"{s.get('index', '')}\t"
                f"{ws:.2f}\t{we:.2f}\t{we - ws:.2f}\t"
                f"{s.get('synth_duration', 0.0):.2f}\t"
                f"{s.get('fitted_duration', 0.0):.2f}\t"
                f"{s.get('requested_ratio', 0.0):.3f}\t"
                f"{s.get('speed_ratio', 0.0):.3f}\t"
                f"{'YES' if s.get('needs_review') else ''}\t"
                f"{s.get('reason') or ''}\t"
                f"{text}"
            )
        plan_tsv_path.write_text("\n".join(lines) + "\n")
        logger.info(f"Wrote dub plan logs: {plan_log_path.name}, {plan_tsv_path.name}")
    except Exception as e:  # noqa: BLE001 — log file is informational only
        logger.warning(f"Could not write dub plan log: {e}")

    return {
        "audio_path": str(output_path),
        "duration": out_duration,
        "segment_count": len(segments),
        "language": language,
        "sentence_plan": sentence_plan,
        "review_count": review_count,
        "plan_log_path": str(plan_log_path),
        "plan_tsv_path": str(plan_tsv_path),
    }


# Public aliases — callers outside this module should import these names so
# they don't cross module boundaries importing leading-underscore private names.
build_llm_translator = _build_llm_translator
