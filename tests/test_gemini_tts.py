"""Unit tests for the Gemini TTS provider.

GeminiTTSProvider calls generativelanguage.googleapis.com/v1beta/models/
{model}:generateContent with responseModalities=AUDIO, parses the
base64 PCM from candidates[0].content.parts[0].inlineData.data, and
wraps the raw PCM into a WAV container (24 kHz mono s16le) so the
assembler reads it through ffmpeg like any other provider's output.
"""

from __future__ import annotations

import base64
import struct
from unittest.mock import AsyncMock, patch

import pytest

from src.tts.gemini_tts import GeminiTTSProvider


class TestVoices:
    @pytest.mark.asyncio
    async def test_voices_static_list(self):
        p = GeminiTTSProvider({"gemini_api_key": "x"})
        voices = await p.list_voices()
        assert len(voices) == len(GeminiTTSProvider.VOICES)
        for v in voices:
            assert v["provider"] == "gemini"
            assert v["gender"] == "neutral"
            assert v["language"] == ""
            assert v["name"] == v["friendly_name"]
            assert v["name"] in GeminiTTSProvider.VOICES

    @pytest.mark.asyncio
    async def test_voices_ignores_language_filter(self):
        p = GeminiTTSProvider({"gemini_api_key": "x"})
        all_voices = await p.list_voices(language=None)
        vi_voices = await p.list_voices(language="vi")
        assert len(all_voices) == len(vi_voices)


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_no_api_key_raises(self):
        p = GeminiTTSProvider({})
        with pytest.raises(ValueError, match="Gemini API key not configured"):
            await p.synthesize("hello", "Kore")

    @pytest.mark.asyncio
    async def test_synthesize_happy_path_wraps_pcm_to_wav(self):
        # Fake PCM payload: 100 bytes of silence.
        pcm = b"\x00" * 100
        response_json = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"data": base64.b64encode(pcm).decode()}}
                        ]
                    }
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: response_json

        config = {
            "gemini_api_key": "k",
            "gemini_model": "gemini-2.5-flash-preview-tts",
        }
        p = GeminiTTSProvider(config)

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            result = await p.synthesize("hello", "Kore")

        # WAV header: RIFF...WAVE...fmt ...data + PCM
        assert result[:4] == b"RIFF"
        assert result[8:12] == b"WAVE"
        # File size in bytes (header[4:8]) = total length - 8
        assert struct.unpack("<I", result[4:8])[0] == len(result) - 8
        # Sample rate at offset 24 = 24000
        assert struct.unpack("<I", result[24:28])[0] == 24000
        # Channels at offset 22 = 1
        assert struct.unpack("<H", result[22:24])[0] == 1
        # Bits-per-sample at offset 34 = 16
        assert struct.unpack("<H", result[34:36])[0] == 16
        # Data chunk size at offset 40 = len(pcm)
        assert struct.unpack("<I", result[40:44])[0] == len(pcm)
        # PCM follows the 44-byte header
        assert result[44:] == pcm

    @pytest.mark.asyncio
    async def test_synthesize_empty_inlinedata_raises(self):
        response_json = {"candidates": [{"content": {"parts": [{}]}}]}
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: response_json

        p = GeminiTTSProvider({"gemini_api_key": "k"})
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(RuntimeError, match="empty audio"):
                await p.synthesize("hello", "Kore")
