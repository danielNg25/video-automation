"""TTS audio assembler: builds a full-length audio track from subtitle segments.

Assembly model (post-simplification):
    - Sentences are merged from consecutive SRT segments (LLM if available,
      heuristic fallback). The merger never spans a silent gap larger than
      MAX_MERGE_GAP_SECONDS so a single dub clip never erases a real pause.
    - Each merged sentence is synthesised once and placed at its source
      `start` at natural speed. No atempo, no shortening, no SRT rewriting.
    - If a clip is longer than its source span, it overruns into the next
      sentence and ffmpeg's amix blends the overlap.
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

# Maximum LLM-driven shortening passes per TTS run. Each subsequent pass
# tightens the target_pct by 5 percentage points (clamped at 30%).
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
    ) -> tuple[Path, list[dict]]:
        """Generate a full-length TTS audio track from subtitle segments.

        Pipeline:
        0. Merge segments into sentence groups (LLM or heuristic). The LLM
           merger never spans gaps > MAX_MERGE_GAP_SECONDS.
        1. Synthesize one clip per sentence at the provider's natural speed.
        2. Apply ffmpeg atempo at the configured `playback_speed` (default
           1.0 = no re-encode). Place each clip at its sentence's source
           `start`. No fitting, no shortening, no shifting. If a clip
           overruns its source span at the chosen speed, ffmpeg's amix
           blends the overlap with the next clip.

        `srt_path` is accepted for back-compat (the assembler no longer
        rewrites the input SRT).
        """
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

            # Per-slot shortening history; surfaced in the sentence_plan + JSON.
            shorten_state: dict[int, dict] = {
                i: {"original_text": sg.text, "passes": 0}
                for i, sg in enumerate(sentence_groups)
            }

            # === Stage 1.5: LLM-driven shortening (skipped without translator) ===
            # When `clip_duration / playback_speed > source_span`, the dub
            # would overrun even after atempo. Ask the LLM to shorten the
            # text and re-synthesise. Up to SHORTENING_MAX_PASSES attempts,
            # each 5pp tighter than the last (clamped at 30%). Slots that
            # fit drop out between passes; slots that still overflow after
            # all passes fall through to Stage 2 and overrun normally.
            speed = playback_speed if (playback_speed and playback_speed > 0) else 1.0

            if self._translator and slots:
                for pass_idx in range(1, SHORTENING_MAX_PASSES + 1):
                    overflow: list[tuple[SegmentSlot, float]] = []
                    for slot in slots:
                        if slot.clip_path is None or slot.clip_duration <= 0:
                            continue
                        span = slot.window_end - slot.window_start
                        if span <= 0:
                            continue
                        if slot.clip_duration / speed > span:
                            overflow.append((slot, span))

                    if not overflow:
                        if pass_idx == 1:
                            logger.info(
                                f"All clips fit at {speed}× — no shortening needed"
                            )
                        break

                    batch: list[dict] = []
                    for slot, span in overflow:
                        natural_pct = (span * speed / slot.clip_duration) * 100
                        target_pct = max(30, int(natural_pct) - 5 * (pass_idx - 1))
                        batch.append({
                            "text": sentence_groups[slot.index].text,
                            "target_pct": target_pct,
                            "current_duration": slot.clip_duration,
                            "target_duration": span,
                            "speed_ratio": slot.clip_duration / span,
                        })

                    logger.info(
                        f"Shortening pass {pass_idx}/{SHORTENING_MAX_PASSES}: "
                        f"{len(overflow)} slots over budget"
                    )
                    if on_progress:
                        on_progress(
                            0, total,
                            f"Shortening pass {pass_idx}: {len(overflow)} sentences",
                        )

                    try:
                        shortened_texts = await self._translator.shorten_texts_batch(batch)
                    except Exception as e:
                        logger.warning(f"Shortening pass {pass_idx} failed: {e}")
                        break

                    # Re-synthesise only sentences whose text actually changed.
                    resynth_targets: list[tuple[SegmentSlot, str]] = []
                    for (slot, _), shortened in zip(overflow, shortened_texts):
                        if shortened == sentence_groups[slot.index].text:
                            continue
                        resynth_targets.append((slot, shortened))

                    if not resynth_targets:
                        # LLM didn't shorten anything this pass — next pass
                        # would just hit the same texts. Bail early.
                        break

                    new_clips = await asyncio.gather(
                        *[synth_one(slot.index, text, suffix=f"_p{pass_idx}")
                          for slot, text in resynth_targets],
                        return_exceptions=True,
                    )

                    for (slot, shortened), new_clip in zip(resynth_targets, new_clips):
                        if isinstance(new_clip, Exception):
                            logger.warning(
                                f"Sentence {slot.index} re-synth failed (pass "
                                f"{pass_idx}): {new_clip!r}"
                            )
                            continue
                        if new_clip is None:
                            continue
                        new_dur = _get_audio_duration(new_clip)
                        if new_dur <= 0 or new_dur >= slot.clip_duration:
                            # Re-synth wasn't actually shorter — keep original.
                            continue
                        # Swap in the shorter clip and update the merged-text
                        # so the persisted merge plan and sentence_plan
                        # reflect what was spoken.
                        slot.clip_path = new_clip
                        slot.clip_duration = new_dur
                        shorten_state[slot.index]["passes"] += 1
                        old_sg = sentence_groups[slot.index]
                        sentence_groups[slot.index] = SentenceGroup(
                            segment_indices=old_sg.segment_indices,
                            text=shortened,
                            start=old_sg.start,
                            end=old_sg.end,
                        )

                if on_progress:
                    on_progress(total, total, "Shortening complete")
            else:
                if not self._translator:
                    logger.info(
                        "LLM shortening skipped — no translator configured "
                        "(save an API key in Settings → API Keys to enable it)."
                    )

            # Persist the merged sentences (post-shortening) alongside the
            # dub WAV. Two artefacts:
            #   - {output}.merged.srt  — readable, source-aligned timings
            #   - {output}.merged.json — adds source_indices, original_text,
            #                            was_shortened, shorten_passes
            try:
                from src.processor.subtitle import write_srt as _write_srt
                merged_srt_path = output_path.with_suffix(".merged.srt")
                _write_srt(
                    [
                        {"start": sg.start, "end": sg.end, "text": sg.text}
                        for sg in sentence_groups
                    ],
                    merged_srt_path,
                )
                merged_json_path = output_path.with_suffix(".merged.json")
                merged_json_path.write_text(
                    json.dumps(
                        [
                            {
                                "index": i,
                                "source_indices": sg.segment_indices,
                                "start": round(sg.start, 3),
                                "end": round(sg.end, 3),
                                "text": sg.text,
                                "original_text": shorten_state[i]["original_text"],
                                "was_shortened": shorten_state[i]["passes"] > 0,
                                "shorten_passes": shorten_state[i]["passes"],
                            }
                            for i, sg in enumerate(sentence_groups)
                        ],
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                logger.info(
                    f"Saved merge plan: {merged_srt_path.name} + {merged_json_path.name}"
                )
            except Exception as e:
                logger.warning(f"Could not save merge-plan files: {e}")

            # === Stage 2: Apply uniform `playback_speed` and place clips ===
            # Each clip is sped up via ffmpeg atempo to the configured speed
            # (1.0 = natural, no re-encode). Then placed at its source `start`.
            # If the speed-adjusted clip is still longer than its source span,
            # it overruns the next slot — ffmpeg amix blends the overlap.
            logger.info(f"TTS dub playback_speed = {speed}× (1.0 = natural, no atempo)")

            fitted_clips: list[tuple[float, Path | None]] = []
            for slot in slots:
                window_size = slot.window_end - slot.window_start

                played_path: Path | None = None
                played_duration = 0.0
                if slot.clip_path is not None and slot.clip_duration > 0:
                    if abs(speed - 1.0) < 0.01:
                        played_path = slot.clip_path
                        played_duration = slot.clip_duration
                    else:
                        fitted_path = tmp / f"fitted_{slot.index:04d}.mp3"
                        try:
                            _speed_up_audio(slot.clip_path, fitted_path, speed)
                            ad = _get_audio_duration(fitted_path)
                            if ad > 0:
                                played_path = fitted_path
                                played_duration = ad
                            else:
                                logger.warning(
                                    f"Sentence {slot.index}: atempo produced empty output, "
                                    f"falling back to natural speed"
                                )
                                played_path = slot.clip_path
                                played_duration = slot.clip_duration
                        except Exception as e:
                            logger.warning(
                                f"Sentence {slot.index}: atempo failed ({e}), "
                                f"falling back to natural speed"
                            )
                            played_path = slot.clip_path
                            played_duration = slot.clip_duration
                    fitted_clips.append((slot.window_start, played_path))
                else:
                    logger.warning(
                        f"Sentence {slot.index} dropped from output: no audio clip "
                        f"(source span {slot.window_start:.2f}–{slot.window_end:.2f}s)"
                    )

                overrun = max(0.0, played_duration - window_size) if played_duration > 0 else 0.0
                state = shorten_state.get(slot.index, {"original_text": "", "passes": 0})
                sentence_plan.append({
                    "index": slot.index,
                    "text": sentence_groups[slot.index].text,
                    "start": round(slot.window_start, 3),
                    "end": round(slot.window_end, 3),
                    "synth_duration": round(slot.clip_duration, 3),
                    "fitted_duration": round(played_duration, 3),
                    "speed_ratio": round(speed, 3),
                    "overrun_seconds": round(overrun, 3),
                    "was_shortened": state["passes"] > 0,
                    "shorten_passes": state["passes"],
                    "original_text": state["original_text"],
                })

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # === Stage 3: Concatenate clips onto a silence track ===
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

        overrun_count = sum(1 for s in sentence_plan if s.get("overrun_seconds", 0) > 0)
        logger.info(
            f"Generated TTS track: {output_path} — {len(sentence_plan)} sentences, "
            f"{overrun_count} overrun their source span"
        )
        return output_path, sentence_plan


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
