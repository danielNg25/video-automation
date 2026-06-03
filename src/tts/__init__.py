"""TTS module: text-to-speech synthesis with pluggable providers."""

from __future__ import annotations

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_tts_provider(config: dict, provider: str | None = None) -> BaseTTSProvider:
    """Factory to create the appropriate TTS provider.

    Args:
        config: Full config dict (may contain 'tts' section).
        provider: Override provider name ("google", "openai", "elevenlabs", "gemini").
            If None, reads from config or defaults to "google".

    Returns:
        Configured TTS provider instance.
    """
    tts_config = config.get("tts", {})
    provider_name = provider or tts_config.get("default_provider", "google")

    if provider_name == "google":
        from src.tts.google_tts import GoogleTTSProvider

        logger.info("Using Google Cloud TTS provider")
        return GoogleTTSProvider(config=tts_config)

    elif provider_name == "elevenlabs":
        from src.tts.elevenlabs import ElevenLabsTTSProvider

        api_key = tts_config.get("elevenlabs_api_key", "")
        model = tts_config.get("elevenlabs_model", "eleven_multilingual_v2")
        logger.info(f"Using ElevenLabs TTS provider (model={model})")
        return ElevenLabsTTSProvider(api_key=api_key, model=model)

    elif provider_name == "openai":
        from src.tts.openai_tts import OpenAITTSProvider

        api_key = tts_config.get("openai_api_key") or config.get("translation", {}).get("api_key")
        model = tts_config.get("openai_model", "tts-1")
        logger.info(f"Using OpenAI TTS provider (model={model})")
        return OpenAITTSProvider(api_key=api_key, model=model)

    elif provider_name == "gemini":
        from src.tts.gemini_tts import GeminiTTSProvider

        model = tts_config.get("gemini_model", GeminiTTSProvider.DEFAULT_MODEL)
        logger.info(f"Using Gemini TTS provider (model={model})")
        return GeminiTTSProvider(config=tts_config)

    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")


