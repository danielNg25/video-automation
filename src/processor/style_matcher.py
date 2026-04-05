"""Subtitle style matcher — derives ASS style from detected subtitle region."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.processor.region_detector import SubtitleRegion

logger = setup_logger(__name__)


class SubtitleStyleMatcher:
    """Derives subtitle styling to position new subtitles where the originals were."""

    def match_style(
        self,
        region: SubtitleRegion,
        video_width: int,
        video_height: int,
        base_style: dict | None = None,
    ) -> dict:
        """Derive ASS style params that position new subtitle in the original's location.

        Args:
            region: Detected subtitle region (pixel coordinates).
            video_width: Video frame width.
            video_height: Video frame height.
            base_style: Base style dict to merge with (from config).

        Returns:
            Style dict with font_size, margin_v, alignment, and optional margin_h.
        """
        style = dict(base_style or {})

        # Font size: estimate from region height
        # At 1080p, typical subtitle height ~50px → font_size ~24
        # Scale proportionally: font_size ≈ region.height * 0.48
        estimated_font_size = max(16, min(48, int(region.height * 0.48)))
        style["font_size"] = estimated_font_size

        # Margin from bottom: distance from video bottom to region bottom
        margin_v = max(0, video_height - region.bottom)
        style["margin_v"] = margin_v

        # Alignment: detect if centered, left, or top
        center_offset_pct = abs(region.center_x - video_width // 2) / video_width
        if center_offset_pct < 0.10:
            # Centered — use bottom-center (ASS alignment 2)
            style["alignment"] = 2
        elif region.center_x < video_width // 2:
            # Left-aligned
            style["alignment"] = 1
        else:
            # Right-aligned
            style["alignment"] = 3

        # If subtitle is in top half, switch to top alignment
        if region.center_y < video_height * 0.4:
            style["alignment"] = style.get("alignment", 2) + 6  # top row in ASS

        # Horizontal margin if off-center
        if center_offset_pct >= 0.10:
            offset = region.center_x - video_width // 2
            style["margin_h"] = offset

        logger.info(
            f"Style matched: font_size={estimated_font_size}, "
            f"margin_v={margin_v}, alignment={style.get('alignment', 2)}"
        )
        return style
