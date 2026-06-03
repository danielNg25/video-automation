"""Google Gemini TTS provider — uses the Generative Language Audio API."""

from __future__ import annotations

import base64
import struct

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _wrap_pcm_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit PCM bytes in a minimal RIFF/WAVE header.

    Gemini returns 24 kHz mono signed 16-bit little-endian PCM. The
    assembler reads everything through ffmpeg, which is happy to consume
    a WAV but won't recognise headerless PCM. This 44-byte prefix is the
    standard PCM/WAVE header.
    """
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm)
    fmt_chunk_size = 16
    riff_size = 4 + (8 + fmt_chunk_size) + (8 + data_size)

    header = b"".join([
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", fmt_chunk_size),
        struct.pack("<H", 1),              # PCM format
        struct.pack("<H", channels),
        struct.pack("<I", sample_rate),
        struct.pack("<I", byte_rate),
        struct.pack("<H", block_align),
        struct.pack("<H", 16),             # bits per sample
        b"data",
        struct.pack("<I", data_size),
    ])
    return header + pcm


class GeminiTTSProvider(BaseTTSProvider):
    """TTS provider using Google's Gemini Audio Generation API.

    Distinct from `GoogleTTSProvider`, which calls the legacy Cloud TTS
    endpoint. Gemini takes an explicit model ID per request and a
    prebuilt voice name from a small static set; output is 24 kHz mono
    PCM that we wrap into a WAV container in-memory.
    """

    DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    # Prebuilt voice names from the Gemini docs. Not language-locked.
    VOICES: tuple[str, ...] = (
        "Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus",
        "Zephyr", "Achernar", "Algenib", "Algieba", "Alnilam", "Autonoe",
        "Callirrhoe", "Despina", "Enceladus", "Erinome", "Gacrux",
        "Iapetus", "Laomedeia", "Pulcherrima", "Rasalgethi", "Sadachbia",
        "Sadaltager", "Schedar", "Sulafat", "Umbriel", "Vindemiatrix",
        "Zubenelgenubi",
    )

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key: str = config.get("gemini_api_key", "")
        self.model: str = config.get("gemini_model", self.DEFAULT_MODEL)

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        if not self.api_key:
            raise ValueError("Gemini API key not configured for TTS")

        body = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice}
                    }
                },
            },
        }

        url = f"{self.BASE_URL}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()

        try:
            inline_data = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            audio_b64 = inline_data["data"]
        except (KeyError, IndexError, TypeError):
            audio_b64 = ""

        if not audio_b64:
            raise RuntimeError("Gemini TTS returned empty audio")

        pcm = base64.b64decode(audio_b64)
        return _wrap_pcm_to_wav(pcm)

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """Static prebuilt voice list. `language` is accepted for ABC
        compatibility but ignored — Gemini voices are not language-locked."""
        return [
            {
                "name": name,
                "language": "",
                "gender": "neutral",
                "provider": "gemini",
                "friendly_name": name,
            }
            for name in self.VOICES
        ]
