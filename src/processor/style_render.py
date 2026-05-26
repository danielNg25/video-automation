"""Unified ffmpeg-side subtitle renderer.

Single entry point `render_for_ffmpeg(spec, srt_path, canvas_w, canvas_h,
output_dir)` produces:
  - An ASS file with text styling baked into the [V4+ Styles] header.
  - When `spec.background.shape == "rounded"` and opacity > 0, a list of
    rounded-rectangle PNGs (one per SRT segment) for the ffmpeg overlay
    filter chain.

Replaces the previously split paths: `srt_to_ass` (in subtitle.py),
`generate_subtitle_background_images` (in subtitle.py), and
`FFmpegProcessor._build_style_string` (in ffmpeg.py). All three folded
into this single, spec-driven module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.processor.style import SubtitleStyleSpec
from src.processor.subtitle import _seconds_to_ass_timestamp, parse_srt
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class RenderArtifacts:
    ass_path: Path
    bg_pngs: list[dict[str, Any]] | None  # each entry: {path, start, end, x, y}


# ── ASS alignment numeric code per spec.position.alignment ──

_ALIGNMENT_TO_ASS = {
    "bottom-left":   1, "bottom-center": 2, "bottom-right":  3,
    "center-left":   4, "center-center": 5, "center-right":  6,
    "top-left":      7, "top-center":    8, "top-right":     9,
}


def render_for_ffmpeg(
    spec: SubtitleStyleSpec,
    srt_path: Path,
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> RenderArtifacts:
    """Produce ASS + (optional) PNG overlays from a single spec."""
    output_dir.mkdir(parents=True, exist_ok=True)
    px = _resolve_px(spec, canvas_w, canvas_h)
    ass_path = _write_ass(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    bg_pngs: list[dict[str, Any]] | None = None
    if spec.background.shape == "rounded" and spec.background.opacity > 0:
        bg_pngs = _render_bg_pngs(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    return RenderArtifacts(ass_path=ass_path, bg_pngs=bg_pngs)


def _resolve_px(spec: SubtitleStyleSpec, w: int, h: int) -> dict[str, int]:
    """Convert all percentage fields to pixel values for this canvas."""
    return {
        "font_size":  max(1, int(round(spec.text.font_size  * h / 100))),
        "margin_v":   max(0, int(round(spec.position.margin_v * h / 100))),
        "margin_h":   int(round(spec.position.margin_h * w / 100)),
        "outline":    max(0, int(round(spec.outline.width * h / 100))),
        "shadow":     max(0, int(round(spec.shadow.depth * h / 100))),
        "radius":     max(0, int(round(spec.background.radius * h / 100))),
        "padding_x":  max(0, int(round(spec.background.padding_x * w / 100))),
        "padding_y":  max(0, int(round(spec.background.padding_y * h / 100))),
    }


def _hex_to_ass_bbggrr(hex_rgb: str, alpha: int = 0) -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR. `alpha` is the ASS alpha byte
    (0 = fully opaque, 255 = fully transparent)."""
    if not (hex_rgb.startswith("#") and len(hex_rgb) == 7):
        # Fall back to opaque black if input is malformed.
        return f"&H{alpha:02X}000000"
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper().replace("&H", "&H")


def _bg_box_colour(spec: SubtitleStyleSpec) -> str:
    """ASS BackColour for shape='rect'. opacity is 0-100 percent."""
    ass_alpha = max(0, 255 - int(spec.background.opacity * 255 / 100))
    return _hex_to_ass_bbggrr(spec.background.color, ass_alpha)


def _write_ass(
    srt_path: Path,
    spec: SubtitleStyleSpec,
    px: dict[str, int],
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> Path:
    """Generate the ASS file with style baked into the [V4+ Styles] header."""
    segments = parse_srt(srt_path)

    primary_colour = _hex_to_ass_bbggrr(spec.text.color, alpha=0)       # opaque
    outline_colour = _hex_to_ass_bbggrr(spec.outline.color, alpha=0)
    bold_flag = -1 if spec.text.bold else 0
    alignment = _ALIGNMENT_TO_ASS[spec.position.alignment]

    if spec.background.shape == "rect":
        back_colour = _bg_box_colour(spec)
        border_style = 3
    else:
        # "none" and "rounded" — no libass-drawn box; PNG path handles rounded.
        back_colour = "&H00000000"
        border_style = 1

    margin_l = max(0, 10 + px["margin_h"])
    margin_r = max(0, 10 - px["margin_h"])

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {canvas_w}\n"
        f"PlayResY: {canvas_h}\n"
        "WrapStyle: 0\n"
        f"; BorderStyle={border_style}\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{spec.text.font_name},{px['font_size']},{primary_colour},&H000000FF,"
        f"{outline_colour},{back_colour},{bold_flag},0,0,0,100,100,0,0,{border_style},"
        f"{px['outline']},{px['shadow']},{alignment},{margin_l},{margin_r},{px['margin_v']},1\n"
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

    out_path = output_dir / f"{srt_path.stem}.render.ass"
    out_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Wrote ASS: {out_path} ({len(segments)} segments)")
    return out_path


def _render_bg_pngs(
    srt_path: Path,
    spec: SubtitleStyleSpec,
    px: dict[str, int],
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> list[dict[str, Any]] | None:
    """Generate per-segment rounded-rect background PNGs for the overlay
    filter chain. Returns None if Pillow isn't installed (renderers should
    gracefully degrade to no bg)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed — skipping rounded-rect backgrounds")
        return None

    # Parse the background color (#RRGGBB) for PIL.
    bg = spec.background.color
    if bg.startswith("#") and len(bg) == 7:
        r = int(bg[1:3], 16); g = int(bg[3:5], 16); b = int(bg[5:7], 16)
    else:
        r, g, b = 0, 0, 0
    a = int(spec.background.opacity * 255 / 100)

    # Try to load a real font for text-bbox measurement; fall back to PIL default.
    try:
        import platform
        if platform.system() == "Darwin":
            font_path = (
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if spec.text.bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf"
            )
        else:
            font_path = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if spec.text.bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            )
        pil_font = ImageFont.truetype(font_path, px["font_size"])
    except Exception:
        pil_font = ImageFont.load_default()

    segments = parse_srt(srt_path)
    if not segments:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    pad_x = max(6, px["padding_x"])
    pad_y = max(4, px["padding_y"])

    for i, seg in enumerate(segments):
        text = seg["text"]
        bbox = pil_font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        img_w = text_w + 2 * pad_x
        img_h = text_h + 2 * pad_y

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [(0, 0), (img_w - 1, img_h - 1)],
            radius=max(2, px["radius"]),
            fill=(r, g, b, a),
        )
        png_path = output_dir / f"bg_{i:04d}.png"
        img.save(png_path)

        # Position: anchor decides bottom/top/center base.
        x = (canvas_w - img_w) // 2 + px["margin_h"]
        if spec.position.alignment.startswith("bottom"):
            text_center_y = canvas_h - px["margin_v"] - px["font_size"] // 2
        elif spec.position.alignment.startswith("top"):
            text_center_y = px["margin_v"] + px["font_size"] // 2
        else:
            text_center_y = canvas_h // 2
        y = text_center_y - img_h // 2

        results.append({
            "path": str(png_path),
            "start": seg["start"],
            "end":   seg["end"],
            "x": x,
            "y": y,
        })

    logger.info(f"Wrote {len(results)} bg PNGs to {output_dir}")
    return results
