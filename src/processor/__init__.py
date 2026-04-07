"""Processor module: subtitle burn-in and platform-specific video reformatting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from src.processor.ffmpeg import FFmpegProcessor
from src.processor.subtitle import select_subtitle_for_platform
from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.processor.region_detector import SubtitleRegion

logger = setup_logger(__name__)


@dataclass
class PlatformResult:
    """Result of processing a video for one platform."""

    output_path: Path
    subtitle_language: str  # language code actually used (e.g. "en", "vi")


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
    subtitle_language_overrides: dict[str, str] | None = None,
    tts_audio_paths: dict[str, Path] | None = None,
    tts_mix_settings: dict[str, dict] | None = None,
    subtitle_region: SubtitleRegion | None = None,
    blur_settings: dict | None = None,
) -> dict[str, PlatformResult]:
    """Process a video for all requested platforms.

    For each platform:
    1. Select the correct translated subtitle based on platform's subtitle_language
       (or user override if provided)
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
        subtitle_language_overrides: Optional per-platform language override.
            e.g. {"tiktok": "en", "youtube": "vi"} to override defaults.
        tts_audio_paths: Optional dict mapping platform name to TTS audio WAV path.
            If provided for a platform, uses burn_reformat_and_dub instead of burn_and_reformat.
        tts_mix_settings: Optional dict mapping platform name to mix settings
            (keys: 'original_volume', 'tts_volume').
        subtitle_region: Optional detected subtitle region for blur.
        blur_settings: Optional dict with blur_strength, blur_mode, fill_color.

    Returns:
        Dict mapping platform name to PlatformResult (output path + language used).
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
    results: dict[str, PlatformResult] = {}

    for i, platform in enumerate(platforms):
        platform_spec = all_platform_specs.get(platform, {})

        # Apply language override if user specified one for this platform
        effective_spec = dict(platform_spec)
        if subtitle_language_overrides and platform in subtitle_language_overrides:
            effective_spec["subtitle_language"] = subtitle_language_overrides[platform]

        if on_progress:
            pct = i / len(platforms)
            sub_lang = effective_spec.get("subtitle_language", "en")
            on_progress(platform, pct, f"Processing for {platform} ({sub_lang})...")

        # Select subtitle file
        srt_path = select_subtitle_for_platform(
            video_id, platform, srt_dir, effective_spec
        )

        if srt_path is None:
            logger.warning(f"Skipping {platform}: no subtitle file found for {video_id}")
            continue

        sub_lang = srt_path.stem.split("_")[-1]
        logger.info(f"Platform {platform}: using {sub_lang} subtitles ({srt_path.name})")

        # Merge styles — if blur is active, apply style matching from region
        p_style = platform_styles.get(platform, {})
        merged_style = _merge_styles(default_style, p_style, style_overrides)

        if subtitle_region is not None and blur_settings and blur_settings.get("auto_match_style", True):
            from src.processor.style_matcher import SubtitleStyleMatcher

            info = processor.get_video_info(video_path)
            matcher = SubtitleStyleMatcher()
            matched = matcher.match_style(
                subtitle_region, info["width"], info["height"], merged_style
            )
            merged_style.update(matched)

        # Output path
        output_path = output_dir / f"{video_id}_{platform}.mp4"

        # Determine blur params
        blur_kwargs = {}
        use_blur = subtitle_region is not None and blur_settings and blur_settings.get("enabled", True)
        if use_blur:
            blur_kwargs = {
                "region": subtitle_region,
                "blur_strength": blur_settings.get("blur_strength", 15),
                "blur_mode": blur_settings.get("blur_mode", "blur"),
                "fill_color": blur_settings.get("fill_color", "#000000"),
            }

        # Check if TTS audio is available for this platform
        tts_path = (tts_audio_paths or {}).get(platform)
        if tts_path and tts_path.exists():
            mix = (tts_mix_settings or {}).get(platform, {})
            original_vol = mix.get("original_volume", 0.3)
            tts_vol = mix.get("tts_volume", 1.0)
            logger.info(f"Platform {platform}: using TTS dubbing (orig={original_vol}, tts={tts_vol})")
            if use_blur:
                processor.blur_burn_reformat_and_dub(
                    video_path=video_path,
                    subtitle_path=srt_path,
                    tts_audio_path=tts_path,
                    platform=platform,
                    output_path=output_path,
                    style=merged_style,
                    platform_specs=platform_spec,
                    original_volume=original_vol,
                    tts_volume=tts_vol,
                    **blur_kwargs,
                )
            else:
                processor.burn_reformat_and_dub(
                    video_path=video_path,
                    subtitle_path=srt_path,
                    tts_audio_path=tts_path,
                    platform=platform,
                    output_path=output_path,
                    style=merged_style,
                    platform_specs=platform_spec,
                    original_volume=original_vol,
                    tts_volume=tts_vol,
                )
        elif use_blur:
            processor.blur_burn_and_reformat(
                video_path=video_path,
                subtitle_path=srt_path,
                platform=platform,
                output_path=output_path,
                style=merged_style,
                platform_specs=platform_spec,
                **blur_kwargs,
            )
        else:
            # Single-pass burn + reformat (no TTS, no blur)
            processor.burn_and_reformat(
                video_path=video_path,
                subtitle_path=srt_path,
                platform=platform,
                output_path=output_path,
                style=merged_style,
                platform_specs=platform_spec,
            )

        results[platform] = PlatformResult(
            output_path=output_path, subtitle_language=sub_lang
        )
        logger.info(f"Completed {platform}: {output_path}")

    if on_progress:
        on_progress("done", 1.0, "Processing complete")

    return results
