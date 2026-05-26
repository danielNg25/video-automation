"""Tests for the unified ffmpeg-side renderer.

`render_for_ffmpeg(spec, srt, canvas_w, canvas_h, output_dir)` produces:
- An ASS file with text styled from spec (font, color, outline, bold, position).
- A list of PNG overlay descriptors when background.shape == 'rounded'.
- No PNG list otherwise; the ASS file itself carries any rectangular bg.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def srt_file(tmp_path):
    path = tmp_path / "test.srt"
    path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nWorld\n",
        encoding="utf-8",
    )
    return path


class TestBackgroundShape:
    def test_shape_none_emits_no_box_no_pngs(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "none"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        assert "BorderStyle=3" not in ass_text  # no box in ASS
        assert out.bg_pngs is None

    def test_shape_rect_uses_libass_box(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "rect"
        spec.background.color = "#FFFF00"
        spec.background.opacity = 80
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # libass renders rect bg via BackColour + BorderStyle=3.
        assert "BorderStyle=3" in ass_text
        # Yellow #FFFF00 with 80% opacity → ASS alpha = 255 - 204 = 51 = 0x33,
        # ASS BBGGRR for yellow = 00FFFF; full literal &H3300FFFF.
        assert "&H3300FFFF" in ass_text
        assert out.bg_pngs is None

    def test_shape_rounded_no_libass_box_yes_pngs(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "rounded"
        spec.background.color = "#FFFF00"
        spec.background.opacity = 90
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        assert "BorderStyle=1" in ass_text  # no libass box
        assert out.bg_pngs is not None
        assert len(out.bg_pngs) == 2  # one per segment
        # Each PNG file actually exists on disk.
        for entry in out.bg_pngs:
            assert Path(entry["path"]).exists()


class TestPercentageToPixel:
    def test_margin_v_scales_with_canvas_height(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.position.margin_v = 30.7  # ≈ 393px on 1280-tall
        spec.position.alignment = "bottom-center"
        out = render_for_ffmpeg(spec, srt_file, 720, 1280, tmp_path)
        ass_text = out.ass_path.read_text()
        # 30.7% of 1280 ≈ 393
        assert "MarginV: 393" in ass_text or ",393," in ass_text or "393" in ass_text

    def test_margin_v_at_1920_canvas(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.position.margin_v = 30.7
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # 30.7% of 1920 ≈ 589
        assert "589" in ass_text or "590" in ass_text


class TestColors:
    def test_text_color_to_primary_colour(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.text.color = "#FF0000"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # #FF0000 (red) → ASS PrimaryColour &H000000FF (BGR order)
        assert "&H000000FF" in ass_text

    def test_outline_color_to_outline_colour(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.outline.color = "#00FF00"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # #00FF00 (green) → ASS OutlineColour &H0000FF00
        assert "&H0000FF00" in ass_text

    def test_bold_emitted(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.text.bold = True
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # ASS Bold = -1 (true) or 0 (false) in the Style line
        assert ",-1," in ass_text
