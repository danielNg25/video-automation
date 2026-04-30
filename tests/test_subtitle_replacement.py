"""Tests for Phase 6: subtitle replacement — region detection, style matching, blur filters."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.processor.region_detector import SubtitleRegion, SubtitleRegionDetector, load_subtitle_region
from src.processor.style_matcher import SubtitleStyleMatcher


# ── SubtitleRegion dataclass ──────────────────────────────────────


class TestSubtitleRegion:
    def test_properties(self):
        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        assert region.center_x == 540
        assert region.center_y == 1590
        assert region.bottom == 1630

    def test_to_dict_roundtrip(self):
        region = SubtitleRegion(x=100, y=200, width=800, height=60)
        d = region.to_dict()
        restored = SubtitleRegion.from_dict(d)
        assert restored == region

    def test_from_dict(self):
        region = SubtitleRegion.from_dict({"x": 10, "y": 20, "width": 300, "height": 50})
        assert region.x == 10
        assert region.width == 300


# ── SubtitleRegionDetector ────────────────────────────────────────


class TestSubtitleRegionDetector:
    def test_detect_from_ocr_meta_file(self, tmp_path):
        """Region is loaded from OCR metadata exactly — no padding applied."""
        meta = {
            "video_id": "test123",
            "video_width": 1080,
            "video_height": 1920,
            "subtitle_region": {"x": 90, "y": 1550, "width": 900, "height": 80},
            "frames_analyzed": 120,
        }
        meta_path = tmp_path / "test123_ocr_meta.json"
        meta_path.write_text(json.dumps(meta))

        detector = SubtitleRegionDetector()
        region = detector.detect_from_ocr_meta(meta_path)

        assert region is not None
        assert region.x == 90
        assert region.y == 1550
        assert region.width == 900
        assert region.height == 80

    def test_horizontal_video_region_unchanged(self, tmp_path):
        """Horizontal video: blur region matches OCR bbox exactly, no width balloon."""
        meta = {
            "video_id": "horiz",
            "video_width": 1920,
            "video_height": 1080,
            "subtitle_region": {"x": 85, "y": 854, "width": 1748, "height": 206},
            "frames_analyzed": 100,
        }
        meta_path = tmp_path / "horiz_ocr_meta.json"
        meta_path.write_text(json.dumps(meta))

        detector = SubtitleRegionDetector()
        region = detector.detect_from_ocr_meta(meta_path)

        assert region is not None
        assert (region.x, region.y, region.width, region.height) == (85, 854, 1748, 206)

    def test_detect_from_missing_file(self, tmp_path):
        """Returns None when OCR metadata file doesn't exist."""
        detector = SubtitleRegionDetector()
        result = detector.detect_from_ocr_meta(tmp_path / "nonexistent.json")
        assert result is None

    def test_detect_from_meta_without_region(self, tmp_path):
        """Returns None when OCR metadata exists but has no subtitle_region."""
        meta = {"video_id": "test123", "video_width": 1080, "video_height": 1920}
        meta_path = tmp_path / "test123_ocr_meta.json"
        meta_path.write_text(json.dumps(meta))

        detector = SubtitleRegionDetector()
        result = detector.detect_from_ocr_meta(meta_path)
        assert result is None

    def test_detect_from_boxes_bottom_subtitles(self):
        """Computes bounding rectangle from OCR boxes in bottom region."""
        boxes = [
            {"bbox": [[100, 1560], [980, 1560], [980, 1620], [100, 1620]], "text": "字幕一", "confidence": 0.95},
            {"bbox": [[120, 1570], [960, 1570], [960, 1630], [120, 1630]], "text": "字幕二", "confidence": 0.90},
        ]
        detector = SubtitleRegionDetector(padding=10)
        region = detector.detect_from_boxes(boxes, 1080, 1920)

        assert region is not None
        # Should encompass both boxes with padding
        assert region.x <= 100
        assert region.y <= 1560
        assert region.x + region.width >= 980
        assert region.y + region.height >= 1630

    def test_detect_from_boxes_filters_top_text(self):
        """Ignores text in the top of the frame (watermarks)."""
        boxes = [
            # Top text — should be filtered
            {"bbox": [[20, 30], [200, 30], [200, 60], [20, 60]], "text": "@user", "confidence": 0.95},
            # Bottom text — should be kept
            {"bbox": [[100, 1560], [980, 1560], [980, 1620], [100, 1620]], "text": "字幕", "confidence": 0.95},
        ]
        detector = SubtitleRegionDetector(padding=10)
        region = detector.detect_from_boxes(boxes, 1080, 1920)

        assert region is not None
        # Region should be in the bottom area, not top
        assert region.y > 1000

    def test_detect_from_boxes_no_subtitles(self):
        """Returns None when no boxes pass the filter."""
        boxes = [
            {"bbox": [[20, 30], [200, 30], [200, 60], [20, 60]], "text": "@user", "confidence": 0.95},
        ]
        detector = SubtitleRegionDetector()
        result = detector.detect_from_boxes(boxes, 1080, 1920)
        assert result is None

    def test_detect_from_boxes_uses_is_subtitle_flag(self):
        """Uses pre-classified is_subtitle flag when available."""
        boxes = [
            {"bbox": [[20, 30], [200, 30], [200, 60], [20, 60]], "text": "@user", "is_subtitle": False},
            {"bbox": [[100, 100], [900, 100], [900, 150], [100, 150]], "text": "字幕", "is_subtitle": True},
        ]
        detector = SubtitleRegionDetector(padding=0)
        region = detector.detect_from_boxes(boxes, 1080, 1920)

        assert region is not None
        assert region.x == 100
        assert region.y == 100

    def test_minimum_height_clamping(self):
        """Region height is clamped to minimum 50px."""
        boxes = [
            {"bbox": [[100, 1600], [900, 1600], [900, 1610], [100, 1610]], "text": "小", "confidence": 0.9},
        ]
        detector = SubtitleRegionDetector(padding=0)
        region = detector.detect_from_boxes(boxes, 1080, 1920)

        assert region is not None
        assert region.height >= 50


class TestLoadSubtitleRegion:
    def test_convenience_function(self, tmp_path):
        """load_subtitle_region reads from the standard path."""
        meta = {
            "video_id": "abc",
            "video_width": 1080,
            "subtitle_region": {"x": 50, "y": 1500, "width": 980, "height": 70},
        }
        srt_dir = tmp_path
        (srt_dir / "abc_ocr_meta.json").write_text(json.dumps(meta))

        region = load_subtitle_region(srt_dir, "abc")
        assert region is not None
        # Region matches OCR bbox exactly — no padding
        assert (region.x, region.y, region.width, region.height) == (50, 1500, 980, 70)

    def test_returns_none_when_missing(self, tmp_path):
        """Returns None for Whisper-transcribed videos without OCR metadata."""
        assert load_subtitle_region(tmp_path, "nonexistent") is None


# ── SubtitleStyleMatcher ──────────────────────────────────────────


class TestSubtitleStyleMatcher:
    def test_centered_bottom_region_native_res(self):
        """At 1080x1920 (native ASS res), text is centered in region."""
        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(region, 1080, 1920)

        assert style["alignment"] == 2  # bottom-center
        # margin_v should center text: PlayResY - center_y - font_size/2
        # center_y = 1590, font ≈ 38, so margin_v ≈ 1920 - 1590 - 19 = 311
        assert style["margin_v"] > 280
        assert 16 <= style["font_size"] <= 72

    def test_scales_to_ass_playres(self):
        """576x1024 video coords are scaled to 1080x1920 ASS PlayRes."""
        # Real Douyin data: 576x1024, region at y=763, h=71, bottom=834
        region = SubtitleRegion(x=56, y=763, width=463, height=71)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(region, 576, 1024)

        # center_y = 798.5, center_y_ass = 798.5 * 1.875 ≈ 1497
        # font_size ≈ 63, margin_v ≈ 1920 - 1497 - 31 ≈ 392
        assert style["margin_v"] > 350
        assert style["alignment"] == 2
        assert style["font_size"] > 40

    def test_left_aligned_region(self):
        """Left-aligned subtitle → alignment 1."""
        region = SubtitleRegion(x=20, y=1550, width=400, height=60)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(region, 1080, 1920)

        assert style["alignment"] == 1  # left

    def test_top_region_alignment(self):
        """Subtitle in top half → top alignment (7, 8, or 9)."""
        region = SubtitleRegion(x=90, y=50, width=900, height=60)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(region, 1080, 1920)

        assert style["alignment"] >= 7  # top row

    def test_font_size_scales_with_region_height(self):
        """Larger regions produce larger font sizes."""
        matcher = SubtitleStyleMatcher()

        small = matcher.match_style(SubtitleRegion(x=90, y=1600, width=900, height=40), 1080, 1920)
        large = matcher.match_style(SubtitleRegion(x=90, y=1500, width=900, height=100), 1080, 1920)

        assert large["font_size"] > small["font_size"]

    def test_merges_with_base_style(self):
        """Matched style is merged with base style dict."""
        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(region, 1080, 1920, {"font_name": "Arial", "bold": True})

        assert style["font_name"] == "Arial"
        assert style["bold"] is True
        assert "font_size" in style

    def test_horizontal_source_vertical_target_lands_in_video_area(self):
        """Horizontal source (1024×576) exported at vertical (1080×1920):

        Subtitle text must end up over the (letterboxed) source video, not in
        the black padding bars. With force_original_aspect_ratio=decrease,
        the source becomes 1080×608 inside the 1080×1920 canvas with
        ~656px top/bottom black bars.
        """
        # Region at the bottom of the source video, exactly where subtitles live.
        region = SubtitleRegion(x=54, y=404, width=655, height=152)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(
            region, video_width=1024, video_height=576,
            output_width=1080, output_height=1920,
        )

        # Letterbox: scale = min(1080/1024, 1920/576) = 1.0546875
        # scaled_h = 576 * 1.0546875 = 607.5 → 607
        # pad_y = (1920 - 607) // 2 = 656
        # video band lives in y ∈ [656, 1263]
        # text bottom = ass_h - margin_v = 1920 - margin_v
        # must be inside [656, 1263] for the text to land on the video.
        text_bottom = 1920 - style["margin_v"]
        assert 656 <= text_bottom <= 1263, (
            f"Subtitle bottom y={text_bottom} not on video band [656, 1263]; "
            f"would render in the black padding"
        )
        # Region is at the bottom of the source video: text uses bottom row
        # alignment (1=left, 2=center, 3=right) — never the top row (7-9).
        assert style["alignment"] in (1, 2, 3)

    def test_match_style_at_source_resolution_is_identity(self):
        """When output == source, scale=1 and pad=0; region stays in source
        coords and the burned subtitle lands directly inside the OCR region.
        Verifies the new default-to-source-resolution export path.
        """
        # Horizontal source — region at the bottom, slightly left of center.
        region = SubtitleRegion(x=54, y=404, width=655, height=152)
        matcher = SubtitleStyleMatcher()
        style = matcher.match_style(
            region, video_width=1024, video_height=576,
            output_width=1024, output_height=576,
        )

        # Reconstruct the text bottom from the returned margin_v (alignment 1
        # or 2 → bottom row → text_bottom = canvas_h - margin_v).
        text_bottom = 576 - style["margin_v"]
        # Must land inside the original subtitle region [404, 556].
        assert 404 <= text_bottom <= 556, (
            f"text_bottom={text_bottom} not inside region [404, 556]"
        )
        # Same for the vertical orientation.
        region_v = SubtitleRegion(x=65, y=776, width=444, height=44)
        style_v = matcher.match_style(
            region_v, video_width=576, video_height=1024,
            output_width=576, output_height=1024,
        )
        text_bottom_v = 1024 - style_v["margin_v"]
        assert 776 <= text_bottom_v <= 820

    def test_legacy_callers_unchanged(self):
        """When output_width/height aren't supplied, falls back to the legacy
        ASS_PLAY_RES_X/Y constants — preserves every old call site."""
        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        matcher = SubtitleStyleMatcher()

        legacy = matcher.match_style(region, 1080, 1920)
        explicit = matcher.match_style(
            region, 1080, 1920, output_width=1080, output_height=1920,
        )
        # Same source dims as ASS canvas → identical output.
        assert legacy["margin_v"] == explicit["margin_v"]
        assert legacy["font_size"] == explicit["font_size"]
        assert legacy["alignment"] == explicit["alignment"]


# ── FFmpeg blur filter construction ───────────────────────────────


class TestFFmpegBlurFilter:
    @patch("src.processor.ffmpeg.subprocess")
    def test_build_blur_filter_boxblur(self, mock_sub):
        """Default blur mode generates crop+boxblur+overlay filter."""
        mock_sub.run.return_value = MagicMock(returncode=0)
        from src.processor.ffmpeg import FFmpegProcessor

        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        fc = FFmpegProcessor._build_blur_filter(region, blur_strength=15, blur_mode="blur")

        assert "crop=900:80:90:1550" in fc
        assert "boxblur=15:15" in fc
        assert "overlay=90:1550" in fc
        assert "[blurred]" in fc

    @patch("src.processor.ffmpeg.subprocess")
    def test_build_blur_filter_fill(self, mock_sub):
        """Fill mode generates drawbox filter."""
        mock_sub.run.return_value = MagicMock(returncode=0)
        from src.processor.ffmpeg import FFmpegProcessor

        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        fc = FFmpegProcessor._build_blur_filter(region, blur_mode="fill", fill_color="#000000")

        assert "drawbox" in fc
        assert "t=fill" in fc
        assert "[blurred]" in fc

    @patch("src.processor.ffmpeg.subprocess")
    def test_build_blur_filter_pixelate(self, mock_sub):
        """Pixelate mode generates crop+scale_down+scale_up+overlay filter."""
        mock_sub.run.return_value = MagicMock(returncode=0)
        from src.processor.ffmpeg import FFmpegProcessor

        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        fc = FFmpegProcessor._build_blur_filter(region, blur_mode="pixelate")

        assert "crop=900:80:90:1550" in fc
        assert "flags=neighbor" in fc
        assert "overlay=90:1550" in fc
        assert "[blurred]" in fc


class TestBlurAndBurnCommand:
    @patch("src.processor.ffmpeg.subprocess")
    def test_blur_and_burn_single_pass(self, mock_sub):
        """blur_and_burn_subtitles generates a single-pass filter_complex."""
        mock_sub.run.return_value = MagicMock(returncode=0)
        from src.processor.ffmpeg import FFmpegProcessor

        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        proc = FFmpegProcessor()

        with tempfile.TemporaryDirectory() as tmpdir:
            video = Path(tmpdir) / "input.mp4"
            video.touch()
            srt = Path(tmpdir) / "test.srt"
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
            output = Path(tmpdir) / "output.mp4"

            proc.blur_and_burn_subtitles(video, srt, region, output)

        # Verify single ffmpeg call with filter_complex containing both blur and subtitles
        assert mock_sub.run.called
        call_args = mock_sub.run.call_args[0][0]
        fc_idx = call_args.index("-filter_complex")
        fc_value = call_args[fc_idx + 1]
        assert "boxblur" in fc_value or "drawbox" in fc_value
        assert "subtitles" in fc_value
        assert "[out]" in fc_value


# ── OCR metadata persistence ─────────────────────────────────────


class TestOCRMetadataPersistence:
    def test_save_ocr_metadata_unions_x_across_frames(self, tmp_path):
        """X-extent is the union across frames so the longest subtitle line
        is fully covered. y/height stays at the median (typical row)."""
        from src.transcriber.ocr import OCRTranscriber

        transcriber = OCRTranscriber()
        # Three frames at the same y/height but different widths:
        # Frame 0: x ∈ [400, 600] (short subtitle)
        # Frame 1: x ∈ [100, 980] (long subtitle — must be fully covered)
        # Frame 2: x ∈ [300, 700] (medium subtitle)
        per_frame = [
            [[[400, 1700], [600, 1700], [600, 1760], [400, 1760]]],
            [[[100, 1700], [980, 1700], [980, 1760], [100, 1760]]],
            [[[300, 1700], [700, 1700], [700, 1760], [300, 1760]]],
        ]

        srt_dir = tmp_path / "srt"
        transcriber._save_ocr_metadata(srt_dir, "test_vid", 1080, 1920, per_frame, 100)

        region = json.loads((srt_dir / "test_vid_ocr_meta.json").read_text())["subtitle_region"]
        # Union x: 100..980 → x=100, w=880. Median y: 1700, median y_max: 1760 → h=60.
        assert region == {"x": 100, "y": 1700, "width": 880, "height": 60}

    def test_save_ocr_metadata_median_y_skips_multi_line_outlier(self, tmp_path):
        """A single multi-line wrap frame must not inflate the blur band's
        height — median y_min / y_max ignores the outlier."""
        from src.transcriber.ocr import OCRTranscriber

        transcriber = OCRTranscriber()
        # Frames 0..2: typical single-line subtitle at y ∈ [1700, 1760]
        # Frame 3: multi-line wrap from y=1500 to y=1760 (much taller)
        per_frame = [
            [[[400, 1700], [800, 1700], [800, 1760], [400, 1760]]],
            [[[400, 1700], [800, 1700], [800, 1760], [400, 1760]]],
            [[[400, 1700], [800, 1700], [800, 1760], [400, 1760]]],
            [
                [[400, 1500], [800, 1500], [800, 1560], [400, 1560]],
                [[400, 1700], [800, 1700], [800, 1760], [400, 1760]],
            ],
        ]

        srt_dir = tmp_path / "srt"
        transcriber._save_ocr_metadata(srt_dir, "vid", 1080, 1920, per_frame, 50)

        region = json.loads((srt_dir / "vid_ocr_meta.json").read_text())["subtitle_region"]
        # Median y_min over [1500, 1700, 1700, 1700] → 1700.
        # Median y_max over [1560, 1760, 1760, 1760] → 1760.
        # Height stays 60 (single-line) instead of being inflated by the
        # multi-line frame.
        assert region["y"] == 1700
        assert region["height"] == 60

    def test_save_no_boxes(self, tmp_path):
        """Does not save metadata when there are no subtitle boxes."""
        from src.transcriber.ocr import OCRTranscriber

        transcriber = OCRTranscriber()
        srt_dir = tmp_path / "srt"
        transcriber._save_ocr_metadata(srt_dir, "empty_vid", 1080, 1920, [], 100)

        assert not (srt_dir / "empty_vid_ocr_meta.json").exists()


# ── Batch processor blur integration ─────────────────────────────


class TestBatchProcessorBlur:
    @patch("src.processor.FFmpegProcessor")
    @patch("src.processor.select_subtitle_for_platform")
    def test_blur_branch_selected(self, mock_select, mock_proc_cls, tmp_path):
        """When subtitle_region and blur_settings are provided, blur method is called."""
        from src.processor import process_for_all_platforms

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        mock_proc.get_video_info.return_value = {"width": 1080, "height": 1920, "duration": 30}

        srt_file = tmp_path / "srt" / "vid_en.srt"
        srt_file.parent.mkdir(parents=True)
        srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        mock_select.return_value = srt_file

        video_path = tmp_path / "raw" / "vid.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.touch()

        region = SubtitleRegion(x=90, y=1550, width=900, height=80)
        blur = {"enabled": True, "blur_strength": 15, "blur_mode": "blur", "fill_color": "#000000"}

        results = process_for_all_platforms(
            "vid", video_path, tmp_path / "srt", tmp_path / "output",
            ["youtube"], {}, subtitle_region=region, blur_settings=blur,
        )

        # Should have called blur_burn_and_reformat, not burn_and_reformat
        assert mock_proc.blur_burn_and_reformat.called
        assert not mock_proc.burn_and_reformat.called

    @patch("src.processor.FFmpegProcessor")
    @patch("src.processor.select_subtitle_for_platform")
    def test_no_blur_when_region_missing(self, mock_select, mock_proc_cls, tmp_path):
        """Without subtitle_region, falls back to normal burn_and_reformat."""
        from src.processor import process_for_all_platforms

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc

        srt_file = tmp_path / "srt" / "vid_en.srt"
        srt_file.parent.mkdir(parents=True)
        srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n")
        mock_select.return_value = srt_file

        video_path = tmp_path / "raw" / "vid.mp4"
        video_path.parent.mkdir(parents=True)
        video_path.touch()

        results = process_for_all_platforms(
            "vid", video_path, tmp_path / "srt", tmp_path / "output",
            ["youtube"], {},
        )

        assert mock_proc.burn_and_reformat.called
        assert not mock_proc.blur_burn_and_reformat.called
