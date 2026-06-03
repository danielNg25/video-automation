"""Unit tests for the translator's __SKIP__ noise-removal flow.

skip_noise=True (default): the system prompt instructs the LLM to
mark OCR noise (watermarks, handles, etc.) as the literal __SKIP__.
The post-parse filter drops those segments entirely from the output
SRT — surrounding segments keep their original timings.

skip_noise=False: the prompt is unchanged and no filtering happens.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.processor.subtitle import parse_srt, write_srt
from src.translator.llm import LLMTranslator
from src.translator.profiles import TranslationProfile


def _profile() -> TranslationProfile:
    return TranslationProfile(
        name="test",
        description="",
        target_language="vi",
        source_language="zh",
        style_guide="Be casual.",
        example_pairs=[],
    )


class TestSkipInstructionInPrompt:
    def test_skip_instruction_appended_when_flag_on(self):
        t = LLMTranslator(skip_noise=True, api_key="x")
        prompt = t._build_system_prompt(_profile())
        assert "__SKIP__" in prompt
        assert "watermark" in prompt.lower() or "handle" in prompt.lower()

    def test_skip_instruction_omitted_when_flag_off(self):
        t = LLMTranslator(skip_noise=False, api_key="x")
        prompt = t._build_system_prompt(_profile())
        assert "__SKIP__" not in prompt


class TestSkipFiltering:
    @pytest.mark.asyncio
    async def test_translate_srt_drops_skip_segments(self, tmp_path: Path):
        """5-segment SRT, LLM marks segments 2 and 4 as __SKIP__ → output
        SRT contains only segments 1, 3, 5 with their original timings."""
        src = tmp_path / "in.srt"
        write_srt(
            [
                {"start": 0.0, "end": 1.0, "text": "real one"},
                {"start": 1.0, "end": 2.0, "text": "@channel_handle"},
                {"start": 2.0, "end": 3.0, "text": "real three"},
                {"start": 3.0, "end": 4.0, "text": "watermark text"},
                {"start": 4.0, "end": 5.0, "text": "real five"},
            ],
            src,
        )
        out = tmp_path / "out.srt"
        t = LLMTranslator(skip_noise=True, api_key="x")

        # The LLM's full-document response format is "N. translated text"
        # per non-empty input line. Mark lines 2 and 4 as __SKIP__.
        llm_response = (
            "1. translated one\n"
            "2. __SKIP__\n"
            "3. translated three\n"
            "4. __SKIP__\n"
            "5. translated five\n"
        )

        with patch.object(t, "_call_llm", new=AsyncMock(return_value=llm_response)):
            await t.translate_srt(src, _profile(), out)

        result = parse_srt(out)
        assert len(result) == 3
        assert result[0]["text"] == "translated one"
        assert result[0]["start"] == 0.0 and result[0]["end"] == 1.0
        assert result[1]["text"] == "translated three"
        assert result[1]["start"] == 2.0 and result[1]["end"] == 3.0
        assert result[2]["text"] == "translated five"
        assert result[2]["start"] == 4.0 and result[2]["end"] == 5.0

    @pytest.mark.asyncio
    async def test_skip_marker_substring_in_real_translation_kept(self, tmp_path: Path):
        """If the LLM accidentally embeds '__SKIP__' inside a real
        translation, the exact-match filter does NOT drop the row."""
        src = tmp_path / "in.srt"
        write_srt(
            [
                {"start": 0.0, "end": 1.0, "text": "hi"},
                {"start": 1.0, "end": 2.0, "text": "bye"},
            ],
            src,
        )
        out = tmp_path / "out.srt"
        t = LLMTranslator(skip_noise=True, api_key="x")

        llm_response = (
            "1. this is __SKIP__ adjacent text\n"
            "2. translated bye\n"
        )

        with patch.object(t, "_call_llm", new=AsyncMock(return_value=llm_response)):
            await t.translate_srt(src, _profile(), out)

        result = parse_srt(out)
        assert len(result) == 2
        assert "__SKIP__" in result[0]["text"]
        assert result[1]["text"] == "translated bye"
