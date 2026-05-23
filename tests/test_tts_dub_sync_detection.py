"""Tests for the SRT-save dub-sync detection helper."""
from __future__ import annotations

from pathlib import Path

from src.tts.dub_meta import DubMeta, save_dub_meta


def _save_meta(tmp_path: Path, texts: list[str], lang: str = "vi") -> None:
    """Helper: persist a dub_meta with the given segment_texts."""
    save_dub_meta(
        tmp_path,
        DubMeta(
            video_id="vid",
            language=lang,
            provider="google",
            voice_id="any",
            playback_speed=1.5,
            underlay_db=-18.0,
            segment_texts=texts,
        ),
    )


def test_check_dub_sync_no_meta_returns_false(tmp_path):
    """No dub_meta on disk = nothing to sync against."""
    from src.api.routers.editor import _check_dub_sync_against_meta

    is_out = _check_dub_sync_against_meta(
        data_dir=tmp_path, video_id="vid", language="vi",
        new_texts=["a", "b", "c"],
    )
    assert is_out is False


def test_check_dub_sync_identical_returns_false(tmp_path):
    from src.api.routers.editor import _check_dub_sync_against_meta

    _save_meta(tmp_path, ["hello", "world"])
    is_out = _check_dub_sync_against_meta(
        data_dir=tmp_path, video_id="vid", language="vi",
        new_texts=["hello", "world"],
    )
    assert is_out is False


def test_check_dub_sync_text_change_returns_true(tmp_path):
    from src.api.routers.editor import _check_dub_sync_against_meta

    _save_meta(tmp_path, ["hello", "world"])
    is_out = _check_dub_sync_against_meta(
        data_dir=tmp_path, video_id="vid", language="vi",
        new_texts=["hello", "earth"],
    )
    assert is_out is True


def test_check_dub_sync_whitespace_only_returns_false(tmp_path):
    """Trivial whitespace differences should not flag the dub as out-of-sync."""
    from src.api.routers.editor import _check_dub_sync_against_meta

    _save_meta(tmp_path, ["hello world", "foo bar"])
    is_out = _check_dub_sync_against_meta(
        data_dir=tmp_path, video_id="vid", language="vi",
        new_texts=["  hello world  ", "foo  bar"],
    )
    assert is_out is False


def test_check_dub_sync_segment_count_change_returns_true(tmp_path):
    from src.api.routers.editor import _check_dub_sync_against_meta

    _save_meta(tmp_path, ["a", "b", "c"])
    is_out = _check_dub_sync_against_meta(
        data_dir=tmp_path, video_id="vid", language="vi",
        new_texts=["a", "b", "c", "d"],
    )
    assert is_out is True
