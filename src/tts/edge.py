"""Edge TTS provider — free Microsoft Edge text-to-speech service."""

from __future__ import annotations

import io

import edge_tts

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class EdgeTTSProvider(BaseTTSProvider):
    """Free TTS provider using Microsoft Edge's online TTS service.

    Supports Vietnamese (vi-VN) and English (en-US) voices with
    configurable rate and pitch parameters.
    """

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech from text using Edge TTS.

        Args:
            text: Text to synthesize.
            voice: Edge voice name (e.g., "vi-VN-HoaiMyNeural").
            **kwargs: Optional 'rate' (e.g., "+0%") and 'pitch' (e.g., "+0Hz").

        Returns:
            MP3 audio bytes.
        """
        rate = kwargs.get("rate") or kwargs.get("speed") or "+0%"
        pitch = kwargs.get("pitch", "+0Hz")

        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        buffer = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])

        audio_bytes = buffer.getvalue()
        if not audio_bytes:
            raise RuntimeError(f"Edge TTS returned empty audio for voice={voice}")

        return audio_bytes

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available Edge TTS voices.

        Args:
            language: Optional language filter (e.g., "vi", "en", "vi-VN").

        Returns:
            List of dicts with name, language, gender, provider keys.
        """
        voices = await edge_tts.list_voices()
        results = []

        for v in voices:
            locale = v.get("Locale", "")
            short_lang = locale.split("-")[0] if locale else ""

            if language:
                # Match full locale (vi-VN) or short code (vi)
                if language != locale and language != short_lang:
                    continue

            results.append({
                "name": v.get("ShortName", ""),
                "language": locale,
                "gender": v.get("Gender", "").lower(),
                "provider": "edge",
                "friendly_name": v.get("FriendlyName", ""),
            })

        return results
