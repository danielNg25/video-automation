"""translate_with_profile stages to a temp file and only publishes when not
cancelled, so a cancel can't overwrite an existing translated SRT."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.translator import translate_with_profile
from src.translator.profiles import TranslationProfile


class _FakeTranslator:
    async def translate_srt(self, srt_path, profile, output_path, progress_callback=None):
        Path(output_path).write_text("1\n00:00:00,000 --> 00:00:01,000\nxin chao\n")
        return output_path


@pytest.fixture
def patched(monkeypatch):
    import src.translator as T

    monkeypatch.setattr(T, "get_translator", lambda config: _FakeTranslator())
    monkeypatch.setattr(
        T,
        "load_profile",
        lambda name: TranslationProfile(
            name=name, description="", style_guide="", target_language="vi", source_language="zh"
        ),
    )


async def test_translate_cancel_does_not_publish(patched, tmp_path):
    (tmp_path / "vid_zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n")
    (tmp_path / "vid_vi.srt").write_text("EXISTING VI")  # must survive a cancel

    out = await translate_with_profile(
        tmp_path / "vid_zh.srt", "p", {}, tmp_path, should_cancel=lambda: True
    )

    assert out is None
    assert (tmp_path / "vid_vi.srt").read_text() == "EXISTING VI"  # untouched
    assert not list(tmp_path.glob("*.tmp.srt"))  # temp cleaned up


async def test_translate_publishes_when_not_cancelled(patched, tmp_path):
    (tmp_path / "vid_zh.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n")

    out = await translate_with_profile(
        tmp_path / "vid_zh.srt", "p", {}, tmp_path, should_cancel=lambda: False
    )

    assert out == tmp_path / "vid_vi.srt"
    assert "xin chao" in (tmp_path / "vid_vi.srt").read_text()
    assert not list(tmp_path.glob("*.tmp.srt"))
