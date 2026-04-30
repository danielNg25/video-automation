"""TTS audio assembler: builds a full-length audio track from subtitle segments."""

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

# Default fixed dub playback speed. Every sentence plays at exactly this
# speed (uniform pacing). If natural synth would require a higher speed to
# fit the slot, the LLM iterative shortening pulls text down until natural
# fits at this rate. Callers override per-request via `playback_speed`.
DEFAULT_DUB_PLAYBACK_SPEED = 1.5
# How many LLM-shortening passes we'll attempt before giving up and flagging
# the sentence as needing human review.
SHORTENING_MAX_PASSES = 3
# Warn (not cap) if a clip even approaches this — still useful as a logging
# signal for genuinely difficult sentences.
MAX_SAFE_SPEED_RATIO = 2.5
# Borrow up to this fraction of neighbor's unused time
GAP_BORROW_FRACTION = 0.80
# Punctuation that signals end of a sentence
_SENTENCE_END_CHARS = set('.!?。！？…)）"」』')


@dataclass
class SegmentSlot:
    """Timing slot for a TTS segment after gap redistribution."""
    index: int
    clip_path: Path | None
    clip_duration: float
    # Original window: next_start - current_start
    window_start: float
    window_end: float
    # Anchor: midpoint of window where the dub is centered
    anchor: float
    # Effective placement after redistribution
    effective_start: float
    effective_end: float


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


async def _merge_into_sentences(
    segments: list[dict],
    llm_caller: Callable | None = None,
    max_gap: float = 1.5,
) -> list[SentenceGroup]:
    """Merge consecutive segments into sentence groups for TTS.

    Uses LLM detection if available, falls back to punctuation + gap heuristics.
    """
    # Get groupings
    llm_results: list[tuple[list[int], str]] | None = None
    if llm_caller:
        try:
            llm_results = await _detect_sentence_boundaries_llm(segments, llm_caller)
        except Exception as e:
            logger.warning(f"LLM sentence detection failed ({e}), using heuristic fallback")

    if llm_results:
        # LLM provided both grouping and punctuated text
        sentence_groups: list[SentenceGroup] = []
        for group_indices, llm_text in llm_results:
            # Use LLM-punctuated text if available, otherwise join raw texts
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

            start = segments[group_indices[0]]["start"]
            end = segments[group_indices[-1]]["end"]
            sentence_groups.append(SentenceGroup(
                segment_indices=group_indices,
                text=merged_text,
                start=start,
                end=end,
            ))
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
        srt_path: Path | None = None,
        playback_speed: float | None = None,
    ) -> tuple[Path, list[dict]]:
        """Generate a full-length TTS audio track from subtitle segments.

        Pipeline:
        0. Merge segments into sentence groups (LLM or heuristic)
        1. Synthesize each sentence concurrently
        2. Anchor each dub at midpoint of its window, redistribute unused time
        3. LLM-shorten text iteratively for sentences whose natural synth
           would require a higher speed than `playback_speed` (up to
           SHORTENING_MAX_PASSES attempts with progressively stricter
           targets); flag sentences still over the cap as `needs_review`.
        4. Speed-adjust with atempo: every sentence plays at exactly
           `playback_speed` (fixed/uniform). If natural would require a
           higher speed to fit, hard-cap at `playback_speed` (silent tail).
        5. Concatenate with silence padding.

        Args:
            playback_speed: Fixed dub playback speed (atempo target). Defaults
                to DEFAULT_DUB_PLAYBACK_SPEED (1.5×) when None. The same speed
                is applied to every sentence — uniform pacing.

        Returns:
            (output_path, sentence_plan) — sentence_plan is a list of dicts
            with keys: index, text, window_start, window_end, synth_duration,
            speed_ratio, requested_ratio, needs_review, reason.
        """
        effective_speed = (
            playback_speed if playback_speed and playback_speed > 0
            else DEFAULT_DUB_PLAYBACK_SPEED
        )
        logger.info(f"TTS dub playback_speed = {effective_speed}×")
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
                synth_items = [
                    (sg.text, sg.start, sg.end, sg.segment_indices)
                    for sg in sentence_groups
                ]
                logger.info(
                    f"Merged {len(segments)} segments into {len(synth_items)} sentence groups"
                )
            else:
                synth_items = []
                for i, seg in enumerate(segments):
                    text = _clean_text(seg.get("text", ""))
                    synth_items.append((text, seg["start"], seg["end"], [i]))

            # Tile windows: each item's window_end = next item's start
            for i in range(len(synth_items) - 1):
                text, start, _, idxs = synth_items[i]
                synth_items[i] = (text, start, synth_items[i + 1][1], idxs)
            if synth_items:
                text, start, _, idxs = synth_items[-1]
                synth_items[-1] = (text, start, video_duration, idxs)

            total = len(synth_items)

            # === Stage 1: Synthesize all items concurrently ===
            async def synth_one(i: int, text: str) -> Path | None:
                if not text:
                    return None
                async with self._semaphore:
                    audio_bytes = await provider.synthesize(text, voice, **kwargs)
                clip_path = tmp / f"seg_{i:04d}.mp3"
                clip_path.write_bytes(audio_bytes)
                return clip_path

            tasks = [synth_one(i, item[0]) for i, item in enumerate(synth_items)]
            raw_clips = await asyncio.gather(*tasks, return_exceptions=True)

            # Build slots with window info
            slots: list[SegmentSlot] = []
            for i, ((text, window_start, window_end, _idxs), clip_result) in enumerate(
                zip(synth_items, raw_clips)
            ):
                clip_path = None
                clip_duration = 0.0
                if isinstance(clip_result, Exception):
                    logger.warning(
                        f"Sentence {i} synthesis failed: {clip_result!r} — "
                        f"text={text[:60]!r}"
                    )
                elif clip_result is None:
                    if text:
                        logger.warning(f"Sentence {i} has text but no audio clip: {text[:60]!r}")
                else:
                    clip_path = clip_result
                    clip_duration = _get_audio_duration(clip_result)
                    if clip_duration <= 0:
                        logger.warning(
                            f"Sentence {i} synthesized clip has zero duration: {clip_result}"
                        )

                anchor = (window_start + window_end) / 2.0
                slots.append(SegmentSlot(
                    index=i,
                    clip_path=clip_path,
                    clip_duration=clip_duration,
                    window_start=window_start,
                    window_end=window_end,
                    anchor=anchor,
                    effective_start=window_start,
                    effective_end=window_end,
                ))

            if on_progress:
                on_progress(total, total, "Optimizing segment timing...")

            # === Stage 2: Redistribute — anchor at midpoint, expand into neighbors ===
            _redistribute_slots(slots, video_duration)

            # === Stage 3: Iterative LLM shortening with hard 1.5× target ===
            # Shorten the WHOLE sentence (not per-segment), then re-synthesize.
            # Loop up to SHORTENING_MAX_PASSES times: each pass targets only
            # sentences still over MAX_DUB_SPEED, with a progressively more
            # aggressive target_pct. Sentences that fit drop out of the loop.
            # Sentences still over the cap after all passes proceed and get
            # hard-capped + flagged in Stage 4.

            async def resynth(slot: SegmentSlot, original_text: str, shortened: str):
                """Re-synthesise a slot with shortened text. Updates the slot
                in-place if the new audio is actually shorter."""
                if shortened == original_text or len(shortened) >= len(original_text):
                    return
                try:
                    async with self._semaphore:
                        new_bytes = await provider.synthesize(shortened, voice, **kwargs)
                    new_path = tmp / f"short_{slot.index:04d}_p{slot._pass}.mp3"
                    new_path.write_bytes(new_bytes)
                    new_duration = _get_audio_duration(new_path)
                    if new_duration > 0 and new_duration < slot.clip_duration:
                        slot.clip_path = new_path
                        slot.clip_duration = new_duration
                        old = synth_items[slot.index]
                        synth_items[slot.index] = (shortened, old[1], old[2], old[3])
                        logger.info(
                            f"Sentence {slot.index} (pass {slot._pass}): "
                            f"shortened '{original_text[:40]}' → '{shortened[:40]}' "
                            f"({new_duration:.2f}s)"
                        )
                except Exception as e:
                    logger.warning(
                        f"Sentence {slot.index} (pass {slot._pass}): "
                        f"re-synthesis failed: {e}"
                    )

            if not self._translator:
                # Quick sanity: if any sentence overflows we'll hit the hard
                # cap in Stage 4. Log once so the user knows shortening is
                # disabled.
                any_overflow = any(
                    slot.clip_path is not None
                    and slot.clip_duration > 0
                    and (slot.effective_end - slot.effective_start) > 0
                    and slot.clip_duration / (slot.effective_end - slot.effective_start) > effective_speed
                    for slot in slots
                )
                if any_overflow:
                    logger.warning(
                        f"Some sentences exceed {effective_speed}× but no LLM "
                        f"translator is configured. Set DEEPSEEK_API_KEY/"
                        f"ANTHROPIC_API_KEY/OPENAI_API_KEY to enable iterative "
                        f"shortening."
                    )

            if self._translator:
                for pass_idx in range(1, SHORTENING_MAX_PASSES + 1):
                    # Re-pick the overflow set each pass — sentences that fit
                    # after a prior pass drop out.
                    overflow: list[tuple[SegmentSlot, str, float]] = []
                    for slot in slots:
                        if slot.clip_path is None or slot.clip_duration <= 0:
                            continue
                        effective_window = slot.effective_end - slot.effective_start
                        if effective_window <= 0:
                            continue
                        ratio = slot.clip_duration / effective_window
                        if ratio > effective_speed:
                            text = synth_items[slot.index][0]
                            if text:
                                overflow.append((slot, text, ratio))

                    if not overflow:
                        if pass_idx == 1:
                            logger.info(
                                f"No sentences exceed {effective_speed}× — skipping shortening"
                            )
                        break

                    if on_progress:
                        on_progress(
                            0, total,
                            f"Shortening pass {pass_idx}/{SHORTENING_MAX_PASSES}: "
                            f"{len(overflow)} sentences",
                        )
                    logger.info(
                        f"Shortening pass {pass_idx}/{SHORTENING_MAX_PASSES}: "
                        f"{len(overflow)} sentences over {effective_speed}×"
                    )

                    # Build the LLM batch. target_pct is calibrated so the
                    # shortened text, at the same speech rate, would fit at
                    # exactly `effective_speed`. Each subsequent pass tightens
                    # by 5 percentage points to push the LLM harder.
                    batch_items = []
                    for slot, text, ratio in overflow:
                        effective_window = slot.effective_end - slot.effective_start
                        # Target proportion of original duration that fits at
                        # `effective_speed`, in percent.
                        natural_pct = (effective_window * effective_speed / slot.clip_duration) * 100
                        target_pct = max(30, int(natural_pct) - 5 * (pass_idx - 1))
                        batch_items.append({
                            "text": text,
                            "target_pct": target_pct,
                            "current_duration": slot.clip_duration,
                            "target_duration": effective_window,
                            "speed_ratio": ratio,
                        })

                    shortened_texts = await self._translator.shorten_texts_batch(batch_items)

                    resynth_tasks = []
                    for (slot, text, _ratio), shortened in zip(overflow, shortened_texts):
                        slot._pass = pass_idx  # for filename + logging
                        resynth_tasks.append(resynth(slot, text, shortened))
                    await asyncio.gather(*resynth_tasks, return_exceptions=True)

                # Re-distribute with the post-shortening clip durations: donors
                # that fed an overflowing slot get their time back if the slot
                # was shortened, and slots that still overflow can re-borrow
                # from now-freed neighbors.
                for slot in slots:
                    slot.effective_start = slot.window_start
                    slot.effective_end = slot.window_end
                _redistribute_slots(slots, video_duration)

                if on_progress:
                    on_progress(total, total, "Text shortening complete")

            # === Stage 4: Apply uniform `effective_speed` to every slot ===
            fitted_clips: list[tuple[float, Path | None]] = []

            for slot in slots:
                if on_progress:
                    on_progress(slot.index + 1, total, f"Fitting segment {slot.index + 1}/{total}")

                slot_text = synth_items[slot.index][0] if slot.index < len(synth_items) else ""

                if slot.clip_path is None or slot.clip_duration <= 0:
                    logger.warning(
                        f"Sentence {slot.index} dropped from output: no audio clip "
                        f"(window {slot.window_start:.2f}–{slot.window_end:.2f}s)"
                    )
                    fitted_clips.append((slot.effective_start, None))
                    sentence_plan.append({
                        "index": slot.index,
                        "text": slot_text,
                        "window_start": round(slot.window_start, 3),
                        "window_end": round(slot.window_end, 3),
                        "synth_duration": round(slot.clip_duration, 3),
                        "speed_ratio": 0.0,
                        "needs_review": True,
                        "reason": "no_audio_clip",
                    })
                    continue

                # Resolve a usable window. Three cases:
                #   1. effective window already > 0 → use it.
                #   2. effective collapsed but base window > 0 → fall back.
                #   3. base window also ≤ 0 (zero-width SRT) → still apply
                #      effective_speed (uniform pacing rule, "fixed" mode).
                effective_window = slot.effective_end - slot.effective_start
                output_start = slot.effective_start
                reason: str | None = None
                needs_review = False

                if effective_window <= 0:
                    base_window = slot.window_end - slot.window_start
                    if base_window <= 0:
                        # Pathological zero-width SRT segment. Still apply the
                        # chosen playback speed so the dub matches the rest
                        # of the track. Audio plays from window_start; will
                        # likely overrun the next slot, but it's at the
                        # configured speed (no 1× outlier).
                        logger.warning(
                            f"Sentence {slot.index}: zero-width SRT slot — "
                            f"playing at chosen speed {effective_speed}x "
                            f"from window_start ({slot.window_start:.2f}s)"
                        )
                        output_start = slot.window_start
                        # Use clip_duration as the denominator; requested ratio
                        # is undefined for zero-width but we record it as 0.
                        requested_ratio = 0.0
                        needs_review = True
                        reason = "zero_width_window"
                        # Skip to the unified atempo block below.
                        effective_window = slot.clip_duration  # for plan record only
                    else:
                        logger.warning(
                            f"Sentence {slot.index}: effective window collapsed "
                            f"({effective_window:.2f}s), falling back to base "
                            f"window ({base_window:.2f}s)"
                        )
                        slot.effective_start = slot.window_start
                        slot.effective_end = slot.window_end
                        effective_window = base_window
                        output_start = slot.effective_start

                if reason is None:
                    requested_ratio = slot.clip_duration / effective_window
                    # Fixed/uniform pacing: every sentence plays at exactly
                    # `effective_speed`. If natural needs more (Stage 3
                    # couldn't shorten enough), the audio will be longer than
                    # the slot — record it for review.
                    if requested_ratio > effective_speed:
                        logger.warning(
                            f"Sentence {slot.index}: needs {requested_ratio:.2f}x "
                            f"to fit ({slot.clip_duration:.2f}s in "
                            f"{effective_window:.2f}s) — capping at "
                            f"{effective_speed}x. Silent tail will follow; "
                            f"flagged for review."
                        )
                        needs_review = True
                        reason = "speed_cap_hit"

                # ALWAYS apply effective_speed via atempo — uniform pacing
                # across every clip, no exceptions for any branch above.
                # Skip only the trivial ~1.0 case to avoid a useless re-encode.
                speed_ratio = effective_speed
                fitted_duration = slot.clip_duration
                if abs(speed_ratio - 1.0) > 0.01:
                    fitted_path = tmp / f"fitted_{slot.index:04d}.mp3"
                    _speed_up_audio(slot.clip_path, fitted_path, speed_ratio)
                    # Verify atempo actually shortened the audio.
                    fitted_duration = _get_audio_duration(fitted_path)
                    expected = slot.clip_duration / speed_ratio
                    if fitted_duration <= 0:
                        logger.error(
                            f"Sentence {slot.index}: atempo produced empty/invalid "
                            f"output ({fitted_path.name}); falling back to "
                            f"original clip at natural speed"
                        )
                        fitted_path = slot.clip_path
                        fitted_duration = slot.clip_duration
                        speed_ratio = 1.0
                        needs_review = True
                        reason = "atempo_failed"
                    elif abs(fitted_duration - expected) / max(expected, 0.01) > 0.10:
                        logger.warning(
                            f"Sentence {slot.index}: atempo output duration "
                            f"{fitted_duration:.2f}s vs expected "
                            f"{expected:.2f}s — atempo may not have applied "
                            f"correctly (input was {slot.clip_duration:.2f}s, "
                            f"speed={speed_ratio})"
                        )
                    fitted_clips.append((output_start, fitted_path))
                else:
                    fitted_clips.append((output_start, slot.clip_path))

                sentence_plan.append({
                    "index": slot.index,
                    "text": slot_text,
                    "window_start": round(slot.window_start, 3),
                    "window_end": round(slot.window_end, 3),
                    "synth_duration": round(slot.clip_duration, 3),
                    "fitted_duration": round(fitted_duration, 3),
                    "speed_ratio": round(speed_ratio, 3),
                    "requested_ratio": round(requested_ratio, 3),
                    "needs_review": needs_review,
                    "reason": reason,
                })

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # === Stage 5: Concatenate with silence gaps ===
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

        # Save the sentences SRT (with any shortening applied) alongside the WAV
        if merge_sentences and synth_items:
            from src.processor.subtitle import write_srt
            sentences_srt = output_path.with_suffix(".sentences.srt")
            sentence_segments = [
                {"start": item[1], "end": item[2], "text": item[0]}
                for item in synth_items if item[0]
            ]
            write_srt(sentence_segments, sentences_srt)
            logger.info(f"Saved sentences SRT: {sentences_srt}")

            # Write shortened text back to the original SRT.
            # Use LLM to split each shortened sentence into subtitle-sized
            # segments at natural phrase boundaries (commas, clauses).
            if srt_path and self._translator:
                sentences_to_split: list[tuple[str, float, float]] = []
                for text, _start, _end, seg_indices in synth_items:
                    if not text or not seg_indices:
                        continue
                    original_concat = " ".join(
                        segments[j].get("text", "") for j in seg_indices if j < len(segments)
                    )
                    if text == original_concat:
                        continue
                    valid = [j for j in seg_indices if j < len(segments)]
                    if not valid:
                        continue
                    group_start = segments[valid[0]]["start"]
                    group_end = segments[valid[-1]]["end"]
                    sentences_to_split.append((text, group_start, group_end))

                if sentences_to_split:
                    # Always returns a list — uses deterministic split on LLM failure
                    split_segments = await _llm_split_subtitles(
                        self._translator, sentences_to_split
                    )
                    # Merge: keep non-shortened segments as-is,
                    # replace shortened sentence groups with the split segments
                    final_segments: list[dict] = []
                    shortened_ranges: set[int] = set()
                    for _text, _start, _end, seg_indices in synth_items:
                        if not _text or not seg_indices:
                            continue
                        original_concat = " ".join(
                            segments[j].get("text", "") for j in seg_indices if j < len(segments)
                        )
                        if _text != original_concat:
                            for j in seg_indices:
                                if j < len(segments):
                                    shortened_ranges.add(j)

                    split_iter = iter(split_segments)
                    i = 0
                    while i < len(segments):
                        if i in shortened_ranges:
                            group_indices = []
                            for _text, _start, _end, seg_indices in synth_items:
                                if i in seg_indices:
                                    group_indices = [j for j in seg_indices if j < len(segments)]
                                    break
                            try:
                                group_splits = next(split_iter)
                                final_segments.extend(group_splits)
                            except StopIteration:
                                for j in group_indices:
                                    final_segments.append(segments[j])
                            i = max(group_indices) + 1 if group_indices else i + 1
                        else:
                            final_segments.append({
                                "start": segments[i]["start"],
                                "end": segments[i]["end"],
                                "text": segments[i].get("text", ""),
                            })
                            i += 1

                    write_srt(final_segments, srt_path)
                    logger.info(
                        f"Updated SRT with split segments: "
                        f"{len(segments)} → {len(final_segments)} segments in {srt_path}"
                    )

        review_count = sum(1 for s in sentence_plan if s.get("needs_review"))
        logger.info(
            f"Generated TTS track: {output_path} — {len(sentence_plan)} "
            f"sentences planned, {review_count} need review"
        )
        return output_path, sentence_plan


def _naive_split_text(text: str, max_chars: int = 35) -> list[str]:
    """Deterministic fallback splitter: break at punctuation, then word boundaries."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    parts = re.split(r"(?<=[,，.。!！?？;；:：])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    out: list[str] = []
    for p in parts:
        if len(p) <= max_chars:
            out.append(p)
            continue
        words = p.split()
        cur = ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                out.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            out.append(cur)
    return out or [text]


def _segments_from_chunks(
    chunks: list[str], group_start: float, group_end: float
) -> list[dict]:
    """Distribute char-proportional timings across chunks."""
    if not chunks:
        return []
    total_time = max(0.0, group_end - group_start)
    total_chars = sum(len(t) for t in chunks) or 1
    cursor = group_start
    out: list[dict] = []
    for k, seg_text in enumerate(chunks):
        seg_time = total_time * (len(seg_text) / total_chars)
        seg_start = round(cursor, 3)
        seg_end = round(cursor + seg_time, 3) if k < len(chunks) - 1 else group_end
        out.append({"start": seg_start, "end": seg_end, "text": seg_text})
        cursor = seg_end
    return out


def _fallback_split_subtitles(
    sentences: list[tuple[str, float, float]],
) -> list[list[dict]]:
    """Deterministic split used when the LLM call fails or returns garbage."""
    return [
        _segments_from_chunks(_naive_split_text(text) or [text], start, end)
        for text, start, end in sentences
    ]


async def _llm_split_subtitles(
    translator,
    sentences: list[tuple[str, float, float]],
) -> list[list[dict]]:
    """Ask LLM to split shortened sentences into subtitle-sized segments.

    Always returns a list (one entry per input sentence). On LLM failure the
    sentence is split deterministically at punctuation/word boundaries, so the
    SRT can always be rewritten and stay in sync with the shortened audio.
    """
    if not sentences:
        return []

    lines = []
    for i, (text, start, end) in enumerate(sentences):
        lines.append(f"{i + 1}. [{start:.1f}s-{end:.1f}s] {text}")

    system = (
        "You are a subtitle segmenter. Split each subtitle sentence into "
        "short display segments (max 35 characters each). Break at natural "
        "boundaries: commas, conjunctions, phrase endings. Each segment must "
        "be a meaningful phrase, not a random word split."
    )
    user = (
        f"Split each of the following {len(sentences)} sentences into subtitle segments.\n"
        f"Rules:\n"
        f"- Each segment must be ≤35 characters\n"
        f"- Break at commas, conjunctions, or natural phrase boundaries\n"
        f"- Keep the exact same words — do NOT change, add, or remove any text\n"
        f"- For each sentence, output the segments on separate lines\n"
        f"- Separate sentences with a blank line\n"
        f"- Output ONLY the segmented text, no numbering, no timestamps\n\n"
        + "\n".join(lines)
    )

    try:
        result = await translator._call_llm(system, user)
        blocks = [b.strip() for b in result.strip().split("\n\n") if b.strip()]

        if len(blocks) != len(sentences):
            logger.warning(
                f"LLM split returned {len(blocks)} blocks for {len(sentences)} sentences, "
                f"using deterministic fallback"
            )
            return _fallback_split_subtitles(sentences)

        all_splits: list[list[dict]] = []
        for block, (text, group_start, group_end) in zip(blocks, sentences):
            seg_texts = [line.strip() for line in block.split("\n") if line.strip()]
            cleaned: list[str] = []
            for t in seg_texts:
                t = re.sub(r"^\d+[\.\)]\s*", "", t)
                t = re.sub(r"^[-•]\s*", "", t)
                t = t.strip()
                if t:
                    cleaned.append(t)

            if not cleaned:
                cleaned = _naive_split_text(text) or [text]

            all_splits.append(_segments_from_chunks(cleaned, group_start, group_end))

        logger.info(
            f"LLM split {len(sentences)} sentences into "
            f"{sum(len(s) for s in all_splits)} subtitle segments"
        )
        return all_splits

    except Exception as e:
        logger.warning(f"LLM subtitle splitting failed: {e} — using deterministic fallback")
        return _fallback_split_subtitles(sentences)


def _redistribute_slots(slots: list[SegmentSlot], video_duration: float) -> None:
    """Redistribute unused time from short segments to overflowing ones.

    Each segment has a window = [window_start, window_end) where window_end = next_start.
    If a clip is shorter than its window, the leftover time is free for neighbors.
    If a clip is longer, it borrows from neighbors' free time.

    Key insight: a segment's "free time" = window_size - clip_duration.
    This free time exists at the END of the window (after the audio finishes).
    An overflowing segment can expand backward into the previous segment's
    free time, or forward into the next segment's free time.
    """
    n = len(slots)
    if n == 0:
        return

    # Calculate free time per segment (positive = has spare, negative = overflows)
    free_time = []
    for s in slots:
        window_size = s.window_end - s.window_start
        if s.clip_duration > 0:
            free_time.append(window_size - s.clip_duration)
        else:
            free_time.append(window_size)

    # Process overflowing segments (negative free_time) by worst first
    overflow_indices = [i for i in range(n) if free_time[i] < 0]
    overflow_indices.sort(key=lambda i: free_time[i])  # most negative first

    for idx in overflow_indices:
        s = slots[idx]
        needed = -free_time[idx]  # how much extra time we need

        # Check previous segment's free time (free time sits at END of prev's window)
        can_borrow_before = 0.0
        if idx > 0 and free_time[idx - 1] > 0:
            can_borrow_before = free_time[idx - 1] * GAP_BORROW_FRACTION

        # Check next segment's free time (free time sits at END of next's window,
        # but we need it at the START — so we shift next's audio later)
        can_borrow_after = 0.0
        if idx + 1 < n and free_time[idx + 1] > 0:
            can_borrow_after = free_time[idx + 1] * GAP_BORROW_FRACTION

        # Borrow: prefer before (shifts start earlier), then after
        borrow_before = min(needed * 0.6, can_borrow_before)
        borrow_after = min(needed - borrow_before, can_borrow_after)
        # If not enough from after, try more from before
        if borrow_before + borrow_after < needed:
            borrow_before = min(needed - borrow_after, can_borrow_before)

        total_borrowed = borrow_before + borrow_after

        if total_borrowed > 0:
            # Expand this segment's effective window
            s.effective_start = s.window_start - borrow_before
            s.effective_end = s.window_end + borrow_after

            # Reduce neighbors' free time
            if borrow_before > 0 and idx > 0:
                free_time[idx - 1] -= borrow_before
            if borrow_after > 0 and idx + 1 < n:
                free_time[idx + 1] -= borrow_after

            old_window = s.window_end - s.window_start
            new_window = s.effective_end - s.effective_start
            old_ratio = s.clip_duration / max(old_window, 0.1)
            new_ratio = s.clip_duration / max(new_window, 0.1)
            logger.info(
                f"Segment {idx}: borrowed {borrow_before:.2f}s before + {borrow_after:.2f}s after "
                f"(prev_free={can_borrow_before / GAP_BORROW_FRACTION:.2f}s, next_free={can_borrow_after / GAP_BORROW_FRACTION:.2f}s) "
                f"→ window {old_window:.2f}s→{new_window:.2f}s, ratio {old_ratio:.1f}x→{new_ratio:.1f}x"
            )

    # Clamp: ensure no overlapping effective windows
    for i in range(n - 1):
        if slots[i].effective_end > slots[i + 1].effective_start:
            mid = (slots[i].effective_end + slots[i + 1].effective_start) / 2.0
            slots[i].effective_end = mid
            slots[i + 1].effective_start = mid


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
    """Build ffmpeg atempo filter chain for the given speed ratio."""
    filters = []
    remaining = speed_ratio

    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0

    if remaining > 1.0:
        filters.append(f"atempo={remaining:.4f}")

    return ",".join(filters) if filters else "atempo=1.0"


def _speed_up_audio(input_path: Path, output_path: Path, speed_ratio: float) -> None:
    """Speed up audio using ffmpeg atempo filter."""
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
    """Concatenate audio clips with silence padding to match video duration."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        silence_path = tmp / "silence.wav"
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"anullsrc=r=24000:cl=mono:d={total_duration}",
                "-c:a", "pcm_s16le",
                str(silence_path),
            ],
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
        filter_parts = []

        for i, (start_time, clip_path) in enumerate(valid_clips):
            inputs.extend(["-i", str(clip_path)])
            input_idx = i + 1
            delay_ms = int(start_time * 1000)
            filter_parts.append(
                f"[{input_idx}]adelay={delay_ms}|{delay_ms}[d{i}]"
            )

        mix_inputs = "[0]" + "".join(f"[d{i}]" for i in range(len(valid_clips)))
        n_inputs = len(valid_clips) + 1
        filter_parts.append(
            f"{mix_inputs}amix=inputs={n_inputs}:duration=first:dropout_transition=0,volume={n_inputs}[boosted]"
        )
        filter_parts.append("[boosted]loudnorm=I=-16:TP=-1.5:LRA=11[out]")

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            *inputs,
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-c:a", "pcm_s16le",
            "-ar", "24000",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Audio concatenation failed: {result.stderr[-500:]}")
