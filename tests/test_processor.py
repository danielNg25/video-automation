"""Tests for processor module: subtitle parsing, ASS conversion, FFmpeg, batch processing."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.processor.ffmpeg import FFmpegProcessor
from src.processor.subtitle import (
    _seconds_to_ass_timestamp,
    _seconds_to_srt_timestamp,
    break_long_lines,
    merge_subtitles,
    parse_srt,
    select_subtitle_for_platform,
)

# ── Sample SRT content ──────────────────────────────────────────────

SAMPLE_SRT_EN = """\
1
00:00:01,000 --> 00:00:04,500
Hello, welcome to the show.

2
00:00:05,000 --> 00:00:09,200
Today we will talk about technology.

3
00:00:10,000 --> 00:00:14,800
Let's get started with the first topic.
"""

SAMPLE_SRT_VI = """\
1
00:00:01,000 --> 00:00:04,500
Xin ch\u00e0o, ch\u00e0o m\u1eebng b\u1ea1n \u0111\u1ebfn ch\u01b0\u01a1ng tr\u00ecnh.

2
00:00:05,000 --> 00:00:09,200
H\u00f4m nay ch\u00fang ta s\u1ebd n\u00f3i v\u1ec1 c\u00f4ng ngh\u1ec7.

3
00:00:10,000 --> 00:00:14,800
H\u00e3y b\u1eaft \u0111\u1ea7u v\u1edbi ch\u1ee7 \u0111\u1ec1 \u0111\u1ea7u ti\u00ean.
"""

SAMPLE_SRT_MULTILINE = """\
1
00:00:01,000 --> 00:00:04,500
First line
Second line

2
00:00:05,000 --> 00:00:08,000
Another subtitle block.
"""


# ── TestParseSrt ─────────────────────────────────────────────────────


class TestParseSrt:
    def test_basic_parsing(self, tmp_path):
        srt = tmp_path / "test.srt"
        srt.write_text(SAMPLE_SRT_EN, encoding="utf-8")

        segments = parse_srt(srt)
        assert len(segments) == 3
        assert segments[0]["index"] == 1
        assert segments[0]["text"] == "Hello, welcome to the show."
        assert segments[0]["start"] == pytest.approx(1.0)
        assert segments[0]["end"] == pytest.approx(4.5)

    def test_vietnamese_diacritics(self, tmp_path):
        srt = tmp_path / "test_vi.srt"
        srt.write_text(SAMPLE_SRT_VI, encoding="utf-8")

        segments = parse_srt(srt)
        assert len(segments) == 3
        assert "chào mừng" in segments[0]["text"]
        assert "công nghệ" in segments[1]["text"]

    def test_multiline_text(self, tmp_path):
        srt = tmp_path / "multi.srt"
        srt.write_text(SAMPLE_SRT_MULTILINE, encoding="utf-8")

        segments = parse_srt(srt)
        assert len(segments) == 2
        assert "First line\nSecond line" == segments[0]["text"]

    def test_empty_file(self, tmp_path):
        srt = tmp_path / "empty.srt"
        srt.write_text("", encoding="utf-8")

        segments = parse_srt(srt)
        assert segments == []


# ── TestTimestamps ───────────────────────────────────────────────────


class TestTimestamps:
    def test_seconds_to_ass_timestamp(self):
        assert _seconds_to_ass_timestamp(0.0) == "0:00:00.00"
        assert _seconds_to_ass_timestamp(61.5) == "0:01:01.50"
        assert _seconds_to_ass_timestamp(3661.99) == "1:01:01.99"

    def test_seconds_to_srt_timestamp(self):
        assert _seconds_to_srt_timestamp(0.0) == "00:00:00,000"
        assert _seconds_to_srt_timestamp(61.5) == "00:01:01,500"
        assert _seconds_to_srt_timestamp(3661.999) == "01:01:01,999"


# ── TestBreakLongLines ───────────────────────────────────────────────


class TestBreakLongLines:
    def test_short_line_unchanged(self):
        assert break_long_lines("Short text") == "Short text"

    def test_long_line_broken(self):
        text = "This is a very long subtitle line that needs to be wrapped at word boundaries"
        result = break_long_lines(text, max_chars=40)
        for line in result.split("\n"):
            assert len(line) <= 40

    def test_preserves_existing_newlines(self):
        text = "Line one\nLine two"
        result = break_long_lines(text, max_chars=40)
        assert "Line one\nLine two" == result

    def test_vietnamese_text(self):
        text = "Xin chào, chào mừng bạn đến chương trình hôm nay"
        result = break_long_lines(text, max_chars=30)
        for line in result.split("\n"):
            assert len(line) <= 30


# ── TestMergeSubtitles ───────────────────────────────────────────────


class TestMergeSubtitles:
    def test_dual_line_merge(self, tmp_path):
        en_srt = tmp_path / "test_en.srt"
        vi_srt = tmp_path / "test_vi.srt"
        en_srt.write_text(SAMPLE_SRT_EN, encoding="utf-8")
        vi_srt.write_text(SAMPLE_SRT_VI, encoding="utf-8")

        merged_path = tmp_path / "merged.srt"
        result = merge_subtitles(en_srt, vi_srt, merged_path)

        content = result.read_text(encoding="utf-8")
        # Each block should have both English and Vietnamese
        assert "Hello, welcome to the show." in content
        assert "chào mừng" in content

    def test_merged_segment_count(self, tmp_path):
        en_srt = tmp_path / "test_en.srt"
        vi_srt = tmp_path / "test_vi.srt"
        en_srt.write_text(SAMPLE_SRT_EN, encoding="utf-8")
        vi_srt.write_text(SAMPLE_SRT_VI, encoding="utf-8")

        merged_path = tmp_path / "merged.srt"
        merge_subtitles(en_srt, vi_srt, merged_path)

        segments = parse_srt(merged_path)
        assert len(segments) == 3


# ── TestSelectSubtitleForPlatform ────────────────────────────────────


class TestSelectSubtitleForPlatform:
    def test_tiktok_gets_vietnamese(self, tmp_path):
        srt_dir = tmp_path
        (srt_dir / "vid1_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n")
        (srt_dir / "vid1_en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n")

        result = select_subtitle_for_platform(
            "vid1", "tiktok", srt_dir, {"subtitle_language": "vi"}
        )
        assert result is not None
        assert result.name == "vid1_vi.srt"

    def test_youtube_gets_english(self, tmp_path):
        srt_dir = tmp_path
        (srt_dir / "vid1_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n")
        (srt_dir / "vid1_en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n")

        result = select_subtitle_for_platform(
            "vid1", "youtube", srt_dir, {"subtitle_language": "en"}
        )
        assert result is not None
        assert result.name == "vid1_en.srt"

    def test_fallback_when_preferred_missing(self, tmp_path):
        srt_dir = tmp_path
        (srt_dir / "vid1_en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\ntest\n")

        result = select_subtitle_for_platform(
            "vid1", "tiktok", srt_dir, {"subtitle_language": "vi"}
        )
        assert result is not None
        assert result.name == "vid1_en.srt"

    def test_no_srt_returns_none(self, tmp_path):
        result = select_subtitle_for_platform(
            "vid1", "tiktok", tmp_path, {"subtitle_language": "vi"}
        )
        assert result is None


# ── TestBuildStyleString ─────────────────────────────────────────────


class TestBuildStyleString:
    def setup_method(self):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            self.proc = FFmpegProcessor()

    def test_default_style(self):
        style = {
            "font_name": "Arial",
            "font_size": 24,
            "primary_color": "&H00FFFFFF",
            "outline_color": "&H00000000",
            "outline_width": 2,
            "bold": True,
        }
        result = self.proc._build_style_string(style)
        assert "FontName=Arial" in result
        assert "FontSize=24" in result
        assert "PrimaryColour=&H00FFFFFF" in result
        assert "Bold=1" in result

    def test_custom_overrides(self):
        style = {"font_name": "Roboto", "font_size": 28, "margin_v": 80}
        result = self.proc._build_style_string(style)
        assert "FontName=Roboto" in result
        assert "FontSize=28" in result
        assert "MarginV=80" in result

    def test_hex_background_color_converts_to_ass(self):
        """#RRGGBB from <input type='color'> → &HAABBGGRR ASS literal."""
        style = {"background_color": "#FFFF00", "background_opacity": 100}
        result = self.proc._build_style_string(style)
        # Yellow #FFFF00 → R=FF G=FF B=00, with alpha=0 (fully opaque). ASS
        # format is &HAABBGGRR so the literal is &H0000FFFF.
        assert "BackColour=&H0000FFFF" in result
        assert "BorderStyle=3" in result

    def test_opacity_is_percentage_inverted_to_ass_alpha(self):
        """`background_opacity` is a percentage; ASS alpha is inverted."""
        style = {"background_color": "#000000", "background_opacity": 90}
        result = self.proc._build_style_string(style)
        # 90% opaque → ASS alpha 255-229=26 → 0x1A.
        assert "BackColour=&H1A000000" in result

    def test_ass_literal_color_passes_through(self):
        style = {"background_color": "&H80FF00FF", "background_opacity": 50}
        result = self.proc._build_style_string(style)
        assert "BackColour=&H80FF00FF" in result

    def test_no_background_when_both_unset(self):
        style = {"font_name": "Arial", "font_size": 24}
        result = self.proc._build_style_string(style)
        assert "BackColour" not in result
        assert "BorderStyle" not in result

    def test_opacity_only_falls_back_to_black(self):
        """No bg_color, only opacity → opaque black box."""
        style = {"background_opacity": 100}
        result = self.proc._build_style_string(style)
        assert "BackColour=&H00000000" in result


# ── TestFFmpegProcessor ──────────────────────────────────────────────


class TestFFmpegProcessor:
    def test_ffmpeg_not_found(self):
        with patch("src.processor.ffmpeg.subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="not found"):
                FFmpegProcessor()

    def test_get_video_info(self):
        mock_output = {
            "format": {"duration": "120.5", "size": "5242880"},
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1080, "height": 1920},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        import json

        with patch("src.processor.ffmpeg.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=json.dumps(mock_output))
            info = proc.get_video_info(Path("test.mp4"))

        assert info["duration"] == pytest.approx(120.5)
        assert info["width"] == 1080
        assert info["height"] == 1920
        assert info["codec"] == "h264"
        assert info["resolution"] == "1080x1920"

    def test_burn_subtitles_command(self, tmp_path):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        output = tmp_path / "output.mp4"
        with patch.object(FFmpegProcessor, "_run_ffmpeg") as mock_ffmpeg:
            proc.burn_subtitles(
                Path("video.mp4"),
                Path("sub.srt"),
                output,
                style={"font_name": "Arial", "font_size": 24},
            )
            mock_ffmpeg.assert_called_once()
            cmd = mock_ffmpeg.call_args[0][0]
            assert "ffmpeg" == cmd[0]
            assert "-vf" in cmd
            # Check subtitles filter is present
            vf_idx = cmd.index("-vf")
            assert "subtitles=" in cmd[vf_idx + 1]
            assert "force_style=" in cmd[vf_idx + 1]

    def test_reformat_with_duration_truncation(self, tmp_path):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        mock_info = {"duration": 300.0, "width": 1080, "height": 1920}
        output = tmp_path / "output.mp4"

        with patch.object(proc, "get_video_info", return_value=mock_info):
            with patch.object(FFmpegProcessor, "_run_ffmpeg") as mock_ffmpeg:
                proc.reformat_for_platform(
                    Path("video.mp4"),
                    "x",
                    output,
                    platform_specs={
                        "resolution": "1080x1920",
                        "crf": 26,
                        "max_bitrate": "4M",
                        "max_duration": 140,
                    },
                )
                cmd = mock_ffmpeg.call_args[0][0]
                assert "-t" in cmd
                t_idx = cmd.index("-t")
                assert cmd[t_idx + 1] == "140"

    def test_burn_and_reformat_single_pass(self, tmp_path):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        mock_info = {"duration": 30.0, "width": 1080, "height": 1920}
        output = tmp_path / "output.mp4"

        with patch.object(proc, "get_video_info", return_value=mock_info):
            with patch.object(FFmpegProcessor, "_run_ffmpeg") as mock_ffmpeg:
                proc.burn_and_reformat(
                    Path("video.mp4"),
                    Path("sub.srt"),
                    "tiktok",
                    output,
                    style={"font_name": "Arial"},
                    platform_specs={"resolution": "1080x1920", "crf": 23, "max_bitrate": "8M"},
                )
                mock_ffmpeg.assert_called_once()
                cmd = mock_ffmpeg.call_args[0][0]
                vf_idx = cmd.index("-vf")
                vf_val = cmd[vf_idx + 1]
                # Should contain both scale/pad and subtitles in one filter
                assert "scale=" in vf_val
                assert "subtitles=" in vf_val


# ── TestExtractFrames ────────────────────────────────────────────────


class TestExtractFrames:
    def test_extract_frames_command(self, tmp_path):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        output_dir = tmp_path / "frames"

        with patch.object(FFmpegProcessor, "_run_ffmpeg") as mock_ffmpeg:
            # Simulate ffmpeg creating frame files
            def create_frames(cmd):
                output_dir.mkdir(parents=True, exist_ok=True)
                for i in range(1, 6):
                    (output_dir / f"frame_{i:06d}.jpg").touch()

            mock_ffmpeg.side_effect = create_frames

            frames = proc.extract_frames(Path("video.mp4"), output_dir, fps=2.0)

            mock_ffmpeg.assert_called_once()
            cmd = mock_ffmpeg.call_args[0][0]
            assert "ffmpeg" == cmd[0]
            assert "-vf" in cmd
            vf_idx = cmd.index("-vf")
            assert "fps=2.0" in cmd[vf_idx + 1]

        assert len(frames) == 5
        assert all(f.name.startswith("frame_") for f in frames)

    def test_extract_frames_sorted(self, tmp_path):
        with patch.object(FFmpegProcessor, "_verify_ffmpeg"):
            proc = FFmpegProcessor()

        output_dir = tmp_path / "frames"

        with patch.object(FFmpegProcessor, "_run_ffmpeg") as mock_ffmpeg:
            def create_frames(cmd):
                output_dir.mkdir(parents=True, exist_ok=True)
                for i in [3, 1, 2]:
                    (output_dir / f"frame_{i:06d}.jpg").touch()

            mock_ffmpeg.side_effect = create_frames

            frames = proc.extract_frames(Path("video.mp4"), output_dir)

        assert frames[0].name == "frame_000001.jpg"
        assert frames[-1].name == "frame_000003.jpg"


# ── TestProcessForAllPlatforms ───────────────────────────────────────


class TestProcessForAllPlatforms:
    def test_correct_subtitle_per_platform(self, tmp_path):
        from src.processor import process_for_all_platforms

        # Setup SRT files
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        (srt_dir / "vid1_en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n")
        (srt_dir / "vid1_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nXin chào\n")

        output_dir = tmp_path / "output"
        video_path = tmp_path / "vid1.mp4"
        video_path.touch()

        selected_subs = []

        def mock_burn_and_reformat(
            video_path, subtitle_path, platform, output_path, style=None, platform_specs=None
        ):
            selected_subs.append((platform, subtitle_path.stem.split("_")[-1]))
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.touch()
            return output_path

        with patch("src.processor.FFmpegProcessor") as MockProc:
            mock_instance = MagicMock()
            mock_instance.burn_and_reformat = mock_burn_and_reformat
            MockProc.return_value = mock_instance

            with patch("src.processor.yaml.safe_load") as mock_yaml:
                mock_yaml.return_value = {
                    "tiktok": {
                        "subtitle_language": "vi",
                        "resolution": "1080x1920",
                        "crf": 23,
                        "max_bitrate": "8M",
                    },
                    "youtube": {
                        "subtitle_language": "en",
                        "resolution": "1080x1920",
                        "crf": 20,
                        "max_bitrate": "12M",
                    },
                }

                results = process_for_all_platforms(
                    "vid1",
                    video_path,
                    srt_dir,
                    output_dir,
                    ["tiktok", "youtube"],
                    {},
                )

        assert len(results) == 2
        # TikTok should get Vietnamese, YouTube should get English
        sub_map = dict(selected_subs)
        assert sub_map["tiktok"] == "vi"
        assert sub_map["youtube"] == "en"

    def test_skip_when_no_srt(self, tmp_path):
        from src.processor import process_for_all_platforms

        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        output_dir = tmp_path / "output"
        video_path = tmp_path / "vid1.mp4"
        video_path.touch()

        with patch("src.processor.FFmpegProcessor") as MockProc:
            MockProc.return_value = MagicMock()

            with patch("src.processor.yaml.safe_load") as mock_yaml:
                mock_yaml.return_value = {
                    "youtube": {"subtitle_language": "en"},
                }

                results = process_for_all_platforms(
                    "vid1",
                    video_path,
                    srt_dir,
                    output_dir,
                    ["youtube"],
                    {},
                )

        assert len(results) == 0


class TestDefaultTtsMixForPlatform:
    """Unit tests for the _default_tts_mix_for_platform helper in task_manager.

    Converts underlay_db (dB scale) to a linear original_volume for a single
    platform's mix. When underlay_db is None, falls back to a hard-coded 0.3.
    """

    def _helper(self):
        from src.api.task_manager import _default_tts_mix_for_platform
        return _default_tts_mix_for_platform

    def test_underlay_db_minus_18(self):
        build = self._helper()
        result = build(-18.0)
        # 10 ** (-18 / 20) = 0.12589...
        assert abs(result["original_volume"] - 0.12589) < 1e-3
        assert result["tts_volume"] == 1.0

    def test_underlay_db_none_uses_default(self):
        build = self._helper()
        result = build(None)
        assert result["original_volume"] == 0.3
        assert result["tts_volume"] == 1.0

    def test_underlay_db_zero_gives_linear_one(self):
        build = self._helper()
        result = build(0.0)
        assert abs(result["original_volume"] - 1.0) < 1e-9
        assert result["tts_volume"] == 1.0

    def test_underlay_db_minus_12_conversion(self):
        build = self._helper()
        result = build(-12.0)
        # 10 ** (-12 / 20) = 0.25119...
        assert abs(result["original_volume"] - 0.25119) < 1e-3


class TestSubtitleSelection:
    def test_working_draft_srt_is_used(self, tmp_path):
        from src.processor.subtitle import select_subtitle_for_platform
        (tmp_path / "abc_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nworking draft\n\n")
        out = select_subtitle_for_platform("abc", "tiktok", tmp_path, {"subtitle_language": "vi"})
        assert out.name == "abc_vi.srt"

    def test_stale_dubsync_is_ignored(self, tmp_path):
        """If a pre-migration .dubsync.srt slips through, the burn-in
        ignores it and reads the working draft only."""
        from src.processor.subtitle import select_subtitle_for_platform
        (tmp_path / "abc_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nworking\n\n")
        (tmp_path / "abc_vi.dubsync.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nstale\n\n")
        out = select_subtitle_for_platform("abc", "tiktok", tmp_path, {"subtitle_language": "vi"})
        assert out.name == "abc_vi.srt"
