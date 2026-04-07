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

    # Background box: use two-layer approach — a background layer with BorderStyle=3
    # renders the colored box, then the main text layer renders on top with normal outline.
    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    back_colour_hex = style_config.get("background_color", "")
    bg_opacity = style_config.get("background_opacity", 0)
    bg_box_colour = ""
    if bg_opacity > 0:
        alpha = 255 - int(bg_opacity * 255 / 100)
        alpha_hex = f"{alpha:02X}"
        if back_colour_hex and back_colour_hex.startswith("#") and len(back_colour_hex) == 7:
            r = int(back_colour_hex[1:3], 16)
            g = int(back_colour_hex[3:5], 16)
            b = int(back_colour_hex[5:7], 16)
            bg_box_colour = f"&H{alpha_hex}{b:02X}{g:02X}{r:02X}"
        else:
            bg_box_colour = f"&H{alpha_hex}000000"
    back_colour_val = "&H00000000"
    border_style = 1  # main style always uses normal outline

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


def generate_subtitle_background_images(
    srt_path: Path,
    style_config: dict,
    output_dir: Path,
    target_width: int = 1080,
    target_height: int = 1920,
    corner_radius: int = 12,
) -> list[dict] | None:
    """Generate transparent PNGs with rounded-rectangle backgrounds for each segment.

    Uses PIL to draw true rounded rectangles. Returns metadata for ffmpeg overlay.

    Args:
        srt_path: SRT file path.
        style_config: Style dict with background_color, background_opacity, font_size, margin_v.
        output_dir: Directory to write PNG files.
        target_width: Output video width.
        target_height: Output video height.
        corner_radius: Border radius in pixels.

    Returns:
        List of dicts with 'path', 'start', 'end', 'x', 'y' for ffmpeg overlay,
        or None if no background configured.
    """
    bg_color_hex = style_config.get("background_color", "")
    bg_opacity = style_config.get("background_opacity", 0)
    if bg_opacity <= 0:
        return None

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed — cannot render rounded-corner backgrounds")
        return None

    # Parse color
    if bg_color_hex and bg_color_hex.startswith("#") and len(bg_color_hex) == 7:
        r = int(bg_color_hex[1:3], 16)
        g = int(bg_color_hex[3:5], 16)
        b = int(bg_color_hex[5:7], 16)
    else:
        r, g, b = 0, 0, 0
    alpha = int(bg_opacity * 255 / 100)

    font_size = style_config.get("font_size", 24)
    margin_v = style_config.get("margin_v", 30)
    alignment = style_config.get("alignment", 2)
    font_name = style_config.get("font_name", "Arial")
    bold = style_config.get("bold", True)

    # Scale font from PlayRes (1920) to target
    scaled_font = int(font_size * target_height / 1920)
    pad_x = max(6, int(scaled_font * 0.15))
    pad_y = max(6, int(scaled_font * 0.2))

    # Try to load font for text measurement
    try:
        import platform
        if platform.system() == "Darwin":
            font_path = "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf"
        else:
            font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        pil_font = ImageFont.truetype(font_path, scaled_font)
    except Exception:
        pil_font = ImageFont.load_default()

    segments = parse_srt(srt_path)
    if not segments:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, seg in enumerate(segments):
        text = seg["text"]
        # Measure text width
        bbox = pil_font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        img_w = text_w + 2 * pad_x
        img_h = text_h + 2 * pad_y

        # Create transparent image with rounded rectangle
        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [(0, 0), (img_w - 1, img_h - 1)],
            radius=corner_radius,
            fill=(r, g, b, alpha),
        )
        png_path = output_dir / f"bg_{i:04d}.png"
        img.save(png_path)

        # Calculate overlay position
        # Center horizontally
        x = (target_width - img_w) // 2
        # Vertical: center the PNG on the ASS text center.
        # ASS alignment 2: text bottom = PlayResY - MarginV, center = bottom - fontSize/2
        scaled_margin = int(margin_v * target_height / 1920)
        if alignment in (1, 2, 3):  # bottom
            text_center_y = target_height - scaled_margin - scaled_font // 2
        elif alignment in (7, 8, 9):  # top
            text_center_y = scaled_margin + scaled_font // 2
        else:  # middle
            text_center_y = target_height // 2
        y = text_center_y - img_h // 2

        results.append({
            "path": str(png_path),
            "start": seg["start"],
            "end": seg["end"],
            "x": x,
            "y": y,
        })

    logger.info(f"Generated {len(results)} rounded-rect background PNGs in {output_dir}")
    return results


def build_background_overlay_filter(bg_images: list[dict]) -> str:
    """Build ffmpeg filter_complex fragment to overlay rounded-rect background PNGs.

    Each image is overlaid with enable='between(t,start,end)' for timing.

    Args:
        bg_images: List from generate_subtitle_background_images().

    Returns:
        filter_complex fragment string. Input is [bg_base], output is [bg_out].
    """
    if not bg_images:
        return ""

    parts = []
    prev_label = "bg_base"
    for i, img in enumerate(bg_images):
        out_label = f"bg_{i}" if i < len(bg_images) - 1 else "bg_out"
        parts.append(
            f"[{prev_label}][{i + 1}:v]overlay={img['x']}:{img['y']}"
            f":enable='between(t,{img['start']:.3f},{img['end']:.3f})'[{out_label}]"
        )
        prev_label = out_label

    return ";".join(parts)


def build_background_drawtext_filter(
    srt_path: Path,
    style_config: dict,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str | None:
    """Build an ffmpeg drawtext filter chain for subtitle background boxes.

    Uses drawtext with box=1 for each segment, timed with enable='between(t,s,e)'.
    Returns None if no background is configured.

    Args:
        srt_path: SRT file to read segments from.
        style_config: Style dict with background_color, background_opacity, font_size, margin_v, etc.
        target_width: Output video width (after scale+pad).
        target_height: Output video height (after scale+pad).
    """
    bg_color_hex = style_config.get("background_color", "")
    bg_opacity = style_config.get("background_opacity", 0)
    if bg_opacity <= 0:
        return None

    # Convert color to ffmpeg format: 0xRRGGBB
    if bg_color_hex and bg_color_hex.startswith("#") and len(bg_color_hex) == 7:
        ffmpeg_color = f"0x{bg_color_hex[1:]}"
    else:
        ffmpeg_color = "0x000000"
    alpha = bg_opacity / 100.0

    font_size = style_config.get("font_size", 24)
    margin_v = style_config.get("margin_v", 30)
    alignment = style_config.get("alignment", 2)
    font_name = style_config.get("font_name", "Arial")
    bold = style_config.get("bold", True)

    # Calculate Y position based on alignment
    # drawtext y is from top; ASS margin_v with alignment 2 is from bottom
    if alignment in (1, 2, 3):
        # Bottom: y = height - margin_v - font_size (text top)
        y_expr = f"{target_height}-{margin_v}-text_h"
    elif alignment in (7, 8, 9):
        y_expr = f"{margin_v}"
    else:
        y_expr = f"({target_height}-text_h)/2"

    # X centering
    x_expr = "(w-text_w)/2"

    segments = parse_srt(srt_path)
    if not segments:
        return None

    # Find a font file
    import platform
    if platform.system() == "Darwin":
        fontfile = "/System/Library/Fonts/Supplemental/Arial.ttf"
    else:
        fontfile = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    # Scale font_size from PlayRes (1920) to target
    scaled_font = int(font_size * target_height / 1920)
    box_pad = max(8, int(scaled_font * 0.25))

    filters = []
    for seg in segments:
        text = seg["text"].replace("'", "'\\''").replace(":", "\\:")
        start = seg["start"]
        end = seg["end"]
        f = (
            f"drawtext=text='{text}'"
            f":fontfile='{fontfile}'"
            f":fontsize={scaled_font}"
            f":fontcolor=white@0"  # invisible text — just for box sizing
            f":x={x_expr}:y={y_expr}"
            f":box=1:boxcolor={ffmpeg_color}@{alpha:.2f}:boxborderw={box_pad}"
            f":enable='between(t,{start:.3f},{end:.3f})'"
        )
        if bold:
            # drawtext doesn't have bold, but we can use a bold font variant
            pass
        filters.append(f)

    return ",".join(filters)


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
