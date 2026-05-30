"""Integration tests for Phase 5: pipeline, state, retry, dedup, CLI, metadata mapper."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Retry utility tests ──


class TestRetryDecorator:
    def test_succeeds_without_retry(self):
        from src.utils.retry import retry

        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retry_on=(ConnectionError,))
        def fn():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert fn() == "ok"
        assert call_count == 1

    def test_retries_on_matching_exception(self):
        from src.utils.retry import retry

        call_count = 0

        @retry(max_attempts=3, base_delay=0.01, retry_on=(ConnectionError,))
        def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("fail")
            return "success"

        assert fn() == "success"
        assert call_count == 3

    def test_raises_after_max_attempts(self):
        from src.utils.retry import retry

        @retry(max_attempts=2, base_delay=0.01, retry_on=(ValueError,))
        def fn():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            fn()

    def test_does_not_retry_on_non_matching_exception(self):
        from src.utils.retry import retry

        @retry(max_attempts=3, base_delay=0.01, retry_on=(ConnectionError,))
        def fn():
            raise TypeError("not retryable")

        with pytest.raises(TypeError):
            fn()


class TestAsyncRetry:
    def test_async_retry_succeeds(self):
        from src.utils.retry import async_retry

        call_count = 0

        @async_retry(max_attempts=3, base_delay=0.01, retry_on=(ConnectionError,))
        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("fail")
            return "ok"

        result = asyncio.get_event_loop().run_until_complete(fn())
        assert result == "ok"
        assert call_count == 2


# ── State persistence tests ──


class TestPipelineState:
    def setup_method(self):
        self._orig_logs = Path("data/logs")
        self._tmpdir = tempfile.mkdtemp()
        # Patch LOGS_DIR to use temp directory
        import src.utils.state as state_mod

        self._orig_dir = state_mod.LOGS_DIR
        self._orig_reg = state_mod.REGISTRY_PATH
        state_mod.LOGS_DIR = Path(self._tmpdir)
        state_mod.REGISTRY_PATH = Path(self._tmpdir) / "processed_videos.json"

    def teardown_method(self):
        import src.utils.state as state_mod

        state_mod.LOGS_DIR = self._orig_dir
        state_mod.REGISTRY_PATH = self._orig_reg
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_and_save(self):
        from src.utils.state import PipelineState

        state = PipelineState(video_id="test1", url="https://example.com")
        state.save()

        state_file = Path(self._tmpdir) / "test1_state.json"
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert data["video_id"] == "test1"
        assert data["status"] == "pending"

    def test_load_existing(self):
        from src.utils.state import PipelineState

        state = PipelineState(video_id="test2", url="https://example.com")
        state.mark_stage_start("download")
        state.mark_stage_complete("download", {"file": "test.mp4"})

        loaded = PipelineState.load("test2")
        assert loaded.video_id == "test2"
        assert "download" in loaded.completed_stages
        assert loaded.stage_results["download"]["file"] == "test.mp4"

    def test_load_missing_returns_fresh(self):
        from src.utils.state import PipelineState

        state = PipelineState.load("nonexistent")
        assert state.video_id == "nonexistent"
        assert state.status == "pending"
        assert state.completed_stages == []

    def test_get_resume_stage(self):
        from src.utils.state import PipelineState

        state = PipelineState(video_id="test3")
        assert state.get_resume_stage() == "download"

        state.mark_stage_complete("download")
        assert state.get_resume_stage() == "transcribe"

        state.mark_stage_complete("transcribe")
        assert state.get_resume_stage() == "translate"

    def test_is_complete(self):
        from src.utils.state import PipelineState

        state = PipelineState(video_id="test4")
        assert not state.is_complete()

        state.mark_done()
        assert state.is_complete()

    def test_mark_failed(self):
        from src.utils.state import PipelineState

        state = PipelineState(video_id="test5")
        state.mark_failed("something broke")
        assert state.status == "failed"
        assert state.error == "something broke"


# ── Duplicate detection tests ──


class TestDuplicateDetection:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        import src.utils.state as state_mod

        self._orig_dir = state_mod.LOGS_DIR
        self._orig_reg = state_mod.REGISTRY_PATH
        state_mod.LOGS_DIR = Path(self._tmpdir)
        state_mod.REGISTRY_PATH = Path(self._tmpdir) / "processed_videos.json"

    def teardown_method(self):
        import src.utils.state as state_mod

        state_mod.LOGS_DIR = self._orig_dir
        state_mod.REGISTRY_PATH = self._orig_reg
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_not_duplicate_initially(self):
        from src.utils.state import is_duplicate

        assert not is_duplicate("vid1")

    def test_is_duplicate_after_register(self):
        from src.utils.state import is_duplicate, register_processed

        register_processed("vid1", {"url": "https://douyin.com/v1", "platforms": ["youtube"]})
        assert is_duplicate("vid1")

    def test_url_based_dedup(self):
        from src.utils.state import is_duplicate, register_processed

        register_processed("vid2", {"url": "https://v.douyin.com/abc123/", "platforms": []})
        # Same URL without trailing slash
        assert is_duplicate("other_id", url="https://v.douyin.com/abc123")

    def test_url_normalization_strips_query_params(self):
        from src.utils.state import is_duplicate, register_processed

        register_processed("vid3", {"url": "https://v.douyin.com/xyz?utm_source=share", "platforms": []})
        assert is_duplicate("other", url="https://v.douyin.com/xyz")

    def test_get_all_states(self):
        from src.utils.state import PipelineState, get_all_states

        PipelineState(video_id="a1", url="url1").save()
        PipelineState(video_id="a2", url="url2").save()

        states = get_all_states()
        assert len(states) == 2
        ids = {s["video_id"] for s in states}
        assert ids == {"a1", "a2"}


# ── Metadata mapper tests ──


class TestMetadataMapper:
    def test_youtube_adds_shorts_for_short_video(self):
        from src.utils.metadata import VideoMetadata, map_metadata

        meta = VideoMetadata(video_id="1", title="Cool Vid", duration=30.0)
        result = map_metadata(meta, "youtube")
        assert "#Shorts" in result["title"]

    def test_youtube_no_shorts_for_long_video(self):
        from src.utils.metadata import VideoMetadata, map_metadata

        meta = VideoMetadata(video_id="1", title="Long Vid", duration=300.0)
        result = map_metadata(meta, "youtube")
        assert "#Shorts" not in result["title"]

    def test_tiktok_hashtags_in_description(self):
        from src.utils.metadata import VideoMetadata, map_metadata

        meta = VideoMetadata(video_id="1", description="Check this", hashtags=["viral", "fun"])
        result = map_metadata(meta, "tiktok")
        assert "#viral" in result["description"]
        assert "#fun" in result["description"]

    def test_x_truncates_title(self):
        from src.utils.metadata import VideoMetadata, map_metadata

        meta = VideoMetadata(video_id="1", title="A" * 300)
        result = map_metadata(meta, "x")
        assert len(result["title"]) == 280
        assert result["title"].endswith("\u2026")

    def test_overrides_applied(self):
        from src.utils.metadata import VideoMetadata, map_metadata

        meta = VideoMetadata(video_id="1", title="Original")
        result = map_metadata(meta, "facebook", overrides={"title": "Custom Title"})
        assert result["title"] == "Custom Title"

    def test_dict_input(self):
        from src.utils.metadata import map_metadata

        result = map_metadata(
            {"title": "Dict Title", "hashtags": [], "duration": 10},
            "youtube",
        )
        assert "Dict Title" in result["title"]


# ── Pipeline orchestrator tests (mocked) ──


class TestPipelineOrchestrator:
    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        import src.utils.state as state_mod

        self._orig_dir = state_mod.LOGS_DIR
        self._orig_reg = state_mod.REGISTRY_PATH
        state_mod.LOGS_DIR = Path(self._tmpdir)
        state_mod.REGISTRY_PATH = Path(self._tmpdir) / "processed_videos.json"

    def teardown_method(self):
        import src.utils.state as state_mod

        state_mod.LOGS_DIR = self._orig_dir
        state_mod.REGISTRY_PATH = self._orig_reg
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_skips_duplicate(self):
        from src.pipeline import Pipeline
        from src.utils.state import register_processed

        register_processed("vid123", {"url": "https://v.douyin.com/vid123", "platforms": ["youtube"]})

        pipeline = Pipeline(config={})
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.process_single(
                "https://v.douyin.com/vid123",
                {"video_id": "vid123"},
            )
        )
        assert result["status"] == "skipped"

    def test_force_ignores_duplicate(self):
        from src.pipeline import Pipeline
        from src.utils.metadata import VideoMetadata
        from src.utils.state import register_processed

        register_processed("vid456", {"url": "https://v.douyin.com/vid456", "platforms": []})

        mock_meta = VideoMetadata(
            video_id="vid456",
            title="Test",
            file_path="/tmp/test.mp4",
        )

        with patch("src.downloader.download_with_fallback", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = mock_meta

            pipeline = Pipeline(config={"ocr": {}})
            # Will fail at transcribe since we're not mocking it, but it should
            # get past the duplicate check
            result = asyncio.get_event_loop().run_until_complete(
                pipeline.process_single(
                    "https://v.douyin.com/vid456",
                    {"video_id": "vid456", "force": True},
                )
            )
            # Either succeeds or fails at a later stage — but not "skipped"
            assert result["status"] != "skipped"


# ── CLI argument parsing tests ──


class TestCLI:
    def test_main_help(self):
        from click.testing import CliRunner

        from src.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Douyin Video Repurposing Pipeline" in result.output
        assert "process" in result.output
        assert "download" in result.output
        assert "batch" in result.output
        assert "status" in result.output

    def test_process_help(self):
        from click.testing import CliRunner

        from src.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["process", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output
        assert "--subtitle-lang" in result.output

    def test_batch_help(self):
        from click.testing import CliRunner

        from src.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["batch", "--help"])
        assert result.exit_code == 0
        assert "--concurrency" in result.output
        assert "URL_FILE" in result.output

    def test_status_no_args(self):
        from click.testing import CliRunner

        from src.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 0

    def test_version(self):
        from click.testing import CliRunner

        from src.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output


# ── Structured logging tests ──


class TestStructuredLogging:
    def test_json_formatter(self):
        from src.utils.logger import JSONFormatter

        import logging

        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        record.video_id = "vid789"
        record.stage = "download"

        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "test message"
        assert data["video_id"] == "vid789"
        assert data["stage"] == "download"
        assert "timestamp" in data

    def test_setup_logger_creates_logger(self):
        from src.utils.logger import setup_logger

        logger = setup_logger("test_phase5")
        assert logger.name == "test_phase5"
        assert len(logger.handlers) > 0

    def test_video_logger_injects_video_id(self):
        from src.utils.logger import get_video_logger

        vlogger = get_video_logger("test_vid_log")
        # Check the filter
        filters = vlogger.filters
        assert any(hasattr(f, "filter") for f in filters)
