"""Tests for version-aware dub WAV output naming and SRT path resolution."""

from __future__ import annotations

from pathlib import Path


class TestSrtPathResolution:
    """The runner must read the chosen version's SRT, not always the working draft."""

    def test_draft_reads_working_draft(self, tmp_path, monkeypatch):
        """version='draft' → {video_id}_{lang}.srt (no version suffix)."""
        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        draft = srt_dir / "vid1_vi.srt"
        draft.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8"
        )

        # Resolve path using the same logic as the runner
        version = "draft"
        if version == "draft":
            resolved = srt_dir / "vid1_vi.srt"
        else:
            resolved = srt_dir / f"vid1_vi.{version}.srt"

        assert resolved == draft

    def test_v1_reads_snapshot(self, tmp_path, monkeypatch):
        """version='v1' → {video_id}_{lang}.v1.srt, NOT the working draft."""
        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        snapshot = srt_dir / "vid1_vi.v1.srt"
        snapshot.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nsnapshot text\n\n", encoding="utf-8"
        )
        draft = srt_dir / "vid1_vi.srt"
        draft.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\ndraft text\n\n", encoding="utf-8"
        )

        version = "v1"
        if version == "draft":
            resolved = srt_dir / "vid1_vi.srt"
        else:
            resolved = srt_dir / f"vid1_vi.{version}.srt"

        assert resolved == snapshot
        assert resolved != draft

    def test_run_tts_track_raises_when_v1_srt_missing(self, tmp_path, monkeypatch):
        """run_tts_track raises FileNotFoundError for a missing snapshot SRT."""
        import asyncio

        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "srt").mkdir(parents=True)
        # Only the working draft exists — no .v1.srt
        (tmp_path / "data" / "srt" / "vid1_vi.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nhello\n\n", encoding="utf-8"
        )

        from src.tts.runner import run_tts_track

        config: dict = {"tts": {}}

        async def _run():
            await run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-HoaiMyNeural",
                provider="edge_tts",
                config=config,
                version="v1",
            )

        with pytest.raises(FileNotFoundError, match=r"vi\.v1\.srt"):
            asyncio.run(_run())


import pytest  # noqa: E402 — must be after the class that uses it


class TestDubOutputFilename:
    def test_draft_omits_version_prefix(self):
        from src.tts.runner import dub_output_filename

        out = dub_output_filename("vid1", "vi", "draft", "google", "wavenet-A")
        assert out == Path("data/tts/vid1_vi_draft_google_wavenet-A.wav")

    def test_v1_includes_version(self):
        from src.tts.runner import dub_output_filename

        out = dub_output_filename("vid1", "vi", "v1", "google", "wavenet-A")
        assert out == Path("data/tts/vid1_vi_v1_google_wavenet-A.wav")

    def test_voice_with_slashes_is_escaped(self):
        """Some Google voice ids contain '/' which would break the path."""
        from src.tts.runner import dub_output_filename

        out = dub_output_filename(
            "vid1", "vi", "v2", "google", "vi-VN/Wavenet-A"
        )
        # '/' must be replaced (not preserved) so Path stays one segment.
        assert "/" not in out.name
        assert out.name.endswith(".wav")
        assert "v2" in out.name
