"""Unit tests for the Vbee TTS provider (async submit→poll→download)."""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from src.tts.vbee_tts import VbeeTTSProvider


class _Resp:
    def __init__(self, status_code=200, json_data=None, content=b""):
        self.status_code = status_code
        self._json = json_data if json_data is not None else {}
        self.content = content
        self.text = str(self._json)

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=None)


class _FakeClient:
    """Stand-in for httpx.AsyncClient as an async context manager.

    `post_results` / `get_results` are popped FIFO. If a list is exhausted,
    the last entry is returned repeatedly (lets poll-timeout tests loop on
    a steady PROCESSING response).
    """

    def __init__(self, post_results, get_results):
        self._post = list(post_results)
        self._get = list(get_results)
        self.post_calls = []
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        self.post_calls.append((url, kw))
        return self._post.pop(0) if len(self._post) > 1 else self._post[0]

    async def get(self, url, **kw):
        self.get_calls.append((url, kw))
        return self._get.pop(0) if len(self._get) > 1 else self._get[0]


def _patch_client(fake):
    # VbeeTTSProvider calls httpx.AsyncClient(timeout=...); return our fake.
    return patch("src.tts.vbee_tts.httpx.AsyncClient", return_value=fake)


def _provider(**over):
    cfg = {
        "vbee_api_key": "tok",
        "vbee_app_id": "app",
        "vbee_poll_interval": 0.01,
        "vbee_poll_timeout": 0.1,
    }
    cfg.update(over)
    return VbeeTTSProvider(cfg)


@pytest.mark.asyncio
async def test_happy_path_returns_audio_bytes():
    fake = _FakeClient(
        post_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
        get_results=[
            _Resp(json_data={"requestId": "r1", "status": "PROCESSING"}),
            _Resp(json_data={"requestId": "r1", "status": "COMPLETED",
                             "audioLink": "https://x/a.mp3"}),
            _Resp(content=b"ID3audio"),
        ],
    )
    with _patch_client(fake):
        out = await _provider().synthesize("xin chao", "hn_female_ngochuyen_full_48k-fhg")
    assert out == b"ID3audio"
    # The audioLink download MUST follow redirects — vbee's link 302-redirects
    # to a presigned S3 URL; without this httpx returns the 302 and errors.
    _, audio_kw = fake.get_calls[-1]
    assert audio_kw.get("follow_redirects") is True


@pytest.mark.asyncio
async def test_immediate_completed():
    fake = _FakeClient(
        post_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
        get_results=[
            _Resp(json_data={"requestId": "r1", "status": "COMPLETED",
                             "audioLink": "https://x/a.mp3"}),
            _Resp(content=b"AUDIO"),
        ],
    )
    with _patch_client(fake):
        out = await _provider().synthesize("hi", "v")
    assert out == b"AUDIO"


@pytest.mark.asyncio
async def test_failed_status_raises():
    fake = _FakeClient(
        post_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
        get_results=[_Resp(json_data={"requestId": "r1", "status": "FAILED"})],
    )
    with _patch_client(fake):
        with pytest.raises(RuntimeError, match="failed"):
            await _provider().synthesize("hi", "v")


@pytest.mark.asyncio
async def test_poll_timeout_raises():
    fake = _FakeClient(
        post_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
        get_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
    )
    with _patch_client(fake):
        with pytest.raises(RuntimeError, match="timed out"):
            await _provider().synthesize("hi", "v")


@pytest.mark.asyncio
async def test_missing_token_raises():
    with pytest.raises(ValueError, match="not configured"):
        await _provider(vbee_api_key="").synthesize("hi", "v")


@pytest.mark.asyncio
async def test_missing_app_id_raises():
    with pytest.raises(ValueError, match="not configured"):
        await _provider(vbee_app_id="").synthesize("hi", "v")


@pytest.mark.asyncio
async def test_429_then_success_retries():
    fake = _FakeClient(
        post_results=[
            _Resp(status_code=429, json_data={"error": {"code": "TTS_CCR_MAX_LIMIT_REACHED"}}),
            _Resp(json_data={"requestId": "r1", "status": "PROCESSING"}),
        ],
        get_results=[
            _Resp(json_data={"status": "COMPLETED", "audioLink": "https://x/a.mp3"}),
            _Resp(content=b"OK"),
        ],
    )
    with _patch_client(fake):
        out = await _provider().synthesize("hi", "v")
    assert out == b"OK"
    assert len(fake.post_calls) == 2


@pytest.mark.asyncio
async def test_http_400_raises_with_message():
    fake = _FakeClient(
        post_results=[_Resp(status_code=400,
                            json_data={"error": {"code": "BAD_REQUEST", "message": "bad voice"}})],
        get_results=[_Resp(content=b"")],
    )
    with _patch_client(fake):
        with pytest.raises(RuntimeError, match="bad voice"):
            await _provider().synthesize("hi", "v")


def test_coerce_speed_clamps_and_parses():
    assert VbeeTTSProvider._coerce_speed(2.5) == 1.9
    assert VbeeTTSProvider._coerce_speed(0.1) == 0.25
    assert VbeeTTSProvider._coerce_speed("+10%") == pytest.approx(1.1)
    assert VbeeTTSProvider._coerce_speed("1.5") == 1.5
    assert VbeeTTSProvider._coerce_speed(None) == 1.0


@pytest.mark.asyncio
async def test_list_voices_curated_shape():
    voices = await _provider().list_voices()
    assert len(voices) == len(VbeeTTSProvider.VOICES)
    for v in voices:
        assert v["provider"] == "vbee"
        assert v["language"] == "vi"
        assert set(v.keys()) == {"name", "language", "gender", "provider", "friendly_name"}


@pytest.mark.asyncio
async def test_submit_body_and_headers():
    fake = _FakeClient(
        post_results=[_Resp(json_data={"requestId": "r1", "status": "PROCESSING"})],
        get_results=[
            _Resp(json_data={"status": "COMPLETED", "audioLink": "https://x/a.mp3"}),
            _Resp(content=b"OK"),
        ],
    )
    with _patch_client(fake):
        await _provider().synthesize("xin chao", "hn_female_ngochuyen_full_48k-fhg")
    _, kw = fake.post_calls[0]
    assert kw["json"]["mode"] == "async"
    assert kw["json"]["webhookUrl"]
    assert kw["json"]["voiceCode"] == "hn_female_ngochuyen_full_48k-fhg"
    assert kw["json"]["text"] == "xin chao"
    assert kw["headers"]["Authorization"] == "Bearer tok"
    assert kw["headers"]["App-Id"] == "app"
