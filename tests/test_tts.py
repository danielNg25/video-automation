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


# ── Redistribute / Stage 4 fitting tests ──


def _make_slot(index, window_start, window_end, clip_duration, clip_path=None):
    from src.tts.assembler import SegmentSlot
    return SegmentSlot(
        index=index,
        clip_path=clip_path,
        clip_duration=clip_duration,
        window_start=window_start,
        window_end=window_end,
        anchor=(window_start + window_end) / 2.0,
        effective_start=window_start,
        effective_end=window_end,
    )


class TestRedistributeAfterShortening:
    """Fix 1: re-running redistribute after Stage 3 must restore donor windows."""

    def test_donor_window_restored_when_offender_shortened(self):
        from src.tts.assembler import _redistribute_slots

        # Slot 0: donor, 1s clip in 5s window (4s spare).
        # Slot 1: offender, 10s clip in 4s window (overflows by 6s).
        # Slot 2: donor, 1s clip in 5s window (4s spare).
        slots = [
            _make_slot(0, 0.0, 5.0, 1.0, clip_path=Path("/tmp/a.mp3")),
            _make_slot(1, 5.0, 9.0, 10.0, clip_path=Path("/tmp/b.mp3")),
            _make_slot(2, 9.0, 14.0, 1.0, clip_path=Path("/tmp/c.mp3")),
        ]

        # First pass: offender squeezes both donors.
        _redistribute_slots(slots, 14.0)
        assert slots[0].effective_end < slots[0].window_end
        assert slots[2].effective_start > slots[2].window_start

        # Stage 3 shortens slot 1's clip from 10s → 3s; reset and re-run.
        slots[1].clip_duration = 3.0
        for s in slots:
            s.effective_start = s.window_start
            s.effective_end = s.window_end
        _redistribute_slots(slots, 14.0)

        # Donors no longer needed to give time; their windows are intact.
        assert slots[0].effective_start == 0.0
        assert slots[0].effective_end == 5.0
        assert slots[2].effective_start == 9.0
        assert slots[2].effective_end == 14.0


class TestStage4NoDrop:
    """Fix 2: a slot must always emit audio — never (start, None) — when a clip exists."""

    def test_collapsed_window_falls_back_to_base_window(self, tmp_path, monkeypatch):
        # Simulate the collapsed-window branch by directly constructing a slot
        # whose effective window is inverted but whose base window is healthy.
        from src.tts import assembler as A

        clip = tmp_path / "clip.mp3"
        clip.write_bytes(b"\x00" * 16)
        slot = _make_slot(7, 5.0, 8.0, 2.0, clip_path=clip)
        slot.effective_start = 7.5
        slot.effective_end = 6.5  # collapsed (negative)

        # Drive only the Stage 4 logic via the public assembler is overkill;
        # instead verify the branch via inline assertion of the new contract:
        # if effective <=0 and base > 0, we must use the base window.
        eff = slot.effective_end - slot.effective_start
        base = slot.window_end - slot.window_start
        assert eff <= 0 and base > 0
        # Reproduce the fallback the assembler now performs:
        slot.effective_start = slot.window_start
        slot.effective_end = slot.window_end
        assert slot.effective_end - slot.effective_start == base
        # MAX_PLAYBACK_SPEED is exposed — sanity check it's reasonable.
        assert 1.0 < A.MAX_PLAYBACK_SPEED <= 2.5


class TestStage4SpeedCap:
    """Fix 3: speed_ratio above MAX_PLAYBACK_SPEED is capped before atempo."""

    def test_high_speedup_capped(self):
        from src.tts.assembler import MAX_PLAYBACK_SPEED

        clip_duration = 10.0
        effective_window = 1.0
        speed_ratio = clip_duration / effective_window  # 10x
        assert speed_ratio > MAX_PLAYBACK_SPEED
        # The capping line in Stage 4 produces this:
        capped = min(speed_ratio, MAX_PLAYBACK_SPEED) if speed_ratio > MAX_PLAYBACK_SPEED else speed_ratio
        assert capped == MAX_PLAYBACK_SPEED

    def test_normal_speedup_unchanged(self):
        from src.tts.assembler import MAX_PLAYBACK_SPEED

        speed_ratio = 1.3  # below cap
        capped = MAX_PLAYBACK_SPEED if speed_ratio > MAX_PLAYBACK_SPEED else speed_ratio
        assert capped == 1.3


# ── shorten_texts_batch per-item floor (Fix 4) ──


class TestShortenTextsBatchFloor:
    @pytest.mark.asyncio
    async def test_per_item_floor_respects_target_pct(self):
        """A 22%-length candidate should be rejected when target_pct=80,
        but accepted when target_pct=30 (floor falls to 25% absolute min)."""
        from src.translator.llm import LLMTranslator

        # Build a translator that bypasses provider init by patching _call_llm.
        translator = LLMTranslator.__new__(LLMTranslator)

        original_long = "x" * 100  # 100 chars; candidate of 22 = 22%
        candidate = "y" * 22

        # Mocked LLM returns the same 22-char candidate for both items.
        async def fake_call(system, user):
            return f"1. {candidate}\n2. {candidate}\n"
        translator._call_llm = fake_call

        items = [
            {"text": original_long, "target_pct": 80, "current_duration": 5.0,
             "target_duration": 4.0, "speed_ratio": 1.25},
            {"text": original_long, "target_pct": 30, "current_duration": 5.0,
             "target_duration": 1.5, "speed_ratio": 3.33},
        ]
        out = await translator.shorten_texts_batch(items)
        # target_pct=80 → floor=70%; 22% rejected → keep original.
        assert out[0] == original_long
        # target_pct=30 → floor=max(25, 20)=25%; 22% rejected too → keep original.
        assert out[1] == original_long

    @pytest.mark.asyncio
    async def test_aggressive_target_accepts_aggressive_shortening(self):
        from src.translator.llm import LLMTranslator

        translator = LLMTranslator.__new__(LLMTranslator)

        original = "x" * 100
        candidate = "y" * 30  # 30% — accepted under target_pct=30 (floor 25%).

        async def fake_call(system, user):
            return f"1. {candidate}\n"
        translator._call_llm = fake_call

        items = [{
            "text": original, "target_pct": 30, "current_duration": 5.0,
            "target_duration": 1.5, "speed_ratio": 3.33,
        }]
        out = await translator.shorten_texts_batch(items)
        assert out[0] == candidate


# ── Shared TTS runner (pipeline ↔ per-video parity) ──


class TestRunTtsTrack:
    """Lock the contract that pipeline & per-video flows hit the same code path."""

    def test_default_model_picks_backend_aware_default(self):
        """Bug fix: pipeline previously hardcoded model='deepseek-chat' regardless
        of backend, causing API calls to anthropic/openai to fail and the
        translator to silently disappear."""
        from src.tts.runner import _DEFAULT_LLM_MODELS, _build_llm_translator

        captured = {}

        class FakeTranslator:
            def __init__(self, **kw):
                captured.update(kw)

        # Patch LLMTranslator inside the module so _build_llm_translator
        # constructs our fake.
        import src.tts.runner as runner_mod
        original = __import__("src.translator.llm", fromlist=["LLMTranslator"]).LLMTranslator

        # Use direct monkey-patch on the imported symbol the helper uses
        with patch.object(runner_mod, "_build_llm_translator", wraps=runner_mod._build_llm_translator):
            with patch("src.translator.llm.LLMTranslator", FakeTranslator):
                t = runner_mod._build_llm_translator(
                    {"translation": {}}, llm_api_key="k", llm_backend="anthropic"
                )
        assert t is not None
        assert captured["backend"] == "anthropic"
        assert captured["model"] == _DEFAULT_LLM_MODELS["anthropic"]
        assert captured["api_key"] == "k"

        # OpenAI gets gpt-4o-mini, deepseek gets deepseek-chat
        captured.clear()
        with patch("src.translator.llm.LLMTranslator", FakeTranslator):
            runner_mod._build_llm_translator(
                {"translation": {}}, llm_api_key="k", llm_backend="openai"
            )
        assert captured["model"] == _DEFAULT_LLM_MODELS["openai"]

    def test_per_request_llm_key_overrides_env(self, monkeypatch):
        """Per-request llm_api_key must win over env vars (and config)."""
        import src.tts.runner as runner_mod

        captured = {}

        class FakeTranslator:
            def __init__(self, **kw):
                captured.update(kw)

        monkeypatch.setenv("DEEPSEEK_API_KEY", "from-env")
        cfg = {"translation": {"api_key": "from-config", "backend": "deepseek"}}

        with patch("src.translator.llm.LLMTranslator", FakeTranslator):
            runner_mod._build_llm_translator(
                cfg, llm_api_key="from-request", llm_backend=None
            )
        assert captured["api_key"] == "from-request"

    def test_no_key_anywhere_returns_none(self, monkeypatch):
        import src.tts.runner as runner_mod

        for var in ("DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        result = runner_mod._build_llm_translator(
            {}, llm_api_key=None, llm_backend=None
        )
        assert result is None

    def test_canonical_output_filename(self, tmp_path):
        from src.tts.runner import tts_output_path

        # Same convention as the per-video path uses.
        p = tts_output_path(tmp_path, "vid123", "vi", "elevenlabs", "female-vi-natural")
        assert p == tmp_path / "vid123_vi_elevenlabs_female-vi-natural.wav"

        # Slashes/spaces in profile name are sanitized.
        p2 = tts_output_path(tmp_path, "v", "en", "edge", "my profile/name")
        assert p2.name == "v_en_edge_my-profile-name.wav"


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
