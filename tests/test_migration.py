"""Tests for ensure_migrated — legacy dub-sync layout → versions layout."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def fake_layout(tmp_path, monkeypatch):
    """Tmp data/srt and data/tts directories with helpers to seed files."""
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir()
    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
    monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)

    def seed_srt(name: str, content: str = "1\n00:00:00,000 --> 00:00:01,000\nhi\n"):
        (srt_dir / name).write_text(content)

    def seed_dub_wav(name: str):
        (tts_dir / name).write_bytes(b"RIFFfake")

    def seed_dub_meta(video_id: str, language: str):
        d = tts_dir / video_id
        d.mkdir(exist_ok=True)
        (d / f"dub_meta_{language}.json").write_text(
            json.dumps({"video_id": video_id, "language": language, "segment_texts": ["hi"]})
        )

    def seed_segments(video_id: str):
        d = tts_dir / video_id / "segments"
        d.mkdir(parents=True, exist_ok=True)
        (d / "0_google_voice.wav").write_bytes(b"RIFFseg")

    return {
        "srt_dir": srt_dir,
        "tts_dir": tts_dir,
        "seed_srt": seed_srt,
        "seed_dub_wav": seed_dub_wav,
        "seed_dub_meta": seed_dub_meta,
        "seed_segments": seed_segments,
    }


class TestEnsureMigrated:
    def test_brand_new_video_writes_empty_versions(self, fake_layout):
        """No SRT files at all → versions.json is [] and nothing else
        happens. Subsequent calls are a no-op."""
        from src.api.versions import ensure_migrated, load_versions

        ensure_migrated("newvid", "vi")
        assert load_versions("newvid", "vi") == []
        assert (fake_layout["srt_dir"] / "newvid_vi.versions.json").exists()

    def test_legacy_srt_only_becomes_v1(self, fake_layout):
        """{id}_{lang}.srt with no dubsync → v1 snapshot copies it."""
        from src.api.versions import ensure_migrated, load_versions

        fake_layout["seed_srt"]("vid1_vi.srt", "1\n00:00:00,000 --> 00:00:01,000\nA\n")
        ensure_migrated("vid1", "vi")
        entries = load_versions("vid1", "vi")
        assert len(entries) == 1
        assert entries[0].id == "v1"
        assert entries[0].name == "migrated"
        # v1 SRT exists with the same content.
        v1 = fake_layout["srt_dir"] / "vid1_vi.v1.srt"
        assert v1.exists()
        assert "A" in v1.read_text()
        # Working draft is unchanged.
        wd = fake_layout["srt_dir"] / "vid1_vi.srt"
        assert wd.exists()
        assert "A" in wd.read_text()

    def test_dubsync_present_becomes_v1_and_working_draft(self, fake_layout):
        """When dubsync.srt exists, it is the source of truth — v1 AND the
        working draft come from it. The legacy .srt (if any) is overwritten.
        The dubsync.srt is deleted."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid2_vi.srt", "OLD legacy timings")
        fake_layout["seed_srt"]("vid2_vi.dubsync.srt", "NEW dubsync timings")
        ensure_migrated("vid2", "vi")
        v1 = fake_layout["srt_dir"] / "vid2_vi.v1.srt"
        wd = fake_layout["srt_dir"] / "vid2_vi.srt"
        dubsync = fake_layout["srt_dir"] / "vid2_vi.dubsync.srt"
        assert "NEW dubsync timings" in v1.read_text()
        assert "NEW dubsync timings" in wd.read_text()
        assert not dubsync.exists()

    def test_existing_dub_wavs_get_v1_infix(self, fake_layout):
        """{id}_{lang}_{provider}_{voice}.wav → {id}_{lang}_v1_{provider}_{voice}.wav."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid3_vi.srt", "x")
        fake_layout["seed_dub_wav"]("vid3_vi_google_wavenet-A.wav")
        ensure_migrated("vid3", "vi")
        tts = fake_layout["tts_dir"]
        assert (tts / "vid3_vi_v1_google_wavenet-A.wav").exists()
        assert not (tts / "vid3_vi_google_wavenet-A.wav").exists()

    def test_already_versioned_wavs_are_left_alone(self, fake_layout):
        """A WAV that already has v{N} or 'draft' in the version slot is
        not double-prefixed."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid4_vi.srt", "x")
        fake_layout["seed_dub_wav"]("vid4_vi_v2_google_wavenet-A.wav")
        ensure_migrated("vid4", "vi")
        tts = fake_layout["tts_dir"]
        assert (tts / "vid4_vi_v2_google_wavenet-A.wav").exists()
        # Should NOT have been turned into vid4_vi_v1_v2_google_wavenet-A.wav.
        assert not (tts / "vid4_vi_v1_v2_google_wavenet-A.wav").exists()

    def test_dub_meta_and_segments_directory_are_deleted(self, fake_layout):
        """dub_meta_{lang}.json and {id}/segments/ both go away."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid5_vi.srt", "x")
        fake_layout["seed_dub_meta"]("vid5", "vi")
        fake_layout["seed_segments"]("vid5")
        ensure_migrated("vid5", "vi")
        tts = fake_layout["tts_dir"]
        assert not (tts / "vid5" / "dub_meta_vi.json").exists()
        assert not (tts / "vid5" / "segments").exists()

    def test_idempotent_second_call_is_noop(self, fake_layout):
        """Once versions.json exists, ensure_migrated returns without doing
        anything (even if other legacy files remain)."""
        from src.api.versions import ensure_migrated

        fake_layout["seed_srt"]("vid6_vi.srt", "x")
        ensure_migrated("vid6", "vi")
        # Manually create a dubsync.srt AFTER migration to verify it's
        # NOT picked up on the second call.
        (fake_layout["srt_dir"] / "vid6_vi.dubsync.srt").write_text("ghost")
        ensure_migrated("vid6", "vi")
        # The dubsync.srt should still be there — second call didn't touch it.
        assert (fake_layout["srt_dir"] / "vid6_vi.dubsync.srt").exists()
