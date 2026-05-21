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


def _required_shorten_pct(desired: float, available: float) -> float:
    """Return the maximum shorten ratio that fits `desired` into `available`.

    The return value is `available / desired` clamped to [0.0, ∞): if the
    sentence is shortened to this fraction (e.g. 0.75 = 75% of original
    length) its played duration will equal `available`. Larger fractions
    overrun; smaller fractions leave silence. Caller still has to pick a
    discrete target from `SHORTEN_TARGETS` via `_pick_shorten_target`.

    Returns 1.0 when desired <= 0 (no shortening computable / needed).
    """
    if desired <= 0:
        return 1.0
    return max(0.0, available / desired)


def _pick_shorten_target(required: float) -> float:
    """Pick the loosest target in SHORTEN_TARGETS that's ≤ required.

    `required` is the fraction (from `_required_shorten_pct`) below which
    the sentence fits its available time. Returns 1.0 when no shortening
    is needed (required >= 1.0). Otherwise iterates SHORTEN_TARGETS
    loosest-first and returns the first target ≤ required.

    When `required` is below the smallest target in SHORTEN_TARGETS
    (currently 0.65), returns SHORTEN_FLOOR (0.60) — note this is a
    hard lower bound, not a guarantee that the sentence will fit. If
    `required < SHORTEN_FLOOR`, even shortening to the floor will
    still overrun and the planner's Phase A walk will add the
    remainder to drift.
    """
    if required >= 1.0:
        return 1.0
    for t in SHORTEN_TARGETS:   # loosest first
        if t <= required:
            return t
    return SHORTEN_FLOOR


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
                sentences=[], playback_speed=playback_speed,
                underlay_db=underlay_db, total_drift_end=0.0,
                drift_cap_hits=0,
            )
        if len(natural_synth_durations) != len(sentences):
            raise ValueError(
                f"natural_synth_durations length {len(natural_synth_durations)} "
                f"does not match sentences length {len(sentences)}"
            )
        if playback_speed <= 0:
            raise ValueError(
                f"playback_speed must be > 0, got {playback_speed}"
            )

        N = len(sentences)
        # Pre-compute per-sentence statics
        orig_starts = [float(s["start"]) for s in sentences]
        orig_ends = [float(s["end"]) for s in sentences]
        slot_sizes = [max(0.0, e - s) for s, e in zip(orig_starts, orig_ends)]
        raw_gaps_after = [
            max(0.0, (orig_starts[i + 1] if i + 1 < N else video_duration) - orig_ends[i])
            for i in range(N)
        ]
        desired_natural = [natural_synth_durations[i] / playback_speed for i in range(N)]

        # Phase B (preview): pick shorten targets based on slot + max reclaim
        shorten_pcts = [1.0] * N
        for i in range(N):
            slot = slot_sizes[i]
            gap = raw_gaps_after[i]
            reclaim_room = max(0.0, gap - RECLAIM_RESERVE) if gap >= RECLAIM_MIN_GAP else 0.0
            available = slot + reclaim_room
            shorten_pcts[i] = _pick_shorten_target(
                _required_shorten_pct(desired_natural[i], available)
            )

        # Effective desired durations after Phase B's shortening decision
        effective_desired = [desired_natural[i] * shorten_pcts[i] for i in range(N)]

        # Phase A (recomputed against effective durations)
        out: list[SentencePlan] = []
        reset_points: list[int] = []
        drift = 0.0
        for i in range(N):
            desired = effective_desired[i]
            slot = slot_sizes[i]
            gap = raw_gaps_after[i]
            drift_in_value = drift
            final_start = orig_starts[i] + drift
            reclaimed = 0.0
            push_amount = 0.0

            if desired <= slot:
                final_duration = desired
                if drift > 0 and gap >= RECLAIM_MIN_GAP:
                    reclaim = min(drift, gap - RECLAIM_RESERVE)
                    if reclaim > 0:
                        drift -= reclaim
                        reclaimed = reclaim
            else:
                overrun = desired - slot
                if gap >= RECLAIM_MIN_GAP:
                    absorb = min(overrun, gap - RECLAIM_RESERVE)
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
                segment_indices=list(sentences[i].get("segment_indices", [i])),
                original_text=sentences[i].get("text", ""),
                target_text=sentences[i].get("text", ""),
                natural_synth_duration=natural_synth_durations[i],
                original_start=orig_starts[i],
                original_end=orig_ends[i],
                final_start=final_start,
                final_duration=final_duration,
                drift_in=drift_in_value,
                drift_out=drift_out,
                shorten_pct=shorten_pcts[i],
                push_amount=push_amount,
                reclaimed_silence=reclaimed,
                needs_review=False,
                reason=None,
            ))

            if gap >= RESET_GAP_THRESHOLD:
                reset_points.append(i)
                drift = 0.0

        return DubPlan(
            sentences=out, playback_speed=playback_speed,
            underlay_db=underlay_db, total_drift_end=drift,
            drift_cap_hits=0, reset_points=reset_points,
        )
