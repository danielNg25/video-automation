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
UNDERLAY_DB_DEFAULT = -18.0
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


def _tighten(current: float) -> float | None:
    """Return the next-tighter target after `current`, or None if at floor.

    Walks SHORTEN_TARGETS in order; returns the first target strictly less
    than `current`; if none, returns SHORTEN_FLOOR if `current` is above
    the floor; else None (caller is already at the hard floor).
    """
    for t in SHORTEN_TARGETS:
        if t < current:
            return t
    if current > SHORTEN_FLOOR:
        return SHORTEN_FLOOR
    return None


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


@dataclass
class _StaticsBundle:
    """Pre-computed per-sentence inputs the planner reuses across iterations."""
    sentences: list[dict]
    natural_synth_durations: list[float]
    playback_speed: float
    video_duration: float
    orig_starts: list[float] = field(init=False)
    orig_ends: list[float] = field(init=False)
    slot_sizes: list[float] = field(init=False)
    gaps_after: list[float] = field(init=False)
    desired_natural: list[float] = field(init=False)

    def __post_init__(self):
        N = len(self.sentences)
        self.orig_starts = [float(s["start"]) for s in self.sentences]
        self.orig_ends = [float(s["end"]) for s in self.sentences]
        self.slot_sizes = [
            max(0.0, e - s) for s, e in zip(self.orig_starts, self.orig_ends)
        ]
        self.gaps_after = [
            max(
                0.0,
                (self.orig_starts[i + 1] if i + 1 < N else self.video_duration)
                - self.orig_ends[i],
            )
            for i in range(N)
        ]
        # playback_speed > 0 is already validated by Planner.build_plan.
        self.desired_natural = [
            self.natural_synth_durations[i] / self.playback_speed for i in range(N)
        ]

    def simulate(
        self, shorten_pcts: list[float]
    ) -> tuple[list[SentencePlan], list[int], float, int]:
        """Walk sentences once with the given shorten_pcts, returning the
        full sentence list, reset points, max drift seen, and the index at
        which max drift was observed."""
        N = len(self.sentences)
        out: list[SentencePlan] = []
        reset_points: list[int] = []
        drift = 0.0
        max_drift = 0.0
        peak_idx = 0
        for i in range(N):
            desired = self.desired_natural[i] * shorten_pcts[i]
            slot = self.slot_sizes[i]
            gap = self.gaps_after[i]
            drift_in_value = drift
            final_start = self.orig_starts[i] + drift
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
            if drift > max_drift:
                max_drift = drift
                peak_idx = i
            out.append(SentencePlan(
                index=i,
                segment_indices=list(self.sentences[i].get("segment_indices", [i])),
                original_text=self.sentences[i].get("text", ""),
                target_text=self.sentences[i].get("text", ""),
                natural_synth_duration=self.natural_synth_durations[i],
                original_start=self.orig_starts[i],
                original_end=self.orig_ends[i],
                final_start=final_start,
                final_duration=final_duration,
                drift_in=drift_in_value,
                drift_out=drift,
                shorten_pct=shorten_pcts[i],
                push_amount=push_amount,
                reclaimed_silence=reclaimed,
                needs_review=False,
                reason=None,
            ))
            if gap >= RESET_GAP_THRESHOLD:
                reset_points.append(i)
                drift = 0.0
        return out, reset_points, max_drift, peak_idx


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
        statics = _StaticsBundle(
            sentences=sentences,
            natural_synth_durations=natural_synth_durations,
            playback_speed=playback_speed,
            video_duration=video_duration,
        )

        # Phase B initial: per-sentence target based on slot + max reclaim
        shorten_pcts: list[float] = []
        for i in range(N):
            slot = statics.slot_sizes[i]
            gap = statics.gaps_after[i]
            reclaim_room = max(0.0, gap - RECLAIM_RESERVE) if gap >= RECLAIM_MIN_GAP else 0.0
            available = slot + reclaim_room
            shorten_pcts.append(_pick_shorten_target(
                _required_shorten_pct(statics.desired_natural[i], available)
            ))

        # Phase C: while max drift exceeds cap, tighten the worst upstream
        # sentence (largest remaining overrun with shorten budget left).
        # Floating-point tolerance for comparisons against DRIFT_CAP.
        _CAP_EPSILON = 1e-6
        drift_cap_hits = 0
        flagged: dict[int, str] = {}
        MAX_REBALANCE_ITERS = N * len(SHORTEN_TARGETS) + N + 1
        out: list[SentencePlan] = []
        reset_points: list[int] = []
        for _ in range(MAX_REBALANCE_ITERS):
            out, reset_points, max_drift, peak_idx = statics.simulate(shorten_pcts)
            if max_drift <= DRIFT_CAP + _CAP_EPSILON:
                break
            # Find an upstream candidate with budget to tighten
            candidates = [
                i for i in range(peak_idx + 1)
                if _tighten(shorten_pcts[i]) is not None
            ]
            if not candidates:
                # Unrecoverable: flag the cap-hit sentence(s) and stop
                for i in range(N):
                    if out[i].drift_out > DRIFT_CAP + 1e-9 and i not in flagged:
                        flagged[i] = "drift_cap_hit"
                break
            # Pick the candidate with the largest overrun (post-shortening)
            def _overrun_for(i: int) -> float:
                desired = statics.desired_natural[i] * shorten_pcts[i]
                return max(0.0, desired - statics.slot_sizes[i])
            target_i = max(candidates, key=_overrun_for)
            next_pct = _tighten(shorten_pcts[target_i])
            if next_pct is None or next_pct >= shorten_pcts[target_i]:
                # Defensive: nothing to do
                for i in range(N):
                    if out[i].drift_out > DRIFT_CAP + 1e-9 and i not in flagged:
                        flagged[i] = "drift_cap_hit"
                break
            shorten_pcts[target_i] = next_pct
            drift_cap_hits += 1

        # Phase C post-pass: flag any sentence whose drift_out strictly
        # exceeds DRIFT_CAP, indicating drift could not be fully contained.
        final_out, reset_points, _final_max_drift, _peak = statics.simulate(shorten_pcts)
        for i in range(N):
            if final_out[i].drift_out > DRIFT_CAP + 1e-9 and i not in flagged:
                flagged[i] = "drift_cap_hit"
        for i, reason in flagged.items():
            final_out[i].needs_review = True
            final_out[i].reason = reason

        return DubPlan(
            sentences=final_out,
            playback_speed=playback_speed,
            underlay_db=underlay_db,
            total_drift_end=final_out[-1].drift_out if final_out else 0.0,
            drift_cap_hits=drift_cap_hits,
            reset_points=reset_points,
        )
