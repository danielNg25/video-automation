"""Tests for the OCR-region position seeding helper."""

from __future__ import annotations


class TestSuggestPosition:
    def test_returns_position_style(self):
        from src.processor.style import PositionStyle
        from src.processor.style_matcher import SubtitleStyleMatcher
        matcher = SubtitleStyleMatcher()
        region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        result = matcher.suggest_position(
            region, video_width=1080, video_height=1920,
            output_width=1080, output_height=1920,
        )
        assert isinstance(result, PositionStyle)
        assert result.alignment in {
            "bottom-left", "bottom-center", "bottom-right",
            "center-left", "center-center", "center-right",
            "top-left",    "top-center",    "top-right",
        }
        # margin_v should be a positive percentage when text is near the bottom.
        assert 0 < result.margin_v < 100

    def test_margin_v_is_percentage_of_output_height(self):
        from src.processor.style_matcher import SubtitleStyleMatcher
        matcher = SubtitleStyleMatcher()
        # Region 80px tall centered at y=1000 in a 1920-tall canvas →
        # text center at y=1040 → distance from bottom = 880 → margin_v
        # encoded as (880 - half-text-height) / 1920 * 100 ≈ 44-ish %.
        region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        result = matcher.suggest_position(
            region, video_width=1080, video_height=1920,
            output_width=1080, output_height=1920,
        )
        # Sanity-check we're in the right band — exact value depends on
        # the matcher's math; assert it's near where the region sits.
        # Region top at y=1000, region bottom at y=1080 → margin_v from
        # bottom (alignment=bottom-*) ~ 1920 - 1080 = 840 → 43.75%.
        assert 35 < result.margin_v < 55
