"""Tests for the TTS module: base class, factory, assembler, and ffmpeg audio mixing."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    def test_default_provider_is_google(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        provider = get_tts_provider({})
        assert isinstance(provider, GoogleTTSProvider)

    def test_explicit_google_provider(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        provider = get_tts_provider({}, provider="google")
        assert isinstance(provider, GoogleTTSProvider)

    def test_unknown_provider_raises(self):
        from src.tts import get_tts_provider

        with pytest.raises(ValueError, match="Unknown TTS provider"):
            get_tts_provider({}, provider="nonexistent")

    def test_removed_providers_raise(self):
        """Edge, gtts, and piper were deleted and now must raise."""
        from src.tts import get_tts_provider

        for removed in ("edge", "gtts", "piper"):
            with pytest.raises(ValueError, match="Unknown TTS provider"):
                get_tts_provider({}, provider=removed)

    def test_config_default_provider(self):
        from src.tts import get_tts_provider
        from src.tts.google_tts import GoogleTTSProvider

        config = {"tts": {"default_provider": "google"}}
        provider = get_tts_provider(config)
        assert isinstance(provider, GoogleTTSProvider)


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
        assert profiles["default_provider"] == "google"
        assert profiles["profiles"] == {}

    def test_save_and_load_profiles(self, tmp_path):
        from src.tts import load_voice_profiles, save_voice_profiles

        config = {"tts": {"voices_config": str(tmp_path / "test_voices.yaml")}}
        data = {
            "default_provider": "google",
            "profiles": {"test-voice": {"provider": "google", "voice": "en-US-Neural2-A", "language": "en"}},
            "platforms": {},
        }
        save_voice_profiles(data, config)
        loaded = load_voice_profiles(config)
        assert loaded["profiles"]["test-voice"]["voice"] == "en-US-Neural2-A"


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
        from src.tts.runner import _DEFAULT_LLM_MODELS

        captured = {}

        class FakeTranslator:
            def __init__(self, **kw):
                captured.update(kw)

        # Patch LLMTranslator inside the module so _build_llm_translator
        # constructs our fake.
        import src.tts.runner as runner_mod

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




class TestDubsyncSrtWriter:
    """The dubsync writer redistributes shortened text and final timings
    proportionally across the original source segments."""

    def test_redistributes_text_at_word_boundaries(self, tmp_path):
        from src.tts.dubsync_srt import write_dubsync_srt
        # One merged sentence covering 3 source segments; target text is
        # shorter than the joined originals.
        source_segments = [
            {"start": 0.0, "end": 1.0, "text": "one two three"},
            {"start": 1.0, "end": 2.0, "text": "four five six seven"},
            {"start": 2.0, "end": 3.0, "text": "eight nine"},
        ]
        sentence_plans = [
            {
                "segment_indices": [0, 1, 2],
                "target_text": "alpha beta gamma delta",
                "final_start": 0.0, "final_duration": 3.0,
            }
        ]
        out = tmp_path / "out.dubsync.srt"
        write_dubsync_srt(source_segments, sentence_plans, out)
        from src.processor.subtitle import parse_srt
        rewritten = parse_srt(out)
        assert len(rewritten) == 3
        joined = " ".join(r["text"] for r in rewritten).replace("  ", " ").strip()
        assert joined == "alpha beta gamma delta"

    def test_timing_is_proportional_to_original_durations(self, tmp_path):
        from src.processor.subtitle import parse_srt
        from src.tts.dubsync_srt import write_dubsync_srt
        source_segments = [
            {"start": 0.0, "end": 0.5, "text": "a"},   # 0.5s
            {"start": 0.5, "end": 2.5, "text": "b"},   # 2.0s
        ]
        sentence_plans = [
            {
                "segment_indices": [0, 1],
                "target_text": "alpha beta",
                "final_start": 10.0, "final_duration": 5.0,
            }
        ]
        out = tmp_path / "out.dubsync.srt"
        write_dubsync_srt(source_segments, sentence_plans, out)
        rewritten = parse_srt(out)
        # First segment: 0.5/2.5 of 5.0 = 1.0s; second: 4.0s
        assert rewritten[0]["start"] == pytest.approx(10.0, abs=1e-3)
        assert rewritten[0]["end"] == pytest.approx(11.0, abs=1e-3)
        assert rewritten[1]["start"] == pytest.approx(11.0, abs=1e-3)
        assert rewritten[1]["end"] == pytest.approx(15.0, abs=1e-3)

    def test_writer_handles_actual_assembler_dict_shape(self, tmp_path):
        """Regression: the assembler's sentence_plan dict shape must include
        `segment_indices`, `target_text`, `final_start`, and `final_duration`.
        If any are missing, the writer's main loop skips the sentence and the
        defensive `preserve source unchanged` branch emits original segments.
        This was a real bug shipped in the dubbing redesign and silently
        masked by the defensive fallback.

        The fix is in `src/tts/assembler.py`'s sentence_plan.append block.
        This test pins the contract by constructing a sentence_plans list
        using the EXACT keys the assembler emits and asserting the writer's
        main loop runs (not the fallback)."""
        from src.processor.subtitle import parse_srt
        from src.tts.dubsync_srt import write_dubsync_srt

        # Source segments — 3 entries with distinct timings
        source_segments = [
            {"start": 0.0, "end": 1.0, "text": "alpha original"},
            {"start": 1.0, "end": 2.0, "text": "beta original"},
            {"start": 2.0, "end": 3.5, "text": "gamma original"},
        ]
        # A single merged sentence covering all 3, with shortened text AND a
        # pushed-back final_start to make the rewrite visible.
        sentence_plans = [
            {
                "index": 0,
                "segment_indices": [0, 1, 2],
                "text": "shortened spoken text",
                "target_text": "shortened spoken text",
                "original_text": "alpha original beta original gamma original",
                "start": 5.0,
                "end": 7.5,
                "final_start": 5.0,
                "final_duration": 2.5,
            }
        ]
        out = tmp_path / "test_id_vi.dubsync.srt"
        write_dubsync_srt(source_segments, sentence_plans, out)
        rewritten = parse_srt(out)

        # The writer's main loop produced 3 entries (one per source segment).
        assert len(rewritten) == 3, (
            f"Expected 3 rewritten entries (one per source segment); got "
            f"{len(rewritten)}. If 0 or unchanged-source, the writer's "
            f"main loop didn't run — segment_indices key likely missing."
        )

        # CRITICAL: each rewritten entry's TEXT is a slice of the SHORTENED
        # `target_text`, not the original segment text. If the writer fell
        # through to the defensive branch, the text would equal the originals
        # ("alpha original" etc.).
        joined = " ".join(r["text"] for r in rewritten).replace("  ", " ").strip()
        assert joined == "shortened spoken text", (
            f"Rewritten text is not the redistributed target_text; got "
            f"{joined!r}. The writer likely fell through to the defensive "
            f"'preserve source unchanged' branch."
        )

        # CRITICAL: timings must be anchored at final_start=5.0, not the
        # source's start=0.0. If the writer fell through, the first entry's
        # start would be 0.0.
        assert rewritten[0]["start"] == pytest.approx(5.0, abs=1e-3), (
            f"First rewritten entry's start is {rewritten[0]['start']!r}; "
            f"expected ~5.0 (from final_start). The writer likely fell "
            f"through to the defensive branch."
        )


