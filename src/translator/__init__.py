"""Translation module: LLM-based subtitle translation with style profiles."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

from src.translator.llm import LLMTranslator
from src.translator.profiles import load_profile
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_translator(config: dict) -> LLMTranslator:
    """Factory: return a configured LLM translator from config['translation']."""
    trans_cfg = config.get("translation", {})
    return LLMTranslator(
        backend=trans_cfg.get("backend", "anthropic"),
        model=trans_cfg.get("model", "claude-sonnet-4-20250514"),
        api_key=trans_cfg.get("api_key"),
        base_url=trans_cfg.get("base_url"),
        max_segments_per_batch=trans_cfg.get("max_segments_per_batch", 8),
        full_document_threshold=trans_cfg.get("full_document_threshold", 100),
        chunk_size=trans_cfg.get("chunk_size", 50),
        temperature=trans_cfg.get("temperature", 0.7),
        skip_noise=trans_cfg.get("skip_noise", True),
    )


async def translate_with_profile(
    srt_path: Path,
    profile_name: str,
    config: dict,
    output_dir: Path,
    progress_callback: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> Path | None:
    """High-level: load profile, translate, publish the output SRT.

    Translation is staged to a temp file and only published (atomic rename)
    when the run was not cancelled — so a cancel during translation can't
    overwrite an existing translated SRT. Returns the published path, or
    ``None`` if the run was cancelled before publication.
    """
    profile = load_profile(profile_name)
    translator = get_translator(config)

    video_stem = srt_path.stem.rsplit("_", 1)[0]  # e.g., "abc123_zh" -> "abc123"
    final_path = output_dir / f"{video_stem}_{profile.target_language}.srt"
    # Containment: a crafted profile target_language (e.g. "x/../../outside")
    # must not move the output outside output_dir. Legitimate tags like "vi"
    # or "vi-VN" keep the parent unchanged; an escape changes it.
    if final_path.parent.resolve() != output_dir.resolve():
        raise ValueError(
            f"Unsafe target_language in profile {profile_name!r}: "
            f"{profile.target_language!r}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = output_dir / f".{video_stem}_{profile.target_language}.{uuid.uuid4().hex}.tmp.srt"

    try:
        await translator.translate_srt(
            srt_path, profile, tmp_path, progress_callback=progress_callback
        )
        if should_cancel and should_cancel():
            tmp_path.unlink(missing_ok=True)
            return None
        os.replace(tmp_path, final_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return final_path
