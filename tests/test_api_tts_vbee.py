"""Router tests for the Vbee TTS integration."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import create_app
from src.tts.vbee_tts import VbeeTTSProvider


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return TestClient(create_app())


def test_providers_list_includes_vbee(client):
    r = client.get("/api/tts/providers")
    assert r.status_code == 200
    providers = {p["id"]: p for p in r.json()}
    assert "vbee" in providers
    assert providers["vbee"]["requires_key"] is True


def test_voices_endpoint_returns_vbee_curated_list(client):
    r = client.get("/api/tts/voices", params={"provider": "vbee", "api_key": "x"})
    assert r.status_code == 200
    voices = r.json()
    assert len(voices) == len(VbeeTTSProvider.VOICES)
    assert all(v["provider"] == "vbee" for v in voices)


def test_preview_threads_app_id_into_provider(client):
    """POST /api/tts/preview with provider=vbee + app_id builds a
    VbeeTTSProvider whose .app_id matches the request."""
    captured = {}
    from src.tts import get_tts_provider as real_get

    def spy(cfg, provider=None):
        prov = real_get(cfg, provider=provider)
        if provider == "vbee":
            captured["app_id"] = prov.app_id
            captured["api_key"] = prov.api_key
        return prov

    async def fake_synth(self, text, voice, **kw):
        return b"RIFFvbee"

    with (
        patch("src.api.routers.tts.get_tts_provider", side_effect=spy),
        patch.object(VbeeTTSProvider, "synthesize", new=fake_synth),
    ):
        r = client.post("/api/tts/preview", json={
            "text": "xin chao",
            "voice": "hn_female_ngochuyen_full_48k-fhg",
            "provider": "vbee",
            "api_key": "tok",
            "app_id": "app",
        })
    assert r.status_code == 200, r.text
    assert captured.get("app_id") == "app"
    assert captured.get("api_key") == "tok"
