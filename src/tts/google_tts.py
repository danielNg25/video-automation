"""Google Cloud TTS provider — uses the Text-to-Speech REST API."""

from __future__ import annotations

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


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
        """List Google Cloud TTS voices via the live voices:list endpoint.

        Hits ``GET /v1/voices`` (optionally filtered with ``languageCode``).
        ``language`` accepts either a short code (``"vi"``, ``"en"``) — which
        matches any locale starting with that prefix — or a full BCP-47 tag
        (``"vi-VN"``, ``"en-US"``). Returns every voice the account is
        entitled to (Standard, Wavenet, Neural2, Studio, Chirp3-HD, News, etc.).
        """
        if not self.api_key:
            raise ValueError(
                "Google TTS API key not configured. "
                "Save it in Settings → API Keys (Google)."
            )

        params: dict[str, str] = {"key": self.api_key}
        is_short_code = bool(language) and "-" not in language
        if language and not is_short_code:
            params["languageCode"] = language

        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{self.base_url}/voices", params=params)
            r.raise_for_status()
            payload = r.json()

        results: list[dict] = []
        for v in payload.get("voices", []):
            codes: list[str] = v.get("languageCodes", []) or []
            primary = codes[0] if codes else ""
            if is_short_code and not any(c.lower().startswith(language.lower()) for c in codes):
                continue
            results.append({
                "name": v.get("name", ""),
                "language": primary,
                "gender": (v.get("ssmlGender") or "NEUTRAL").lower(),
                "provider": "google",
                "friendly_name": v.get("name", ""),
            })

        return results
