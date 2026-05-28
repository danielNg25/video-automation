"""TTS audio assembler: builds a full-length audio track from subtitle segments.

Assembly model (planner architecture):
    - Stage 0: Sentences are merged from consecutive SRT segments (LLM if
      available, heuristic fallback). The merger never spans a silent gap
      larger than MAX_MERGE_GAP_SECONDS so a single dub clip never erases a
      real pause.
    - Stage 1: Synthesize one clip per sentence at the provider's natural
      speed.
    - Stage 2: Build a DubPlan via the pure-function Planner. The planner
      decides per-sentence shortening targets, drift accumulation, gap reclaim,
      and reset points — globally, without I/O.
    - Stage 3: Batch re-synthesise sentences flagged by the planner. A single
      LLM call shortens all flagged sentences; clips that came out shorter are
      swapped in; others fall back to the Stage 1 clip and are flagged for
      review.
    - Stage 4: Apply atempo per the plan's effective_speed, anchor each clip
      at its plan-determined final_start.
    - Stage 5: Concatenate clips onto a silence track. Source-video audio
      mixing is handled exclusively by the processor (src/processor/ffmpeg.py)
      at the original_volume level derived from the user's underlay_db setting.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from src.tts.base import BaseTTSProvider, _clean_text
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Maximum silent gap (seconds) the sentence merger may span. Above this,
# even when the LLM groups two segments because the text reads as a
# continuous thought, we split — synthesising as one clip would erase the
# natural pause and shift downstream timestamps.
MAX_MERGE_GAP_SECONDS = 1.5

# Stage 3 LLM-shortening iteration cap. After the planner-assigned target,
# any sentence whose current clip still overruns `final_duration *
# effective_speed` is retried with a stricter shorten_pct (one notch down
# the SHORTEN_TARGETS ladder) until it fits or we hit this many total
# batched LLM calls.
SHORTENING_MAX_PASSES = 3

# Punctuation that signals end of a sentence (used by the heuristic merger).
_SENTENCE_END_CHARS = set('.!?。！？…)）"」』')


@dataclass
class SegmentSlot:
    """Timing slot for a TTS segment. Anchored at the source-segment start."""
    index: int
    clip_path: Path | None
    clip_duration: float
    window_start: float  # = first source segment's start
    window_end: float    # = last source segment's end


@dataclass
class SentenceGroup:
    """A group of consecutive subtitle segments forming one complete sentence."""
    segment_indices: list[int]
    text: str
    start: float
    end: float


async def _detect_sentence_boundaries_llm(
    segments: list[dict],
    llm_caller: Callable,
) -> list[tuple[list[int], str]]:
    """Ask LLM to group segment indices into complete sentences with proper punctuation.

    Args:
        segments: Non-empty subtitle segments with 'text' field.
        llm_caller: Async function(system, user, max_tokens) -> str.

    Returns:
        List of (group_indices, merged_text) tuples. merged_text has proper
        punctuation added by the LLM for natural TTS speech.
    """
    numbered = []
    for i, seg in enumerate(segments):
        text = _clean_text(seg.get("text", "")).replace("\n", " ")
        if text:
            numbered.append(f"{i + 1}. {text}")

    system = (
        "You are a subtitle analyst preparing text for text-to-speech. "
        "Group subtitle segments into complete sentences, then merge each group "
        "into a single natural sentence with proper punctuation (commas, periods, etc.) "
        "so it sounds natural when spoken aloud."
    )
    user = (
        f"Here are {len(numbered)} subtitle segments from a video.\n"
        "For each complete sentence, output one line in this format:\n"
        "[segment numbers] merged text with proper punctuation\n\n"
        "Example:\n"
        "[1,2,3] Nếu bạn ngẩng đầu lên, thấy có ai giơ tay chào, đừng vội sợ nha.\n"
        "[4] Nó chỉ muốn xin đồ ăn thôi.\n\n"
        "Rules:\n"
        "- Every segment number must appear in exactly one group\n"
        "- Add commas, periods, and other punctuation where natural for speech\n"
        "- Keep the original meaning, just combine and punctuate naturally\n"
        "- Return ONLY the formatted lines, nothing else\n\n"
        + "\n".join(numbered)
    )

    response = await llm_caller(system, user, 4096)

    # Parse response: [1,2,3] merged text
    results: list[tuple[list[int], str]] = []
    seen = set()
    for line in response.strip().split("\n"):
        line = line.strip()
        if not line:
            continue

        # Match [numbers] text pattern, or fall back to plain comma-separated numbers
        m = re.match(r"\[([^\]]+)\]\s*(.*)", line)
        if m:
            nums_str = m.group(1)
            merged_text = m.group(2).strip()
        else:
            nums_str = line
            merged_text = ""
        nums = re.findall(r"\d+", nums_str)
        if not nums:
            continue
        group = []
        for n in nums:
            idx = int(n) - 1  # convert to 0-based
            if 0 <= idx < len(segments) and idx not in seen:
                group.append(idx)
        if not group:
            continue
        # Mark seen only when we actually commit the group, so empty-text lines
        # don't strand segments (the missing-segments fallback below depends on
        # `seen` accurately reflecting what landed in `results`).
        for idx in group:
            seen.add(idx)
        results.append((sorted(group), merged_text))

    # Add any missing segments as individual groups
    for i in range(len(segments)):
        if i not in seen:
            text = _clean_text(segments[i].get("text", ""))
            results.append(([i], text))
            seen.add(i)

    # Sort by first segment index
    results.sort(key=lambda r: r[0][0])

    logger.info(f"LLM grouped {len(segments)} segments into {len(results)} sentences")
    return results


def _merge_into_sentences_heuristic(
    segments: list[dict], max_gap: float = 1.5
) -> list[list[int]]:
    """Group segments into sentences using punctuation and time gap heuristics.

    Returns list of groups, each group is a list of 0-based segment indices.
    """
    groups: list[list[int]] = []
    current_group: list[int] = []

    for i, seg in enumerate(segments):
        text = _clean_text(seg.get("text", ""))
        if not text:
            continue

        current_group.append(i)

        # Check for sentence boundary
        is_sentence_end = text[-1] in _SENTENCE_END_CHARS if text else False

        # Check for time gap to next segment
        has_gap = False
        if i + 1 < len(segments):
            gap = segments[i + 1]["start"] - seg["end"]
            has_gap = gap > max_gap

        is_last = i == len(segments) - 1

        if is_sentence_end or has_gap or is_last:
            if current_group:
                groups.append(current_group)
                current_group = []

    if current_group:
        groups.append(current_group)

    return groups


def _split_group_on_gaps(
    group_indices: list[int],
    segments: list[dict],
    max_gap: float,
) -> list[list[int]]:
    """Split one segment group wherever consecutive segments are separated
    by more than `max_gap` seconds of silence.

    Returns at least one sub-group; the input is returned unchanged when
    no internal gap exceeds the threshold. The LLM merger uses this guard
    so that text-level continuity (the LLM doesn't see timestamps) can't
    silently merge two segments that the source had a long pause between
    — synthesising as one clip would erase the pause.
    """
    if len(group_indices) <= 1:
        return [list(group_indices)]
    sub_groups: list[list[int]] = []
    current = [group_indices[0]]
    for prev_idx, next_idx in zip(group_indices, group_indices[1:]):
        gap = segments[next_idx]["start"] - segments[prev_idx]["end"]
        if gap > max_gap:
            sub_groups.append(current)
            current = [next_idx]
        else:
            current.append(next_idx)
    sub_groups.append(current)
    return sub_groups


async def _merge_into_sentences(
    segments: list[dict],
    llm_caller: Callable | None = None,
    max_gap: float = MAX_MERGE_GAP_SECONDS,
) -> list[SentenceGroup]:
    """Merge consecutive segments into sentence groups for TTS.

    Uses LLM detection if available, falls back to punctuation + gap heuristics.
    No group spans a gap larger than `max_gap` regardless of branch.
    """
    # Get groupings
    llm_results: list[tuple[list[int], str]] | None = None
    if llm_caller:
        try:
            llm_results = await _detect_sentence_boundaries_llm(segments, llm_caller)
        except Exception as e:
            logger.warning(f"LLM sentence detection failed ({e}), using heuristic fallback")

    if llm_results:
        # LLM provided grouping and punctuated text. Post-split any group
        # whose internal segments cross a gap > `max_gap` — the LLM is
        # text-only and will merge across long pauses based on reading
        # flow, which would erase the natural silence.
        sentence_groups: list[SentenceGroup] = []
        splits_made = 0
        for group_indices, llm_text in llm_results:
            sub_groups = _split_group_on_gaps(group_indices, segments, max_gap)

            if len(sub_groups) > 1:
                # The LLM's punctuated text covered the whole merged
                # sentence; reusing it on a single sub-group would be
                # wrong. All sub-groups fall back to raw segment text.
                splits_made += 1
                for sub in sub_groups:
                    texts = [_clean_text(segments[idx].get("text", "")) for idx in sub]
                    merged_text = " ".join(t for t in texts if t)
                    if not merged_text:
                        continue
                    sentence_groups.append(SentenceGroup(
                        segment_indices=sub,
                        text=merged_text,
                        start=segments[sub[0]]["start"],
                        end=segments[sub[-1]]["end"],
                    ))
                continue

            # No split — keep the LLM's punctuated text.
            if llm_text:
                merged_text = llm_text
            else:
                texts = [_clean_text(segments[idx].get("text", "")) for idx in group_indices]
                merged_text = " ".join(t for t in texts if t)

            if not merged_text:
                logger.warning(
                    f"Sentence group {group_indices} has no usable text after cleaning — "
                    f"originals: {[segments[i].get('text', '') for i in group_indices]}"
                )
                continue

            sentence_groups.append(SentenceGroup(
                segment_indices=group_indices,
                text=merged_text,
                start=segments[group_indices[0]]["start"],
                end=segments[group_indices[-1]]["end"],
            ))

        if splits_made:
            logger.info(
                f"Split {splits_made} LLM sentence groups at gaps > {max_gap}s "
                f"({len(llm_results)} LLM groups → {len(sentence_groups)} sentences)"
            )
    else:
        # Heuristic fallback — join with spaces (no LLM punctuation)
        groups = _merge_into_sentences_heuristic(segments, max_gap)
        sentence_groups = []
        for group_indices in groups:
            texts = [_clean_text(segments[idx].get("text", "")) for idx in group_indices]
            merged_text = " ".join(t for t in texts if t)
            if not merged_text:
                continue
            start = segments[group_indices[0]]["start"]
            end = segments[group_indices[-1]]["end"]
            sentence_groups.append(SentenceGroup(
                segment_indices=group_indices,
                text=merged_text,
                start=start,
                end=end,
            ))

    return sentence_groups


class TTSAssembler:
    """Assembles per-segment TTS audio into a full-length audio track."""

    def __init__(self, max_concurrent: int = 5, translator=None):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._translator = translator  # LLMTranslator or None

    async def _run_shortening_pass(
        self, *, targets, slots, provider, voice, kwargs, tmp,
        effective_speed, pass_idx,
    ):
        """One batched LLM-shortening call plus concurrent re-synthesis.

        For each `targets` SentencePlan, sends its currently-playing text
        (sp.target_text, falling back to sp.original_text) to the LLM at the
        sp.shorten_pct the caller picked for this pass. Accepts the new
        clip only when it is strictly shorter than the slot's current clip.
        Mutates per sp: target_text (only on accept), needs_review, reason;
        and slots[sp.index].clip_path / clip_duration on accept.
        """
        from src.tts.planner import SHORTEN_UNDERSHOOT_OK

        if not targets:
            return

        batch = []
        for sp in targets:
            slot = slots[sp.index]
            current_text = sp.target_text or sp.original_text
            batch.append({
                "text": current_text,
                "target_pct": int(sp.shorten_pct * 100),
                "current_duration": slot.clip_duration,
                "target_duration": sp.final_duration,
                "speed_ratio": (
                    slot.clip_duration / sp.final_duration
                    if sp.final_duration > 0 else 1.0
                ),
            })

        try:
            shortened_texts = await self._translator.shorten_texts_batch(batch)
        except Exception as e:
            logger.warning(
                f"Stage 3 pass {pass_idx}: batched shortening failed: {e}"
            )
            for sp in targets:
                sp.needs_review = True
                sp.reason = "reshorten_failed"
            return

        # Build the re-synth set: skip sentences where the LLM returned the
        # same text it received (no progress this pass; the iteration loop
        # may still try a stricter target on the next pass).
        resynth: list[tuple] = []
        for sp, new_text in zip(targets, shortened_texts):
            current_text = sp.target_text or sp.original_text
            if new_text == current_text:
                sp.needs_review = True
                sp.reason = "llm_no_shorter_text"
                continue
            resynth.append((sp, new_text))

        if not resynth:
            return

        async def _synth(text):
            async with self._semaphore:
                return await provider.synthesize(text, voice, **kwargs)

        results = await asyncio.gather(
            *[_synth(text) for _sp, text in resynth],
            return_exceptions=True,
        )

        for (sp, new_text), audio in zip(resynth, results):
            slot = slots[sp.index]
            if isinstance(audio, Exception) or audio is None or len(audio) == 0:
                # Synth failure — keep current clip + target_text.
                sp.needs_review = True
                sp.reason = "reshorten_failed"
                continue
            new_clip = tmp / f"reshort_p{pass_idx}_{sp.index:04d}.mp3"
            new_clip.write_bytes(audio)
            new_dur = _get_audio_duration(new_clip)
            if new_dur <= 0 or new_dur >= slot.clip_duration:
                # Not strictly shorter than what we already have. Keep
                # current slot state and target_text; flag for review.
                sp.needs_review = True
                sp.reason = "reshorten_not_shorter"
                continue
            # Accept the shorter clip and commit its text.
            sp.target_text = new_text
            slot.clip_path = new_clip
            slot.clip_duration = new_dur
            planned = sp.final_duration * effective_speed
            ratio = new_dur / planned if planned > 0 else 0.0
            if ratio > 1.0 + SHORTEN_UNDERSHOOT_OK:
                sp.needs_review = True
                sp.reason = "shorten_undershot"
            else:
                sp.needs_review = False
                sp.reason = None

    async def _apply_shortening(
        self, *, plan, sentence_groups, slots, provider, voice, kwargs,
        tmp, effective_speed,
    ):
        """Stage 3: iteratively shorten sentences whose clips overrun their
        planner-allocated span at effective_speed.

        Pass 1 targets every planner-flagged sentence (shorten_pct < 1.0)
        with the planner's chosen target. Passes 2..SHORTENING_MAX_PASSES
        re-derive targets from sentences whose CURRENT clip (potentially
        already shortened in an earlier pass) still satisfies
        ``clip_duration / effective_speed > sp.final_duration``. Each retry
        tightens sp.shorten_pct one notch via planner._tighten; sentences
        at SHORTEN_FLOOR are flagged for review and skipped.
        """
        from src.tts.planner import _tighten

        if not self._translator:
            # No LLM — skip shortening; planner-flagged sentences just get
            # the review flag.
            for sp in plan.sentences:
                if sp.shorten_pct < 1.0:
                    sp.needs_review = True
                    sp.reason = "shorten_no_llm"
            return

        # Pass 1: planner-flagged sentences only.
        initial_targets = [sp for sp in plan.sentences if sp.shorten_pct < 1.0]
        if not initial_targets:
            return

        await self._run_shortening_pass(
            targets=initial_targets, slots=slots, provider=provider,
            voice=voice, kwargs=kwargs, tmp=tmp,
            effective_speed=effective_speed, pass_idx=1,
        )

        # Passes 2..N: tighten unrecovered slots and retry.
        for pass_idx in range(2, SHORTENING_MAX_PASSES + 1):
            retry_targets: list = []
            for sp in plan.sentences:
                slot = slots[sp.index]
                if slot.clip_path is None or slot.clip_duration <= 0:
                    continue
                if sp.final_duration <= 0:
                    continue
                if slot.clip_duration / effective_speed <= sp.final_duration:
                    continue  # fits
                next_pct = _tighten(sp.shorten_pct)
                if next_pct is None or next_pct >= sp.shorten_pct:
                    sp.needs_review = True
                    sp.reason = sp.reason or "shorten_floor_reached"
                    continue
                sp.shorten_pct = next_pct
                retry_targets.append(sp)

            if not retry_targets:
                logger.info(
                    f"Stage 3 shortening converged after pass {pass_idx - 1}"
                )
                break

            logger.info(
                f"Stage 3 shortening pass {pass_idx}/{SHORTENING_MAX_PASSES}: "
                f"{len(retry_targets)} slot(s) still overrun"
            )
            await self._run_shortening_pass(
                targets=retry_targets, slots=slots, provider=provider,
                voice=voice, kwargs=kwargs, tmp=tmp,
                effective_speed=effective_speed, pass_idx=pass_idx,
            )

    async def generate_full_track(
        self,
        provider: BaseTTSProvider,
        segments: list[dict],
        voice_profile: dict,
        video_duration: float,
        output_path: Path,
        on_progress: callable | None = None,
        merge_sentences: bool = True,
        llm_caller: Callable | None = None,
        srt_path: Path | None = None,  # kept for back-compat; ignored
        playback_speed: float | None = None,
        video_id: str | None = None,
        language: str | None = None,
        provider_name: str | None = None,
        underlay_db: float | None = None,
    ) -> tuple[Path, list[dict]]:
        """Generate a full-length TTS audio track from subtitle segments.

        Returns ``(output_path, sentence_plan)`` where ``sentence_plan`` is a
        list of per-sentence dicts with the following keys:

            index            – sentence index (0-based)
            text             – final (possibly shortened) text spoken
            original_text    – pre-shortening text from Stage 1
            start            – plan final_start (seconds)
            end              – plan final_start + final_duration (seconds)
            window_start     – original source subtitle start (seconds)
            window_end       – original source subtitle end (seconds)
            synth_duration   – natural duration of Stage 1 clip (seconds)
            fitted_duration  – actual duration placed in the track (seconds)
            speed_ratio      – effective playback speed applied
            shorten_pct      – fraction the planner asked for (1.0 = no shorten)
            drift_in         – accumulated drift at sentence start (seconds)
            drift_out        – accumulated drift after sentence (seconds)
            push_amount      – seconds of overrun pushed to downstream (seconds)
            reclaimed_silence – silence consumed by this sentence's clip (seconds)
            was_shortened    – True if the LLM provided a shorter version
            needs_review     – True if the clip failed some quality check
            reason           – short reason code if needs_review else None

        Pipeline stages:
        0. Merge segments into sentence groups (LLM or heuristic). The LLM
           merger never spans gaps > MAX_MERGE_GAP_SECONDS.
        1. Synthesize one clip per sentence at the provider's natural speed.
        2. Build a DubPlan via Planner.build_plan (pure, no I/O). Decides
           per-sentence shortening targets, drift, gap reclaim, reset points.
        3. Batch re-synthesise shortened sentences via one LLM call. Clips
           that are not shorter fall back to the Stage 1 clip.
        4. Apply atempo per effective_speed, place clips at plan final_start.
        5. Concatenate clips onto a silence track via ffmpeg.

        ``srt_path`` is accepted for back-compat (the assembler no longer
        rewrites the input SRT). Source-video audio mixing is the processor's
        responsibility — see src/processor/ffmpeg.py.
        """
        # Defensive coercion: any caller that passes a stringified numeric
        # (e.g. from a config path the runner didn't catch) gets handled
        # here so the ffmpeg filter-graph builder can rely on numeric types.
        if isinstance(playback_speed, str):
            try:
                playback_speed = float(playback_speed)
            except ValueError:
                playback_speed = None

        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice = voice_profile["voice"]
        kwargs = {}
        if "speed" in voice_profile:
            kwargs["speed"] = voice_profile["speed"]
        if "pitch" in voice_profile:
            kwargs["pitch"] = voice_profile["pitch"]

        sentence_plan: list[dict] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)

            # === Stage 0: Merge segments into sentence groups ===
            if merge_sentences:
                sentence_groups = await _merge_into_sentences(
                    segments, llm_caller=llm_caller
                )
                logger.info(
                    f"Merged {len(segments)} segments into {len(sentence_groups)} sentence groups"
                )
            else:
                sentence_groups = []
                for i, seg in enumerate(segments):
                    text = _clean_text(seg.get("text", ""))
                    if not text:
                        continue
                    sentence_groups.append(SentenceGroup(
                        segment_indices=[i],
                        text=text,
                        start=seg["start"],
                        end=seg["end"],
                    ))

            # Per-group debug log so you can see which source segments got
            # merged into which sentence — surfaces aggressive LLM merging
            # immediately, without waiting for full synth.
            for sg in sentence_groups:
                logger.info(
                    f"  group idx={sg.segment_indices} "
                    f"[{sg.start:.2f}s, {sg.end:.2f}s)  text={sg.text[:80]!r}"
                )

            total = len(sentence_groups)

            # Closure used by Stage 1 (initial synth) and Stage 1.5 (re-synth
            # after LLM shortening). Lives inside the temp-dir block so all
            # generated clip files are cleaned up together.
            async def synth_one(i: int, text: str, suffix: str = "") -> Path | None:
                if not text:
                    return None
                async with self._semaphore:
                    audio_bytes = await provider.synthesize(text, voice, **kwargs)
                clip_path = tmp / f"seg_{i:04d}{suffix}.mp3"
                clip_path.write_bytes(audio_bytes)
                return clip_path

            # === Stage 1: Synthesize one clip per sentence ===
            tasks = [synth_one(i, sg.text) for i, sg in enumerate(sentence_groups)]
            raw_clips = await asyncio.gather(*tasks, return_exceptions=True)

            slots: list[SegmentSlot] = []
            for i, (sg, clip_result) in enumerate(zip(sentence_groups, raw_clips)):
                clip_path = None
                clip_duration = 0.0
                if isinstance(clip_result, Exception):
                    logger.warning(
                        f"Sentence {i} synthesis failed: {clip_result!r} — "
                        f"text={sg.text[:60]!r}"
                    )
                elif clip_result is None:
                    if sg.text:
                        logger.warning(
                            f"Sentence {i} has text but no audio clip: {sg.text[:60]!r}"
                        )
                else:
                    clip_path = clip_result
                    clip_duration = _get_audio_duration(clip_result)
                    if clip_duration <= 0:
                        logger.warning(
                            f"Sentence {i} synthesized clip has zero duration: {clip_result}"
                        )

                slots.append(SegmentSlot(
                    index=i,
                    clip_path=clip_path,
                    clip_duration=clip_duration,
                    window_start=sg.start,
                    window_end=sg.end,
                ))

            # === Stage 1.5: Persist natural-speed clips for dub-sync ===
            # Copy each slot's natural-speed clip into the per-video cache so
            # a future Sync-Dub run can reuse the unchanged segments without
            # re-synthesising. Best-effort: cache write failures are logged
            # and do not block the main dub.
            if video_id and language:
                from src.tts.segment_cache import save_segment_clip

                tts_cache_dir = Path("data/tts")
                for slot in slots:
                    if slot.clip_path is None:
                        continue
                    try:
                        save_segment_clip(
                            tts_cache_dir,
                            video_id,
                            language,
                            slot.index,
                            slot.clip_path,
                        )
                    except OSError as e:
                        logger.warning(f"Failed to cache segment {slot.index}: {e}")

            # === Stage 2: Build DubPlan (pure function, no I/O) ===
            from src.tts.planner import (
                PLAYBACK_SPEED_DEFAULT,
                Planner,
            )

            effective_speed = (
                playback_speed if (playback_speed and playback_speed > 0)
                else PLAYBACK_SPEED_DEFAULT
            )

            sentence_inputs = [
                {
                    "index": sg.segment_indices[0] if sg.segment_indices else i,
                    "segment_indices": sg.segment_indices,
                    "text": sg.text,
                    "start": sg.start,
                    "end": sg.end,
                }
                for i, sg in enumerate(sentence_groups)
            ]
            natural_durations = [s.clip_duration for s in slots]

            dub_plan = Planner.build_plan(
                sentences=sentence_inputs,
                natural_synth_durations=natural_durations,
                playback_speed=effective_speed,
                video_duration=video_duration,
            )

            logger.info(
                f"Planner: speed={effective_speed}x "
                f"sentences={len(dub_plan.sentences)} "
                f"shortened={sum(1 for s in dub_plan.sentences if s.shorten_pct < 1.0)} "
                f"drift_end={dub_plan.total_drift_end:.2f}s "
                f"cap_hits={dub_plan.drift_cap_hits}"
            )

            # === Stage 3: Batch re-synthesise shortened sentences ===
            await self._apply_shortening(
                plan=dub_plan, sentence_groups=sentence_groups, slots=slots,
                provider=provider, voice=voice, kwargs=kwargs, tmp=tmp,
                effective_speed=effective_speed,
            )

            if on_progress:
                on_progress(total, total, "Shortening complete")

            # === Stage 4: Apply atempo per plan, prepare clip list ===
            logger.info(f"TTS dub playback_speed = {effective_speed}×")
            fitted_clips: list[tuple[float, Path | None]] = []
            for sp in dub_plan.sentences:
                slot = slots[sp.index]
                played_path: Path | None = None
                played_duration = 0.0
                if slot.clip_path is not None and slot.clip_duration > 0:
                    if abs(effective_speed - 1.0) < 0.01:
                        played_path = slot.clip_path
                        played_duration = slot.clip_duration
                    else:
                        fitted_path = tmp / f"fitted_{sp.index:04d}.mp3"
                        try:
                            _speed_up_audio(slot.clip_path, fitted_path, effective_speed)
                            ad = _get_audio_duration(fitted_path)
                            if ad > 0:
                                played_path = fitted_path
                                played_duration = ad
                            else:
                                logger.warning(
                                    f"Sentence {sp.index}: atempo empty output, "
                                    f"falling back to natural speed"
                                )
                                sp.needs_review = True
                                sp.reason = sp.reason or "atempo_off_target"
                                played_path = slot.clip_path
                                played_duration = slot.clip_duration
                        except Exception as e:
                            logger.warning(
                                f"Sentence {sp.index}: atempo failed ({e}), "
                                f"falling back to natural speed"
                            )
                            sp.needs_review = True
                            sp.reason = sp.reason or "atempo_failed"
                            played_path = slot.clip_path
                            played_duration = slot.clip_duration
                    fitted_clips.append((sp.final_start, played_path))
                else:
                    # No clip — flag for review; the source-language audio
                    # will still be audible via the processor's original_volume
                    # mix, at the same level as the rest of the video.
                    sp.needs_review = True
                    sp.reason = sp.reason or "synth_empty"
                sentence_plan.append({
                    "index": sp.index,
                    "segment_indices": list(sentence_groups[sp.index].segment_indices),
                    "text": sp.target_text,
                    "target_text": sp.target_text,
                    "original_text": sp.original_text,
                    "start": round(sp.final_start, 3),
                    "end": round(sp.final_start + sp.final_duration, 3),
                    "final_start": round(sp.final_start, 3),
                    "final_duration": round(sp.final_duration, 3),
                    "window_start": round(sp.original_start, 3),
                    "window_end": round(sp.original_end, 3),
                    "synth_duration": round(slot.clip_duration, 3),
                    "fitted_duration": round(played_duration, 3),
                    "speed_ratio": round(effective_speed, 3),
                    "shorten_pct": round(sp.shorten_pct, 3),
                    "drift_in": round(sp.drift_in, 3),
                    "drift_out": round(sp.drift_out, 3),
                    "push_amount": round(sp.push_amount, 3),
                    "reclaimed_silence": round(sp.reclaimed_silence, 3),
                    "was_shortened": sp.shorten_pct < 1.0,
                    "needs_review": sp.needs_review,
                    "reason": sp.reason,
                })

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # === Stage 5: Concatenate clips onto a silence track ===
            # Source-video audio mixing happens in the processor stage, not here.
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

            # === Stage 6: Emit per-segment dubsync.srt ===
            # Derive the canonical (video_id, language) used by all downstream
            # artefacts. Prefer the caller-supplied values; fall back to the
            # historical derivation from output_path / voice_profile so
            # back-compat is preserved when callers don't pass them.
            if not language:
                language = voice_profile.get("language") or "vi"
            if not video_id:
                stem = output_path.stem
                video_id = stem.split("_")[0] if "_" in stem else stem
            try:
                from src.tts.dubsync_srt import write_dubsync_srt
                dubsync_path = Path("data/srt") / f"{video_id}_{language}.dubsync.srt"
                dubsync_path.parent.mkdir(parents=True, exist_ok=True)
                write_dubsync_srt(segments, sentence_plan, dubsync_path)
                logger.info(f"Wrote dubsync SRT: {dubsync_path}")
            except Exception as e:
                logger.warning(f"Could not write dubsync SRT: {e}")

            # === Stage 7: Persist dub metadata for future Sync-Dub ===
            # Captures the parameters of this run + the per-segment texts so
            # Sync-Dub can (a) detect which segments changed by diffing the
            # new SRT against the recorded segment_texts, and (b) replay the
            # same provider/voice/playback_speed for the cells it does need
            # to re-synthesise.
            try:
                from src.tts.dub_meta import DubMeta, save_dub_meta

                meta = DubMeta(
                    video_id=video_id,
                    language=language,
                    provider=provider_name or "",
                    voice_id=voice or "",
                    playback_speed=effective_speed,
                    underlay_db=underlay_db if underlay_db is not None else 0.0,
                    segment_texts=[sg.text for sg in sentence_groups],
                )
                save_dub_meta(Path("data/tts"), meta)
            except Exception as e:
                logger.warning(
                    f"Failed to write dub_meta for {video_id}/{language}: {e}"
                )

        overrun_count = sum(1 for s in sentence_plan if s.get("overrun_seconds", 0) > 0)
        logger.info(
            f"Generated TTS track: {output_path} — {len(sentence_plan)} sentences, "
            f"{overrun_count} overrun their source span"
        )
        return output_path, sentence_plan

    async def run_partial(
        self,
        *,
        provider: BaseTTSProvider,
        video_id: str,
        language: str,
        new_texts: list[str],
        clip_overrides: dict[int, Path],
        dirty_indices: list[int],
        voice_profile: dict,
        provider_name: str,
        playback_speed: float,
        underlay_db: float,
        video_path: Path,
        output_path: Path,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> Path:
        """Re-assemble the dub WAV using cached clips for non-dirty segments
        and freshly-synthesised clips for `dirty_indices`. Returns the path
        to the rewritten dub WAV.

        Sentence groups are built one-per-`new_texts` entry. Timings are
        sourced from the most recent SRT (dubsync if present, legacy
        otherwise), so partial regen never re-runs the LLM sentence
        merger and never re-derives groupings — preserving 1:1 alignment
        with the persisted `dub_meta.segment_texts`.

        Stages mirrored from `generate_full_track`:
          1.   Synth dirty segments (use cache otherwise).
          1.5. Re-write cache for newly synthesised clips.
          2.   Build DubPlan (planner, pure function).
          3.   LLM batch shortening for sentences the planner flagged.
          4.   atempo per effective_speed.
          5.   Concat + silence base mix.
          6.   Write `dubsync.srt`.
          7.   Update `dub_meta`.
        """
        from src.api.routers.transcribe import _resolve_srt_path
        from src.processor.subtitle import parse_srt
        from src.tts.dub_meta import DubMeta, save_dub_meta
        from src.tts.dubsync_srt import write_dubsync_srt
        from src.tts.planner import PLAYBACK_SPEED_DEFAULT, Planner
        from src.tts.segment_cache import save_segment_clip
        from src.utils.metadata import extract_metadata_from_file

        if isinstance(playback_speed, str):
            try:
                playback_speed = float(playback_speed)
            except ValueError:
                playback_speed = None

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Load timings from the SRT. The editor saves edits into dubsync.srt
        # when it exists, so this is the source of truth for current
        # per-segment start/end after the user's most recent edits.
        srt_path, _ = _resolve_srt_path(video_id, language)
        if not srt_path.exists():
            raise FileNotFoundError(
                f"Sync-Dub: SRT not found for {video_id}/{language}: {srt_path}"
            )
        srt_segments = parse_srt(srt_path)
        if len(srt_segments) != len(new_texts):
            raise ValueError(
                f"Sync-Dub: SRT segment count ({len(srt_segments)}) does "
                f"not match new_texts count ({len(new_texts)})"
            )

        # Build sentence_groups one-per-segment (no merging during partial
        # regen — `dub_meta.segment_texts` indexes the existing cache).
        sentence_groups: list[SentenceGroup] = []
        for i, (seg, text) in enumerate(zip(srt_segments, new_texts)):
            sentence_groups.append(SentenceGroup(
                segment_indices=[i],
                text=_clean_text(text),
                start=seg["start"],
                end=seg["end"],
            ))

        # Canonical video duration. Falls back to the last segment's end.
        file_meta = (
            extract_metadata_from_file(video_path) if video_path.exists() else {}
        )
        video_duration = float(file_meta.get("duration", 0.0))
        if video_duration <= 0 and srt_segments:
            video_duration = float(srt_segments[-1]["end"])
        if video_duration <= 0:
            raise ValueError(
                f"Sync-Dub: could not determine duration for {video_path}"
            )

        voice = voice_profile["voice"]
        kwargs = {}
        if "speed" in voice_profile:
            kwargs["speed"] = voice_profile["speed"]
        if "pitch" in voice_profile:
            kwargs["pitch"] = voice_profile["pitch"]

        sentence_plan: list[dict] = []
        dirty_set = set(dirty_indices)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            total = len(sentence_groups)

            async def synth_one(i: int, text: str) -> Path | None:
                if not text:
                    return None
                async with self._semaphore:
                    audio_bytes = await provider.synthesize(text, voice, **kwargs)
                clip_path = tmp / f"seg_{i:04d}.mp3"
                clip_path.write_bytes(audio_bytes)
                return clip_path

            # === Stage 1: Synthesise dirty segments / reuse cache ===
            tasks: list = []
            task_indices: list[int] = []
            for i, sg in enumerate(sentence_groups):
                if i in dirty_set:
                    tasks.append(synth_one(i, sg.text))
                    task_indices.append(i)
                else:
                    tasks.append(None)

            if tasks:
                results = await asyncio.gather(
                    *[t for t in tasks if t is not None],
                    return_exceptions=True,
                )
            else:
                results = []
            result_map: dict[int, Path | Exception | None] = {}
            for idx, res in zip(task_indices, results):
                result_map[idx] = res

            slots: list[SegmentSlot] = []
            for i, sg in enumerate(sentence_groups):
                clip_path: Path | None = None
                clip_duration = 0.0
                if i in dirty_set:
                    res = result_map.get(i)
                    if isinstance(res, Exception):
                        logger.warning(
                            f"Sync-Dub: sentence {i} synth failed: {res!r} — "
                            f"text={sg.text[:60]!r}"
                        )
                    elif res is None:
                        if sg.text:
                            logger.warning(
                                f"Sync-Dub: sentence {i} produced no clip: "
                                f"{sg.text[:60]!r}"
                            )
                    else:
                        clip_path = res
                        clip_duration = _get_audio_duration(res)
                else:
                    cached = clip_overrides.get(i)
                    if cached is not None and cached.exists():
                        clip_path = cached
                        clip_duration = _get_audio_duration(cached)
                    else:
                        logger.warning(
                            f"Sync-Dub: no cached clip for non-dirty index {i}"
                        )

                slots.append(SegmentSlot(
                    index=i,
                    clip_path=clip_path,
                    clip_duration=clip_duration,
                    window_start=sg.start,
                    window_end=sg.end,
                ))

            if on_progress:
                on_progress(int(total * 0.4), total, "Synthesis complete")

            # === Stage 1.5: Re-cache newly synthesised clips ===
            tts_cache_dir = Path("data/tts")
            for slot in slots:
                if slot.index not in dirty_set:
                    continue
                if slot.clip_path is None:
                    continue
                try:
                    save_segment_clip(
                        tts_cache_dir, video_id, language,
                        slot.index, slot.clip_path,
                    )
                except OSError as e:
                    logger.warning(
                        f"Sync-Dub: failed to cache segment {slot.index}: {e}"
                    )

            # === Stage 2: Build DubPlan ===
            effective_speed = (
                playback_speed if (playback_speed and playback_speed > 0)
                else PLAYBACK_SPEED_DEFAULT
            )

            sentence_inputs = [
                {
                    "index": sg.segment_indices[0] if sg.segment_indices else i,
                    "segment_indices": sg.segment_indices,
                    "text": sg.text,
                    "start": sg.start,
                    "end": sg.end,
                }
                for i, sg in enumerate(sentence_groups)
            ]
            natural_durations = [s.clip_duration for s in slots]
            dub_plan = Planner.build_plan(
                sentences=sentence_inputs,
                natural_synth_durations=natural_durations,
                playback_speed=effective_speed,
                video_duration=video_duration,
            )
            logger.info(
                f"Sync-Dub planner: speed={effective_speed}x "
                f"sentences={len(dub_plan.sentences)} "
                f"shortened={sum(1 for s in dub_plan.sentences if s.shorten_pct < 1.0)} "
                f"drift_end={dub_plan.total_drift_end:.2f}s "
                f"cap_hits={dub_plan.drift_cap_hits}"
            )

            # === Stage 3: Batch re-synthesise shortened sentences ===
            await self._apply_shortening(
                plan=dub_plan, sentence_groups=sentence_groups, slots=slots,
                provider=provider, voice=voice, kwargs=kwargs, tmp=tmp,
                effective_speed=effective_speed,
            )

            if on_progress:
                on_progress(int(total * 0.7), total, "Shortening complete")

            # === Stage 4: Apply atempo per plan, build clip list ===
            fitted_clips: list[tuple[float, Path | None]] = []
            for sp in dub_plan.sentences:
                slot = slots[sp.index]
                played_path: Path | None = None
                played_duration = 0.0
                if slot.clip_path is not None and slot.clip_duration > 0:
                    if abs(effective_speed - 1.0) < 0.01:
                        played_path = slot.clip_path
                        played_duration = slot.clip_duration
                    else:
                        fitted_path = tmp / f"fitted_{sp.index:04d}.mp3"
                        try:
                            _speed_up_audio(
                                slot.clip_path, fitted_path, effective_speed
                            )
                            ad = _get_audio_duration(fitted_path)
                            if ad > 0:
                                played_path = fitted_path
                                played_duration = ad
                            else:
                                logger.warning(
                                    f"Sync-Dub: sentence {sp.index} atempo "
                                    f"empty output, falling back to natural speed"
                                )
                                sp.needs_review = True
                                sp.reason = sp.reason or "atempo_off_target"
                                played_path = slot.clip_path
                                played_duration = slot.clip_duration
                        except Exception as e:
                            logger.warning(
                                f"Sync-Dub: sentence {sp.index} atempo failed "
                                f"({e}), falling back to natural speed"
                            )
                            sp.needs_review = True
                            sp.reason = sp.reason or "atempo_failed"
                            played_path = slot.clip_path
                            played_duration = slot.clip_duration
                    fitted_clips.append((sp.final_start, played_path))
                else:
                    sp.needs_review = True
                    sp.reason = sp.reason or "synth_empty"
                sentence_plan.append({
                    "index": sp.index,
                    "segment_indices": list(sentence_groups[sp.index].segment_indices),
                    "text": sp.target_text,
                    "target_text": sp.target_text,
                    "original_text": sp.original_text,
                    "start": round(sp.final_start, 3),
                    "end": round(sp.final_start + sp.final_duration, 3),
                    "final_start": round(sp.final_start, 3),
                    "final_duration": round(sp.final_duration, 3),
                    "window_start": round(sp.original_start, 3),
                    "window_end": round(sp.original_end, 3),
                    "synth_duration": round(slot.clip_duration, 3),
                    "fitted_duration": round(played_duration, 3),
                    "speed_ratio": round(effective_speed, 3),
                    "shorten_pct": round(sp.shorten_pct, 3),
                    "drift_in": round(sp.drift_in, 3),
                    "drift_out": round(sp.drift_out, 3),
                    "push_amount": round(sp.push_amount, 3),
                    "reclaimed_silence": round(sp.reclaimed_silence, 3),
                    "was_shortened": sp.shorten_pct < 1.0,
                    "needs_review": sp.needs_review,
                    "reason": sp.reason,
                })

            if on_progress:
                on_progress(int(total * 0.9), total, "Concatenating audio track...")

            # === Stage 5: Concatenate ===
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

            # === Stage 6: Emit dubsync.srt ===
            try:
                dubsync_path = (
                    Path("data/srt") / f"{video_id}_{language}.dubsync.srt"
                )
                dubsync_path.parent.mkdir(parents=True, exist_ok=True)
                write_dubsync_srt(srt_segments, sentence_plan, dubsync_path)
                logger.info(f"Sync-Dub: wrote dubsync SRT: {dubsync_path}")
            except Exception as e:
                logger.warning(f"Sync-Dub: could not write dubsync SRT: {e}")

            # === Stage 7: Update dub_meta with the new segment_texts ===
            try:
                meta = DubMeta(
                    video_id=video_id,
                    language=language,
                    provider=provider_name or "",
                    voice_id=voice or "",
                    playback_speed=effective_speed,
                    underlay_db=underlay_db if underlay_db is not None else 0.0,
                    segment_texts=[sg.text for sg in sentence_groups],
                )
                save_dub_meta(Path("data/tts"), meta)
            except Exception as e:
                logger.warning(
                    f"Sync-Dub: failed to write dub_meta "
                    f"for {video_id}/{language}: {e}"
                )

        if on_progress:
            on_progress(total, total, "Sync-Dub complete")
        logger.info(
            f"Sync-Dub: regenerated {output_path} — {len(sentence_plan)} sentences, "
            f"{len(dirty_indices)} dirty"
        )
        return output_path


def _get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(audio_path),
            ],
            capture_output=True, text=True, check=True, timeout=10,
        )
        data = json.loads(result.stdout)
        return float(data.get("format", {}).get("duration", 0))
    except (subprocess.SubprocessError, json.JSONDecodeError, ValueError):
        return 0.0


def _build_atempo_filter(speed_ratio: float) -> str:
    """Build ffmpeg atempo filter chain for the given speed ratio.

    ffmpeg's atempo accepts 0.5–2.0 per filter; we chain to reach higher
    ratios. A ratio of exactly 1.0 returns a no-op chain.
    """
    if speed_ratio <= 0:
        return "atempo=1.0"
    filters: list[str] = []
    remaining = speed_ratio
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    if abs(remaining - 1.0) > 1e-4:
        filters.append(f"atempo={remaining:.4f}")
    return ",".join(filters) if filters else "atempo=1.0"


def _speed_up_audio(input_path: Path, output_path: Path, speed_ratio: float) -> None:
    """Speed-adjust audio with ffmpeg atempo. Emits an MP3 at output_path."""
    atempo = _build_atempo_filter(speed_ratio)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", atempo,
        "-c:a", "libmp3lame",
        "-q:a", "4",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"atempo failed: {result.stderr[-300:]}")


def _concatenate_with_silence(
    clips: list[tuple[float, Path | None]],
    total_duration: float,
    output_path: Path,
) -> None:
    """Concatenate audio clips with silence padding to match video duration.

    Produces a WAV containing only the dub clips placed at their final_start
    positions, on a base of silence. Source-video audio mixing is the
    processor's responsibility — see src/processor/ffmpeg.py.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        silence_path = tmp / "silence.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi",
             "-i", f"anullsrc=r=24000:cl=mono:d={total_duration}",
             "-c:a", "pcm_s16le", str(silence_path)],
            capture_output=True, text=True, check=True, timeout=60,
        )

        valid_clips = [(t, p) for t, p in clips if p is not None and p.exists()]
        if not valid_clips:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(silence_path), str(output_path)],
                capture_output=True, text=True, check=True, timeout=60,
            )
            return

        inputs = ["-i", str(silence_path)]
        filter_parts: list[str] = []
        for i, (start_time, clip_path) in enumerate(valid_clips):
            inputs.extend(["-i", str(clip_path)])
            input_idx = 1 + i
            delay_ms = int(start_time * 1000)
            filter_parts.append(f"[{input_idx}]adelay={delay_ms}|{delay_ms}[d{i}]")

        mix_inputs = "[0]" + "".join(f"[d{i}]" for i in range(len(valid_clips)))
        n_total = 1 + len(valid_clips)
        filter_parts.append(
            f"{mix_inputs}amix=inputs={n_total}:duration=first:"
            f"dropout_transition=0,volume={n_total}[mixed]"
        )
        filter_parts.append("[mixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]")

        filter_complex = ";".join(filter_parts)
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "pcm_s16le", "-ar", "24000",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Audio concatenation failed: {result.stderr[-500:]}")
