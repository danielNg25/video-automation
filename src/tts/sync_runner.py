"""Sync runner — partial dub regeneration after subtitle edits.

Reuses cached natural-speed clips for unchanged segments and re-synthesises
only the changed ones, then delegates to the existing planner + assembler
for re-running the plan and re-assembling the WAV.

Fallback triggers (force full regen):
- > 50% of segments are dirty
- Segment count changed
- Provider / voice_id / playback_speed / underlay_db mismatch with dub_meta

When falling back, this module delegates to the existing dub runner
(`src.tts.runner.run_tts_track`) so the behaviour is byte-identical to a
fresh dub generation kicked off from the per-video TTS endpoint.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from src.api.deps import get_config
from src.tts.base import _clean_text
from src.tts.dub_meta import DubMeta, load_dub_meta
from src.tts.segment_cache import load_segment_clip
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

DIRTY_THRESHOLD_RATIO = 0.5     # > 50% dirty → fall back to full regen


def identify_dirty_segments(
    saved_texts: list[str], new_texts: list[str]
) -> list[int]:
    """Indices of segments whose text differs (after _clean_text normalisation).

    When the lengths differ we treat every index up to the larger length as
    dirty — callers should fall back to a full regen in that case, but the
    list is still useful for diagnostics.
    """
    if len(saved_texts) != len(new_texts):
        return list(range(max(len(saved_texts), len(new_texts))))
    dirty: list[int] = []
    for i, (old, new) in enumerate(zip(saved_texts, new_texts)):
        if _clean_text(old) != _clean_text(new):
            dirty.append(i)
    return dirty


def should_fall_back_to_full_regen(
    meta: DubMeta,
    current_params: dict,
    new_texts: list[str],
) -> tuple[bool, str]:
    """Return (should_fall_back, reason).

    Triggers (in order checked):
      - segment_count_changed: len(meta.segment_texts) != len(new_texts)
      - provider_mismatch
      - voice_id_mismatch
      - playback_speed_mismatch (tol 0.01)
      - underlay_db_mismatch (tol 0.01)
      - majority_dirty: > 50% of segments need re-synthesis
    """
    if len(meta.segment_texts) != len(new_texts):
        return (True, "segment_count_changed")
    if meta.provider != current_params.get("provider"):
        return (True, "provider_mismatch")
    if meta.voice_id != current_params.get("voice_id"):
        return (True, "voice_id_mismatch")
    try:
        req_speed = float(current_params.get("playback_speed", 1.0))
    except (TypeError, ValueError):
        req_speed = 1.0
    if abs(meta.playback_speed - req_speed) > 0.01:
        return (True, "playback_speed_mismatch")
    try:
        req_underlay = float(current_params.get("underlay_db", 0.0))
    except (TypeError, ValueError):
        req_underlay = 0.0
    if abs(meta.underlay_db - req_underlay) > 0.01:
        return (True, "underlay_db_mismatch")

    dirty = identify_dirty_segments(meta.segment_texts, new_texts)
    if len(dirty) > len(new_texts) * DIRTY_THRESHOLD_RATIO:
        return (True, "majority_dirty")

    return (False, "")


async def run_dub_sync(
    video_id: str,
    language: str,
    new_texts: list[str],
    current_params: dict,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> dict:
    """Top-level sync entry point.

    Loads dub_meta + segment cache, decides between partial / full regen,
    and dispatches. Always returns a dict with:
        mode:         'partial' | 'full'
        dirty_count:  number of segments re-synthesised
        reason:       fallback reason (only when mode == 'full')
    """
    tts_data_dir = Path("data/tts")
    meta = load_dub_meta(tts_data_dir, video_id, language)
    if meta is None:
        logger.info(
            f"No dub_meta for {video_id}/{language} — falling back to full regen"
        )
        await _run_full_regen(video_id, language, current_params, on_progress)
        return {
            "mode": "full",
            "dirty_count": len(new_texts),
            "reason": "no_meta",
        }

    should_fall_back, reason = should_fall_back_to_full_regen(
        meta, current_params, new_texts
    )
    if should_fall_back:
        logger.info(f"Sync-Dub falling back to full regen: {reason}")
        await _run_full_regen(video_id, language, current_params, on_progress)
        return {
            "mode": "full",
            "dirty_count": len(new_texts),
            "reason": reason,
        }

    dirty = identify_dirty_segments(meta.segment_texts, new_texts)
    logger.info(
        f"Sync-Dub partial: {len(dirty)} dirty / {len(new_texts)} total"
    )

    # Build clip_overrides from cache for unchanged segments.
    clip_overrides: dict[int, Path] = {}
    missing_cache: list[int] = []
    for i in range(len(new_texts)):
        if i in dirty:
            continue
        cached = load_segment_clip(tts_data_dir, video_id, language, i)
        if cached is not None:
            clip_overrides[i] = cached
        else:
            missing_cache.append(i)

    if missing_cache:
        # Treat missing-cache indices as dirty so they get re-synthesised
        # rather than left silent. This shouldn't happen if Stage 1.5 ran
        # cleanly, but guards against partial caches from older dubs.
        logger.info(
            f"Sync-Dub: {len(missing_cache)} cached clips missing, "
            f"will re-synthesise: {missing_cache}"
        )
        dirty = sorted(set(dirty) | set(missing_cache))

    await _run_partial_regen(
        video_id=video_id,
        language=language,
        new_texts=new_texts,
        dirty_indices=dirty,
        clip_overrides=clip_overrides,
        meta=meta,
        current_params=current_params,
        on_progress=on_progress,
    )
    return {"mode": "partial", "dirty_count": len(dirty)}


async def _run_full_regen(
    video_id: str,
    language: str,
    params: dict,
    on_progress: Callable[[int, int, str], None] | None,
) -> None:
    """Delegate to the existing full dub runner.

    The runner needs a voice_profile_name (key in voice profiles config);
    when the caller didn't supply one (Sync-Dub endpoint doesn't take it),
    we synthesise an ephemeral profile name and inject a matching profile
    into the runner's voice-profile lookup via override args.

    The runner reads `voice_profile_name` to look up the provider+voice,
    but we already have those in `params` — so we use voice_override +
    provider_override and pick an arbitrary existing profile name as the
    base (just so the lookup doesn't fail).
    """
    from src.tts import load_voice_profiles
    from src.tts.runner import run_tts_track

    config = get_config()

    # Find the video file path. Both the API task manager and the CLI
    # pipeline put MP4s in data/raw, so derive the path directly rather
    # than depending on a TaskManager instance (this code runs inside the
    # event loop kicked off by the API endpoint, but tests may not have
    # the singleton populated).
    video_path = Path("data/raw") / f"{video_id}.mp4"

    # Pick any existing voice profile as the base — its provider/voice
    # gets overridden anyway.
    profiles_data = load_voice_profiles(config)
    profiles = profiles_data.get("profiles", {})
    if not profiles:
        raise RuntimeError("No voice profiles configured; cannot run full regen")
    base_profile_name = next(iter(profiles.keys()))

    # Inject underlay_db into the config the runner sees so dub_meta
    # records the requested value.
    underlay_db = params.get("underlay_db")
    effective_config = config
    if underlay_db is not None:
        tts_section = dict(config.get("tts", {}))
        tts_section["underlay_db"] = float(underlay_db)
        effective_config = {**config, "tts": tts_section}

    # Bridge our (current, total, message) progress into the runner's
    # callback shape, which is also (current, total, message).
    runner_progress = on_progress

    await run_tts_track(
        video_id=video_id,
        video_path=video_path,
        language=language,
        voice_profile_name=base_profile_name,
        config=effective_config,
        provider_override=params.get("provider"),
        voice_override=params.get("voice_id"),
        api_key_override=params.get("api_key"),
        playback_speed=params.get("playback_speed"),
        on_progress=runner_progress,
    )


async def _run_partial_regen(
    video_id: str,
    language: str,
    new_texts: list[str],
    dirty_indices: list[int],
    clip_overrides: dict[int, Path],
    meta: DubMeta,
    current_params: dict,
    on_progress: Callable[[int, int, str], None] | None,
) -> None:
    """Re-synthesise dirty segments only; use cache for the rest.

    Delegates to `Assembler.run_partial` which mirrors Stages 1.5–7 of
    `generate_full_track` but accepts `clip_overrides` for cached
    natural-speed clips.
    """
    from src.tts import get_tts_provider, load_voice_profiles
    from src.tts.assembler import TTSAssembler

    config = get_config()

    # Find the source MP4 for the canonical duration.
    video_path = Path("data/raw") / f"{video_id}.mp4"

    # Build a TTS provider, injecting the per-request API key into config.
    provider_name = meta.provider
    effective_config = config
    api_key = current_params.get("api_key")
    if api_key:
        tts_section = dict(config.get("tts", {}))
        if provider_name == "elevenlabs":
            tts_section["elevenlabs_api_key"] = api_key
        elif provider_name == "openai":
            tts_section["openai_api_key"] = api_key
        elif provider_name == "google":
            tts_section["google_api_key"] = api_key
        effective_config = {**config, "tts": tts_section}
    tts_provider = get_tts_provider(effective_config, provider=provider_name)

    # Pick a base voice profile to inherit speed/pitch kwargs from.
    profiles_data = load_voice_profiles(config)
    profiles = profiles_data.get("profiles", {})
    base_profile = next(iter(profiles.values()), {}) if profiles else {}

    voice_profile = {**base_profile, "voice": meta.voice_id}

    # Output path mirrors the runner's tts_output_path so subsequent dub
    # consumers (processor) pick up the right file.
    safe_profile = "sync"
    tts_dir = Path("data/tts")
    tts_dir.mkdir(parents=True, exist_ok=True)
    output_path = (
        tts_dir
        / f"{video_id}_{language}_{provider_name}_{safe_profile}.wav"
    )

    # Build a translator for Stage 3 LLM shortening, mirroring runner.py's
    # _build_llm_translator so the partial path is behaviorally equivalent
    # to the full dub path.
    from src.tts.runner import _build_llm_translator

    translator = _build_llm_translator(
        config,
        llm_api_key=current_params.get("llm_api_key"),
        llm_backend=current_params.get("llm_backend"),
    )

    assembler = TTSAssembler(translator=translator)
    await assembler.run_partial(
        provider=tts_provider,
        video_id=video_id,
        language=language,
        new_texts=new_texts,
        clip_overrides=clip_overrides,
        dirty_indices=dirty_indices,
        voice_profile=voice_profile,
        provider_name=provider_name,
        playback_speed=meta.playback_speed,
        underlay_db=meta.underlay_db,
        video_path=video_path,
        output_path=output_path,
        on_progress=on_progress,
    )
