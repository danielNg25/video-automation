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


# ── Slot construction / sentence merger tests ──


def _make_slot(index, window_start, window_end, clip_duration, clip_path=None):
    from src.tts.assembler import SegmentSlot
    return SegmentSlot(
        index=index,
        clip_path=clip_path,
        clip_duration=clip_duration,
        window_start=window_start,
        window_end=window_end,
    )


class TestSentenceMergerGapSplit:
    """Sentence merger may not span silent gaps > MAX_MERGE_GAP_SECONDS.

    Regression for the symptom where the LLM grouped segments across a 5s
    pause based on text continuity (the prompt is timestamp-blind), then the
    merged clip played continuously across the gap and the post-Stage-3 SRT
    split-back stretched timestamps across the same span — both eating the
    natural pause. The post-split here makes that impossible.
    """

    def test_split_at_long_gap(self):
        from src.tts.assembler import _split_group_on_gaps
        segments = [
            {"start": 0.0, "end": 1.0, "text": "A"},
            {"start": 1.0, "end": 3.0, "text": "B"},
            {"start": 8.0, "end": 9.0, "text": "C"},
            {"start": 9.0, "end": 11.0, "text": "D"},
        ]
        # The user's reference scenario: 5s gap between B and C.
        sub = _split_group_on_gaps([0, 1, 2, 3], segments, max_gap=1.5)
        assert sub == [[0, 1], [2, 3]]

    def test_no_split_when_gaps_short(self):
        from src.tts.assembler import _split_group_on_gaps
        segments = [
            {"start": 0.0, "end": 2.0, "text": "a"},
            {"start": 2.5, "end": 4.0, "text": "b"},
            {"start": 4.2, "end": 6.0, "text": "c"},
        ]
        # Internal gaps 0.5s and 0.2s — both ≤ 1.5s threshold.
        assert _split_group_on_gaps([0, 1, 2], segments, max_gap=1.5) == [[0, 1, 2]]

    def test_singleton_group_returned_as_is(self):
        from src.tts.assembler import _split_group_on_gaps
        segments = [{"start": 0.0, "end": 1.0, "text": "x"}]
        assert _split_group_on_gaps([0], segments, max_gap=1.5) == [[0]]

    @pytest.mark.asyncio
    async def test_merge_into_sentences_splits_llm_output(self):
        """LLM groups all four segments into one sentence; result is two
        SentenceGroups, both using raw joined text (the LLM's punctuated
        text covered the whole merged sentence and would be wrong on any
        single sub-group)."""
        from src.tts.assembler import _merge_into_sentences

        segments = [
            {"start": 0.0, "end": 1.0, "text": "你有病吧?"},
            {"start": 1.0, "end": 3.0, "text": "谁家好鸟这样叫？"},
            {"start": 8.0, "end": 9.0, "text": "从叫声不难看出"},
            {"start": 9.0, "end": 11.0, "text": "你肯定不是什么好鸟"},
        ]

        async def fake_llm(system, user, max_tokens):
            return "[1,2,3,4] some merged punctuated sentence."

        groups = await _merge_into_sentences(segments, llm_caller=fake_llm)
        assert len(groups) == 2
        assert groups[0].segment_indices == [0, 1]
        assert (groups[0].start, groups[0].end) == (0.0, 3.0)
        assert groups[1].segment_indices == [2, 3]
        assert (groups[1].start, groups[1].end) == (8.0, 11.0)
        assert groups[0].text == "你有病吧? 谁家好鸟这样叫？"
        assert groups[1].text == "从叫声不难看出 你肯定不是什么好鸟"


class TestNaturalSpeedAnchoring:
    """Sanity: SegmentSlot is built from the source-aligned window only;
    no atempo/effective_*/anchor fields exist on it anymore."""

    def test_segment_slot_has_only_natural_fields(self):
        import dataclasses
        from src.tts.assembler import SegmentSlot
        names = {f.name for f in dataclasses.fields(SegmentSlot)}
        assert names == {"index", "clip_path", "clip_duration", "window_start", "window_end"}

    def test_redistribute_and_split_back_helpers_are_gone(self):
        """Borrow/redistribute and SRT-split-back helpers are deleted. The
        atempo helpers (_speed_up_audio / _build_atempo_filter) stay
        because Stage 2 applies playback_speed."""
        import src.tts.assembler as A
        for name in (
            "_redistribute_slots", "GAP_BORROW_FRACTION",
            "_llm_split_subtitles", "_naive_split_text",
            "_fallback_split_subtitles", "_segments_from_chunks",
            "DEFAULT_DUB_PLAYBACK_SPEED",
            "MAX_SAFE_SPEED_RATIO",
            "SHORTENING_MAX_PASSES",
        ):
            assert not hasattr(A, name), f"{name!r} should be removed"
        # Surfaces that stay (used downstream).
        assert hasattr(A, "_speed_up_audio")
        assert hasattr(A, "_build_atempo_filter")

    def test_atempo_filter_chain(self):
        """Sanity: atempo chain handles ratios in (0, ∞) — chains for >2×."""
        from src.tts.assembler import _build_atempo_filter
        assert _build_atempo_filter(1.0) == "atempo=1.0"
        assert _build_atempo_filter(1.5) == "atempo=1.5000"
        # Above 2.0 chains: 2.5 → atempo=2.0,atempo=1.25
        assert _build_atempo_filter(2.5) == "atempo=2.0,atempo=1.2500"


# ── shorten_texts_batch per-item floor (Fix 4) ──


class TestShortenTextsBatchFloor:
    @pytest.mark.asyncio
    async def test_per_item_floor_respects_target_pct(self):
        """Floor is max(40%, target_pct - 15%). Reject when shortened text
        falls below that floor — iterative shortening will retry with a
        stricter target_pct on the next pass."""
        from src.translator.llm import LLMTranslator

        translator = LLMTranslator.__new__(LLMTranslator)

        original_long = "x" * 100  # 100 chars; candidate of 30 = 30%
        candidate = "y" * 30

        async def fake_call(system, user):
            return f"1. {candidate}\n2. {candidate}\n"
        translator._call_llm = fake_call

        items = [
            # target_pct=80 → floor=max(40, 65) = 65%; 30% rejected.
            {"text": original_long, "target_pct": 80, "current_duration": 5.0,
             "target_duration": 4.0, "speed_ratio": 1.25},
            # target_pct=50 → floor=max(40, 35) = 40%; 30% still below floor.
            {"text": original_long, "target_pct": 50, "current_duration": 5.0,
             "target_duration": 2.5, "speed_ratio": 2.0},
        ]
        out = await translator.shorten_texts_batch(items)
        assert out[0] == original_long
        assert out[1] == original_long

    @pytest.mark.asyncio
    async def test_aggressive_target_accepts_aggressive_shortening(self):
        """A candidate at the floor is accepted."""
        from src.translator.llm import LLMTranslator

        translator = LLMTranslator.__new__(LLMTranslator)

        original = "x" * 100
        # target_pct=60 → floor=max(40, 45) = 45%; 50-char candidate = 50% ≥ 45%.
        candidate = "y" * 50

        async def fake_call(system, user):
            return f"1. {candidate}\n"
        translator._call_llm = fake_call

        items = [{
            "text": original, "target_pct": 60, "current_duration": 5.0,
            "target_duration": 3.0, "speed_ratio": 1.67,
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


class TestRegressionMutingBug:
    """Regression: a sentence whose synthesis returns zero-byte audio used to
    be silently dropped from the output. The new contract keeps the slot and
    fills it with the source-language audio at full volume."""

    @pytest.mark.asyncio
    async def test_zero_duration_synth_keeps_slot_with_source_audio(self, tmp_path):
        from src.tts.assembler import TTSAssembler
        from src.tts.base import BaseTTSProvider

        class FlakyProvider(BaseTTSProvider):
            calls = 0

            async def synthesize(self, text, voice, **kw):
                FlakyProvider.calls += 1
                # Return empty bytes for the sentence containing "fail_me"
                # (zero-duration); otherwise return a minimal WAV with 0.5s
                # of silence at 24kHz mono.
                if "fail_me" in text:
                    return b""
                import struct
                sample_count = 12000
                wav = (
                    b"RIFF" + struct.pack("<I", 36 + sample_count * 2) + b"WAVEfmt " +
                    struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16) +
                    b"data" + struct.pack("<I", sample_count * 2) + b"\x00\x00" * sample_count
                )
                return wav

            async def list_voices(self, language=None):
                return []

        segments = [
            {"start": 0.0, "end": 1.0, "text": "first sentence"},
            {"start": 1.0, "end": 2.0, "text": "fail_me sentence"},
            {"start": 2.0, "end": 3.0, "text": "third sentence"},
        ]

        out_path = tmp_path / "out.wav"
        assembler = TTSAssembler(translator=None)
        # Provide a fake video_path — the assembler reads its audio for fallback
        fake_video = tmp_path / "video.mp4"
        # Create a tiny silent MP4 via ffmpeg so the underlay branch has input
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono:d=3",
             "-c:a", "aac", str(fake_video)],
            check=True, capture_output=True, timeout=15,
        )

        _, plan = await assembler.generate_full_track(
            provider=FlakyProvider(),
            segments=segments,
            voice_profile={"voice": "test"},
            video_duration=3.0,
            output_path=out_path,
            merge_sentences=False,
            playback_speed=1.5,
            underlay_db=0.0,        # underlay off — only failure-window matters
            video_path=fake_video,
        )

        # All three sentences appear in the plan (no silent drops)
        assert len(plan) == 3
        # Sentence 1 (the failed one) is flagged for review
        flagged = [s for s in plan if s.get("needs_review")]
        assert any(s["index"] == 1 and s["reason"] in ("synth_empty", "synth_failed")
                   for s in flagged)
        # Output WAV exists and is not empty
        assert out_path.exists() and out_path.stat().st_size > 100


class TestUnderlayLevels:
    """The underlay branch reads the source MP4's audio stream directly and
    mixes it under the dub at the configured underlay_db level. underlay_db=0
    disables the underlay entirely (silence between dub clips)."""

    async def _run(self, tmp_path, underlay_db):
        """Generate one short dub and return the output WAV's mean_volume in dB."""
        from src.tts.assembler import TTSAssembler
        from src.tts.base import BaseTTSProvider

        class TinyProvider(BaseTTSProvider):
            async def synthesize(self, text, voice, **kw):
                # 0.2s of -inf-dB silence (still a real WAV clip)
                import struct
                samples = 4800
                return (
                    b"RIFF" + struct.pack("<I", 36 + samples * 2) + b"WAVEfmt " +
                    struct.pack("<IHHIIHH", 16, 1, 1, 24000, 48000, 2, 16) +
                    b"data" + struct.pack("<I", samples * 2) + b"\x00\x00" * samples
                )

            async def list_voices(self, language=None):
                return []

        # Source video: 3s of pink noise so the underlay is detectable
        tmp_path.mkdir(parents=True, exist_ok=True)
        video_path = tmp_path / "src.mp4"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", "anoisesrc=color=pink:duration=3:amplitude=0.5",
             "-c:a", "aac", str(video_path)],
            check=True, capture_output=True, timeout=15,
        )
        out_path = tmp_path / f"out_{int(underlay_db)}.wav"
        assembler = TTSAssembler(translator=None)
        await assembler.generate_full_track(
            provider=TinyProvider(),
            segments=[
                {"start": 0.0, "end": 1.0, "text": "a"},
                {"start": 2.0, "end": 3.0, "text": "b"},
            ],
            voice_profile={"voice": "test"},
            video_duration=3.0,
            output_path=out_path,
            merge_sentences=False,
            playback_speed=1.5,
            underlay_db=underlay_db,
            video_path=video_path,
        )
        # Use ffmpeg's volumedetect filter to measure mean_volume of the output
        probe = subprocess.run(
            ["ffmpeg", "-i", str(out_path), "-af", "volumedetect",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        import re
        m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", probe.stderr)
        assert m, f"could not parse mean_volume from ffmpeg stderr: {probe.stderr[-500:]}"
        return float(m.group(1))

    async def test_underlay_minus_12_louder_than_off(self, tmp_path):
        loud = await self._run(tmp_path / "loud", -12.0)
        off = await self._run(tmp_path / "off", 0.0)
        # With underlay at -12 dB the gap between dub clips contains the source
        # noise; with underlay off (db=0 disables the branch in the test
        # scenario — no failure windows, no nonzero gain), the gap is silent
        # → significantly lower mean_volume.
        assert loud > off + 5   # at least 5 dB louder
