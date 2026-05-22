"""Tests for the dub_status helper that powers VideoResponse.dub_status."""
from __future__ import annotations

_DUB_META_TEMPLATE = (
    '{{"video_id":"{vid}","language":"{lang}","provider":"google","voice_id":"x",'
    '"playback_speed":1.5,"underlay_db":-18.0,"segment_texts":[]}}'
)


def test_build_dub_status_no_tts_dir_returns_empty(tmp_path, monkeypatch):
    """When data/tts/{video_id}/ doesn't exist, return []."""
    monkeypatch.chdir(tmp_path)
    from src.api.task_manager import _build_dub_status

    result = _build_dub_status("nonexistent_video")
    assert result == []


def test_build_dub_status_with_meta_files(tmp_path, monkeypatch):
    """Returns one entry per dub_meta_*.json file, sorted by language."""
    monkeypatch.chdir(tmp_path)

    video_id = "vid123"
    tts_dir = tmp_path / "data" / "tts" / video_id
    tts_dir.mkdir(parents=True)
    (tts_dir / "dub_meta_vi.json").write_text(
        _DUB_META_TEMPLATE.format(vid=video_id, lang="vi"), encoding="utf-8"
    )
    (tts_dir / "dub_meta_en.json").write_text(
        _DUB_META_TEMPLATE.format(vid=video_id, lang="en"), encoding="utf-8"
    )

    from src.api.task_manager import _build_dub_status

    result = _build_dub_status(video_id)
    languages = [e["language"] for e in result]
    assert languages == ["en", "vi"]  # sorted alphabetically
    assert all("out_of_sync" in e for e in result)
    assert all("last_synced_at" in e for e in result)


def test_build_dub_status_flags_out_of_sync(tmp_path, monkeypatch):
    """When PipelineState lists a language as out-of-sync, the entry reflects it."""
    monkeypatch.chdir(tmp_path)

    video_id = "vid456"
    tts_dir = tmp_path / "data" / "tts" / video_id
    tts_dir.mkdir(parents=True)
    (tts_dir / "dub_meta_vi.json").write_text(
        _DUB_META_TEMPLATE.format(vid=video_id, lang="vi"), encoding="utf-8"
    )

    # Write state with vi flagged out-of-sync
    state_dir = tmp_path / "data" / "logs"
    state_dir.mkdir(parents=True)
    state_file = state_dir / f"{video_id}_state.json"
    state_file.write_text(
        '{"video_id":"vid456","completed_stages":[],"dub_out_of_sync_languages":["vi"]}',
        encoding="utf-8",
    )

    from src.api.task_manager import _build_dub_status

    result = _build_dub_status(video_id)
    assert len(result) == 1
    assert result[0]["language"] == "vi"
    assert result[0]["out_of_sync"] is True


def test_build_dub_status_default_in_sync(tmp_path, monkeypatch):
    """When PipelineState has no out-of-sync languages, all entries are out_of_sync=False."""
    monkeypatch.chdir(tmp_path)

    video_id = "vid789"
    tts_dir = tmp_path / "data" / "tts" / video_id
    tts_dir.mkdir(parents=True)
    (tts_dir / "dub_meta_vi.json").write_text(
        _DUB_META_TEMPLATE.format(vid=video_id, lang="vi"), encoding="utf-8"
    )

    from src.api.task_manager import _build_dub_status

    result = _build_dub_status(video_id)
    assert len(result) == 1
    assert result[0]["out_of_sync"] is False
