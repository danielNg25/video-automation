"""Translation module: LLM-based subtitle translation with style profiles."""

from __future__ import annotations

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
) -> Path:
    """High-level: load profile, create translator, translate, return output path."""
    profile = load_profile(profile_name)
    translator = get_translator(config)

    video_stem = srt_path.stem.rsplit("_", 1)[0]  # e.g., "abc123_zh" -> "abc123"
    output_path = output_dir / f"{video_stem}_{profile.target_language}.srt"

    return await translator.translate_srt(
        srt_path, profile, output_path, progress_callback=progress_callback
    )
