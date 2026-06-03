"""Router-level tests for the Gemini TTS provider integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.tts.gemini_tts import GeminiTTSProvider


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    app = create_app()
    return TestClient(app)


def test_providers_list_includes_gemini(client):
    r = client.get("/api/tts/providers")
    assert r.status_code == 200
    providers = r.json()
    ids = {p["id"] for p in providers}
    assert "gemini" in ids
    gemini = next(p for p in providers if p["id"] == "gemini")
    assert gemini["requires_key"] is True
    assert gemini["free"] is False


def test_voices_endpoint_returns_gemini_static_list(client):
    r = client.get("/api/tts/voices", params={"provider": "gemini", "api_key": "x"})
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == len(GeminiTTSProvider.VOICES)
    assert all(v["provider"] == "gemini" for v in voices)


def test_preview_threads_gemini_model_into_config(client):
    """POST /api/tts/preview with provider=gemini + model should construct
    a GeminiTTSProvider whose .model matches the request's model field."""
    captured: dict = {}

    real_get_provider = None
    from src.tts import get_tts_provider as _gp
    real_get_provider = _gp

    def spy_get_tts_provider(cfg, provider=None):
        prov = real_get_provider(cfg, provider=provider)
        if provider == "gemini":
            captured["model"] = prov.model
        return prov

    # Stub synthesize so we don't hit the network.
    async def fake_synth(self, text, voice, **kw):
        return b"RIFF\x00\x00\x00\x00WAVE"

    with (
        patch("src.api.routers.tts.get_tts_provider", side_effect=spy_get_tts_provider),
        patch.object(GeminiTTSProvider, "synthesize", new=fake_synth),
    ):
        r = client.post(
            "/api/tts/preview",
            json={
                "text": "hello",
                "voice": "Kore",
                "provider": "gemini",
                "api_key": "x",
                "model": "gemini-2.5-pro-preview-tts",
            },
        )
    assert r.status_code == 200, r.text
    assert captured.get("model") == "gemini-2.5-pro-preview-tts"
