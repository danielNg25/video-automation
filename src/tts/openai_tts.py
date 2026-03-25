"""OpenAI TTS provider — uses the /v1/audio/speech API endpoint."""

from __future__ import annotations

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Available voices for OpenAI TTS
OPENAI_VOICES = ["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class OpenAITTSProvider(BaseTTSProvider):
    """TTS provider using OpenAI's audio speech API.

    Supports models: tts-1 (fast), tts-1-hd (quality).
    Voices: alloy, echo, fable, onyx, nova, shimmer.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "tts-1",
        base_url: str = "https://api.openai.com/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech using OpenAI TTS API.

        Args:
            text: Text to synthesize.
            voice: OpenAI voice name (alloy, echo, fable, onyx, nova, shimmer).
            **kwargs: Optional 'speed' (0.25-4.0, default 1.0), 'model' override.

        Returns:
            MP3 audio bytes.
        """
        if not self.api_key:
            raise ValueError("OpenAI API key not configured for TTS")

        speed = kwargs.get("speed", 1.0)
        if isinstance(speed, str):
            # Convert "+10%" style to float
            speed = 1.0 + float(speed.replace("%", "").replace("+", "")) / 100
        model = kwargs.get("model", self.model)

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/audio/speech",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": text,
                    "voice": voice,
                    "speed": speed,
                    "response_format": "mp3",
                },
            )
            response.raise_for_status()
            return response.content

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available OpenAI TTS voices.

        OpenAI voices are multilingual — all voices support all languages.

        Args:
            language: Ignored (all voices are multilingual).

        Returns:
            List of voice dicts.
        """
        return [
            {
                "name": v,
                "language": "multilingual",
                "gender": "neutral",
                "provider": "openai",
                "friendly_name": f"OpenAI {v.title()}",
            }
            for v in OPENAI_VOICES
        ]
