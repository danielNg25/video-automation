"""Tests for the per-segment clip cache + dub metadata."""
from __future__ import annotations

from src.tts.dub_meta import DubMeta, load_dub_meta, save_dub_meta
from src.tts.segment_cache import (
    cache_basename_for_segment,
    cache_dir_for_video,
    load_segment_clip,
    save_segment_clip,
    segments_dir_for_video,
)


def test_cache_basename_format():
    """cache_basename_for_segment returns deterministic stem strings."""
    assert cache_basename_for_segment("vi", 0) == "vi_000"
    assert cache_basename_for_segment("vi", 42) == "vi_042"
    assert cache_basename_for_segment("en", 5) == "en_005"


def test_segments_dir_for_video(tmp_path):
    """segments_dir_for_video returns the expected path."""
    d = segments_dir_for_video(tmp_path, "abc123")
    assert d == tmp_path / "abc123" / "segments"


def test_save_and_load_segment_clip(tmp_path):
    """save_segment_clip copies a source MP3 into the cache preserving extension;
    load returns the cached path."""
    source = tmp_path / "src.mp3"
    source.write_bytes(b"MP3-DATA")

    cached = save_segment_clip(tmp_path, "abc123", "vi", 5, source)
    assert cached.exists()
    assert cached.suffix == ".mp3"
    assert cached.read_bytes() == b"MP3-DATA"

    loaded = load_segment_clip(tmp_path, "abc123", "vi", 5)
    assert loaded == cached
    assert loaded.exists()


def test_load_segment_clip_missing_returns_none(tmp_path):
    """When the cached clip doesn't exist, load returns None."""
    loaded = load_segment_clip(tmp_path, "abc123", "vi", 99)
    assert loaded is None


def test_cache_dir_for_video(tmp_path):
    cache = cache_dir_for_video(tmp_path, "abc123")
    assert cache == tmp_path / "abc123"


def test_save_replaces_stale_extension(tmp_path):
    """If a cached clip exists with a different extension, save removes it."""
    # First save as .wav
    src_wav = tmp_path / "first.wav"
    src_wav.write_bytes(b"WAV-DATA")
    save_segment_clip(tmp_path, "vid", "vi", 0, src_wav)

    # Save again as .mp3
    src_mp3 = tmp_path / "second.mp3"
    src_mp3.write_bytes(b"MP3-DATA")
    saved = save_segment_clip(tmp_path, "vid", "vi", 0, src_mp3)

    # Only the .mp3 should remain
    assert saved.suffix == ".mp3"
    assert saved.read_bytes() == b"MP3-DATA"

    segments_dir = segments_dir_for_video(tmp_path, "vid")
    cached_files = list(segments_dir.glob("vi_000.*"))
    assert len(cached_files) == 1
    assert cached_files[0].suffix == ".mp3"


def test_load_returns_any_extension(tmp_path):
    """load_segment_clip finds the cached file regardless of extension."""
    src = tmp_path / "clip.mp3"
    src.write_bytes(b"MP3")
    save_segment_clip(tmp_path, "vid", "vi", 5, src)

    found = load_segment_clip(tmp_path, "vid", "vi", 5)
    assert found is not None
    assert found.suffix == ".mp3"
    assert found.read_bytes() == b"MP3"


def test_dub_meta_round_trip(tmp_path):
    """save_dub_meta then load_dub_meta returns the same object."""
    meta = DubMeta(
        video_id="abc123",
        language="vi",
        provider="google",
        voice_id="vi-VN-Standard-A",
        playback_speed=1.5,
        underlay_db=-18.0,
        segment_texts=["hello", "world"],
    )
    save_dub_meta(tmp_path, meta)

    loaded = load_dub_meta(tmp_path, "abc123", "vi")
    assert loaded == meta


def test_dub_meta_missing_returns_none(tmp_path):
    """load_dub_meta returns None when no metadata file exists."""
    assert load_dub_meta(tmp_path, "abc123", "vi") is None
