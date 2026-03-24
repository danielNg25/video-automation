"""gTTS provider — Google Translate text-to-speech (free, no API key)."""

from __future__ import annotations

import io
import asyncio

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Languages supported by gTTS with Vietnamese
GTTS_LANGUAGES = {
    "vi": "Vietnamese",
    "en": "English",
    "zh-CN": "Chinese (Simplified)",
    "ja": "Japanese",
    "ko": "Korean",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "pt": "Portuguese",
    "th": "Thai",
}


class GTTSProvider(BaseTTSProvider):
    """Free TTS using Google Translate's text-to-speech.

    No API key required. Quality is decent for subtitles.
    Supports many languages including Vietnamese.
    """

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech using gTTS.

        Args:
            text: Text to synthesize.
            voice: Language code (e.g., "vi", "en"). gTTS uses language
                   as the voice selector — there's one voice per language.
            **kwargs: Optional 'slow' (bool, default False) for slower speech.

        Returns:
            MP3 audio bytes.
        """
        from gtts import gTTS

        slow = kwargs.get("slow", False)
        # Map short codes to gTTS language codes
        lang = voice if len(voice) > 2 else voice

        def _generate() -> bytes:
            tts = gTTS(text=text, lang=lang, slow=slow)
            buf = io.BytesIO()
            tts.write_to_fp(buf)
            return buf.getvalue()

        audio_bytes = await asyncio.to_thread(_generate)
        if not audio_bytes:
            raise RuntimeError(f"gTTS returned empty audio for lang={lang}")
        return audio_bytes

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available gTTS voices (one per language)."""
        results = []
        for code, name in GTTS_LANGUAGES.items():
            short = code.split("-")[0]
            if language and language != code and language != short:
                continue
            results.append({
                "name": code,
                "language": short,
                "gender": "neutral",
                "provider": "gtts",
                "friendly_name": f"Google Translate — {name}",
            })
        return results
