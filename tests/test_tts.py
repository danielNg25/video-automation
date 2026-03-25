"""Tests for the TTS module: base class, factory, assembler, and ffmpeg audio mixing."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.tts.base import BaseTTSProvider, _clean_text


# ── Text cleanup tests ──


class TestCleanText:
    def test_strips_html_tags(self):
        assert _clean_text("<i>hello</i> world") == "hello world"

    def test_strips_ass_overrides(self):
        assert _clean_text("{\\an8}centered text") == "centered text"

    def test_strips_multiple_tags(self):
        assert _clean_text("<b>{\\pos(320,50)}bold text</b>") == "bold text"

    def test_collapses_whitespace(self):
        assert _clean_text("  hello   world  ") == "hello world"

    def test_empty_string(self):
        assert _clean_text("") == ""

    def test_no_tags(self):
        assert _clean_text("plain text") == "plain text"


# ── ABC contract tests ──


class TestBaseTTSProvider:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            BaseTTSProvider()

    def test_concrete_subclass_works(self):
        class FakeTTS(BaseTTSProvider):
            async def synthesize(self, text, voice, **kw):
                return b"audio"

            async def list_voices(self, language=None):
                return [{"name": "test", "language": "en", "gender": "female", "provider": "fake"}]

        tts = FakeTTS()
        result = asyncio.get_event_loop().run_until_complete(tts.synthesize("hi", "test"))
        assert result == b"audio"


# ── Factory tests ──


class TestTTSFactory:
    def test_get_edge_provider(self):
        from src.tts import get_tts_provider
        from src.tts.edge import EdgeTTSProvider

        provider = get_tts_provider({}, provider="edge")
        assert isinstance(provider, EdgeTTSProvider)

    def test_default_provider_is_edge(self):
        from src.tts import get_tts_provider
        from src.tts.edge import EdgeTTSProvider

        provider = get_tts_provider({})
        assert isinstance(provider, EdgeTTSProvider)

    def test_unknown_provider_raises(self):
        from src.tts import get_tts_provider

        with pytest.raises(ValueError, match="Unknown TTS provider"):
            get_tts_provider({}, provider="nonexistent")

    def test_config_default_provider(self):
        from src.tts import get_tts_provider
        from src.tts.edge import EdgeTTSProvider

        config = {"tts": {"default_provider": "edge"}}
        provider = get_tts_provider(config)
        assert isinstance(provider, EdgeTTSProvider)


# ── Voice profiles tests ──


class TestVoiceProfiles:
    def test_load_profiles_from_file(self):
        from src.tts import load_voice_profiles

        profiles = load_voice_profiles()
        assert "profiles" in profiles
        assert "platforms" in profiles
        assert "female-vi-natural" in profiles["profiles"]

    def test_load_profiles_missing_file(self, tmp_path):
        from src.tts import load_voice_profiles

        config = {"tts": {"voices_config": str(tmp_path / "nonexistent.yaml")}}
        profiles = load_voice_profiles(config)
        assert profiles["default_provider"] == "edge"
        assert profiles["profiles"] == {}

    def test_save_and_load_profiles(self, tmp_path):
        from src.tts import load_voice_profiles, save_voice_profiles

        config = {"tts": {"voices_config": str(tmp_path / "test_voices.yaml")}}
        data = {
            "default_provider": "edge",
            "profiles": {"test-voice": {"provider": "edge", "voice": "en-US-Test", "language": "en"}},
            "platforms": {},
        }
        save_voice_profiles(data, config)
        loaded = load_voice_profiles(config)
        assert loaded["profiles"]["test-voice"]["voice"] == "en-US-Test"


# ── Assembler duration fitting tests ──


class TestAssemblerHelpers:
    def test_build_atempo_filter_simple(self):
        from src.tts.assembler import _build_atempo_filter

        assert _build_atempo_filter(1.5) == "atempo=1.5000"

    def test_build_atempo_filter_double(self):
        from src.tts.assembler import _build_atempo_filter

        result = _build_atempo_filter(2.5)
        assert result == "atempo=2.0,atempo=1.2500"

    def test_build_atempo_filter_triple(self):
        from src.tts.assembler import _build_atempo_filter

        result = _build_atempo_filter(5.0)
        # 5.0 / 2.0 = 2.5 → 2.5 / 2.0 = 1.25
        assert result == "atempo=2.0,atempo=2.0,atempo=1.2500"

    def test_build_atempo_filter_exact_two(self):
        from src.tts.assembler import _build_atempo_filter

        result = _build_atempo_filter(2.0)
        assert result == "atempo=2.0000"

    def test_build_atempo_filter_one(self):
        from src.tts.assembler import _build_atempo_filter

        result = _build_atempo_filter(1.0)
        assert result == "atempo=1.0"


# ── FFmpeg audio mix command tests ──


class TestFFmpegAudioMix:
    @patch("src.processor.ffmpeg.subprocess.run")
    @patch("src.processor.ffmpeg.FFmpegProcessor._verify_ffmpeg")
    def test_mix_audio_command(self, mock_verify, mock_run):
        """Verify mix_audio constructs correct ffmpeg command."""
        from src.processor.ffmpeg import FFmpegProcessor

        mock_run.return_value = MagicMock(returncode=0)

        proc = FFmpegProcessor()
        proc.mix_audio(
            Path("video.mp4"),
            Path("tts.wav"),
            Path("output.mp4"),
            original_volume=0.3,
            tts_volume=1.0,
        )

        # Get the ffmpeg call (skip verify calls)
        calls = [c for c in mock_run.call_args_list if "mix" not in str(c) or True]
        ffmpeg_call = calls[-1]
        cmd = ffmpeg_call[0][0]

        assert "ffmpeg" in cmd[0]
        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        filter_str = cmd[fc_idx + 1]
        assert "volume=0.3" in filter_str
        assert "volume=1.0" in filter_str
        assert "amix=inputs=2" in filter_str

    @patch("src.processor.ffmpeg.subprocess.run")
    @patch("src.processor.ffmpeg.FFmpegProcessor._verify_ffmpeg")
    def test_burn_reformat_and_dub_command(self, mock_verify, mock_run):
        """Verify burn_reformat_and_dub constructs correct ffmpeg command."""
        from src.processor.ffmpeg import FFmpegProcessor

        # Mock ffprobe for get_video_info (if called for duration check)
        def side_effect(cmd, **kwargs):
            if "ffprobe" in cmd[0]:
                result = MagicMock()
                result.stdout = json.dumps({
                    "format": {"duration": "30.0", "size": "1000000"},
                    "streams": [{"codec_type": "video", "width": 1080, "height": 1920, "codec_name": "h264"}],
                })
                result.returncode = 0
                return result
            result = MagicMock()
            result.returncode = 0
            return result

        mock_run.side_effect = side_effect

        proc = FFmpegProcessor()
        proc.burn_reformat_and_dub(
            video_path=Path("video.mp4"),
            subtitle_path=Path("subs.srt"),
            tts_audio_path=Path("tts.wav"),
            platform="youtube",
            output_path=Path("out.mp4"),
            original_volume=0.2,
            tts_volume=0.8,
        )

        # Find the main ffmpeg call (not ffprobe)
        ffmpeg_calls = [c for c in mock_run.call_args_list if c[0][0][0] == "ffmpeg"]
        assert len(ffmpeg_calls) >= 1


# ── Batch processor TTS integration tests ──


class TestBatchProcessorTTS:
    @patch("src.processor.FFmpegProcessor")
    def test_process_with_tts_calls_dub(self, mock_proc_cls):
        """When tts_audio_paths is provided, burn_reformat_and_dub is called."""
        from src.processor import process_for_all_platforms

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        mock_proc.burn_reformat_and_dub.return_value = Path("data/output/test_youtube.mp4")

        # Create a fake SRT file
        srt_dir = Path("data/srt")
        srt_dir.mkdir(parents=True, exist_ok=True)
        srt_path = srt_dir / "test_en.srt"
        srt_path.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n",
            encoding="utf-8",
        )

        tts_path = Path("data/tts/test_en.wav")
        tts_path.parent.mkdir(parents=True, exist_ok=True)
        tts_path.write_bytes(b"fake wav data")

        try:
            results = process_for_all_platforms(
                video_id="test",
                video_path=Path("data/raw/test.mp4"),
                srt_dir=srt_dir,
                output_dir=Path("data/output"),
                platforms=["youtube"],
                config={},
                tts_audio_paths={"youtube": tts_path},
                tts_mix_settings={"youtube": {"original_volume": 0.2, "tts_volume": 0.9}},
            )
            mock_proc.burn_reformat_and_dub.assert_called_once()
            call_kwargs = mock_proc.burn_reformat_and_dub.call_args
            assert call_kwargs[1]["original_volume"] == 0.2
            assert call_kwargs[1]["tts_volume"] == 0.9
        finally:
            srt_path.unlink(missing_ok=True)
            tts_path.unlink(missing_ok=True)

    @patch("src.processor.FFmpegProcessor")
    def test_process_without_tts_calls_burn_and_reformat(self, mock_proc_cls):
        """When no TTS is provided, regular burn_and_reformat is called."""
        from src.processor import process_for_all_platforms

        mock_proc = MagicMock()
        mock_proc_cls.return_value = mock_proc
        mock_proc.burn_and_reformat.return_value = Path("data/output/test_youtube.mp4")

        srt_dir = Path("data/srt")
        srt_dir.mkdir(parents=True, exist_ok=True)
        srt_path = srt_dir / "test_en.srt"
        srt_path.write_text(
            "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n",
            encoding="utf-8",
        )

        try:
            results = process_for_all_platforms(
                video_id="test",
                video_path=Path("data/raw/test.mp4"),
                srt_dir=srt_dir,
                output_dir=Path("data/output"),
                platforms=["youtube"],
                config={},
            )
            mock_proc.burn_and_reformat.assert_called_once()
            mock_proc.burn_reformat_and_dub.assert_not_called()
        finally:
            srt_path.unlink(missing_ok=True)
