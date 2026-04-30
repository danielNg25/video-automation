"""Subtitle style matcher — derives ASS style from detected subtitle region."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.processor.region_detector import SubtitleRegion

logger = setup_logger(__name__)


class SubtitleStyleMatcher:
    """Derives subtitle styling to position new subtitles where the originals were."""

    # Legacy default ASS canvas — used when callers don't pass an output size.
    ASS_PLAY_RES_X = 1080
    ASS_PLAY_RES_Y = 1920

    def match_style(
        self,
        region: SubtitleRegion,
        video_width: int,
        video_height: int,
        base_style: dict | None = None,
        output_width: int | None = None,
        output_height: int | None = None,
    ) -> dict:
        """Derive ASS style params that position new subtitle in the original's location.

        Maps the source-pixel region through the same scale + letterbox-pad
        transform that the export pipeline applies to the video itself, then
        expresses the result in the ASS canvas. When the ASS canvas equals the
        export output (set via srt_to_ass(play_res_x/y)), output-pixel coords
        ARE ASS coords, so the new subtitle lands directly on top of the
        blurred original — even when source AR ≠ target AR.

        Args:
            region: Detected subtitle region (source-pixel coordinates).
            video_width: Source video frame width.
            video_height: Source video frame height.
            base_style: Base style dict to merge with (from config).
            output_width: Final export width. When None, falls back to
                ASS_PLAY_RES_X (legacy behavior — no letterbox correction).
            output_height: Final export height. When None, falls back to
                ASS_PLAY_RES_Y.

        Returns:
            Style dict with font_size, margin_v, alignment, and optional margin_h.
        """
        style = dict(base_style or {})

        # Determine the ASS canvas the burned subtitle will be rendered into.
        # We require srt_to_ass to be called with PlayResX/Y == output width/height
        # so that ASS pixels map 1:1 to output pixels.
        ass_w = output_width if output_width and output_width > 0 else self.ASS_PLAY_RES_X
        ass_h = output_height if output_height and output_height > 0 else self.ASS_PLAY_RES_Y

        # Letterbox math — must match the scale/pad chain in the export ffmpeg
        # filter (force_original_aspect_ratio=decrease + pad with center offset).
        if video_width > 0 and video_height > 0:
            scale = min(ass_w / video_width, ass_h / video_height)
            scaled_w = int(video_width * scale)
            scaled_h = int(video_height * scale)
            pad_x = (ass_w - scaled_w) // 2
            pad_y = (ass_h - scaled_h) // 2
        else:
            scale = 1.0
            pad_x = pad_y = 0

        # Region in OUTPUT/ASS-pixel space (lives inside the actual video area
        # of the letterboxed output, NOT in the black bars).
        out_w = max(1, int(region.width * scale))
        out_h = max(1, int(region.height * scale))
        out_center_x = int(region.center_x * scale + pad_x)
        out_center_y = int(region.center_y * scale + pad_y)

        # Font size: estimate from output-pixel region height, but ALSO cap
        # by canvas height. The 72 hard-cap was tuned for a 1920-tall canvas;
        # on a 576-tall canvas (e.g. native horizontal Douyin) 72 means each
        # line is 12.5% of frame height — visually huge. Limit to ~5% of
        # canvas height so subtitle scale stays reasonable across resolutions.
        canvas_cap = max(16, int(ass_h * 0.05))
        region_estimate = int(out_h * 0.48)
        estimated_font_size = max(16, min(72, canvas_cap, region_estimate))
        style["font_size"] = estimated_font_size

        # ASS Alignment 2 (bottom-center): MarginV = distance from canvas
        # bottom to text bottom edge. Center text vertically inside region:
        # text_bottom = out_center_y + font_size/2.
        margin_v = max(0, ass_h - out_center_y - estimated_font_size // 2)
        style["margin_v"] = margin_v

        # Alignment: detect if centered, left, or right (relative to canvas center).
        # 15% threshold: OCR-detected regions often pick up watermarks or
        # off-center artifacts that drag the apparent center sideways even
        # though the actual subtitle is centered. Default to center unless
        # clearly off.
        center_offset_pct = abs(out_center_x - ass_w // 2) / max(1, ass_w)
        if center_offset_pct < 0.15:
            style["alignment"] = 2  # bottom-center
        elif out_center_x < ass_w // 2:
            style["alignment"] = 1  # left
        else:
            style["alignment"] = 3  # right

        # If subtitle is in top half, switch to top alignment.
        if out_center_y < ass_h * 0.4:
            style["alignment"] = style.get("alignment", 2) + 6  # top row in ASS

        # Horizontal margin if off-center.
        if center_offset_pct >= 0.10:
            offset = out_center_x - ass_w // 2
            style["margin_h"] = offset

        logger.info(
            f"Style matched: font_size={estimated_font_size}, "
            f"margin_v={margin_v}, alignment={style.get('alignment', 2)} "
            f"(video {video_width}x{video_height} → ASS {ass_w}x{ass_h}, "
            f"scale={scale:.3f}, pad_y={pad_y})"
        )
        return style
