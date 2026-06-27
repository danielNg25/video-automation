# Vbee TTS Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Vbee (vbee.vn / AIVoice) as a selectable TTS provider for Vietnamese dubbing, hiding its asynchronous submit→poll→download API behind the synchronous `synthesize() -> bytes` contract so no other pipeline layer changes.

**Architecture:** A new `VbeeTTSProvider` performs `POST /v1/tts` (mode=async) → poll `GET /v1/tts/requests/{id}` until `COMPLETED` → download the `audioLink` mp3, all inside one `synthesize()` call. Auth needs two secrets (Bearer token + `App-Id` header); the token rides the existing `api_key` rail and the `app_id` rides the same per-request config-injection rail already used for Gemini's `model`. Voices are a curated Vietnamese list plus a manual custom-code input.

**Tech Stack:** Python 3.11, `httpx` (async), pytest + `unittest.mock`, FastAPI, React 19 + TypeScript.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-20-vbee-tts-provider-design.md`. Reference API docs: `docs/vbee/batchapi.md`, `docs/vbee/getrequest.md`, `docs/vbee/callbackapi.md`.
- Endpoint base: `https://api.vbee.vn/v1`. Submit: `POST /tts`. Poll: `GET /tts/requests/{requestId}`.
- Headers on every call: `Authorization: Bearer <token>`, `App-Id: <app_id>`, `Content-Type: application/json`.
- Submit body required fields: `text`, `mode:"async"`, `webhookUrl`, `voiceCode`. Optional: `outputFormat` (mp3 default), `bitrate` (8/16/32/64/128, default 128), `speed` (0.25–1.9, default 1.0), `sampleRate`.
- `webhookUrl` is required by the API even though we poll — send a placeholder.
- Poll terminal states: success = `COMPLETED` or `SUCCESS` (accept both) with `audioLink`; failure = `FAILED`/`FAILURE`. `audioLink` expires in 3 min (download immediately).
- Errors are HTTP-coded with `{"error": {"code", "message"}}`: 401 `UNAUTHORIZED`, 400 `BAD_REQUEST`, 500 `INTERNAL_SERVER_ERROR`; 429 = rate/concurrency limit.
- Provider id string is `"vbee"` everywhere (factory, routers, FE).
- Commit rules (from CLAUDE.md): no AI attribution in messages; update `README.md` Implementation Progress + `CHANGELOG.md` `[Unreleased]` on the docs-rollup task. All work on branch `feature/vbee-tts-provider`.
- `BaseTTSProvider.synthesize(self, text, voice, **kwargs) -> bytes` and `list_voices(self, language=None) -> list[dict]` (keys: `name, language, gender, provider, friendly_name`) are the contracts to satisfy.

---

### Task 1: `VbeeTTSProvider` + unit tests

**Files:**
- Create: `src/tts/vbee_tts.py`
- Create: `tests/test_vbee_tts.py`

**Interfaces:**
- Consumes: `src.tts.base.BaseTTSProvider`.
- Produces: `VbeeTTSProvider(config: dict | None)` with class attrs `BASE_URL`, `DEFAULT_VOICE`, `VOICES: tuple[tuple[str,str], ...]`; instance attrs `api_key`, `app_id`, `default_voice`, `output_format`, `bitrate`, `sample_rate`, `webhook_url`, `poll_interval_s`, `poll_timeout_s`; methods `async synthesize(text, voice, **kwargs) -> bytes`, `async list_voices(language=None) -> list[dict]`, static `_coerce_speed(raw) -> float`. Module function `_vbee_error(resp) -> str`.

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_vbee_tts.py`:

```python
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
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vbee_tts.py -v 2>&1 | tail -15`
Expected: `ModuleNotFoundError: No module named 'src.tts.vbee_tts'`.

- [ ] **Step 1.3: Create `src/tts/vbee_tts.py`**

```python
"""Vbee (vbee.vn / AIVoice) TTS provider — async submit→poll→download.

Vbee's synthesis API is asynchronous: POST returns a requestId, you poll
GET /tts/requests/{id} until COMPLETED with an audioLink, then download
that URL. The whole flow is hidden inside synthesize() so the rest of the
pipeline keeps its synchronous "synthesize(text, voice) -> bytes" contract.
"""

from __future__ import annotations

import asyncio

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _vbee_error(resp: httpx.Response) -> str:
    """Build a readable error string from a vbee error response."""
    try:
        data = resp.json()
        err = data.get("error") or {}
        code = err.get("code") or resp.status_code
        message = err.get("message") or resp.text
        return f"vbee API error {code}: {message}"
    except Exception:
        return f"vbee API error {resp.status_code}: {resp.text}"


class VbeeTTSProvider(BaseTTSProvider):
    """TTS provider for Vbee's Vietnamese voices (async Batch API)."""

    BASE_URL = "https://api.vbee.vn/v1"
    DEFAULT_VOICE = "hn_female_ngochuyen_full_48k-fhg"

    # Curated Vietnamese voices (code, friendly label). Extend by editing.
    VOICES: tuple[tuple[str, str], ...] = (
        ("hn_female_ngochuyen_full_48k-fhg", "Ngọc Huyền — Hà Nội, nữ"),
        ("hn_male_manhdung_news_48k-fhg", "Mạnh Dũng — Hà Nội, nam"),
        ("sg_female_thaotrinh_full_48k-fhg", "Thảo Trinh — Sài Gòn, nữ"),
        ("sg_male_minhhoang_full_48k-fhg", "Minh Hoàng — Sài Gòn, nam"),
        ("hue_female_huonggiang_full_48k-fhg", "Hương Giang — Huế, nữ"),
    )

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key: str = config.get("vbee_api_key", "")
        self.app_id: str = config.get("vbee_app_id", "")
        self.default_voice: str = config.get("vbee_default_voice", self.DEFAULT_VOICE)
        self.output_format: str = config.get("vbee_output_format", "mp3")
        self.bitrate: int = int(config.get("vbee_bitrate", 128))
        self.sample_rate = config.get("vbee_sample_rate")  # None => voice default
        # webhookUrl is a required field even though we poll; placeholder is fine.
        self.webhook_url: str = config.get(
            "vbee_webhook_url", "https://example.com/vbee-callback"
        )
        self.poll_interval_s: float = float(config.get("vbee_poll_interval", 2.0))
        self.poll_timeout_s: float = float(config.get("vbee_poll_timeout", 90.0))

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "App-Id": self.app_id,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _coerce_speed(raw) -> float:
        """Normalise a speed kwarg to vbee's 0.25–1.9 numeric range.

        Accepts floats, numeric strings, and OpenAI-style '+10%' strings.
        """
        speed = raw if raw is not None else 1.0
        if isinstance(speed, str):
            s = speed.strip()
            if s.endswith("%"):
                speed = 1.0 + float(s.replace("%", "").replace("+", "")) / 100
            else:
                speed = float(s)
        speed = float(speed)
        return max(0.25, min(1.9, speed))

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        if not self.api_key or not self.app_id:
            raise ValueError("Vbee token/app_id not configured for TTS")

        body = {
            "text": text,
            "voiceCode": voice or self.default_voice,
            "mode": "async",
            "webhookUrl": self.webhook_url,
            "outputFormat": self.output_format,
            "bitrate": self.bitrate,
            "speed": self._coerce_speed(kwargs.get("speed", 1.0)),
        }
        if self.sample_rate:
            body["sampleRate"] = int(self.sample_rate)

        async with httpx.AsyncClient(timeout=60.0) as client:
            request_id = await self._submit(client, body)
            audio_link = await self._poll(client, request_id)
            audio = await client.get(audio_link)
            audio.raise_for_status()
            return audio.content

    async def _submit(self, client: httpx.AsyncClient, body: dict, max_retries: int = 3) -> str:
        last_err = "vbee submit failed"
        for attempt in range(max_retries):
            resp = await client.post(
                f"{self.BASE_URL}/tts", headers=self._headers(), json=body
            )
            if resp.status_code == 429:
                last_err = "vbee rate limited (429)"
                logger.warning(f"{last_err}; retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(self.poll_interval_s * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise RuntimeError(_vbee_error(resp))
            data = resp.json()
            request_id = data.get("requestId")
            if not request_id:
                raise RuntimeError(f"vbee submit returned no requestId: {data}")
            return request_id
        raise RuntimeError(last_err)

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> str:
        url = f"{self.BASE_URL}/tts/requests/{request_id}"
        elapsed = 0.0
        while elapsed < self.poll_timeout_s:
            resp = await client.get(url, headers=self._headers())
            if resp.status_code >= 400:
                raise RuntimeError(_vbee_error(resp))
            data = resp.json()
            status = (data.get("status") or "").upper()
            if status in ("COMPLETED", "SUCCESS"):
                audio_link = data.get("audioLink") or data.get("audio_link")
                if not audio_link:
                    raise RuntimeError(f"vbee COMPLETED but no audioLink: {data}")
                return audio_link
            if status in ("FAILED", "FAILURE"):
                raise RuntimeError(f"vbee synthesis failed: {data}")
            await asyncio.sleep(self.poll_interval_s)
            elapsed += self.poll_interval_s
        raise RuntimeError(
            f"vbee synthesis timed out after {self.poll_timeout_s}s (request {request_id})"
        )

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """Curated Vietnamese voice list. `language` is ignored (all vi).

        Custom voice codes are supplied free-text from the UI, so this only
        needs to surface the known-good defaults for the dropdown.
        """
        out = []
        for code, label in self.VOICES:
            gender = "female" if "_female_" in code else "male" if "_male_" in code else "neutral"
            out.append({
                "name": code,
                "language": "vi",
                "gender": gender,
                "provider": "vbee",
                "friendly_name": label,
            })
        return out
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vbee_tts.py -v 2>&1 | tail -15`
Expected: 11 passed.

- [ ] **Step 1.5: Lint**

Run: `ruff check src/tts/vbee_tts.py tests/test_vbee_tts.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 1.6: Commit**

```bash
git add src/tts/vbee_tts.py tests/test_vbee_tts.py
git commit -m "feat(tts): Vbee provider — async submit/poll/download behind synthesize()

VbeeTTSProvider hides vbee's asynchronous Batch API behind the standard
synchronous synthesize(text, voice) -> bytes contract: POST /v1/tts
(mode=async) returns a requestId, poll GET /v1/tts/requests/{id} until
COMPLETED (accepts COMPLETED or SUCCESS), then download the audioLink mp3
and return its bytes. Two-secret auth via Authorization: Bearer + App-Id
headers. webhookUrl is sent as a required placeholder since we poll. 429
gets a bounded backoff-retry; FAILED/timeout/HTTP>=400 raise so the
assembler flags needs_review and falls back to source audio. speed is
coerced + clamped to 0.25-1.9; pitch ignored (no API param). list_voices
returns a curated Vietnamese set. 11 unit tests."
```

---

### Task 2: Factory wire-up + test

**Files:**
- Modify: `src/tts/__init__.py`
- Create: `tests/test_tts_factory_vbee.py`

**Interfaces:**
- Consumes: `VbeeTTSProvider` from Task 1; existing `get_tts_provider(config, provider=None)`.
- Produces: `get_tts_provider(cfg, provider="vbee")` returns a `VbeeTTSProvider` built from `cfg["tts"]`.

- [ ] **Step 2.1: Write the failing test**

Create `tests/test_tts_factory_vbee.py`:

```python
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
```

- [ ] **Step 2.2: Run to verify it fails**

Run: `python -m pytest tests/test_tts_factory_vbee.py -v 2>&1 | tail -10`
Expected: `ValueError: Unknown TTS provider: vbee`.

- [ ] **Step 2.3: Add the vbee branch in `src/tts/__init__.py`**

Insert this branch immediately before the final `else:` (after the `gemini` branch, line ~52):

```python
    elif provider_name == "vbee":
        from src.tts.vbee_tts import VbeeTTSProvider

        logger.info("Using Vbee TTS provider")
        return VbeeTTSProvider(config=tts_config)
```

Also update the docstring's provider list (line 16) from `"google", "openai", "elevenlabs", "gemini"` to `"google", "openai", "elevenlabs", "gemini", "vbee"`.

- [ ] **Step 2.4: Run test to verify it passes**

Run: `python -m pytest tests/test_tts_factory_vbee.py -v 2>&1 | tail -10`
Expected: 1 passed.

- [ ] **Step 2.5: Lint**

Run: `ruff check src/tts/__init__.py tests/test_tts_factory_vbee.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 2.6: Commit**

```bash
git add src/tts/__init__.py tests/test_tts_factory_vbee.py
git commit -m "feat(tts): wire VbeeTTSProvider through get_tts_provider

get_tts_provider gains a 'vbee' branch returning VbeeTTSProvider built
from the tts config section (reads vbee_api_key + vbee_app_id directly,
same pattern as GoogleTTSProvider). Docstring provider list updated. One
factory test."
```

---

### Task 3: Per-video + preview + voices wiring (token + app_id)

**Files:**
- Modify: `src/api/models.py` (TTSRequest, TTSPreviewRequest)
- Modify: `src/api/routers/tts.py` (start_tts, preview_tts, list_providers)
- Modify: `src/tts/runner.py` (generalise api_key_override injection)
- Create: `tests/test_api_tts_vbee.py`

**Interfaces:**
- Consumes: factory from Task 2; `VbeeTTSProvider.VOICES` from Task 1.
- Produces: `TTSRequest.app_id: str | None`, `TTSPreviewRequest.app_id: str | None`; `/api/tts/providers` includes `{"id": "vbee", ...}`; `run_tts_track` injects `tts_section[f"{provider}_api_key"]` for any provider (so vbee's token reaches the provider).

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_api_tts_vbee.py`:

```python
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
```

- [ ] **Step 3.2: Run to verify they fail**

Run: `python -m pytest tests/test_api_tts_vbee.py -v 2>&1 | tail -20`
Expected: providers test fails (no vbee), preview test fails (`app_id` not a field / not injected).

- [ ] **Step 3.3: Add `app_id` to the request models**

In `src/api/models.py`, find `TTSRequest`. Immediately after its `model: str | None = None` line (the Gemini field) add:

```python
    app_id: str | None = None  # Vbee App-Id; ignored by other providers
```

Do the same in `TTSPreviewRequest` (add the identical line after its `model` field).

- [ ] **Step 3.4: Add vbee to `/api/tts/providers`**

In `src/api/routers/tts.py`, `list_providers()` (line ~88), add the vbee entry after the gemini entry:

```python
        {"id": "vbee", "name": "Vbee (Vietnamese)", "free": False, "requires_key": True},
```

- [ ] **Step 3.5: Inject `vbee_app_id` in `preview_tts`**

In `src/api/routers/tts.py`, `preview_tts` (line ~206), after the existing Gemini-model injection block (the `if request.provider == "gemini" and request.model:` block, ~line 219-222) add:

```python
    # Inject per-request Vbee App-Id so the factory passes it to VbeeTTSProvider.
    if request.provider == "vbee" and request.app_id:
        tts_section = dict(effective_config.get("tts", {}))
        tts_section["vbee_app_id"] = request.app_id
        effective_config = {**effective_config, "tts": tts_section}
```

(The token already flows: the existing `if request.api_key:` block sets `tts_section[f"{request.provider}_api_key"]` → `vbee_api_key`.)

- [ ] **Step 3.6: Inject `vbee_app_id` in `start_tts`**

In `src/api/routers/tts.py`, `start_tts` (line ~34), after the existing Gemini-model injection block (`if request.provider == "gemini" and request.model:`, ~line 42-45) add:

```python
    # Inject per-request Vbee App-Id so run_tts's factory call sees it.
    if request.provider == "vbee" and request.app_id:
        tts_section = dict(config.get("tts", {}))
        tts_section["vbee_app_id"] = request.app_id
        config = {**config, "tts": tts_section}
```

- [ ] **Step 3.7: Generalise the token injection in `run_tts_track`**

In `src/tts/runner.py`, replace the provider-specific `api_key_override` block (lines ~210-218):

```python
    if api_key_override:
        tts_section = dict(config.get("tts", {}))
        if provider_name == "elevenlabs":
            tts_section["elevenlabs_api_key"] = api_key_override
        elif provider_name == "openai":
            tts_section["openai_api_key"] = api_key_override
        elif provider_name == "google":
            tts_section["google_api_key"] = api_key_override
        effective_config = {**config, "tts": tts_section}
```

with the generic form (covers vbee + gemini + any future provider; matches what `run_standalone_dub` already does):

```python
    if api_key_override:
        tts_section = dict(config.get("tts", {}))
        tts_section[f"{provider_name}_api_key"] = api_key_override
        effective_config = {**config, "tts": tts_section}
```

- [ ] **Step 3.8: Run the new tests to verify they pass**

Run: `python -m pytest tests/test_api_tts_vbee.py -v 2>&1 | tail -15`
Expected: 3 passed.

- [ ] **Step 3.9: Run the broader BE suite for regressions**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green (the runner-injection change must not break existing google/openai/elevenlabs key tests).

- [ ] **Step 3.10: Lint**

Run: `ruff check src/api/models.py src/api/routers/tts.py src/tts/runner.py tests/test_api_tts_vbee.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 3.11: Commit**

```bash
git add src/api/models.py src/api/routers/tts.py src/tts/runner.py tests/test_api_tts_vbee.py
git commit -m "feat(api): thread Vbee token + app_id through per-video/preview TTS

TTSRequest and TTSPreviewRequest gain optional app_id (ignored by other
providers). /api/tts/providers lists 'vbee'. start_tts and preview_tts
inject vbee_app_id into the tts config when provider=='vbee', mirroring
the Gemini-model injection. run_tts_track's api_key_override injection is
generalised to tts_section[f'{provider}_api_key'] so vbee's token reaches
the provider (also closes a latent gap for gemini per-video dubs). The
/api/tts/voices path already dispatches via the factory, so the curated
vbee voice list works for free. 3 router tests."
```

---

### Task 4: Standalone-dub + pipeline wiring (token + app_id)

**Files:**
- Modify: `src/api/models.py` (FullPipelineRequest, BatchPipelineRequest)
- Modify: `src/api/routers/pipeline.py` (full + batch dispatch + `_run_full_pipeline`/`_run_batch_pipeline` signatures + options)
- Modify: `src/pipeline.py` (inject vbee_app_id before run_tts_track)
- Modify: `src/api/routers/standalone_dub.py` (add `app_id` Form param)
- Modify: `src/api/task_manager.py` (`run_standalone_dub` gains `app_id` + injects it)

**Interfaces:**
- Consumes: factory from Task 2; `vbee_app_id` config key read by `VbeeTTSProvider`.
- Produces: `FullPipelineRequest.tts_app_id` / `BatchPipelineRequest.tts_app_id`; `run_standalone_dub(..., app_id=None)`; pipeline injects `tts_section["vbee_app_id"]` from `options["tts_app_id"]`.

- [ ] **Step 4.1: Add `tts_app_id` to pipeline request models**

In `src/api/models.py`, in `FullPipelineRequest`, after its `tts_model: str | None = None` line add:

```python
    tts_app_id: str | None = None  # Vbee App-Id; ignored by other providers
```

Add the identical line in `BatchPipelineRequest` after its `tts_model` field.

- [ ] **Step 4.2: Thread `tts_app_id` through the pipeline router**

In `src/api/routers/pipeline.py`:

(a) In `_run_full_pipeline`'s signature, after `tts_model: str | None = None,` add:
```python
    tts_app_id: str | None = None,
```

(b) In `_run_full_pipeline`'s `options = {...}` dict, after the `"tts_model": tts_model,` entry add:
```python
            "tts_app_id": tts_app_id,
```

(c) In the `start_full_pipeline` dispatch call to `_run_full_pipeline(...)`, after `tts_model=request.tts_model,` add:
```python
            tts_app_id=request.tts_app_id,
```

(d) In `_run_batch_pipeline`'s signature, after `tts_model: str | None = None,` add:
```python
    tts_app_id: str | None = None,
```

(e) In `_run_batch_pipeline`'s inner `_run_full_pipeline(...)` call (inside `process_one`), after `tts_model=tts_model,` add:
```python
                tts_app_id=tts_app_id,
```

(f) In the `start_batch_pipeline` dispatch call to `_run_batch_pipeline(...)`, after `tts_model=request.tts_model,` add:
```python
            tts_app_id=request.tts_app_id,
```

- [ ] **Step 4.3: Inject `vbee_app_id` in `src/pipeline.py`**

In `src/pipeline.py`, after the Gemini-model injection block (the `if tts_provider == "gemini" and tts_model:` block, ~line 253-256) add:

```python
                # Inject Vbee App-Id when the provider is vbee.
                tts_app_id = options.get("tts_app_id")
                if tts_provider == "vbee" and tts_app_id:
                    tts_section = dict(tts_config.get("tts", {}))
                    tts_section["vbee_app_id"] = tts_app_id
                    tts_config = {**tts_config, "tts": tts_section}
```

(The token already flows via `api_key_override=options.get("tts_api_key")` → `run_tts_track`'s now-generic injection from Task 3.)

- [ ] **Step 4.4: Add `app_id` to the standalone-dub route**

In `src/api/routers/standalone_dub.py`, find the route handler that already has `model: str | None = Form(None)`. Add an analogous param:

```python
    app_id: str | None = Form(None),
```

and pass it through to the `run_standalone_dub(...)` call by adding:

```python
        app_id=app_id,
```

- [ ] **Step 4.5: Inject `vbee_app_id` in `run_standalone_dub`**

In `src/api/task_manager.py`, `run_standalone_dub` (line ~733):

(a) Add to the signature after `model: str | None = None,`:
```python
        app_id: str | None = None,
```

(b) After the existing Gemini-model injection block (`if provider == "gemini" and model:`, ~line 804-807) add:
```python
            # Inject Vbee App-Id when the provider is vbee.
            if provider == "vbee" and app_id:
                tts_cfg = dict(effective_config.get("tts", {}))
                tts_cfg["vbee_app_id"] = app_id
                effective_config = {**effective_config, "tts": tts_cfg}
```

(The token already flows via the generic `tts_cfg[f"{provider}_api_key"] = api_key_override` already present in `run_standalone_dub`.)

- [ ] **Step 4.6: Verify the full BE suite stays green**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. (No new tests here — this is plumbing exercised by Task 3's preview test pattern and existing pipeline tests; a regression in the existing pipeline/standalone tests would catch a threading mistake.)

- [ ] **Step 4.7: Lint**

Run: `ruff check src/api/models.py src/api/routers/pipeline.py src/pipeline.py src/api/routers/standalone_dub.py src/api/task_manager.py 2>&1 | tail -3`
Expected: `All checks passed!` (pre-existing F401/E501 in `pipeline.py` unrelated to this diff are acceptable; do not introduce new ones).

- [ ] **Step 4.8: Commit**

```bash
git add src/api/models.py src/api/routers/pipeline.py src/pipeline.py src/api/routers/standalone_dub.py src/api/task_manager.py
git commit -m "feat(api): thread Vbee app_id through pipeline + standalone-dub paths

FullPipelineRequest and BatchPipelineRequest gain tts_app_id; the
pipeline router threads it into the options dict for both full and batch
runs, and src/pipeline.py injects vbee_app_id into the tts config before
run_tts_track when provider=='vbee'. The standalone-dub route gains an
app_id Form param that run_standalone_dub injects the same way. Tokens
flow via the already-generic {provider}_api_key injection. Mirrors the
Gemini-model threading exactly."
```

---

### Task 5: Document config keys

**Files:**
- Modify: `config/config.example.yaml`

- [ ] **Step 5.1: Add vbee keys under the `tts:` block**

In `config/config.example.yaml`, inside the `tts:` block (after the `gemini_model:` line), add:

```yaml
    # Vbee (vbee.vn / AIVoice) — Vietnamese TTS. Token + App-Id are entered
    # in the UI (Settings → API Keys); the per-request values override these.
    # app_id here is just an optional fallback default.
    vbee_app_id: ''
    vbee_default_voice: 'hn_female_ngochuyen_full_48k-fhg'
    # Optional output tuning (sane defaults baked into the provider):
    # vbee_bitrate: 128            # 8 | 16 | 32 | 64 | 128
    # vbee_sample_rate: 48000      # 8000..48000; omit to use the voice default
    # vbee_webhook_url: 'https://example.com/vbee-callback'  # required by API; we poll
```

- [ ] **Step 5.2: Sanity-check YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('config/config.example.yaml'))" && echo OK`
Expected: `OK`.

- [ ] **Step 5.3: Commit**

```bash
git add config/config.example.yaml
git commit -m "docs(config): document vbee_app_id + vbee_default_voice under tts

Adds the Vbee config keys with a comment noting the token + App-Id are
entered in the UI (per-request override wins); app_id in YAML is an
optional fallback. Output-tuning keys documented but commented out."
```

---

### Task 6: Settings — Vbee Token + App ID fields

**Files:**
- Modify: `ui-app/src/pages/settings/ApiKeysSection.tsx`
- Modify: `ui-app/src/utils/storage.ts`

**Interfaces:**
- Produces: localStorage keys `api_key_vbee` (token) and `api_key_vbee_app_id`; `LLMApiKeys` gains `vbee` + `vbee_app_id`; `loadApiKeys()` returns both.

- [ ] **Step 6.1: Add the two fields to the Settings PROVIDERS array**

In `ui-app/src/pages/settings/ApiKeysSection.tsx`, find the `PROVIDERS` array (the entries like `{ key: 'google', label: 'Google Cloud', ... }`). After the `google` entry add:

```tsx
  { key: 'vbee', label: 'Vbee Token', placeholder: 'Bearer access token', icon: 'graphic_eq' },
  { key: 'vbee_app_id', label: 'Vbee App ID', placeholder: 'app-id UUID', icon: 'badge' },
```

- [ ] **Step 6.2: Add both to the storage types + loader**

In `ui-app/src/utils/storage.ts`, in the `LLMApiKeys` interface add (after `google: string;`):

```ts
  vbee: string;
  vbee_app_id: string;
```

And in `loadApiKeys()` add (after the `google: storageGet('api_key_google'),` line):

```ts
    vbee: storageGet('api_key_vbee'),
    vbee_app_id: storageGet('api_key_vbee_app_id'),
```

- [ ] **Step 6.3: Typecheck + lint the touched files**

Run (from repo root):
```bash
cd ui-app && npx tsc --noEmit 2>&1 | grep -E "(ApiKeysSection|storage)" | head -5; npx eslint src/pages/settings/ApiKeysSection.tsx src/utils/storage.ts 2>&1 | tail -3
```
Expected: no errors referencing these files.

- [ ] **Step 6.4: Commit**

```bash
git add ui-app/src/pages/settings/ApiKeysSection.tsx ui-app/src/utils/storage.ts
git commit -m "feat(settings): Vbee Token + App ID key fields

Two new entries in the Settings API-keys list (Vbee Token, Vbee App ID),
stored as api_key_vbee / api_key_vbee_app_id. LLMApiKeys + loadApiKeys
gain both. Renders as password fields via the existing array-driven UI."
```

---

### Task 7: Frontend — provider wiring + custom voiceCode

**Files:**
- Modify: `ui-app/src/api/client.ts` (postTTS, postPipeline ttsOverrides type)
- Modify: `ui-app/src/api/standaloneDub.ts` (app_id Form field)
- Modify: `ui-app/src/pages/VideoDetail.tsx` (pass app_id to postTTS for DubTab)
- Modify: `ui-app/src/pages/DubStudio.tsx` (app_id + custom voiceCode)
- Modify: `ui-app/src/pages/DownloadTranscribe.tsx` (vbee api-key arm + app_id + custom voiceCode)

**Interfaces:**
- Consumes: `apiKeys.vbee` + `apiKeys.vbee_app_id` from Task 6; `/api/tts/voices?provider=vbee` from Task 3.
- Produces: every dub entry point sends `apiKeys.vbee` as the TTS api key and `apiKeys.vbee_app_id` as `app_id`/`tts_app_id` when provider is `vbee`, plus an optional custom voiceCode that overrides the dropdown selection.

- [ ] **Step 7.1: `client.ts` — add `appId` to `postTTS` + `tts_app_id` to `postPipeline`**

In `ui-app/src/api/client.ts`, `postTTS` (line ~276): add a parameter after `model?: string,`:

```ts
  appId?: string,
```

and in its JSON body (after the `...(model ? { model } : {}),` line) add:

```ts
      ...(appId ? { app_id: appId } : {}),
```

In `postPipeline`'s `ttsOverrides` type (line ~226), after `tts_model?: string;` add:

```ts
    tts_app_id?: string;
```

and in the POST body (after `tts_model: ttsOverrides?.tts_model ?? null,`, line ~250) add:

```ts
      tts_app_id: ttsOverrides?.tts_app_id ?? null,
```

- [ ] **Step 7.2: `standaloneDub.ts` — add `appId` Form field**

In `ui-app/src/api/standaloneDub.ts`, add `appId?: string;` to the options type (after `model?: string;`, line ~26), and after the `if (opts.model) formData.append('model', opts.model);` line (~42) add:

```ts
  if (opts.appId) formData.append('app_id', opts.appId);
```

- [ ] **Step 7.3: `VideoDetail.tsx` — pass app_id to `postTTS`**

In `ui-app/src/pages/VideoDetail.tsx`, find the `postTTS(...)` call. It currently passes the Gemini model as the last arg (`provider === 'gemini' ? geminiModel : undefined`). Add the app_id argument right after it:

```tsx
      provider === 'vbee' ? apiKeys.vbee_app_id : undefined,
```

Ensure the TTS api key passed to `postTTS` resolves `apiKeys.vbee` when `provider === 'vbee'` — find the api-key resolution expression used for the `apiKey` argument and add a `vbee` arm:

```tsx
      provider === 'vbee' ? apiKeys.vbee :
```

(Insert into the existing `provider === 'gemini' ? apiKeys.gemini : ... ` chain.)

- [ ] **Step 7.4: `DubStudio.tsx` — app_id + custom voiceCode**

In `ui-app/src/pages/DubStudio.tsx`:

(a) Add a custom-voice state near the other `useState`s:
```tsx
  const [vbeeCustomVoice, setVbeeCustomVoice] = useState('');
```

(b) In the `postStandaloneDub({...})` call (line ~244), the existing `voice: voiceId,` becomes a vbee-aware value, and add `appId`:
```tsx
        voice: provider === 'vbee' && vbeeCustomVoice.trim() ? vbeeCustomVoice.trim() : voiceId,
        appId: provider === 'vbee' ? apiKeys.vbee_app_id : undefined,
```
(If `apiKeys` isn't already loaded in this component, load it via `loadApiKeys()` as the other pages do; the api key passed to `postStandaloneDub` must also use `apiKeys.vbee` when `provider === 'vbee'` — add a `vbee` arm to the existing key resolution.)

(c) Render a custom-voice input shown only for vbee, directly under the voice dropdown (the `value={voiceId}` select near line ~442):
```tsx
        {provider === 'vbee' && (
          <input
            type="text"
            value={vbeeCustomVoice}
            onChange={(e) => setVbeeCustomVoice(e.target.value)}
            placeholder="Custom voiceCode (optional, overrides dropdown)"
            className="w-full bg-surface-container-lowest border border-outline-variant/20 focus:border-primary/50 focus:ring-0 rounded p-2 text-xs font-mono mt-2"
          />
        )}
```

- [ ] **Step 7.5: `DownloadTranscribe.tsx` — vbee api-key arm + app_id + custom voiceCode**

In `ui-app/src/pages/DownloadTranscribe.tsx`:

(a) In the api-key resolution chain (the `ttsProviderName === 'gemini' ? apiKeys.gemini : ...` block), add a `vbee` arm:
```tsx
      ttsProviderName === 'vbee' ? apiKeys.vbee :
```

(b) Add a custom-voice state alongside the other pipeline-config `useState`s:
```tsx
  const [vbeeCustomVoice, setVbeeCustomVoice] = useState('');
```

(c) In the `ttsOverrides` object (where `tts_model` is set), add the app_id and let the custom voice override `tts_voice`:
```tsx
      ...(selectedTtsProvider === 'vbee' ? { tts_app_id: apiKeys.vbee_app_id } : {}),
```
and where `tts_voice` is assigned, use `selectedTtsProvider === 'vbee' && vbeeCustomVoice.trim() ? vbeeCustomVoice.trim() : (ttsVoiceId || undefined)`.

(d) Render the custom-voice input under the voice picker, gated on `selectedTtsProvider === 'vbee'` (same JSX shape as Step 7.4c).

- [ ] **Step 7.6: Typecheck + lint touched FE files**

Run (from repo root):
```bash
cd ui-app && npx tsc --noEmit 2>&1 | grep -E "(client|standaloneDub|VideoDetail|DubStudio|DownloadTranscribe)" | head -10; npx eslint src/api/client.ts src/api/standaloneDub.ts src/pages/VideoDetail.tsx src/pages/DubStudio.tsx src/pages/DownloadTranscribe.tsx 2>&1 | tail -5
```
Expected: no NEW errors in these files (pre-existing `set-state-in-effect` warnings in `DownloadTranscribe.tsx` / `VideoDetail.tsx` are acceptable; do not add new ones).

- [ ] **Step 7.7: Commit**

```bash
git add ui-app/src/api/client.ts ui-app/src/api/standaloneDub.ts ui-app/src/pages/VideoDetail.tsx ui-app/src/pages/DubStudio.tsx ui-app/src/pages/DownloadTranscribe.tsx
git commit -m "feat(ui): wire Vbee provider — token, app_id, custom voiceCode

postTTS gains an appId arg (-> app_id body field); postPipeline's
ttsOverrides + standaloneDub gain app_id. DubTab (via VideoDetail),
DubStudio, and the Pipeline page each resolve apiKeys.vbee as the TTS
key, send apiKeys.vbee_app_id as app_id/tts_app_id when provider is
vbee, and expose a free-text Custom voiceCode input that overrides the
curated dropdown selection."
```

---

### Task 8: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 8.1: CHANGELOG entry**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Added`, add at the top:

```markdown
- **Vbee TTS provider (Vietnamese).** New `VbeeTTSProvider` (`src/tts/vbee_tts.py`) integrates vbee.vn / AIVoice. Vbee's synthesis is asynchronous (POST `/v1/tts` mode=async → poll `GET /v1/tts/requests/{id}` until `COMPLETED` → download the `audioLink` mp3); the whole flow is hidden inside `synthesize()` so the assembler/planner/runner/preview are unchanged. Two-secret auth (Bearer token + `App-Id` header): the token rides the existing api-key rail, the `app_id` rides the per-request config-injection rail used for Gemini's model. Surface: "Vbee (Vietnamese)" in the provider dropdown; curated Vietnamese voice list plus a free-text custom voiceCode input; new "Vbee Token" + "Vbee App ID" Settings fields. `429` gets bounded retry; `FAILED`/timeout/HTTP errors fall back to source audio via the assembler's existing `needs_review` path. Config: `tts.vbee_app_id` / `tts.vbee_default_voice` documented in `config.example.yaml`. 15 new tests (11 provider + 1 factory + 3 router).
```

- [ ] **Step 8.2: README progress entry**

In `README.md`, find the most recent dated subsection under Implementation Progress. Immediately after its trailing `---`, insert:

```markdown
### Vbee TTS provider — Vietnamese (2026-06-20)

> Adds vbee.vn / AIVoice as a TTS provider, hiding its async submit→poll→download API behind the synchronous `synthesize()` contract. See [`docs/superpowers/specs/2026-06-20-vbee-tts-provider-design.md`](docs/superpowers/specs/2026-06-20-vbee-tts-provider-design.md) and [`docs/superpowers/plans/2026-06-20-vbee-tts-provider.md`](docs/superpowers/plans/2026-06-20-vbee-tts-provider.md).

- [x] **Task 1** — `src/tts/vbee_tts.py::VbeeTTSProvider`: async submit/poll/download behind `synthesize()`; curated Vietnamese voices; speed clamp; 11 unit tests.
- [x] **Task 2** — Factory branch in `src/tts/__init__.py`. 1 test.
- [x] **Task 3** — `app_id` on TTSRequest/TTSPreviewRequest; `/api/tts/providers` lists vbee; start_tts/preview_tts inject `vbee_app_id`; `run_tts_track` token injection generalised. 3 router tests.
- [x] **Task 4** — `tts_app_id` threaded through pipeline (full + batch) + standalone dub.
- [x] **Task 5** — `config.example.yaml` documents `vbee_app_id` / `vbee_default_voice`.
- [x] **Task 6** — Settings "Vbee Token" + "Vbee App ID" fields.
- [x] **Task 7** — FE wiring: api-key arm, app_id, custom voiceCode on DubTab / DubStudio / Pipeline.
- [x] **Task 8** — CHANGELOG + README rollup.

---
```

- [ ] **Step 8.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(vbee-tts): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. +15 tests over baseline (11 provider + 1 factory + 3 router).

- [ ] **Step F.2: BE lint on every touched file**

```bash
ruff check src/tts/vbee_tts.py src/tts/__init__.py src/tts/runner.py \
  src/api/models.py src/api/routers/tts.py src/api/routers/pipeline.py \
  src/api/routers/standalone_dub.py src/api/task_manager.py src/pipeline.py \
  tests/test_vbee_tts.py tests/test_tts_factory_vbee.py tests/test_api_tts_vbee.py \
  2>&1 | tail -3
```
Expected: `All checks passed!` (pre-existing F401/E501 in `pipeline.py`/`task_manager.py` unrelated to this work are acceptable; no NEW issues).

- [ ] **Step F.3: FE typecheck + lint on touched files**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -5
npx eslint src/api/client.ts src/api/standaloneDub.ts src/utils/storage.ts \
  src/pages/settings/ApiKeysSection.tsx src/pages/VideoDetail.tsx \
  src/pages/DubStudio.tsx src/pages/DownloadTranscribe.tsx 2>&1 | tail -5
```
Expected: no new errors on touched files.

- [ ] **Step F.4: Manual smoke (user, real credentials)**

1. Settings → enter **Vbee Token** + **Vbee App ID** → Save → reload persists.
2. Dub Studio → provider "Vbee (Vietnamese)" → voice dropdown populates with curated voices.
3. Preview a Vietnamese sentence → audio plays; network shows `api.vbee.vn/v1/tts` submit + `.../requests/{id}` polls + audioLink download.
4. Enter a custom voiceCode → preview uses it (overrides dropdown).
5. Per-video dub (DubTab) with provider=vbee → final WAV plays; dubsync SRT saved.
6. Pipeline page with provider=vbee → full run produces the Vietnamese dub.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: provider (T1), factory (T2), per-video/preview/voices + token (T3), pipeline/standalone (T4), config (T5), Settings (T6), FE wiring + custom voice (T7), docs (T8). All spec sections mapped.
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere — code shown in every code step.
- [ ] Name consistency: `VbeeTTSProvider`, `vbee_api_key`, `vbee_app_id`, provider id `"vbee"`, request fields `app_id` (TTS/preview) and `tts_app_id` (pipeline), localStorage `api_key_vbee` / `api_key_vbee_app_id` — used identically across tasks.
- [ ] Async hidden inside `synthesize()`; no assembler/planner/base changes.
- [ ] Token via generic `{provider}_api_key` injection (runner generalised in T3); app_id via per-request config injection mirroring Gemini's model.
- [ ] All work on `feature/vbee-tts-provider`; no AI attribution in commit messages.
- [ ] CHANGELOG under `Added` in `[Unreleased]`; README entry beside other dated subsections.
```
