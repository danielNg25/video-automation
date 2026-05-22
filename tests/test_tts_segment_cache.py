"""Tests for the per-segment WAV cache + dub metadata."""
from __future__ import annotations

from src.tts.dub_meta import DubMeta, load_dub_meta, save_dub_meta
from src.tts.segment_cache import (
    cache_dir_for_video,
    cache_path_for_segment,
    load_segment_clip,
    save_segment_clip,
)


def test_cache_path_format(tmp_path):
    """cache_path_for_segment returns deterministic per-(video, lang, idx) paths."""
    p = cache_path_for_segment(tmp_path, "abc123", "vi", 0)
    assert p == tmp_path / "abc123" / "segments" / "vi_000.wav"

    p2 = cache_path_for_segment(tmp_path, "abc123", "vi", 42)
    assert p2 == tmp_path / "abc123" / "segments" / "vi_042.wav"


def test_save_and_load_segment_clip(tmp_path):
    """save_segment_clip copies a source WAV into the cache; load returns the cached path."""
    source = tmp_path / "src.wav"
    source.write_bytes(b"RIFF....fake-wav-data")

    cached = save_segment_clip(tmp_path, "abc123", "vi", 5, source)
    assert cached.exists()
    assert cached.read_bytes() == b"RIFF....fake-wav-data"

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
