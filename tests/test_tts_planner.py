"""Tests for the pure-function TTS dubbing planner.

The planner takes sentence groups + their natural-speed synth durations
+ user playback_speed + video_duration, and returns a DubPlan that
decides shortening targets, push amounts, gap reclaims, and review flags.
No ffmpeg, no LLM, no network — all tests run in milliseconds.
"""
from __future__ import annotations

from src.tts.planner import (
    DRIFT_CAP,
    PLAYBACK_SPEED_DEFAULT,
    RECLAIM_MIN_GAP,
    RESET_GAP_THRESHOLD,
    SHORTEN_FLOOR,
    SHORTEN_TARGETS,
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
        assert RESET_GAP_THRESHOLD == 3.0
        assert DRIFT_CAP == 3.0


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
