"""Tests for OCR cancellation via the injected should_cancel callback, and
the transcriber→API decoupling."""

from __future__ import annotations

import inspect

from src.transcriber.ocr import OCRTranscriber


def test_transcribe_stops_when_should_cancel(monkeypatch, tmp_path):
    """The loop polls should_cancel() and returns partial results early."""
    calls = {"ocr": 0}

    def fake_should_cancel():
        # cancel as soon as one frame has been OCR'd
        return calls["ocr"] >= 1

    t = OCRTranscriber(fps=2.0, crop_bottom_pct=0.0, should_cancel=fake_should_cancel)

    def fake_ocr(path):
        calls["ocr"] += 1
        return ([], 0.0)

    monkeypatch.setattr(t, "_get_ocr", lambda lang="ch": fake_ocr)

    from src.processor import ffmpeg as ff

    monkeypatch.setattr(ff.FFmpegProcessor, "_verify_ffmpeg", lambda self: None)
    monkeypatch.setattr(
        ff.FFmpegProcessor, "get_video_info", lambda self, p: {"height": 1920, "width": 1080}
    )
    frames = [tmp_path / f"f{i}.jpg" for i in range(10)]
    for f in frames:
        f.write_bytes(b"x")
    monkeypatch.setattr(
        ff.FFmpegProcessor,
        "extract_frames",
        lambda self, vp, od, fps=2.0, crop_bottom_pct=0.0: frames,
    )

    segs = t.transcribe("video.mp4", "zh", "transcribe")

    # Frame 0 is OCR'd; the check at the top of frame 1 sees the cancel.
    assert calls["ocr"] == 1
    assert isinstance(segs, list)


def test_no_cancel_processes_all_frames(monkeypatch, tmp_path):
    calls = {"ocr": 0}
    t = OCRTranscriber(fps=2.0, crop_bottom_pct=0.0, should_cancel=None)

    def fake_ocr(path):
        calls["ocr"] += 1
        return ([], 0.0)

    monkeypatch.setattr(t, "_get_ocr", lambda lang="ch": fake_ocr)
    from src.processor import ffmpeg as ff

    monkeypatch.setattr(ff.FFmpegProcessor, "_verify_ffmpeg", lambda self: None)
    monkeypatch.setattr(
        ff.FFmpegProcessor, "get_video_info", lambda self, p: {"height": 1920, "width": 1080}
    )
    frames = [tmp_path / f"f{i}.jpg" for i in range(5)]
    for f in frames:
        f.write_bytes(b"x")
    monkeypatch.setattr(
        ff.FFmpegProcessor,
        "extract_frames",
        lambda self, vp, od, fps=2.0, crop_bottom_pct=0.0: frames,
    )

    t.transcribe("video.mp4", "zh", "transcribe")
    assert calls["ocr"] == 5


def test_transcriber_does_not_import_api():
    """Layering: the transcriber must not reach back into src.api."""
    src = inspect.getsource(__import__("src.transcriber.ocr", fromlist=["x"]))
    assert "get_task_manager_instance" not in src
    assert "from src.api" not in src
    assert "import src.api" not in src
