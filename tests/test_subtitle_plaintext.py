"""Unit tests for srt_segments_to_text (plain-text subtitle export) +
the /api/videos/{id}/srt/download?fmt=txt endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.processor.subtitle import srt_segments_to_text


class TestSrtSegmentsToText:
    def test_one_segment_per_line(self):
        segs = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "Xin chào"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "các bạn"},
        ]
        assert srt_segments_to_text(segs) == "Xin chào\ncác bạn"

    def test_no_trailing_newline(self):
        segs = [{"index": 1, "start": 0.0, "end": 1.0, "text": "hello"}]
        assert srt_segments_to_text(segs) == "hello"

    def test_internal_newlines_collapse_to_space(self):
        segs = [{"index": 1, "start": 0.0, "end": 1.0, "text": "line one\nline two"}]
        assert srt_segments_to_text(segs) == "line one line two"

    def test_repeated_whitespace_collapses(self):
        segs = [{"index": 1, "start": 0.0, "end": 1.0, "text": "  a   b  "}]
        assert srt_segments_to_text(segs) == "a b"

    def test_empty_segments_skipped(self):
        segs = [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "keep"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "   "},
            {"index": 3, "start": 2.0, "end": 3.0, "text": "also keep"},
        ]
        assert srt_segments_to_text(segs) == "keep\nalso keep"

    def test_empty_input(self):
        assert srt_segments_to_text([]) == ""


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from src.api import create_app

    return TestClient(create_app())


def _write_srt(tmp_path, video_id: str, language: str, body: str):
    srt_dir = tmp_path / "srt"
    srt_dir.mkdir(parents=True, exist_ok=True)
    (srt_dir / f"{video_id}_{language}.srt").write_text(body, encoding="utf-8")


def test_download_txt_returns_plain_lines(client, tmp_path, monkeypatch):
    # The endpoint resolves SRT via src.api.versions.SRT_DIR; point it at tmp.
    from src.api import versions

    monkeypatch.setattr(versions, "SRT_DIR", tmp_path / "srt")
    _write_srt(
        tmp_path,
        "vid1",
        "vi",
        "1\n00:00:00,000 --> 00:00:01,000\nXin chào\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\ncác bạn\n",
    )

    r = client.get("/api/videos/vid1/srt/download", params={"language": "vi", "fmt": "txt"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/plain")
    assert "00:00:00" not in r.text  # no timestamps
    assert r.text == "Xin chào\ncác bạn"
    # filename should be a .txt
    assert ".txt" in r.headers.get("content-disposition", "")


def test_download_srt_still_serves_srt(client, tmp_path, monkeypatch):
    from src.api import versions

    monkeypatch.setattr(versions, "SRT_DIR", tmp_path / "srt")
    _write_srt(
        tmp_path,
        "vid1",
        "vi",
        "1\n00:00:00,000 --> 00:00:01,000\nXin chào\n",
    )

    r = client.get("/api/videos/vid1/srt/download", params={"language": "vi"})
    assert r.status_code == 200, r.text
    assert "00:00:00,000 --> 00:00:01,000" in r.text  # raw SRT preserved
    assert ".srt" in r.headers.get("content-disposition", "")
