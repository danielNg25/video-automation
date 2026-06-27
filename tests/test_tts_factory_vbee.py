"""Factory test: get_tts_provider builds VbeeTTSProvider from config."""

from __future__ import annotations

from src.tts import get_tts_provider
from src.tts.vbee_tts import VbeeTTSProvider


def test_factory_builds_vbee_with_token_and_app_id():
    cfg = {"tts": {"vbee_api_key": "tok", "vbee_app_id": "app"}}
    provider = get_tts_provider(cfg, provider="vbee")
    assert isinstance(provider, VbeeTTSProvider)
    assert provider.api_key == "tok"
    assert provider.app_id == "app"
    assert provider.default_voice == VbeeTTSProvider.DEFAULT_VOICE
