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


class TestPickShortenTarget:
    """Direct unit tests for the _pick_shorten_target helper.

    These tests pin the contract independently of Planner.build_plan so
    the helper's boundaries are unambiguous to anyone reading or
    reordering SHORTEN_TARGETS.
    """

    def test_returns_one_when_no_shortening_needed(self):
        from src.tts.planner import _pick_shorten_target
        assert _pick_shorten_target(1.0) == 1.0
        assert _pick_shorten_target(1.5) == 1.0

    def test_returns_85_at_exact_boundary(self):
        from src.tts.planner import _pick_shorten_target
        # required == 0.85 exactly → 0.85 ≤ 0.85 → returns 0.85
        assert _pick_shorten_target(0.85) == 0.85

    def test_returns_75_just_below_85(self):
        from src.tts.planner import _pick_shorten_target
        # required = 0.849 → 0.85 doesn't fit (0.85 > 0.849); 0.75 does
        assert _pick_shorten_target(0.849) == 0.75

    def test_returns_floor_when_required_below_lowest_target(self):
        from src.tts.planner import _pick_shorten_target
        # required = 0.40 → no target ≤ 0.40 → floor (0.60)
        assert _pick_shorten_target(0.40) == SHORTEN_FLOOR
        # required = 0 (extreme) → floor
        assert _pick_shorten_target(0.0) == SHORTEN_FLOOR

    def test_floor_returned_does_not_guarantee_fit(self):
        from src.tts.planner import _pick_shorten_target
        # Documenting via test: a required value below the floor still
        # returns the floor — the caller must handle the residual overrun.
        # 0.50 < SHORTEN_FLOOR (0.60), but the function returns 0.60
        # because that's the hard lower bound.
        assert _pick_shorten_target(0.50) == SHORTEN_FLOOR


class TestPhaseCDriftCap:
    """Phase C: if projected drift exceeds DRIFT_CAP, tighten upstream
    shortening until drift is bounded; flag if unrecoverable."""

    def test_no_rebalance_when_drift_under_cap(self):
        # Single small overrun → drift well under 3s cap
        sents = [_sentence(0, 0.0, 1.0), _sentence(1, 1.0, 5.0)]
        plan = Planner.build_plan(
            sentences=sents, natural_synth_durations=[1.8, 0.5],
            playback_speed=1.5, video_duration=5.0, underlay_db=-12.0,
        )
        assert plan.drift_cap_hits == 0

    def test_rebalance_floor_shortening_contains_drift(self):
        # Stack four sentences where each natural duration overruns the 1s slot.
        # Phase B applies SHORTEN_FLOOR (0.60) to each; the resulting 0.2s push
        # per sentence accumulates to only 0.8s drift — well under the 3s cap.
        # Phase C loop does not need to fire, so drift_cap_hits == 0.
        sents = [
            _sentence(0, 0.0, 1.0),
            _sentence(1, 1.0, 2.0),
            _sentence(2, 2.0, 3.0),
            _sentence(3, 3.0, 4.0),
            _sentence(4, 4.0, 10.0),   # big slot, no further drift
        ]
        # 3.0s natural at 1.5× → desired 2.0s; slot=1.0; required=0.5 → SHORTEN_FLOOR
        # played = 2.0×0.60 = 1.2s → push = 0.2s each → total drift = 0.8s < DRIFT_CAP
        plan = Planner.build_plan(
            sentences=sents, natural_synth_durations=[3.0, 3.0, 3.0, 3.0, 0.5],
            playback_speed=1.5, video_duration=10.0, underlay_db=-12.0,
        )
        # drift is contained by floor shortening; Phase C loop did not tighten anything
        assert plan.drift_cap_hits == 0
        # no sentence was flagged needs_review
        assert not any(s.needs_review for s in plan.sentences)
        # max drift across the four overrunning sentences is well under the cap
        max_drift = max(plan.sentences[i].drift_out for i in range(4))
        assert max_drift <= DRIFT_CAP

    def test_unrecoverable_drift_flags_needs_review(self):
        # All sentences already at SHORTEN_FLOOR — can't tighten further.
        # Six sentences, each 1s slot, 4s natural (2.67s played at 1.5×),
        # required shorten = 0.375 → all pick SHORTEN_FLOOR (0.60), still
        # overrun by 2.67×0.60 - 1.0 = 0.6s each → drift = 3.6s at sentence 5,
        # which strictly exceeds DRIFT_CAP (3.0s) and must be flagged.
        sents = [_sentence(i, float(i), float(i) + 1) for i in range(6)]
        sents.append(_sentence(6, 6.0, 16.0))   # final sentence has slack
        plan = Planner.build_plan(
            sentences=sents,
            natural_synth_durations=[4.0, 4.0, 4.0, 4.0, 4.0, 4.0, 0.5],
            playback_speed=1.5, video_duration=16.0, underlay_db=-12.0,
        )
        # At least one sentence flagged with drift_cap_hit
        review = [s for s in plan.sentences if s.needs_review]
        assert any(s.reason == "drift_cap_hit" for s in review)
        # The flagged sentence(s) must have drift strictly over the cap
        for s in review:
            assert s.drift_out > DRIFT_CAP


class TestPlaybackSpeedScaling:
    """The planner's decisions scale with playback_speed."""

    def _sents(self):
        return [
            _sentence(0, 0.0, 2.0),
            _sentence(1, 2.0, 4.0),
            _sentence(2, 4.0, 6.0),
        ]

    def test_at_1x_more_shortening_than_at_1_5x(self):
        natural = [3.0, 3.0, 3.0]
        plan_1x = Planner.build_plan(
            sentences=self._sents(), natural_synth_durations=natural,
            playback_speed=1.0, video_duration=6.0, underlay_db=-12.0,
        )
        plan_15 = Planner.build_plan(
            sentences=self._sents(), natural_synth_durations=natural,
            playback_speed=1.5, video_duration=6.0, underlay_db=-12.0,
        )
        shorten_count_1x = sum(1 for s in plan_1x.sentences if s.shorten_pct < 1.0)
        shorten_count_15 = sum(1 for s in plan_15.sentences if s.shorten_pct < 1.0)
        assert shorten_count_1x >= shorten_count_15

    def test_at_2x_no_shortening_needed(self):
        # 3s natural / 2.0× = 1.5s played; slots are 2s → fits without shortening
        natural = [3.0, 3.0, 3.0]
        plan = Planner.build_plan(
            sentences=self._sents(), natural_synth_durations=natural,
            playback_speed=2.0, video_duration=6.0, underlay_db=-12.0,
        )
        assert all(s.shorten_pct == 1.0 for s in plan.sentences)
        assert plan.total_drift_end == 0.0

    def test_played_duration_scales_inversely_with_speed(self):
        natural = [3.0]
        sents = [_sentence(0, 0.0, 10.0)]
        plan_1x = Planner.build_plan(
            sentences=sents, natural_synth_durations=natural,
            playback_speed=1.0, video_duration=10.0, underlay_db=-12.0,
        )
        plan_15 = Planner.build_plan(
            sentences=sents, natural_synth_durations=natural,
            playback_speed=1.5, video_duration=10.0, underlay_db=-12.0,
        )
        assert plan_1x.sentences[0].final_duration == pytest.approx(3.0, abs=1e-6)
        assert plan_15.sentences[0].final_duration == pytest.approx(2.0, abs=1e-6)
