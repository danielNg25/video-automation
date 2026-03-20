import json
import subprocess
from dataclasses import dataclass, field
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
