"""TTS audio assembler: builds a full-length audio track from subtitle segments."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# --- Timing constants ---
GAP_BORROW_FRACTION = 0.80  # borrow up to 80% of adjacent gaps
SPEEDUP_TRIGGER = 1.05      # apply atempo above this ratio
SHORTENING_TRIGGER = 1.25   # trigger LLM text shortening above this
HARD_CAP_SPEED = 1.50       # absolute max speedup; truncate beyond this
FADE_OUT_MS = 300            # fade-out duration when truncating


@dataclass
class SegmentTiming:
    """Timing info for a single TTS segment after gap redistribution."""
    index: int
    original_start: float
    original_end: float
    effective_start: float
    effective_end: float
    clip_duration: float
    clip_path: Path | None
    text: str
    speed_ratio: float = 0.0


class TTSAssembler:
    """Assembles per-segment TTS audio into a full-length audio track."""

    def __init__(self, max_concurrent: int = 5, translator=None):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._translator = translator  # LLMTranslator or None (for Phase 2)

    async def generate_full_track(
        self,
        provider: BaseTTSProvider,
        segments: list[dict],
        voice_profile: dict,
        video_duration: float,
        output_path: Path,
        on_progress: callable | None = None,
    ) -> Path:
        """Generate a full-length TTS audio track from subtitle segments.

        Pipeline:
        1. Synthesize each segment concurrently
        2. Redistribute gap time to overflowing segments (Phase 1)
        3. LLM-shorten text for segments still > 1.25x (Phase 2, if translator available)
        4. Speed-adjust with hard cap at 1.5x + truncation (Phase 3)
        5. Concatenate all clips with silence padding
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
            total = len(segments)

            # === Stage A: Synthesize all segments concurrently ===
            async def synth_one(i: int, seg: dict) -> Path | None:
                from src.tts.base import _clean_text
                text = _clean_text(seg.get("text", ""))
                if not text:
                    return None
                async with self._semaphore:
                    audio_bytes = await provider.synthesize(text, voice, **kwargs)
                clip_path = tmp / f"seg_{i:04d}.mp3"
                clip_path.write_bytes(audio_bytes)
                return clip_path

            tasks = [synth_one(i, seg) for i, seg in enumerate(segments)]
            raw_clips = await asyncio.gather(*tasks, return_exceptions=True)

            # Build clip data
            clip_paths: list[Path | None] = []
            clip_durations: list[float] = []
            for i, clip_result in enumerate(raw_clips):
                if isinstance(clip_result, Exception):
                    logger.warning(f"Segment {i} synthesis failed: {clip_result}")
                    clip_paths.append(None)
                    clip_durations.append(0.0)
                elif clip_result is None:
                    clip_paths.append(None)
                    clip_durations.append(0.0)
                else:
                    clip_paths.append(clip_result)
                    clip_durations.append(_get_audio_duration(clip_result))

            if on_progress:
                on_progress(total, total, "Optimizing segment timing...")

            # === Stage B: Gap redistribution (Phase 1) ===
            timings = _redistribute_gaps(segments, clip_durations, clip_paths, video_duration)

            # === Stage C: LLM text shortening (Phase 2) ===
            if self._translator:
                for t in timings:
                    if t.clip_path and t.speed_ratio > SHORTENING_TRIGGER:
                        if on_progress:
                            on_progress(t.index + 1, total, f"Shortening segment {t.index + 1} text (ratio {t.speed_ratio:.1f}x)...")
                        try:
                            await _shorten_and_resynthesize(
                                t, provider, voice, kwargs, self._translator, tmp,
                            )
                        except Exception as e:
                            logger.warning(f"Segment {t.index}: text shortening failed: {e}")

            # === Stage D: Speed adjustment with hard cap (Phase 3) ===
            fitted_clips: list[tuple[float, Path | None]] = []

            for i, t in enumerate(timings):
                if on_progress:
                    on_progress(i + 1, total, f"Fitting segment {i + 1}/{total}")

                if t.clip_path is None or t.clip_duration <= 0:
                    fitted_clips.append((t.effective_start, None))
                    continue

                effective_window = t.effective_end - t.effective_start
                if effective_window <= 0:
                    fitted_clips.append((t.effective_start, None))
                    continue

                speed_ratio = t.clip_duration / effective_window

                if speed_ratio > HARD_CAP_SPEED:
                    # Apply capped speedup + truncate with fade-out
                    logger.warning(
                        f"Segment {t.index}: {speed_ratio:.1f}x needed, capping at {HARD_CAP_SPEED}x + truncation"
                    )
                    sped_path = tmp / f"sped_{t.index:04d}.mp3"
                    _speed_up_audio(t.clip_path, sped_path, HARD_CAP_SPEED)
                    truncated_path = tmp / f"trunc_{t.index:04d}.mp3"
                    _truncate_with_fade(sped_path, truncated_path, effective_window)
                    fitted_clips.append((t.effective_start, truncated_path))
                elif speed_ratio > SPEEDUP_TRIGGER:
                    fitted_path = tmp / f"fitted_{t.index:04d}.mp3"
                    _speed_up_audio(t.clip_path, fitted_path, speed_ratio)
                    fitted_clips.append((t.effective_start, fitted_path))
                else:
                    fitted_clips.append((t.effective_start, t.clip_path))

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # === Stage E: Concatenate with silence gaps ===
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

        logger.info(f"Generated TTS track: {output_path}")
        return output_path


# --- Phase 1: Gap redistribution ---

def _redistribute_gaps(
    segments: list[dict],
    clip_durations: list[float],
    clip_paths: list[Path | None],
    video_duration: float,
) -> list[SegmentTiming]:
    """Redistribute unused gap time to segments that need more space.

    Processes worst-ratio segments first so the most constrained get
    priority access to adjacent gap time.
    """
    n = len(segments)
    timings: list[SegmentTiming] = []

    for i, seg in enumerate(segments):
        from src.tts.base import _clean_text
        timings.append(SegmentTiming(
            index=i,
            original_start=seg["start"],
            original_end=seg.get("end", seg["start"]),
            effective_start=seg["start"],
            effective_end=seg.get("end", seg["start"]),
            clip_duration=clip_durations[i],
            clip_path=clip_paths[i],
            text=_clean_text(seg.get("text", "")),
        ))

    # Calculate initial speed ratios using original subtitle window
    for t in timings:
        window = t.original_end - t.original_start
        if window > 0 and t.clip_duration > 0:
            t.speed_ratio = t.clip_duration / window
        else:
            t.speed_ratio = 0.0

    # Process segments by worst ratio first
    sorted_indices = sorted(range(n), key=lambda i: timings[i].speed_ratio, reverse=True)

    for idx in sorted_indices:
        t = timings[idx]
        if t.clip_duration <= 0 or t.speed_ratio <= SPEEDUP_TRIGGER:
            continue

        effective_window = t.effective_end - t.effective_start
        needed_extra = t.clip_duration - effective_window
        if needed_extra <= 0:
            continue

        # Calculate available gap before and after
        if idx > 0:
            gap_before = t.effective_start - timings[idx - 1].effective_end
        else:
            gap_before = t.effective_start  # gap from video start

        if idx + 1 < n:
            gap_after = timings[idx + 1].effective_start - t.effective_end
        else:
            gap_after = video_duration - t.effective_end  # gap to video end

        gap_before = max(gap_before, 0.0)
        gap_after = max(gap_after, 0.0)

        # Borrow from both sides, up to 80% of each gap
        borrow_before = min(needed_extra * 0.5, gap_before * GAP_BORROW_FRACTION)
        borrow_after = min(needed_extra - borrow_before, gap_after * GAP_BORROW_FRACTION)
        # If we couldn't get enough from after, try more from before
        if borrow_before + borrow_after < needed_extra:
            borrow_before = min(needed_extra - borrow_after, gap_before * GAP_BORROW_FRACTION)

        if borrow_before > 0 or borrow_after > 0:
            t.effective_start -= borrow_before
            t.effective_end += borrow_after
            new_window = t.effective_end - t.effective_start
            t.speed_ratio = t.clip_duration / max(new_window, 0.1)
            logger.info(
                f"Segment {idx}: borrowed {borrow_before:.2f}s before + {borrow_after:.2f}s after "
                f"→ ratio {t.speed_ratio:.2f}x (was {t.clip_duration / max(effective_window, 0.1):.2f}x)"
            )

    # Clamp overlapping effective windows (sequential pass)
    for i in range(n - 1):
        if timings[i].effective_end > timings[i + 1].effective_start:
            timings[i].effective_end = timings[i + 1].effective_start
            window = timings[i].effective_end - timings[i].effective_start
            if window > 0 and timings[i].clip_duration > 0:
                timings[i].speed_ratio = timings[i].clip_duration / window

    return timings


# --- Phase 2: LLM text shortening + re-synthesis ---

async def _shorten_and_resynthesize(
    timing: SegmentTiming,
    provider: BaseTTSProvider,
    voice: str,
    kwargs: dict,
    translator,
    tmp_dir: Path,
) -> None:
    """Shorten segment text via LLM and re-synthesize. Modifies timing in-place."""
    effective_window = timing.effective_end - timing.effective_start
    if effective_window <= 0:
        return

    target_ratio = effective_window / timing.clip_duration
    target_pct = max(30, int(target_ratio * 100))

    shortened = await translator.shorten_text(timing.text, target_ratio)

    if not shortened or len(shortened) >= len(timing.text):
        logger.info(f"Segment {timing.index}: shortening produced no improvement")
        return

    logger.info(
        f"Segment {timing.index}: shortened '{timing.text[:40]}...' → '{shortened[:40]}...' "
        f"(target {target_pct}%)"
    )

    # Re-synthesize with shortened text
    audio_bytes = await provider.synthesize(shortened, voice, **kwargs)
    new_path = tmp_dir / f"short_{timing.index:04d}.mp3"
    new_path.write_bytes(audio_bytes)

    new_duration = _get_audio_duration(new_path)
    if new_duration <= 0:
        return

    # Update timing
    timing.text = shortened
    timing.clip_path = new_path
    timing.clip_duration = new_duration
    timing.speed_ratio = new_duration / effective_window


# --- Phase 3 helpers ---

def _truncate_with_fade(
    input_path: Path,
    output_path: Path,
    max_duration_s: float,
    fade_ms: int = FADE_OUT_MS,
) -> None:
    """Hard-cut audio at max_duration_s with a gentle fade-out."""
    fade_s = fade_ms / 1000.0
    fade_start = max(0, max_duration_s - fade_s)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", f"afade=t=out:st={fade_start:.3f}:d={fade_s:.3f}",
        "-t", f"{max_duration_s:.3f}",
        "-c:a", "libmp3lame", "-q:a", "4",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Audio truncation failed: {result.stderr[-300:]}")


# --- Shared utilities ---

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
