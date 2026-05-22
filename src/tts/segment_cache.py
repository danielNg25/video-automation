"""Per-segment natural-speed WAV cache for dub-sync.

After the dub assembler synthesises each segment at natural speed (before
atempo/concatenation), we persist a copy here so a subsequent "Sync Dub"
operation can reuse unchanged segments without re-synthesising them.

Cache layout under `data_dir`:

    {video_id}/segments/{lang}_{idx:03d}.wav

The data_dir is typically `data/tts/`. Files are plain WAV (the provider's
raw output — typically 16-bit PCM mono).
"""
from __future__ import annotations

import shutil
from pathlib import Path


def cache_dir_for_video(data_dir: Path, video_id: str) -> Path:
    """Per-video cache root: `{data_dir}/{video_id}`."""
    return data_dir / video_id


def cache_path_for_segment(
    data_dir: Path, video_id: str, language: str, index: int
) -> Path:
    """Deterministic path for a single segment's cached WAV."""
    return cache_dir_for_video(data_dir, video_id) / "segments" / f"{language}_{index:03d}.wav"


def save_segment_clip(
    data_dir: Path, video_id: str, language: str, index: int, source: Path
) -> Path:
    """Copy `source` into the cache; return the cached path. Creates parent dirs."""
    dest = cache_path_for_segment(data_dir, video_id, language, index)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return dest


def load_segment_clip(
    data_dir: Path, video_id: str, language: str, index: int
) -> Path | None:
    """Return the cached path if it exists, else None."""
    path = cache_path_for_segment(data_dir, video_id, language, index)
    return path if path.exists() else None
