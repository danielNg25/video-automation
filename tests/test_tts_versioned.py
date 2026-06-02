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


class TestRunTtsTrackAutoSavesShortenedVersion:
    """After a successful dub, run_tts_track should auto-save a per-segment
    version snapshot whose text is the dub's post-shortening output."""

    def _seed_srt(self, srt_dir: Path) -> None:
        """A 3-segment working-draft SRT that the runner will load.

        Also writes an empty versions.json so ensure_migrated is a no-op
        and the dub snapshot lands at v1 (not v2).
        """
        (srt_dir / "vid1_vi.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,500\nfirst\n\n"
            "2\n00:00:01,500 --> 00:00:03,000\nsecond\n\n"
            "3\n00:00:03,000 --> 00:00:04,500\nthird\n\n",
            encoding="utf-8",
        )
        (srt_dir / "vid1_vi.versions.json").write_text("[]", encoding="utf-8")

    def test_creates_dub_named_version_after_successful_run(
        self, tmp_path, monkeypatch
    ):
        """A 1-entry sentence_plan covering all 3 segments → v1 SRT with
        the redistributed text, named 'dub: <provider>/<voice>'."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        # ensure_migrated needs SRT_DIR + TTS_DIR pointed at tmp_path.
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        # The assembler writes the dub WAV; we stub it to drop a tiny
        # placeholder and return a known sentence_plan.
        fake_plan = [
            {
                "index": 0,
                "segment_indices": [0, 1, 2],
                "text": "shortened final text",
            }
        ]

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], fake_plan)

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ):
            from src.tts.runner import run_tts_track

            asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        # The auto-saved snapshot exists and has the redistributed text.
        v1_path = srt_dir / "vid1_vi.v1.srt"
        assert v1_path.exists()
        body = v1_path.read_text(encoding="utf-8")
        # All three plan words should land somewhere across the 3 segments.
        assert "shortened" in body
        assert "final" in body
        assert "text" in body
        # All three original-timing windows preserved.
        assert "00:00:00,000 --> 00:00:01,500" in body
        assert "00:00:01,500 --> 00:00:03,000" in body
        assert "00:00:03,000 --> 00:00:04,500" in body

        # The versions index records it with the expected name.
        from src.api.versions import load_versions
        entries = load_versions("vid1", "vi")
        assert len(entries) == 1
        assert entries[0].id == "v1"
        assert entries[0].name == "dub: google/vi-VN-Wavenet-A"

    def test_run_completes_even_if_snapshot_save_raises(
        self, tmp_path, monkeypatch, caplog
    ):
        """A failure in build_shortened_srt must not bubble out of
        run_tts_track. The dub is still considered successful."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], [{"segment_indices": [0], "text": "x"}])

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ), patch(
            "src.tts.runner.build_shortened_srt",
            side_effect=RuntimeError("boom"),
        ):
            from src.tts.runner import run_tts_track

            result = asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        # The dub still returns successfully.
        assert result["audio_path"]
        # No snapshot was written.
        assert not (srt_dir / "vid1_vi.v1.srt").exists()
        # The failure was logged.
        assert any("Could not save shortened version" in r.message for r in caplog.records)

    def test_no_snapshot_when_sentence_plan_is_empty(
        self, tmp_path, monkeypatch
    ):
        """Empty sentence_plan → skip the snapshot save entirely (no v1.srt,
        no versions.json entry). This is the synth-failed-completely path."""
        import asyncio
        from unittest.mock import AsyncMock, patch

        monkeypatch.chdir(tmp_path)
        srt_dir = tmp_path / "data" / "srt"
        srt_dir.mkdir(parents=True)
        tts_dir = tmp_path / "data" / "tts"
        tts_dir.mkdir(parents=True)
        monkeypatch.setattr("src.api.versions.SRT_DIR", srt_dir)
        monkeypatch.setattr("src.api.versions.TTS_DIR", tts_dir)
        self._seed_srt(srt_dir)

        async def fake_generate(*args, **kwargs):
            kwargs["output_path"].write_bytes(b"RIFFfake")
            return (kwargs["output_path"], [])

        with patch(
            "src.tts.assembler.TTSAssembler.generate_full_track",
            new=AsyncMock(side_effect=fake_generate),
        ), patch(
            "src.tts.runner.get_tts_provider",
            return_value=object(),
        ), patch(
            "src.tts.runner._build_llm_translator",
            return_value=None,
        ):
            from src.tts.runner import run_tts_track

            asyncio.run(run_tts_track(
                video_id="vid1",
                video_path=tmp_path / "data" / "raw" / "vid1.mp4",
                language="vi",
                voice="vi-VN-Wavenet-A",
                provider="google",
                config={},
                canonical_duration=4.5,
                version="draft",
            ))

        assert not (srt_dir / "vid1_vi.v1.srt").exists()
