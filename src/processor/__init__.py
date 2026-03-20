"""Processor module: subtitle burn-in and platform-specific video reformatting."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from src.processor.ffmpeg import FFmpegProcessor
from src.processor.subtitle import select_subtitle_for_platform
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _load_subtitle_styles() -> dict:
    """Load subtitle styles from config file."""
    config_path = Path("config/subtitle_styles.yaml")
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f)
    return {"default": {"font_name": "Arial", "font_size": 24}}


def _merge_styles(default: dict, platform_override: dict, user_override: dict | None) -> dict:
    """Merge style dicts: default <- platform override <- user override."""
    merged = {**default}
    merged.update(platform_override)
    if user_override:
        merged.update(user_override)
    return merged


def process_for_all_platforms(
    video_id: str,
    video_path: Path,
    srt_dir: Path,
    output_dir: Path,
    platforms: list[str],
    config: dict,
    style_overrides: dict | None = None,
    on_progress: Callable[[str, float, str], None] | None = None,
) -> dict[str, Path]:
    """Process a video for all requested platforms.

    For each platform:
    1. Select the correct translated subtitle based on platform's subtitle_language
    2. Merge default style + platform override + user override
    3. Burn subtitles + reformat in a single ffmpeg pass

    Args:
        video_id: Video identifier.
        video_path: Path to source video.
        srt_dir: Directory containing SRT files.
        output_dir: Directory for output videos.
        platforms: List of platform names to process.
        config: Full config dict (may contain platform and style sections).
        style_overrides: Optional user style overrides.
        on_progress: Callback(platform, progress_pct, message) for progress updates.

    Returns:
        Dict mapping platform name to output video path.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load platform specs
    platforms_config_path = Path("config/platforms.yaml")
    if platforms_config_path.exists():
        with open(platforms_config_path) as f:
            all_platform_specs = yaml.safe_load(f)
    else:
        all_platform_specs = {}

    # Load subtitle styles
    styles = _load_subtitle_styles()
    default_style = styles.get("default", {})
    platform_styles = styles.get("platforms", {})

    processor = FFmpegProcessor(config.get("ffmpeg", {}))
    results: dict[str, Path] = {}

    for i, platform in enumerate(platforms):
        platform_spec = all_platform_specs.get(platform, {})

        if on_progress:
            pct = i / len(platforms)
            sub_lang = platform_spec.get("subtitle_language", "en")
            on_progress(platform, pct, f"Processing for {platform} ({sub_lang})...")

        # Select subtitle file
        srt_path = select_subtitle_for_platform(video_id, platform, srt_dir, platform_spec)

        if srt_path is None:
            logger.warning(f"Skipping {platform}: no subtitle file found for {video_id}")
            continue

        sub_lang = srt_path.stem.split("_")[-1]
        logger.info(f"Platform {platform}: using {sub_lang} subtitles ({srt_path.name})")

        # Merge styles
        p_style = platform_styles.get(platform, {})
        merged_style = _merge_styles(default_style, p_style, style_overrides)

        # Output path
        output_path = output_dir / f"{video_id}_{platform}.mp4"

        # Single-pass burn + reformat
        processor.burn_and_reformat(
            video_path=video_path,
            subtitle_path=srt_path,
            platform=platform,
            output_path=output_path,
            style=merged_style,
            platform_specs=platform_spec,
        )

        results[platform] = output_path
        logger.info(f"Completed {platform}: {output_path}")

    if on_progress:
        on_progress("done", 1.0, "Processing complete")

    return results
