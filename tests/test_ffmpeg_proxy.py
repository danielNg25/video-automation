"""Tests for atomic proxy publication in FFmpegProcessor.generate_proxy."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def proc():
    # Skip the real ffmpeg/ffprobe availability check so the unit can run
    # without the binaries installed.
    mod = __import__("src.processor.ffmpeg", fromlist=["FFmpegProcessor"])
    with patch.object(mod.FFmpegProcessor, "_verify_ffmpeg", lambda self: None):
        yield mod.FFmpegProcessor()


def test_proxy_encodes_to_staging_not_final(proc, tmp_path):
    """ffmpeg must be told to write a temp path, never the final one — this is
    what makes the publish atomic (end-state alone wouldn't prove it)."""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "proxy.mp4"
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"encoded proxy")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with patch("src.processor.ffmpeg.subprocess.run", fake_run):
        result = proc.generate_proxy(src, out)

    assert result == out
    assert out.read_bytes() == b"encoded proxy"
    # ffmpeg's output arg (last) is a staging path, not the published file.
    assert seen["cmd"][-1] != str(out)
    assert seen["cmd"][-1].endswith(".part.mp4")
    assert not list(tmp_path.glob("*.part.mp4"))


def test_proxy_failure_preserves_existing_and_cleans_temp(proc, tmp_path):
    """A failed encode must not clobber an existing proxy, and must leave no
    staging file behind."""
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "proxy.mp4"
    out.write_bytes(b"GOOD EXISTING PROXY")

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_bytes(b"partial")  # ffmpeg wrote some of the temp
        return subprocess.CompletedProcess(cmd, 1, "", "boom")

    with patch("src.processor.ffmpeg.subprocess.run", fake_run):
        with pytest.raises(RuntimeError, match="Proxy generation failed"):
            proc.generate_proxy(src, out)

    assert out.read_bytes() == b"GOOD EXISTING PROXY"  # untouched
    assert not list(tmp_path.glob("*.part.mp4"))  # temp cleaned up
