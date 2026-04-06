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

# Warn if TTS clip needs to be sped up beyond this ratio
MAX_SAFE_SPEED_RATIO = 2.5
# Trigger LLM text shortening above this ratio
# 1.5x speedup still sounds natural; only shorten above that
SHORTENING_TRIGGER = 1.5
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

        # Match [numbers] text pattern
        m = re.match(r"\[([^\]]+)\]\s*(.+)", line)
        if m:
            nums_str = m.group(1)
            merged_text = m.group(2).strip()
            nums = re.findall(r"\d+", nums_str)
            group = []
            for n in nums:
                idx = int(n) - 1  # convert to 0-based
                if 0 <= idx < len(segments) and idx not in seen:
                    group.append(idx)
                    seen.add(idx)
            if group and merged_text:
                results.append((sorted(group), merged_text))
        else:
            # Fallback: try plain comma-separated numbers (old format)
            nums = re.findall(r"\d+", line)
            if nums:
                group = []
                for n in nums:
                    idx = int(n) - 1
                    if 0 <= idx < len(segments) and idx not in seen:
                        group.append(idx)
                        seen.add(idx)
                if group:
                    # No merged text from LLM, will fall back to joining later
                    results.append((sorted(group), ""))

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
    ) -> Path:
        """Generate a full-length TTS audio track from subtitle segments.

        Pipeline:
        0. Merge segments into sentence groups (LLM or heuristic)
        1. Synthesize each sentence concurrently
        2. Anchor each dub at midpoint of its window, redistribute unused time
        3. LLM-shorten text for sentences still needing > 1.25x speedup
        4. Speed-adjust with atempo
        5. Concatenate with silence padding
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        voice = voice_profile["voice"]
        kwargs = {}
        if "speed" in voice_profile:
            kwargs["speed"] = voice_profile["speed"]
        if "pitch" in voice_profile:
            kwargs["pitch"] = voice_profile["pitch"]

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
                if not isinstance(clip_result, Exception) and clip_result is not None:
                    clip_path = clip_result
                    clip_duration = _get_audio_duration(clip_result)

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

            # === Stage 3: LLM shortening for sentences exceeding speedup threshold ===
            # Shorten the WHOLE sentence (not per-segment), then re-synthesize.
            # Also update synth_items text so exported SRT stays in sync.
            needs_shortening: list[tuple[SegmentSlot, str, float]] = []
            for slot in slots:
                if slot.clip_path is None or slot.clip_duration <= 0:
                    continue
                effective_window = slot.effective_end - slot.effective_start
                if effective_window <= 0:
                    continue
                ratio = slot.clip_duration / effective_window
                if ratio > SHORTENING_TRIGGER:
                    text = synth_items[slot.index][0]
                    if text:
                        needs_shortening.append((slot, text, ratio))

            if needs_shortening and not self._translator:
                logger.warning(
                    f"{len(needs_shortening)} sentences need >1.25x speedup but no LLM translator configured. "
                    f"Set DEEPSEEK_API_KEY or ANTHROPIC_API_KEY env var to enable text shortening."
                )

            if needs_shortening and self._translator:
                if on_progress:
                    on_progress(0, total, f"Shortening {len(needs_shortening)} sentences via LLM...")

                # Single batch LLM call — shorten whole sentences
                batch_items = []
                for slot, text, ratio in needs_shortening:
                    effective_window = slot.effective_end - slot.effective_start
                    batch_items.append({
                        "text": text,
                        "target_pct": max(30, int((effective_window / slot.clip_duration) * 100)),
                        "current_duration": slot.clip_duration,
                        "target_duration": effective_window,
                        "speed_ratio": ratio,
                    })

                shortened_texts = await self._translator.shorten_texts_batch(batch_items)

                # Re-synthesize shortened sentences and update synth_items
                async def resynth(slot: SegmentSlot, original_text: str, shortened: str):
                    if shortened == original_text or len(shortened) >= len(original_text):
                        return
                    try:
                        async with self._semaphore:
                            new_bytes = await provider.synthesize(shortened, voice, **kwargs)
                        new_path = tmp / f"short_{slot.index:04d}.mp3"
                        new_path.write_bytes(new_bytes)
                        new_duration = _get_audio_duration(new_path)
                        if new_duration > 0 and new_duration < slot.clip_duration:
                            slot.clip_path = new_path
                            slot.clip_duration = new_duration
                            # Update synth_items so the text stays in sync
                            old = synth_items[slot.index]
                            synth_items[slot.index] = (shortened, old[1], old[2], old[3])
                            logger.info(
                                f"Sentence {slot.index}: shortened '{original_text[:40]}' "
                                f"→ '{shortened[:40]}'"
                            )
                    except Exception as e:
                        logger.warning(f"Sentence {slot.index}: re-synthesis failed: {e}")

                resynth_tasks = []
                for (slot, text, _ratio), shortened in zip(needs_shortening, shortened_texts):
                    resynth_tasks.append(resynth(slot, text, shortened))
                await asyncio.gather(*resynth_tasks)

                if on_progress:
                    on_progress(total, total, "Text shortening complete")

            # === Stage 4: Speed adjustment ===
            fitted_clips: list[tuple[float, Path | None]] = []

            for slot in slots:
                if on_progress:
                    on_progress(slot.index + 1, total, f"Fitting segment {slot.index + 1}/{total}")

                if slot.clip_path is None or slot.clip_duration <= 0:
                    fitted_clips.append((slot.effective_start, None))
                    continue

                effective_window = slot.effective_end - slot.effective_start
                if effective_window <= 0:
                    fitted_clips.append((slot.effective_start, None))
                    continue

                speed_ratio = slot.clip_duration / effective_window

                if speed_ratio > 1.05:
                    if speed_ratio > MAX_SAFE_SPEED_RATIO:
                        logger.warning(
                            f"Segment {slot.index}: TTS is {slot.clip_duration:.1f}s for "
                            f"{effective_window:.1f}s available ({speed_ratio:.1f}x speedup)"
                        )
                    fitted_path = tmp / f"fitted_{slot.index:04d}.mp3"
                    _speed_up_audio(slot.clip_path, fitted_path, speed_ratio)
                    fitted_clips.append((slot.effective_start, fitted_path))
                else:
                    fitted_clips.append((slot.effective_start, slot.clip_path))

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # === Stage 5: Concatenate with silence gaps ===
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

        # Save the sentences SRT (with any shortening applied) alongside the WAV
        if merge_sentences and synth_items:
            from src.processor.subtitle import break_long_lines, write_srt
            sentences_srt = output_path.with_suffix(".sentences.srt")
            sentence_segments = [
                {"start": item[1], "end": item[2], "text": item[0]}
                for item in synth_items if item[0]
            ]
            write_srt(sentence_segments, sentences_srt)
            logger.info(f"Saved sentences SRT: {sentences_srt}")

            # Write shortened text back to the original SRT so burned-in
            # subtitles match the spoken dub audio.
            # Break long merged sentences into lines (~40 chars) so they
            # don't overflow the video width.
            if srt_path and any(
                synth_items[i][0] != segments[min(i, len(segments) - 1)].get("text", "")
                for i in range(len(synth_items))
                if synth_items[i][0]
            ):
                wrapped_segments = [
                    {**seg, "text": break_long_lines(seg["text"], max_chars=40)}
                    for seg in sentence_segments
                ]
                write_srt(wrapped_segments, srt_path)
                logger.info(f"Updated original SRT with shortened text: {srt_path}")

        logger.info(f"Generated TTS track: {output_path}")
        return output_path


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
