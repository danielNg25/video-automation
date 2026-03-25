import re
import textwrap
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Fallback chain for subtitle language selection
_LANGUAGE_FALLBACK = ["en", "vi", "zh"]


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



def _seconds_to_ass_timestamp(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds % 1) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


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


def break_long_lines(text: str, max_chars: int = 40) -> str:
    """Break text at word boundaries if exceeding max_chars per line.

    Args:
        text: Subtitle text (may already contain newlines).
        max_chars: Maximum characters per line.

    Returns:
        Text with lines wrapped at word boundaries.
    """
    result_lines = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            result_lines.append(line)
        else:
            wrapped = textwrap.fill(
                line, width=max_chars, break_long_words=False, break_on_hyphens=True
            )
            result_lines.append(wrapped)
    return "\n".join(result_lines)


def srt_to_ass(srt_path: Path, style_config: dict, output_path: Path) -> Path:
    """Convert SRT to styled ASS format.

    Args:
        srt_path: Path to source SRT file.
        style_config: Style dict with font_name, font_size, primary_color, etc.
        output_path: Path for output ASS file.

    Returns:
        Path to generated ASS file.
    """
    segments = parse_srt(srt_path)

    font_name = style_config.get("font_name", "Arial")
    font_size = style_config.get("font_size", 24)
    primary_color = style_config.get("primary_color", "&H00FFFFFF")
    outline_color = style_config.get("outline_color", "&H00000000")
    outline_width = style_config.get("outline_width", 2)
    shadow_depth = style_config.get("shadow_depth", 1)
    alignment = style_config.get("alignment", 2)
    margin_v = style_config.get("margin_v", 30)
    margin_h = style_config.get("margin_h", 0)
    bold = -1 if style_config.get("bold", True) else 0

    # Background: BorderStyle=3 (opaque box) when background_color is set
    back_colour = style_config.get("background_color", "")
    bg_opacity = style_config.get("background_opacity", 0)
    if back_colour:
        back_colour_val = back_colour
        border_style = 3  # opaque box behind text
    elif bg_opacity > 0:
        # Semi-transparent black background from opacity alone
        alpha_hex = f"{bg_opacity:02X}"
        back_colour_val = f"&H{alpha_hex}000000"
        border_style = 3
    else:
        back_colour_val = "&H00000000"
        border_style = 1  # normal outline + shadow

    margin_l = max(0, 10 + margin_h)
    margin_r = max(0, 10 - margin_h)

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{primary_color},&H000000FF,"
        f"{outline_color},{back_colour_val},{bold},0,0,0,100,100,0,0,{border_style},"
        f"{outline_width},{shadow_depth},{alignment},{margin_l},{margin_r},{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for seg in segments:
        start = _seconds_to_ass_timestamp(seg["start"])
        end = _seconds_to_ass_timestamp(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Generated ASS file: {output_path} ({len(segments)} segments)")
    return output_path


def merge_subtitles(primary_srt: Path, secondary_srt: Path, output_path: Path) -> Path:
    """Create dual-line subtitle file (primary line above, secondary below).

    Aligns segments by timestamp overlap. Each output block has primary text
    on the first line and secondary text on the second line.

    Args:
        primary_srt: Path to primary language SRT (e.g., English).
        secondary_srt: Path to secondary language SRT (e.g., Vietnamese).
        output_path: Path for merged SRT output.

    Returns:
        Path to merged SRT file.
    """
    primary_segs = parse_srt(primary_srt)
    secondary_segs = parse_srt(secondary_srt)

    merged = []
    sec_idx = 0
    for p_seg in primary_segs:
        combined_text = p_seg["text"]

        # Find best matching secondary segment by overlap
        best_overlap = 0.0
        best_sec = None
        for j in range(max(0, sec_idx - 1), len(secondary_segs)):
            s_seg = secondary_segs[j]
            if s_seg["start"] > p_seg["end"]:
                break
            overlap_start = max(p_seg["start"], s_seg["start"])
            overlap_end = min(p_seg["end"], s_seg["end"])
            overlap = max(0.0, overlap_end - overlap_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_sec = s_seg
                sec_idx = j

        if best_sec and best_overlap > 0:
            combined_text = p_seg["text"] + "\n" + best_sec["text"]

        merged.append(
            {
                "index": len(merged) + 1,
                "start": p_seg["start"],
                "end": p_seg["end"],
                "text": combined_text,
            }
        )

    # Write merged SRT
    lines = []
    for seg in merged:
        start_ts = _seconds_to_srt_timestamp(seg["start"])
        end_ts = _seconds_to_srt_timestamp(seg["end"])
        lines.append(f"{seg['index']}\n{start_ts} --> {end_ts}\n{seg['text']}\n\n")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Merged subtitles: {output_path} ({len(merged)} segments)")
    return output_path


def select_subtitle_for_platform(
    video_id: str, platform: str, srt_dir: Path, platform_config: dict
) -> Path | None:
    """Return the correct SRT path for a platform's configured subtitle language.

    Looks for the platform's configured language first, then falls back through
    en → vi → zh.

    Args:
        video_id: Video identifier (used in SRT filenames).
        platform: Platform name (e.g., "tiktok", "youtube").
        srt_dir: Directory containing SRT files.
        platform_config: Platform config dict with 'subtitle_language' key.

    Returns:
        Path to best matching SRT file, or None if no SRT exists.
    """
    configured_lang = platform_config.get("subtitle_language", "en")

    # Build ordered search list: configured first, then fallbacks
    search_langs = [configured_lang]
    for lang in _LANGUAGE_FALLBACK:
        if lang not in search_langs:
            search_langs.append(lang)

    for lang in search_langs:
        srt_path = srt_dir / f"{video_id}_{lang}.srt"
        if srt_path.exists():
            if lang != configured_lang:
                logger.warning(
                    f"Platform {platform}: preferred '{configured_lang}' SRT not found, "
                    f"falling back to '{lang}'"
                )
            return srt_path

    logger.warning(f"No SRT found for video {video_id} (searched: {search_langs})")
    return None
