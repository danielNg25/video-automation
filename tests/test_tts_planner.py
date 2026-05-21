"""Tests for the pure-function TTS dubbing planner.

The planner takes sentence groups + their natural-speed synth durations
+ user playback_speed + video_duration, and returns a DubPlan that
decides shortening targets, push amounts, gap reclaims, and review flags.
No ffmpeg, no LLM, no network — all tests run in milliseconds.
"""
from __future__ import annotations

import pytest

from src.tts.planner import (
    DRIFT_CAP,
    PLAYBACK_SPEED_DEFAULT,
    RECLAIM_MIN_GAP,
    RECLAIM_RESERVE,
    RESET_GAP_THRESHOLD,
    SHORTEN_FLOOR,
    SHORTEN_TARGETS,
    SHORTEN_UNDERSHOOT_OK,
    UNDERLAY_DB_DEFAULT,
    DubPlan,
    Planner,
    SentencePlan,
)


def _sentence(index: int, start: float, end: float, text: str = "test"):
    """Build the input shape the planner expects for one sentence group."""
    return {
        "index": index,
        "segment_indices": [index],
        "text": text,
        "start": start,
        "end": end,
    }


class TestPlannerConstants:
    def test_constants_match_spec(self):
        assert PLAYBACK_SPEED_DEFAULT == 1.5
        assert UNDERLAY_DB_DEFAULT == -12.0
        assert SHORTEN_TARGETS == (0.85, 0.75, 0.65)
        assert SHORTEN_FLOOR == 0.60
        assert RECLAIM_MIN_GAP == 1.0
        assert RECLAIM_RESERVE == 0.2
        assert RESET_GAP_THRESHOLD == 3.0
        assert DRIFT_CAP == 3.0
        assert SHORTEN_UNDERSHOOT_OK == 0.10


class TestDataclassShape:
    def test_sentence_plan_required_fields(self):
        p = SentencePlan(
            index=0, segment_indices=[0],
            original_text="x", target_text="x",
            natural_synth_duration=2.0,
            original_start=0.0, original_end=2.0,
            final_start=0.0, final_duration=2.0 / 1.5,
            drift_in=0.0, drift_out=0.0,
            shorten_pct=1.0, push_amount=0.0, reclaimed_silence=0.0,
            needs_review=False, reason=None,
        )
        assert p.index == 0
        assert p.target_text == "x"
        assert p.drift_in == 0.0
        assert p.drift_out == 0.0
        assert p.needs_review is False
        assert p.reason is None

    def test_dub_plan_required_fields(self):
        plan = DubPlan(
            sentences=[],
            playback_speed=1.5,
            underlay_db=-12.0,
            total_drift_end=0.0,
            drift_cap_hits=0,
            reset_points=[],
        )
        assert plan.playback_speed == 1.5
        assert plan.underlay_db == -12.0
        assert plan.drift_cap_hits == 0
        assert plan.reset_points == []


class TestPlannerEmpty:
    def test_empty_sentences_returns_empty_plan(self):
        plan = Planner.build_plan(
            sentences=[],
            natural_synth_durations=[],
            playback_speed=1.5,
            video_duration=10.0,
            underlay_db=-12.0,
        )
        assert plan.sentences == []
        assert plan.total_drift_end == 0.0
        assert plan.drift_cap_hits == 0
        assert plan.reset_points == []


class TestPhaseA:
    """Phase A: drift accumulation, gap reclaim, and reset at long pauses."""

    def test_all_sentences_fit_no_drift(self):
        # 3 sentences, each 2s slot, 2.0s natural synth → 1.33s played at 1.5×
        sents = [
            _sentence(0, 0.0, 2.0), _sentence(1, 2.0, 4.0), _sentence(2, 4.0, 6.0),
        ]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[2.0, 2.0, 2.0],
            playback_speed=1.5,
            video_duration=6.0,
            underlay_db=-12.0,
        )
        assert len(plan.sentences) == 3
        for sp in plan.sentences:
            assert sp.shorten_pct == 1.0
            assert sp.push_amount == 0.0
            assert sp.drift_in == 0.0
            assert sp.drift_out == 0.0
            assert sp.needs_review is False
            assert abs(sp.final_duration - 2.0 / 1.5) < 1e-6
            assert sp.final_start == sp.original_start

    def test_reclaim_recovers_drift_in_qualifying_gap(self):
        # Sentence 0 overruns its 1s slot by 0.6s (synth 2.4s @ 1.5× = 1.6s played)
        # Sentence 1 starts at t=2.0 → gap before it is 1.0s (qualifies, ≥ RECLAIM_MIN_GAP)
        # Sentence 1 is short and creates a 1.2s gap after itself (also qualifies)
        sents = [
            _sentence(0, 0.0, 1.0),
            _sentence(1, 2.0, 2.5),
            _sentence(2, 3.7, 5.0),
        ]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[2.4, 0.6, 1.5],
            playback_speed=1.5,
            video_duration=5.0,
            underlay_db=-12.0,
        )
        # Sentence 0 overruns by 0.6s; gap after = 1.0s → can absorb 1.0-0.2=0.8s
        # So sentence 0 absorbs all 0.6s; drift_out = 0
        assert plan.sentences[0].reclaimed_silence == pytest.approx(0.6, abs=1e-6)
        assert plan.sentences[0].push_amount == 0.0
        assert plan.sentences[0].drift_out == 0.0

    def test_drift_resets_at_long_pause(self):
        # Force drift via overrun, then a long pause (≥ RESET_GAP_THRESHOLD)
        sents = [
            _sentence(0, 0.0, 1.0),
            _sentence(1, 1.2, 1.5),   # tight gap, no reclaim
            _sentence(2, 5.0, 6.0),   # 3.5s gap before — should reset drift
        ]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[3.0, 0.5, 1.0],   # s0 overruns by 1.0s played
            playback_speed=1.5,
            video_duration=6.0,
            underlay_db=-12.0,
        )
        # After sentence 1, drift > 0. Sentence 2 follows a 3.5s gap → reset.
        assert plan.sentences[2].drift_in == 0.0
        assert plan.sentences[2].final_start == pytest.approx(5.0, abs=1e-6)
        assert 1 in plan.reset_points  # reset happened after sentence 1


class TestPhaseBShortenTargets:
    """Phase B picks the loosest target from SHORTEN_TARGETS that fits."""

    def test_picks_75_for_moderate_overrun(self):
        # 1s slot, 1.3s desired (1.95/1.5)
        # Required shorten ≈ 1.0/1.3 = 0.77 → pick loosest of (0.85, 0.75, 0.65)
        # that's ≤ 0.77 → 0.75
        sents = [
            _sentence(0, 0.0, 1.0),
            _sentence(1, 1.0, 5.0),   # big slot so no further drift
        ]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[1.95, 0.5],   # 1.95/1.5 = 1.3 played
            playback_speed=1.5,
            video_duration=5.0,
            underlay_db=-12.0,
        )
        assert plan.sentences[0].shorten_pct == 0.75

    def test_picks_85_when_15pct_overrun(self):
        # 1s slot, ~1.17s desired → required ≈ 1/1.17 = 0.855 → pick 0.85
        sents = [_sentence(0, 0.0, 1.0), _sentence(1, 1.0, 5.0)]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[1.755, 0.5],   # 1.755 / 1.5 = 1.17 played
            playback_speed=1.5,
            video_duration=5.0,
            underlay_db=-12.0,
        )
        assert plan.sentences[0].shorten_pct == 0.85

    def test_floor_at_60_when_even_65_does_not_fit(self):
        # 1s slot, 2.0s desired → required = 0.5 → no target ≤ 0.5, take SHORTEN_FLOOR
        sents = [_sentence(0, 0.0, 1.0), _sentence(1, 1.0, 5.0)]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[3.0, 0.5],   # 3.0 / 1.5 = 2.0 played
            playback_speed=1.5,
            video_duration=5.0,
            underlay_db=-12.0,
        )
        assert plan.sentences[0].shorten_pct == SHORTEN_FLOOR  # 0.60

    def test_no_shortening_when_no_overflow(self):
        sents = [_sentence(0, 0.0, 5.0)]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[3.0],
            playback_speed=1.5,
            video_duration=5.0,
            underlay_db=-12.0,
        )
        assert plan.sentences[0].shorten_pct == 1.0

    def test_reclaim_runs_before_shortening(self):
        # 1s slot, 1.2s desired, 2s gap after → reclaim absorbs the 0.2s overrun,
        # no shortening needed
        sents = [_sentence(0, 0.0, 1.0), _sentence(1, 3.0, 4.0)]
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[1.8, 0.5],
            playback_speed=1.5,
            video_duration=4.0,
            underlay_db=-12.0,
        )
        assert plan.sentences[0].shorten_pct == 1.0
        assert plan.sentences[0].reclaimed_silence > 0
