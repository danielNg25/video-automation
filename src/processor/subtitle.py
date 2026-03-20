import re
from pathlib import Path

from src.transcriber import get_transcriber
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


def translate_srt(
    srt_path: Path,
    video_path: str | None = None,
    whisper_config: dict | None = None,
    method: str = "whisper",
) -> Path:
    """Translate an SRT file from Chinese to English.

    Args:
        srt_path: Path to source SRT file.
        video_path: Path to source video (required for whisper method).
        whisper_config: Whisper config dict (required for whisper method).
        method: Translation method - 'whisper' or 'deepl'.

    Returns:
        Path to translated SRT file.
    """
    output_path = srt_path.with_name(srt_path.stem.replace("_zh", "") + "_en.srt")

    if method == "whisper":
        if not video_path or not whisper_config:
            raise ValueError("video_path and whisper_config required for whisper translation")

        transcriber = get_transcriber(whisper_config)
        segments = transcriber.transcribe(video_path, language="zh", task="translate")
        transcriber.generate_srt(segments, output_path)
        logger.info(f"Translated via Whisper: {output_path}")

    elif method == "deepl":
        logger.warning("DeepL translation not yet implemented")
        raise NotImplementedError("DeepL translation support is planned for a future release")

    else:
        raise ValueError(f"Unknown translation method: {method}")

    return output_path
