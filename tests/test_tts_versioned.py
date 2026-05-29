"""Tests for version-aware dub WAV output naming."""

from __future__ import annotations

from pathlib import Path


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
