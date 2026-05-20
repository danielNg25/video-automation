"""Pure-function TTS dubbing planner.

Decides, for each merged sentence: shortening target, push amount, gap
reclaim, and needs_review flag. Returns a DubPlan that downstream
emission consumes. No ffmpeg, no LLM, no I/O — everything here is
deterministic so it can be unit-tested without external dependencies.

All durations are in "played-seconds" (post-atempo at playback_speed).
The conversion `played = natural / playback_speed` is applied once at
the top of build_plan; nothing downstream needs to know about natural
speed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Constants (see docs/superpowers/specs/2026-05-20-tts-dubbing-redesign.md) ──
PLAYBACK_SPEED_DEFAULT = 1.5
UNDERLAY_DB_DEFAULT = -12.0
SHORTEN_TARGETS = (0.85, 0.75, 0.65)   # try in order, loosest first
SHORTEN_FLOOR = 0.60                    # never accept text below this fraction
RECLAIM_MIN_GAP = 1.0                   # only reclaim from silent gaps ≥ this
RECLAIM_RESERVE = 0.2                   # leave this much silence after reclaim
RESET_GAP_THRESHOLD = 3.0               # gaps ≥ this reset accumulated drift
DRIFT_CAP = 3.0                         # max accumulated drift before rebalance
SHORTEN_UNDERSHOOT_OK = 0.10            # accept clip up to 10% over planned


@dataclass
class SentencePlan:
    index: int
    segment_indices: list[int]
    original_text: str
    target_text: str
    natural_synth_duration: float
    original_start: float
    original_end: float
    final_start: float
    final_duration: float
    drift_in: float
    drift_out: float
    shorten_pct: float
    push_amount: float
    reclaimed_silence: float
    needs_review: bool
    reason: str | None


@dataclass
class DubPlan:
    sentences: list[SentencePlan]
    playback_speed: float
    underlay_db: float
    total_drift_end: float
    drift_cap_hits: int
    reset_points: list[int] = field(default_factory=list)


class Planner:
    """Pure-function planner. All methods static; no instance state."""

    @staticmethod
    def build_plan(
        *,
        sentences: list[dict],
        natural_synth_durations: list[float],
        playback_speed: float,
        video_duration: float,
        underlay_db: float,
    ) -> DubPlan:
        """Build the global DubPlan. Returns an empty plan for empty input."""
        if not sentences:
            return DubPlan(
                sentences=[],
                playback_speed=playback_speed,
                underlay_db=underlay_db,
                total_drift_end=0.0,
                drift_cap_hits=0,
            )
        if len(natural_synth_durations) != len(sentences):
            raise ValueError(
                f"natural_synth_durations length {len(natural_synth_durations)} "
                f"does not match sentences length {len(sentences)}"
            )

        out: list[SentencePlan] = []
        reset_points: list[int] = []
        drift = 0.0
        N = len(sentences)

        for i in range(N):
            s = sentences[i]
            natural = natural_synth_durations[i]
            desired = natural / playback_speed if playback_speed > 0 else natural
            orig_start = float(s["start"])
            orig_end = float(s["end"])
            slot_size = max(0.0, orig_end - orig_start)
            next_start = (
                float(sentences[i + 1]["start"]) if i + 1 < N else video_duration
            )
            raw_gap_after = max(0.0, next_start - orig_end)

            final_start = orig_start + drift
            reclaimed = 0.0
            push_amount = 0.0

            if desired <= slot_size:
                final_duration = desired
                # If we entered with drift, try to recover via the gap after us.
                if drift > 0 and raw_gap_after >= RECLAIM_MIN_GAP:
                    reclaim = min(drift, raw_gap_after - RECLAIM_RESERVE)
                    if reclaim > 0:
                        drift -= reclaim
                        reclaimed = reclaim
            else:
                overrun = desired - slot_size
                # First absorb what the gap will let us
                if raw_gap_after >= RECLAIM_MIN_GAP:
                    absorb = min(overrun, raw_gap_after - RECLAIM_RESERVE)
                    if absorb > 0:
                        overrun -= absorb
                        reclaimed = absorb
                final_duration = desired
                if overrun > 0:
                    drift += overrun
                    push_amount = overrun

            drift_out = drift

            out.append(SentencePlan(
                index=i,
                segment_indices=list(s.get("segment_indices", [i])),
                original_text=s.get("text", ""),
                target_text=s.get("text", ""),
                natural_synth_duration=natural,
                original_start=orig_start,
                original_end=orig_end,
                final_start=final_start,
                final_duration=final_duration,
                drift_in=final_start - orig_start,
                drift_out=drift_out,
                shorten_pct=1.0,
                push_amount=push_amount,
                reclaimed_silence=reclaimed,
                needs_review=False,
                reason=None,
            ))

            if raw_gap_after >= RESET_GAP_THRESHOLD:
                reset_points.append(i)
                drift = 0.0

        return DubPlan(
            sentences=out,
            playback_speed=playback_speed,
            underlay_db=underlay_db,
            total_drift_end=drift,
            drift_cap_hits=0,
            reset_points=reset_points,
        )
