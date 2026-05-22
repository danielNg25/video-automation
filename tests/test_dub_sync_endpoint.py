"""Tests for POST /api/videos/{id}/dub/sync and the sync_runner helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from src.tts.dub_meta import DubMeta


def _write_srt(path: Path, texts: list[str]) -> None:
    """Write a multi-segment SRT (one second apart, one text each)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    blocks = []
    for i, text in enumerate(texts, start=1):
        start_h, start_m, start_s = 0, 0, i - 1
        end_h, end_m, end_s = 0, 0, i
        blocks.append(
            f"{i}\n"
            f"{start_h:02d}:{start_m:02d}:{start_s:02d},000 --> "
            f"{end_h:02d}:{end_m:02d}:{end_s:02d},000\n"
            f"{text}\n"
        )
    path.write_text("\n".join(blocks) + "\n", encoding="utf-8")


def _make_client(tmp_path, monkeypatch, video_id: str = "vid001"):
    """Build a FastAPI TestClient with data_dir pointing into tmp_path and a
    registered video."""
    monkeypatch.chdir(tmp_path)
    from src.api import create_app
    from src.api.deps import get_task_manager
    from src.api.models import VideoResponse

    app = create_app()
    tm = get_task_manager()
    # Wipe any state lingering from earlier tests sharing the singleton.
    tm.video_index.clear()
    tm.tasks.clear()
    tm.video_index[video_id] = VideoResponse(
        video_id=video_id,
        title="t", duration=10.0, source_url="",
        thumbnail="", has_srt=True, srt_languages=["vi"],
        status="dubbed",
    )
    return TestClient(app)


# ───── Endpoint tests ────────────────────────────────────────────────────


class TestSyncDubEndpoint:
    def test_sync_dub_returns_task_id(self, tmp_path, monkeypatch):
        _write_srt(
            tmp_path / "data" / "srt" / "vid001_vi.srt",
            ["hello", "world"],
        )
        client = _make_client(tmp_path, monkeypatch)

        payload = {
            "language": "vi",
            "provider": "google",
            "voice_id": "vi-VN-Standard-A",
            "playback_speed": 1.5,
            "underlay_db": -18.0,
        }
        with patch(
            "src.tts.sync_runner.run_dub_sync", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = {"mode": "partial", "dirty_count": 1}
            r = client.post(
                "/api/videos/vid001/dub/sync", json=payload
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "task_id" in body
        assert body["status"] in ("queued", "running", "completed")

    def test_sync_dub_missing_video_returns_404(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        payload = {
            "language": "vi",
            "provider": "google",
            "voice_id": "any",
        }
        r = client.post(
            "/api/videos/nonexistent/dub/sync", json=payload
        )
        assert r.status_code == 404

    def test_sync_dub_missing_srt_returns_404(self, tmp_path, monkeypatch):
        client = _make_client(tmp_path, monkeypatch)
        payload = {
            "language": "es",  # language unlikely to exist
            "provider": "google",
            "voice_id": "any",
        }
        r = client.post(
            "/api/videos/vid001/dub/sync", json=payload
        )
        assert r.status_code == 404


# ───── identify_dirty_segments ──────────────────────────────────────────


class TestIdentifyDirtySegments:
    def test_no_change(self):
        from src.tts.sync_runner import identify_dirty_segments

        assert identify_dirty_segments(["a", "b"], ["a", "b"]) == []

    def test_text_change(self):
        from src.tts.sync_runner import identify_dirty_segments

        assert identify_dirty_segments(["a", "b"], ["a", "c"]) == [1]

    def test_whitespace_only_normalised(self):
        """_clean_text collapses whitespace, so these should not flag."""
        from src.tts.sync_runner import identify_dirty_segments

        assert identify_dirty_segments(["a b", "c"], ["a  b", "c"]) == []

    def test_length_mismatch_reports_all_indices(self):
        from src.tts.sync_runner import identify_dirty_segments

        # 3 vs 2 → max length 3, so [0, 1, 2]
        assert identify_dirty_segments(["a", "b", "c"], ["a", "b"]) == [0, 1, 2]


# ───── should_fall_back_to_full_regen ───────────────────────────────────


def _meta(texts: list[str], *, provider="google", voice="x",
          speed=1.5, underlay=-18.0) -> DubMeta:
    return DubMeta(
        video_id="v",
        language="vi",
        provider=provider,
        voice_id=voice,
        playback_speed=speed,
        underlay_db=underlay,
        segment_texts=texts,
    )


def _params(*, provider="google", voice="x", speed=1.5, underlay=-18.0) -> dict:
    return {
        "provider": provider,
        "voice_id": voice,
        "playback_speed": speed,
        "underlay_db": underlay,
    }


class TestShouldFallBackToFullRegen:
    def test_count_change(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b"]), _params(), ["a", "b", "c"]
        )
        assert should is True
        assert reason == "segment_count_changed"

    def test_provider_mismatch(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b"]),
            _params(provider="elevenlabs"),
            ["a", "b"],
        )
        assert should is True
        assert reason == "provider_mismatch"

    def test_voice_mismatch(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b"]),
            _params(voice="y"),
            ["a", "b"],
        )
        assert should is True
        assert reason == "voice_id_mismatch"

    def test_speed_mismatch(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b"]),
            _params(speed=2.0),
            ["a", "b"],
        )
        assert should is True
        assert reason == "playback_speed_mismatch"

    def test_underlay_mismatch(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b"]),
            _params(underlay=-12.0),
            ["a", "b"],
        )
        assert should is True
        assert reason == "underlay_db_mismatch"

    def test_majority_dirty(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        # 3 of 4 changed = 75% > 50% → majority_dirty
        should, reason = should_fall_back_to_full_regen(
            _meta(["a", "b", "c", "d"]),
            _params(),
            ["x", "y", "z", "d"],
        )
        assert should is True
        assert reason == "majority_dirty"

    def test_minority_dirty_does_not_fall_back(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        # 1 of 4 changed = 25% < 50% → partial path is fine.
        should, _ = should_fall_back_to_full_regen(
            _meta(["a", "b", "c", "d"]),
            _params(),
            ["x", "b", "c", "d"],
        )
        assert should is False

    def test_no_change_does_not_fall_back(self):
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, _ = should_fall_back_to_full_regen(
            _meta(["a", "b"]),
            _params(),
            ["a", "b"],
        )
        assert should is False

    def test_speed_within_tolerance_does_not_fall_back(self):
        """Tolerance is 0.01; 1.505 vs 1.5 should be accepted."""
        from src.tts.sync_runner import should_fall_back_to_full_regen

        should, _ = should_fall_back_to_full_regen(
            _meta(["a", "b"], speed=1.5),
            _params(speed=1.505),
            ["a", "b"],
        )
        assert should is False
