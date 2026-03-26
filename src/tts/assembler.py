"""TTS audio assembler: builds a full-length audio track from subtitle segments."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Warn if TTS clip needs to be sped up beyond this ratio
MAX_SAFE_SPEED_RATIO = 2.5


class TTSAssembler:
    """Assembles per-segment TTS audio into a full-length audio track."""

    def __init__(self, max_concurrent: int = 5):
        self._semaphore = asyncio.Semaphore(max_concurrent)

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

        Algorithm:
        1. Synthesize each segment concurrently (with semaphore limit)
        2. Get clip duration via ffprobe
        3. If clip is longer than segment window: speed up with ffmpeg atempo
        4. Concatenate all clips with silence padding to match video duration

        Args:
            provider: TTS provider instance.
            segments: List of dicts with 'start', 'end', 'text' keys.
            voice_profile: Dict with 'voice', 'speed', 'pitch' keys.
            video_duration: Total video duration in seconds.
            output_path: Path for the output WAV file.
            on_progress: Optional callback(current, total, message).

        Returns:
            Path to the generated WAV file.
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

            # Step 1: Synthesize all segments concurrently
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

            tasks = []
            for i, seg in enumerate(segments):
                tasks.append(synth_one(i, seg))

            raw_clips = await asyncio.gather(*tasks, return_exceptions=True)

            # Step 2-4: Duration fitting — only speed up if clip would
            # overlap the *next* segment's start time, allowing natural
            # speech to overflow its own subtitle window.
            fitted_clips: list[tuple[float, Path | None]] = []  # (start_time, clip_path)

            for i, (seg, clip_result) in enumerate(zip(segments, raw_clips)):
                if on_progress:
                    on_progress(i + 1, total, f"Fitting segment {i + 1}/{total}")

                if isinstance(clip_result, Exception):
                    logger.warning(f"Segment {i} synthesis failed: {clip_result}")
                    fitted_clips.append((seg["start"], None))
                    continue

                if clip_result is None:
                    fitted_clips.append((seg["start"], None))
                    continue

                clip_path = clip_result
                clip_duration = _get_audio_duration(clip_path)
                if clip_duration <= 0:
                    fitted_clips.append((seg["start"], None))
                    continue

                # Available space: from this segment's start to the next
                # segment's start (or video end for the last segment).
                if i + 1 < total:
                    next_start = segments[i + 1]["start"]
                else:
                    next_start = video_duration
                available = max(next_start - seg["start"], 0.1)

                speed_ratio = clip_duration / available

                if speed_ratio > 1.05:
                    if speed_ratio > MAX_SAFE_SPEED_RATIO:
                        logger.warning(
                            f"Segment {i}: TTS is {clip_duration:.1f}s for "
                            f"{available:.1f}s available ({speed_ratio:.1f}x speedup needed)"
                        )

                    fitted_path = tmp / f"fitted_{i:04d}.mp3"
                    _speed_up_audio(clip_path, fitted_path, speed_ratio)
                    fitted_clips.append((seg["start"], fitted_path))
                else:
                    fitted_clips.append((seg["start"], clip_path))

            if on_progress:
                on_progress(total, total, "Concatenating audio track...")

            # Step 5: Concatenate with silence gaps
            _concatenate_with_silence(fitted_clips, video_duration, output_path)

        logger.info(f"Generated TTS track: {output_path}")
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

    atempo supports 0.5-100.0 range per filter, but for accuracy
    we chain multiple filters for ratios > 2.0.
    """
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
    """Concatenate audio clips with silence padding to match video duration.

    Each clip is placed at its segment start time. Gaps between clips are
    filled with silence. The output is a single WAV file.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # Generate a silence source as a WAV base
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

        # If no valid clips, just output silence
        valid_clips = [(t, p) for t, p in clips if p is not None and p.exists()]
        if not valid_clips:
            # Convert silence to output format
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(silence_path), str(output_path)],
                capture_output=True, text=True, check=True, timeout=60,
            )
            return

        # Build complex filter to overlay each clip at its start time
        inputs = ["-i", str(silence_path)]
        filter_parts = []

        for i, (start_time, clip_path) in enumerate(valid_clips):
            inputs.extend(["-i", str(clip_path)])
            input_idx = i + 1  # 0 is silence base
            # Delay the clip to its start time (in milliseconds)
            delay_ms = int(start_time * 1000)
            filter_parts.append(
                f"[{input_idx}]adelay={delay_ms}|{delay_ms}[d{i}]"
            )

        # Mix all delayed clips with the silence base
        mix_inputs = "[0]" + "".join(f"[d{i}]" for i in range(len(valid_clips)))
        n_inputs = len(valid_clips) + 1
        filter_parts.append(
            f"{mix_inputs}amix=inputs={n_inputs}:duration=first:dropout_transition=0,volume={n_inputs}[boosted]"
        )
        # Normalize loudness to broadcast standard (-16 LUFS)
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
