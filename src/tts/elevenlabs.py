"""ElevenLabs TTS provider — high-quality multilingual text-to-speech."""

from __future__ import annotations

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class ElevenLabsTTSProvider(BaseTTSProvider):
    """TTS provider using the ElevenLabs v1 API.

    Supports 29 languages including Vietnamese with excellent quality.
    Voice cloning available on paid plans.
    """

    def __init__(self, api_key: str | None = None, model: str = "eleven_multilingual_v2"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.elevenlabs.io/v1"

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech using ElevenLabs API.

        Args:
            text: Text to synthesize.
            voice: ElevenLabs voice ID (e.g., "21m00Tcm4TlvDq8ikWAM").
            **kwargs: Optional 'stability' (0-1), 'similarity_boost' (0-1),
                      'model' override, 'style' (0-1), 'speed' (0.7-1.2).

        Returns:
            MP3 audio bytes.
        """
        if not self.api_key:
            raise ValueError("ElevenLabs API key not configured")

        model = kwargs.get("model", self.model)
        stability = kwargs.get("stability", 0.5)
        similarity_boost = kwargs.get("similarity_boost", 0.75)
        style = kwargs.get("style", 0.0)

        body: dict = {
            "text": text,
            "model_id": model,
            "voice_settings": {
                "stability": stability,
                "similarity_boost": similarity_boost,
                "style": style,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/text-to-speech/{voice}",
                headers={
                    "xi-api-key": self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "audio/mpeg",
                },
                json=body,
            )
            if response.status_code == 401:
                raise ValueError("Invalid ElevenLabs API key")
            if not response.is_success:
                # Parse ElevenLabs error detail
                try:
                    err = response.json()
                    detail = err.get("detail", {})
                    if isinstance(detail, dict):
                        msg = detail.get("message", response.text)
                    else:
                        msg = str(detail)
                except Exception:
                    msg = response.text[:300]
                logger.error(f"ElevenLabs {response.status_code}: {msg}")
                raise RuntimeError(f"ElevenLabs ({response.status_code}): {msg}")
            return response.content

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available ElevenLabs voices.

        Fetches from the API if an API key is configured, otherwise
        returns an empty list (free tier can only use own voices).

        Args:
            language: Optional language filter (ignored for API fetch).

        Returns:
            List of voice dicts.
        """
        if self.api_key:
            return await self._fetch_voices_from_api(language)
        return []

    async def _fetch_voices_from_api(self, language: str | None) -> list[dict]:
        """Fetch voices from ElevenLabs API."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}/voices",
                    headers={"xi-api-key": self.api_key},
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for v in data.get("voices", []):
                labels = v.get("labels", {})
                voice_lang = labels.get("language", "multilingual")

                results.append({
                    "name": v["voice_id"],
                    "language": voice_lang,
                    "gender": labels.get("gender", "neutral"),
                    "provider": "elevenlabs",
                    "friendly_name": v.get("name", v["voice_id"]),
                })
            return results
        except Exception as e:
            logger.warning(f"Failed to fetch ElevenLabs voices: {e}")
            return self._default_voices(language)

    @staticmethod
    def _default_voices(language: str | None) -> list[dict]:
        """Return curated list of popular ElevenLabs default voices."""
        defaults = [
            {"name": "21m00Tcm4TlvDq8ikWAM", "friendly_name": "Rachel", "gender": "female"},
            {"name": "29vD33N1CtxCmqQRPOHJ", "friendly_name": "Drew", "gender": "male"},
            {"name": "2EiwWnXFnvU5JabPnv8n", "friendly_name": "Clyde", "gender": "male"},
            {"name": "5Q0t7uMcjvnagumLfvZi", "friendly_name": "Paul", "gender": "male"},
            {"name": "AZnzlk1XvdvUeBnXmlld", "friendly_name": "Domi", "gender": "female"},
            {"name": "EXAVITQu4vr4xnSDxMaL", "friendly_name": "Bella", "gender": "female"},
            {"name": "ErXwobaYiN019PkySvjV", "friendly_name": "Antoni", "gender": "male"},
            {"name": "MF3mGyEYCl7XYWbV9V6O", "friendly_name": "Elli", "gender": "female"},
            {"name": "TxGEqnHWrfWFTfGW9XjX", "friendly_name": "Josh", "gender": "male"},
            {"name": "VR6AewLTigWG4xSOukaG", "friendly_name": "Arnold", "gender": "male"},
            {"name": "pNInz6obpgDQGcFmaJgB", "friendly_name": "Adam", "gender": "male"},
            {"name": "yoZ06aMxZJJ28mfd3POQ", "friendly_name": "Sam", "gender": "male"},
        ]
        return [
            {
                **v,
                "language": "multilingual",
                "provider": "elevenlabs",
            }
            for v in defaults
        ]
