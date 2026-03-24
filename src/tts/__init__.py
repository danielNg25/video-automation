"""TTS module: text-to-speech synthesis with pluggable providers."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_tts_provider(config: dict, provider: str | None = None) -> BaseTTSProvider:
    """Factory to create the appropriate TTS provider.

    Args:
        config: Full config dict (may contain 'tts' section).
        provider: Override provider name ("edge", "openai", "google").
            If None, reads from config or defaults to "edge".

    Returns:
        Configured TTS provider instance.
    """
    tts_config = config.get("tts", {})
    provider_name = provider or tts_config.get("default_provider", "edge")

    if provider_name == "edge":
        from src.tts.edge import EdgeTTSProvider

        logger.info("Using Edge TTS provider")
        return EdgeTTSProvider()

    elif provider_name == "openai":
        from src.tts.openai_tts import OpenAITTSProvider

        api_key = tts_config.get("openai_api_key") or config.get("translation", {}).get("api_key")
        model = tts_config.get("openai_model", "tts-1")
        logger.info(f"Using OpenAI TTS provider (model={model})")
        return OpenAITTSProvider(api_key=api_key, model=model)

    elif provider_name == "google":
        from src.tts.google_tts import GoogleTTSProvider

        logger.info("Using Google Cloud TTS provider")
        return GoogleTTSProvider(config=tts_config)

    elif provider_name == "elevenlabs":
        from src.tts.elevenlabs import ElevenLabsTTSProvider

        api_key = tts_config.get("elevenlabs_api_key", "")
        model = tts_config.get("elevenlabs_model", "eleven_multilingual_v2")
        logger.info(f"Using ElevenLabs TTS provider (model={model})")
        return ElevenLabsTTSProvider(api_key=api_key, model=model)

    elif provider_name == "gtts":
        from src.tts.gtts_provider import GTTSProvider

        logger.info("Using gTTS provider (Google Translate)")
        return GTTSProvider()

    elif provider_name == "piper":
        from src.tts.piper_tts import PiperTTSProvider

        model_dir = tts_config.get("piper_model_dir")
        logger.info("Using Piper TTS provider (local)")
        return PiperTTSProvider(model_dir=model_dir)

    else:
        raise ValueError(f"Unknown TTS provider: {provider_name}")


def load_voice_profiles(config: dict | None = None) -> dict:
    """Load voice profiles from YAML config.

    Args:
        config: Optional config dict with 'tts.voices_config' path.

    Returns:
        Full voice profiles dict with 'profiles' and 'platforms' keys.
    """
    config_path = "config/tts_voices.yaml"
    if config:
        tts_config = config.get("tts", {})
        config_path = tts_config.get("voices_config", config_path)

    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Voice profiles not found at {config_path}, using defaults")
        return {"default_provider": "edge", "profiles": {}, "platforms": {}}

    with open(path) as f:
        return yaml.safe_load(f) or {}


def save_voice_profiles(profiles: dict, config: dict | None = None) -> None:
    """Save voice profiles to YAML config.

    Args:
        profiles: Full voice profiles dict.
        config: Optional config dict with 'tts.voices_config' path.
    """
    config_path = "config/tts_voices.yaml"
    if config:
        tts_config = config.get("tts", {})
        config_path = tts_config.get("voices_config", config_path)

    with open(config_path, "w") as f:
        yaml.safe_dump(profiles, f, default_flow_style=False)

    logger.info(f"Saved voice profiles to {config_path}")
