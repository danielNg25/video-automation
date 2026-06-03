"""Factory tests confirming get_tts_provider('gemini') wires the right config."""

from __future__ import annotations

from src.tts import get_tts_provider
from src.tts.gemini_tts import GeminiTTSProvider


def test_factory_builds_gemini_provider_with_default_model():
    cfg = {"tts": {"gemini_api_key": "x"}}
    p = get_tts_provider(cfg, provider="gemini")
    assert isinstance(p, GeminiTTSProvider)
    assert p.api_key == "x"
    assert p.model == GeminiTTSProvider.DEFAULT_MODEL


def test_factory_respects_gemini_model_override():
    cfg = {
        "tts": {
            "gemini_api_key": "x",
            "gemini_model": "gemini-2.5-pro-preview-tts",
        }
    }
    p = get_tts_provider(cfg, provider="gemini")
    assert p.model == "gemini-2.5-pro-preview-tts"
