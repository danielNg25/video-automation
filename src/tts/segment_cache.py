"""Per-segment natural-speed clip cache for dub-sync.

After the dub assembler synthesises each segment (before atempo/
concatenation), we persist a copy here so a subsequent "Sync Dub"
operation can reuse unchanged segments without re-synthesising.

Cache layout:

    {data_dir}/{video_id}/segments/{lang}_{idx:03d}.{ext}

where `{ext}` is whatever the underlying provider produced (typically
`.mp3` for Google / ElevenLabs / OpenAI TTS). We don't transcode — the
file is opaque to us; ffmpeg detects content by header at consumer time.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def cache_dir_for_video(data_dir: Path, video_id: str) -> Path:
    """Per-video cache root: `{data_dir}/{video_id}`."""
    return data_dir / video_id


def segments_dir_for_video(data_dir: Path, video_id: str) -> Path:
    """Per-video segments subdirectory: `{data_dir}/{video_id}/segments`."""
    return cache_dir_for_video(data_dir, video_id) / "segments"


def cache_basename_for_segment(language: str, index: int) -> str:
    """Filename stem (no extension): `{lang}_{idx:03d}`."""
    return f"{language}_{index:03d}"


def save_segment_clip(
    data_dir: Path, video_id: str, language: str, index: int, source: Path
) -> Path:
    """Copy `source` into the cache, preserving its extension. Returns cached path.

    If a cached file already exists for this (video, lang, index) with a
    DIFFERENT extension, it's removed first to avoid stale duplicates.
    """
    segments_dir = segments_dir_for_video(data_dir, video_id)
    segments_dir.mkdir(parents=True, exist_ok=True)

    basename = cache_basename_for_segment(language, index)

    # Remove any stale cached files with different extensions
    for existing in segments_dir.glob(f"{basename}.*"):
        try:
            existing.unlink()
        except OSError:
            pass

    dest = segments_dir / f"{basename}{source.suffix}"
    shutil.copyfile(source, dest)
    return dest


def load_segment_clip(
    data_dir: Path, video_id: str, language: str, index: int
) -> Path | None:
    """Return the cached path if any extension exists, else None."""
    segments_dir = segments_dir_for_video(data_dir, video_id)
    if not segments_dir.exists():
        return None
    basename = cache_basename_for_segment(language, index)
    matches = sorted(segments_dir.glob(f"{basename}.*"))
    return matches[0] if matches else None
