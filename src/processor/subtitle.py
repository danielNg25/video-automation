import re
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def parse_srt(srt_path: Path) -> list[dict]:
    """Parse an SRT file into a list of segment dicts.

    Args:
        srt_path: Path to SRT file.

    Returns:
        List of dicts with 'index', 'start', 'end', 'text' keys.
    """
    content = srt_path.read_text(encoding="utf-8")
    segments = []

    blocks = re.split(r"\n\n+", content.strip())
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue

        index = int(lines[0])
        timestamp_match = re.match(
            r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})",
            lines[1],
        )
        if not timestamp_match:
            continue

        text = "\n".join(lines[2:])
        segments.append(
            {
                "index": index,
                "start": _timestamp_to_seconds(timestamp_match.group(1)),
                "end": _timestamp_to_seconds(timestamp_match.group(2)),
                "text": text,
            }
        )

    return segments


def _timestamp_to_seconds(ts: str) -> float:
    """Convert SRT timestamp (HH:MM:SS,mmm) to seconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def _seconds_to_srt_timestamp(seconds: float) -> str:
    """Convert seconds to SRT timestamp format (HH:MM:SS,mmm)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(segments: list[dict], output_path: Path) -> Path:
    """Write segments to an SRT file.

    Inverse of parse_srt(). Renumbers segments sequentially.

    Args:
        segments: List of dicts with 'start' (float seconds), 'end' (float seconds), 'text'.
        output_path: Path for output SRT file.

    Returns:
        Path to written SRT file.
    """
    lines = []
    for i, seg in enumerate(segments, start=1):
        start_ts = _seconds_to_srt_timestamp(seg["start"])
        end_ts = _seconds_to_srt_timestamp(seg["end"])
        lines.append(f"{i}\n{start_ts} --> {end_ts}\n{seg['text']}\n\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Wrote SRT file: {output_path} ({len(segments)} segments)")
    return output_path
