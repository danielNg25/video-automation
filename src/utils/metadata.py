"""Video metadata utilities and per-platform metadata mapping."""

from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class VideoMetadata:
    """Metadata for a downloaded video."""

    video_id: str
    title: str = ""
    author: str = ""
    duration: float = 0.0
    resolution: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    source_url: str = ""
    file_path: str = ""
    thumbnail_url: str = ""


def extract_metadata_from_file(path: Path) -> dict:
    """Extract video metadata using ffprobe.

    Args:
        path: Path to video file.

    Returns:
        Dict with duration, resolution, and codec info.
    """
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        probe_data = json.loads(result.stdout)
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError):
        return {}

    metadata = {}

    # Extract duration from format
    fmt = probe_data.get("format", {})
    if "duration" in fmt:
        metadata["duration"] = float(fmt["duration"])

    # Extract resolution from first video stream
    for stream in probe_data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width", 0)
            height = stream.get("height", 0)
            metadata["resolution"] = f"{width}x{height}"
            metadata["codec"] = stream.get("codec_name", "")
            break

    return metadata


# --- Per-platform metadata mapping ---

# Platform-specific limits
PLATFORM_LIMITS = {
    "youtube": {"title_max": 100, "description_max": 5000},
    "youtube_shorts": {"title_max": 100, "description_max": 5000},
    "tiktok": {"title_max": 150, "description_max": 2200},
    "facebook": {"title_max": 255, "description_max": 5000},
    "x": {"title_max": 280, "description_max": 280},
}


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if it exceeds max length."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "\u2026"


def _format_hashtags(tags: list[str]) -> str:
    """Format hashtags with # prefix."""
    return " ".join(f"#{tag.lstrip('#')}" for tag in tags if tag.strip())


def map_metadata(
    source_meta: VideoMetadata | dict,
    platform: str,
    overrides: dict | None = None,
) -> dict:
    """Map Douyin video metadata to platform-specific format.

    Applies per-platform formatting rules:
    - YouTube: Append #Shorts if short-form. Title max 100 chars.
    - TikTok: Hashtags in description. Description max 2200 chars.
    - Facebook: Standard title + description.
    - X/Twitter: Tweet text max 280 chars.

    Args:
        source_meta: Original VideoMetadata or dict.
        platform: Target platform name.
        overrides: User overrides applied last (title, description, tags, privacy).

    Returns:
        Dict with platform-formatted title, description, tags, privacy.
    """
    if isinstance(source_meta, VideoMetadata):
        meta = asdict(source_meta)
    else:
        meta = dict(source_meta)

    overrides = overrides or {}
    limits = PLATFORM_LIMITS.get(platform, PLATFORM_LIMITS.get("facebook", {}))

    title = overrides.get("title", meta.get("title", ""))
    description = overrides.get("description", meta.get("description", ""))
    hashtags = overrides.get("tags", meta.get("hashtags", []))
    if isinstance(hashtags, str):
        hashtags = [t.strip() for t in hashtags.split(",") if t.strip()]
    privacy = overrides.get("privacy", "private")

    # Platform-specific formatting
    if platform in ("youtube", "youtube_shorts"):
        # Append #Shorts for short-form
        duration = meta.get("duration", 0)
        if platform == "youtube_shorts" or (duration and duration <= 60):
            if "#Shorts" not in title:
                title = f"{title} #Shorts".strip()
        # Hashtags go at end of description
        if hashtags:
            tag_str = _format_hashtags(hashtags)
            description = f"{description}\n\n{tag_str}".strip()

    elif platform == "tiktok":
        # TikTok: hashtags in description, not separate
        if hashtags:
            tag_str = _format_hashtags(hashtags)
            description = f"{description}\n{tag_str}".strip()

    elif platform == "x":
        # X: combine into single tweet-like text
        if hashtags:
            tag_str = _format_hashtags(hashtags[:3])  # limit to 3 tags for space
            description = f"{description}\n{tag_str}".strip()

    # Enforce character limits
    title_max = limits.get("title_max", 100)
    desc_max = limits.get("description_max", 5000)

    return {
        "title": _truncate(title, title_max),
        "description": _truncate(description, desc_max),
        "tags": hashtags,
        "privacy": privacy,
        "platform": platform,
    }
