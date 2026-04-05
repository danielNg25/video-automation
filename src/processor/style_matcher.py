"""Subtitle style matcher — derives ASS style from detected subtitle region."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.utils.logger import setup_logger

if TYPE_CHECKING:
    from src.processor.region_detector import SubtitleRegion

logger = setup_logger(__name__)


class SubtitleStyleMatcher:
    """Derives subtitle styling to position new subtitles where the originals were."""

    # ASS PlayRes defaults used by srt_to_ass()
    ASS_PLAY_RES_X = 1080
    ASS_PLAY_RES_Y = 1920

    def match_style(
        self,
        region: SubtitleRegion,
        video_width: int,
        video_height: int,
        base_style: dict | None = None,
    ) -> dict:
        """Derive ASS style params that position new subtitle in the original's location.

        All values are scaled to ASS PlayRes coordinates (1080x1920) since
        srt_to_ass() hardcodes those. The region is in actual video pixels,
        which may differ (e.g. 576x1024 Douyin videos).

        Args:
            region: Detected subtitle region (pixel coordinates).
            video_width: Video frame width.
            video_height: Video frame height.
            base_style: Base style dict to merge with (from config).

        Returns:
            Style dict with font_size, margin_v, alignment, and optional margin_h.
        """
        style = dict(base_style or {})

        # Scale factors from actual video coords to ASS PlayRes coords
        scale_x = self.ASS_PLAY_RES_X / video_width if video_width > 0 else 1.0
        scale_y = self.ASS_PLAY_RES_Y / video_height if video_height > 0 else 1.0

        # Scale region to ASS coordinates
        region_bottom_ass = int(region.bottom * scale_y)
        region_height_ass = int(region.height * scale_y)
        region_center_x_ass = int(region.center_x * scale_x)
        region_center_y_ass = int(region.center_y * scale_y)

        # Font size: estimate from scaled region height
        # region_height_ass ~100px at 1920p → font_size ≈ 48
        estimated_font_size = max(16, min(72, int(region_height_ass * 0.48)))
        style["font_size"] = estimated_font_size

        # Margin from bottom in ASS coords: distance from PlayResY bottom to region bottom
        margin_v = max(0, self.ASS_PLAY_RES_Y - region_bottom_ass)
        style["margin_v"] = margin_v

        # Alignment: detect if centered, left, or top
        center_offset_pct = abs(region_center_x_ass - self.ASS_PLAY_RES_X // 2) / self.ASS_PLAY_RES_X
        if center_offset_pct < 0.10:
            style["alignment"] = 2  # bottom-center
        elif region_center_x_ass < self.ASS_PLAY_RES_X // 2:
            style["alignment"] = 1  # left
        else:
            style["alignment"] = 3  # right

        # If subtitle is in top half, switch to top alignment
        if region_center_y_ass < self.ASS_PLAY_RES_Y * 0.4:
            style["alignment"] = style.get("alignment", 2) + 6  # top row in ASS

        # Horizontal margin if off-center
        if center_offset_pct >= 0.10:
            offset = region_center_x_ass - self.ASS_PLAY_RES_X // 2
            style["margin_h"] = offset

        logger.info(
            f"Style matched: font_size={estimated_font_size}, "
            f"margin_v={margin_v}, alignment={style.get('alignment', 2)} "
            f"(video {video_width}x{video_height} → ASS {self.ASS_PLAY_RES_X}x{self.ASS_PLAY_RES_Y})"
        )
        return style
