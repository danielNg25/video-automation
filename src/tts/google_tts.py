"""Google Cloud TTS provider — uses the Text-to-Speech REST API."""

from __future__ import annotations

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Common Vietnamese and English voices
GOOGLE_VOICES = {
    "vi": [
        {"name": "vi-VN-Standard-A", "gender": "female"},
        {"name": "vi-VN-Standard-B", "gender": "male"},
        {"name": "vi-VN-Standard-C", "gender": "female"},
        {"name": "vi-VN-Standard-D", "gender": "male"},
        {"name": "vi-VN-Wavenet-A", "gender": "female"},
        {"name": "vi-VN-Wavenet-B", "gender": "male"},
        {"name": "vi-VN-Wavenet-C", "gender": "female"},
        {"name": "vi-VN-Wavenet-D", "gender": "male"},
    ],
    "en": [
        {"name": "en-US-Standard-A", "gender": "male"},
        {"name": "en-US-Standard-C", "gender": "female"},
        {"name": "en-US-Standard-D", "gender": "male"},
        {"name": "en-US-Standard-E", "gender": "female"},
        {"name": "en-US-Wavenet-A", "gender": "male"},
        {"name": "en-US-Wavenet-C", "gender": "female"},
        {"name": "en-US-Wavenet-D", "gender": "male"},
        {"name": "en-US-Wavenet-F", "gender": "female"},
    ],
}


class GoogleTTSProvider(BaseTTSProvider):
    """TTS provider using Google Cloud Text-to-Speech REST API.

    Requires a Google Cloud API key with Text-to-Speech API enabled.
    Excellent Vietnamese quality with Wavenet voices.
    """

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key = config.get("google_api_key", "")
        self.base_url = "https://texttospeech.googleapis.com/v1"

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech using Google Cloud TTS.

        Args:
            text: Text to synthesize.
            voice: Google voice name (e.g., "vi-VN-Wavenet-A").
            **kwargs: Optional 'pitch' (semitones, e.g., 0.0),
                      'speed' (0.25-4.0, e.g., 1.0).

        Returns:
            MP3 audio bytes.
        """
        if not self.api_key:
            raise ValueError("Google Cloud API key not configured for TTS")

        # Parse language code from voice name
        parts = voice.split("-")
        language_code = f"{parts[0]}-{parts[1]}" if len(parts) >= 2 else "vi-VN"

        speed = kwargs.get("speed", 1.0)
        if isinstance(speed, str):
            speed = 1.0 + float(speed.replace("%", "").replace("+", "")) / 100
        pitch = kwargs.get("pitch", 0.0)
        if isinstance(pitch, str):
            pitch = float(pitch.replace("Hz", "").replace("+", ""))

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/text:synthesize",
                params={"key": self.api_key},
                json={
                    "input": {"text": text},
                    "voice": {
                        "languageCode": language_code,
                        "name": voice,
                    },
                    "audioConfig": {
                        "audioEncoding": "MP3",
                        "speakingRate": speed,
                        "pitch": pitch,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        # Google returns base64-encoded audio
        import base64

        audio_content = data.get("audioContent", "")
        if not audio_content:
            raise RuntimeError("Google TTS returned empty audio content")

        return base64.b64decode(audio_content)

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available Google Cloud TTS voices.

        Args:
            language: Optional language filter ("vi", "en").

        Returns:
            List of voice dicts.
        """
        results = []

        for lang_code, voices in GOOGLE_VOICES.items():
            if language and language != lang_code:
                # Also check full locale match
                if not any(v["name"].startswith(language) for v in voices):
                    continue

            for v in voices:
                if language and not v["name"].startswith(language) and lang_code != language:
                    continue
                results.append({
                    "name": v["name"],
                    "language": lang_code,
                    "gender": v["gender"],
                    "provider": "google",
                    "friendly_name": f"Google {v['name']}",
                })

        return results
