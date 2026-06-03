# Gemini TTS Provider — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GeminiTTSProvider` — a new TTS provider that calls Google's Gemini Audio Generation API (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`) — alongside the existing legacy `GoogleTTSProvider`. The user picks model (Gemini 2.5 Flash TTS vs Pro TTS) from a model dropdown that only renders when Gemini is the selected provider.

**Architecture:** New `src/tts/gemini_tts.py` mirroring `google_tts.py`. Factory in `src/tts/__init__.py` gets a new branch. API request models gain optional `model` field that's threaded into the config dict. Backend `/api/tts/providers` returns a new entry. Voices endpoint dispatches to the new provider's static voice list. Frontend gets the new provider option automatically (the list comes from the BE), plus a model dropdown that renders conditionally for `provider === 'gemini'`, plus a separate API key field on Settings.

**Tech Stack:** Python 3.11, httpx (already a dep), pytest + `unittest.mock.AsyncMock`, FastAPI, React 19, Vitest (FE optional). No new dependencies.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `src/tts/gemini_tts.py` | `GeminiTTSProvider` class — synthesise PCM via Gemini API, wrap to WAV in-memory, static voice list. | **Create** |
| `tests/test_gemini_tts.py` | 5 unit tests (voices_static, voices_ignores_lang, synth_no_key, synth_happy_path, synth_empty_inlinedata). | **Create** |
| `src/tts/__init__.py` | Factory: add `gemini` branch reading `gemini_api_key` + `gemini_model` from `tts_config`. | **Modify** |
| `tests/test_tts_factory_gemini.py` | 2 factory tests (default model, model override). | **Create** |
| `src/api/models.py` | `TTSRequest` and `TTSPreviewRequest` gain `model: str | None = None`. | **Modify** |
| `src/api/routers/tts.py` | `/api/tts/providers` adds gemini entry. `start_tts` and `preview_tts` inject `gemini_model` into `tts_section` when `provider == "gemini"`. | **Modify** |
| `tests/test_api_tts_gemini.py` | 3 router tests (providers-list contains gemini; voices endpoint returns gemini list; model threaded into config). | **Create** |
| `config/config.example.yaml` | Documents `tts.gemini_api_key` and `tts.gemini_model`. | **Modify** |
| `ui-app/src/pages/settings/ApiKeysSection.tsx` | New `gemini` key entry alongside google/openai/elevenlabs. | **Modify** |
| `ui-app/src/constants/geminiModels.ts` | `GEMINI_TTS_MODELS` constant list shared across pages. | **Create** |
| `ui-app/src/pages/videoDetail/DubTab.tsx` | Gemini-only model dropdown above voice picker; thread `model` through TTS calls. | **Modify** |
| `ui-app/src/pages/DubStudio.tsx` | Same model dropdown + threading. | **Modify** |
| `ui-app/src/pages/DownloadTranscribe.tsx` | Same model dropdown + threading. | **Modify** |
| `ui-app/src/api/client.ts` | `runTts` / `previewTts` payload types gain optional `model`. | **Modify** |
| `CHANGELOG.md` | `Added` entry under `[Unreleased]`. | **Modify** |
| `README.md` | New dated subsection. | **Modify** |

---

### Task 1: `GeminiTTSProvider` + 5 unit tests

**Files:**
- Create: `src/tts/gemini_tts.py`
- Create: `tests/test_gemini_tts.py`

- [ ] **Step 1.1: Write the failing tests**

Create `tests/test_gemini_tts.py`:

```python
"""Unit tests for the Gemini TTS provider.

GeminiTTSProvider calls generativelanguage.googleapis.com/v1beta/models/
{model}:generateContent with responseModalities=AUDIO, parses the
base64 PCM from candidates[0].content.parts[0].inlineData.data, and
wraps the raw PCM into a WAV container (24 kHz mono s16le) so the
assembler reads it through ffmpeg like any other provider's output.
"""

from __future__ import annotations

import base64
import struct
from unittest.mock import AsyncMock, patch

import pytest

from src.tts.gemini_tts import GeminiTTSProvider


class TestVoices:
    @pytest.mark.asyncio
    async def test_voices_static_list(self):
        p = GeminiTTSProvider({"gemini_api_key": "x"})
        voices = await p.list_voices()
        assert len(voices) == len(GeminiTTSProvider.VOICES)
        for v in voices:
            assert v["provider"] == "gemini"
            assert v["gender"] == "neutral"
            assert v["language"] == ""
            assert v["name"] == v["friendly_name"]
            assert v["name"] in GeminiTTSProvider.VOICES

    @pytest.mark.asyncio
    async def test_voices_ignores_language_filter(self):
        p = GeminiTTSProvider({"gemini_api_key": "x"})
        all_voices = await p.list_voices(language=None)
        vi_voices = await p.list_voices(language="vi")
        assert len(all_voices) == len(vi_voices)


class TestSynthesize:
    @pytest.mark.asyncio
    async def test_synthesize_no_api_key_raises(self):
        p = GeminiTTSProvider({})
        with pytest.raises(ValueError, match="Gemini API key not configured"):
            await p.synthesize("hello", "Kore")

    @pytest.mark.asyncio
    async def test_synthesize_happy_path_wraps_pcm_to_wav(self):
        # Fake PCM payload: 100 bytes of silence.
        pcm = b"\x00" * 100
        response_json = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"data": base64.b64encode(pcm).decode()}}
                        ]
                    }
                }
            ]
        }

        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: response_json

        p = GeminiTTSProvider({"gemini_api_key": "k", "gemini_model": "gemini-2.5-flash-preview-tts"})

        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            result = await p.synthesize("hello", "Kore")

        # WAV header: RIFF...WAVE...fmt ...data + PCM
        assert result[:4] == b"RIFF"
        assert result[8:12] == b"WAVE"
        # File size in bytes (header[4:8]) = total length - 8
        assert struct.unpack("<I", result[4:8])[0] == len(result) - 8
        # Sample rate at offset 24 = 24000
        assert struct.unpack("<I", result[24:28])[0] == 24000
        # Channels at offset 22 = 1
        assert struct.unpack("<H", result[22:24])[0] == 1
        # Bits-per-sample at offset 34 = 16
        assert struct.unpack("<H", result[34:36])[0] == 16
        # Data chunk size at offset 40 = len(pcm)
        assert struct.unpack("<I", result[40:44])[0] == len(pcm)
        # PCM follows the 44-byte header
        assert result[44:] == pcm

    @pytest.mark.asyncio
    async def test_synthesize_empty_inlinedata_raises(self):
        response_json = {"candidates": [{"content": {"parts": [{}]}}]}
        mock_response = AsyncMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json = lambda: response_json

        p = GeminiTTSProvider({"gemini_api_key": "k"})
        with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=mock_response)):
            with pytest.raises(RuntimeError, match="empty audio"):
                await p.synthesize("hello", "Kore")
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `python -m pytest tests/test_gemini_tts.py -v 2>&1 | tail -10`
Expected: `ModuleNotFoundError: No module named 'src.tts.gemini_tts'`

- [ ] **Step 1.3: Create `src/tts/gemini_tts.py`**

```python
"""Google Gemini TTS provider — uses the Generative Language Audio API."""

from __future__ import annotations

import base64
import struct

import httpx

from src.tts.base import BaseTTSProvider
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def _wrap_pcm_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit PCM bytes in a minimal RIFF/WAVE header.

    Gemini returns 24 kHz mono signed 16-bit little-endian PCM. The
    assembler reads everything through ffmpeg, which is happy to consume
    a WAV but won't recognise headerless PCM. This 44-byte prefix is the
    standard PCM/WAVE header.
    """
    byte_rate = sample_rate * channels * 2
    block_align = channels * 2
    data_size = len(pcm)
    fmt_chunk_size = 16
    riff_size = 4 + (8 + fmt_chunk_size) + (8 + data_size)

    header = b"".join([
        b"RIFF",
        struct.pack("<I", riff_size),
        b"WAVE",
        b"fmt ",
        struct.pack("<I", fmt_chunk_size),
        struct.pack("<H", 1),              # PCM format
        struct.pack("<H", channels),
        struct.pack("<I", sample_rate),
        struct.pack("<I", byte_rate),
        struct.pack("<H", block_align),
        struct.pack("<H", 16),             # bits per sample
        b"data",
        struct.pack("<I", data_size),
    ])
    return header + pcm


class GeminiTTSProvider(BaseTTSProvider):
    """TTS provider using Google's Gemini Audio Generation API.

    Distinct from `GoogleTTSProvider`, which calls the legacy Cloud TTS
    endpoint. Gemini takes an explicit model ID per request and a
    prebuilt voice name from a small static set; output is 24 kHz mono
    PCM that we wrap into a WAV container in-memory.
    """

    DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    # Prebuilt voice names from the Gemini docs. Not language-locked.
    VOICES: tuple[str, ...] = (
        "Aoede", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus",
        "Zephyr", "Achernar", "Algenib", "Algieba", "Alnilam", "Autonoe",
        "Callirrhoe", "Despina", "Enceladus", "Erinome", "Gacrux",
        "Iapetus", "Laomedeia", "Pulcherrima", "Rasalgethi", "Sadachbia",
        "Sadaltager", "Schedar", "Sulafat", "Umbriel", "Vindemiatrix",
        "Zubenelgenubi",
    )

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key: str = config.get("gemini_api_key", "")
        self.model: str = config.get("gemini_model", self.DEFAULT_MODEL)

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        if not self.api_key:
            raise ValueError("Gemini API key not configured for TTS")

        body = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {"voiceName": voice}
                    }
                },
            },
        }

        url = f"{self.BASE_URL}/models/{self.model}:generateContent"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                params={"key": self.api_key},
                json=body,
            )
            response.raise_for_status()
            data = response.json()

        try:
            inline_data = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            audio_b64 = inline_data["data"]
        except (KeyError, IndexError, TypeError):
            audio_b64 = ""

        if not audio_b64:
            raise RuntimeError("Gemini TTS returned empty audio")

        pcm = base64.b64decode(audio_b64)
        return _wrap_pcm_to_wav(pcm)

    async def list_voices(self, language: str | None = None) -> list[dict]:
        """Static prebuilt voice list. `language` is accepted for ABC
        compatibility but ignored — Gemini voices are not language-locked."""
        return [
            {
                "name": name,
                "language": "",
                "gender": "neutral",
                "provider": "gemini",
                "friendly_name": name,
            }
            for name in self.VOICES
        ]
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_gemini_tts.py -v 2>&1 | tail -12`
Expected: 5 passed.

- [ ] **Step 1.5: Lint clean**

Run: `ruff check src/tts/gemini_tts.py tests/test_gemini_tts.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 1.6: Commit**

```bash
git add src/tts/gemini_tts.py tests/test_gemini_tts.py
git commit -m "feat(tts): Gemini Audio Generation provider

GeminiTTSProvider calls generativelanguage.googleapis.com/v1beta/
models/{model}:generateContent with responseModalities=AUDIO and a
prebuilt voice config. Response payload is base64-encoded 24 kHz mono
s16le PCM under candidates[0].content.parts[0].inlineData.data — we
wrap it in a 44-byte RIFF/WAVE header so the assembler reads it
through ffmpeg like any other provider's output.

list_voices() returns the 29 prebuilt voice names from the Gemini
docs (Aoede, Puck, Charon, Kore, etc.). Voices are not language-
locked; the language arg is accepted for ABC compatibility but
ignored. 5 unit tests cover the static list, language-filter no-op,
missing-key error, happy-path WAV wrap (header bytes verified), and
empty-inlineData error."
```

---

### Task 2: Factory wire-up + 2 tests

**Files:**
- Modify: `src/tts/__init__.py`
- Create: `tests/test_tts_factory_gemini.py`

- [ ] **Step 2.1: Write the failing tests**

Create `tests/test_tts_factory_gemini.py`:

```python
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
```

- [ ] **Step 2.2: Run to verify they fail**

Run: `python -m pytest tests/test_tts_factory_gemini.py -v 2>&1 | tail -10`
Expected: `ValueError: Unknown TTS provider: gemini`.

- [ ] **Step 2.3: Add the gemini branch to `src/tts/__init__.py`**

Find the current factory (after the `openai` branch, around line 39). Insert a new elif branch BEFORE the `else: raise ValueError(...)`:

```python
    elif provider_name == "gemini":
        from src.tts.gemini_tts import GeminiTTSProvider

        logger.info(f"Using Gemini TTS provider (model={tts_config.get('gemini_model', GeminiTTSProvider.DEFAULT_MODEL)})")
        return GeminiTTSProvider(config=tts_config)
```

- [ ] **Step 2.4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tts_factory_gemini.py -v 2>&1 | tail -10`
Expected: 2 passed.

- [ ] **Step 2.5: Lint**

Run: `ruff check src/tts/__init__.py tests/test_tts_factory_gemini.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 2.6: Commit**

```bash
git add src/tts/__init__.py tests/test_tts_factory_gemini.py
git commit -m "feat(tts): wire GeminiTTSProvider through get_tts_provider

get_tts_provider gains a 'gemini' branch that imports and constructs
GeminiTTSProvider with the full tts_config dict (the provider reads
gemini_api_key and gemini_model from it directly, same pattern as
GoogleTTSProvider's google_api_key lookup). Logs the model in use,
mirroring how the elevenlabs and openai branches log theirs.

2 factory tests: default model when only the API key is set;
respects an explicit gemini_model override."
```

---

### Task 3: API router + request model + 3 tests

**Files:**
- Modify: `src/api/models.py`
- Modify: `src/api/routers/tts.py`
- Create: `tests/test_api_tts_gemini.py`

- [ ] **Step 3.1: Write the failing tests**

Create `tests/test_api_tts_gemini.py`:

```python
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
    async def fake_synth(text, voice, **kw):
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
```

- [ ] **Step 3.2: Run to verify they fail**

Run: `python -m pytest tests/test_api_tts_gemini.py -v 2>&1 | tail -15`
Expected: failures — providers list doesn't include gemini; voices route 400/500s on unknown provider; model field doesn't exist on TTSPreviewRequest.

- [ ] **Step 3.3: Add `model` field to request models**

In `src/api/models.py`, find `TTSRequest` (around line 230) and `TTSPreviewRequest` (around line 255). Add `model: str | None = None  # Gemini model ID; ignored by other providers` to both, placed near the existing `provider:` field.

For example, `TTSRequest`:
```python
class TTSRequest(BaseModel):
    video_id: str
    language: str = "vi"
    voice: str = "vi-VN-Wavenet-A"
    provider: str = "google"  # google | elevenlabs | openai | gemini (FE picks)
    model: str | None = None  # Gemini model ID; ignored by other providers
    api_key: str | None = None
    # ... rest unchanged
```

Same shape for `TTSPreviewRequest`. (Match the exact existing field ordering — just add the new line right after the `provider:` field.)

- [ ] **Step 3.4: Update `/api/tts/providers` to include gemini**

In `src/api/routers/tts.py`, line 84:

```python
@router.get("/api/tts/providers")
async def list_providers():
    """List available TTS providers."""
    return [
        {"id": "google", "name": "Google Cloud TTS", "free": False, "requires_key": True},
        {"id": "gemini", "name": "Gemini TTS", "free": False, "requires_key": True},
        {"id": "elevenlabs", "name": "ElevenLabs", "free": False, "requires_key": True},
        {"id": "openai", "name": "OpenAI TTS", "free": False, "requires_key": True},
    ]
```

- [ ] **Step 3.5: Inject `gemini_model` into the config in `preview_tts`**

In `src/api/routers/tts.py`, find the `preview_tts` body (around line 186). After the existing api_key-injection block (lines 193-198), add an analogous model-injection block:

```python
    # Inject per-request API key for paid providers
    effective_config = config
    if request.api_key:
        tts_section = dict(config.get("tts", {}))
        tts_section[f"{request.provider}_api_key"] = request.api_key
        effective_config = {**config, "tts": tts_section}

    # Inject per-request Gemini model
    if request.provider == "gemini" and request.model:
        tts_section = dict(effective_config.get("tts", {}))
        tts_section["gemini_model"] = request.model
        effective_config = {**effective_config, "tts": tts_section}
```

- [ ] **Step 3.6: Inject `gemini_model` into the config in `start_tts`**

In `src/api/routers/tts.py`, find `start_tts` (line 32). The current implementation passes `config` directly to `tm.run_tts`. Add an injection block before the `task._asyncio_task = ...` line:

```python
    # Inject per-request Gemini model into config so run_tts sees it.
    if request.provider == "gemini" and request.model:
        tts_section = dict(config.get("tts", {}))
        tts_section["gemini_model"] = request.model
        config = {**config, "tts": tts_section}
```

(`config` is a local fetched from `get_config()` at the top of the function; reassigning the local doesn't mutate the cached singleton.)

- [ ] **Step 3.7: Run tests to verify they pass**

Run: `python -m pytest tests/test_api_tts_gemini.py -v 2>&1 | tail -15`
Expected: 3 passed.

- [ ] **Step 3.8: Run the full BE suite (sanity)**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -8`
Expected: green. +10 new tests over baseline (5 provider + 2 factory + 3 router).

- [ ] **Step 3.9: Lint**

Run: `ruff check src/api/models.py src/api/routers/tts.py tests/test_api_tts_gemini.py 2>&1 | tail -3`
Expected: `All checks passed!`

- [ ] **Step 3.10: Commit**

```bash
git add src/api/models.py src/api/routers/tts.py tests/test_api_tts_gemini.py
git commit -m "feat(api): expose Gemini TTS provider + thread model field

TTSRequest and TTSPreviewRequest gain optional 'model: str | None'
that's ignored by every provider except Gemini. /api/tts/providers
returns a new {id: 'gemini', ...} entry alongside google/openai/
elevenlabs so the FE dropdown picks it up automatically.

Both start_tts and preview_tts now inject 'gemini_model' into the
'tts' section of the config dict when provider=='gemini' and the
request carries a model — mirroring how api_key is injected today.
The factory then reads gemini_model out of that section to build
GeminiTTSProvider with the right model. /api/tts/voices already
dispatches via the factory, so the gemini voice list works for free
once the factory branch from Task 2 is in.

3 router tests: providers list contains gemini, voices endpoint
returns the 29 static voices, and a preview request with model
overrides reaches the provider with .model set correctly."
```

---

### Task 4: Document `gemini_api_key` + `gemini_model` in config example

**Files:**
- Modify: `config/config.example.yaml`

- [ ] **Step 4.1: Find the `tts:` block**

Read `config/config.example.yaml` — locate the `tts:` block (it contains keys like `default_provider:`, `google_api_key:`, `elevenlabs_api_key:`, `openai_api_key:`).

- [ ] **Step 4.2: Append Gemini keys**

Add these lines inside the `tts:` block, after the existing `google_api_key:` line (matching the surrounding indentation):

```yaml
    # Gemini Audio Generation API (separate from Google Cloud TTS).
    # Uses a Google AI Studio API key — enable the Generative Language
    # API in your AI Studio project, NOT the same key as google_api_key.
    gemini_api_key: ''
    # Default Gemini TTS model. Per-request override via the API/UI.
    gemini_model: 'gemini-2.5-flash-preview-tts'
```

- [ ] **Step 4.3: Commit**

```bash
git add config/config.example.yaml
git commit -m "docs(config): document gemini_api_key + gemini_model under tts:

Adds the two new keys with a comment clarifying that the Gemini
audio API uses a Google AI Studio key (not the same Cloud Console
key as google_api_key). Default model is the flash preview."
```

---

### Task 5: Settings — Gemini API key field

**Files:**
- Modify: `ui-app/src/pages/settings/ApiKeysSection.tsx`

- [ ] **Step 5.1: Read the current API_KEYS array**

Open `ui-app/src/pages/settings/ApiKeysSection.tsx`. The file defines an array of provider entries — currently `openai`, `elevenlabs`, `google`. Each entry has shape `{ key, label, placeholder, icon }`.

- [ ] **Step 5.2: Add the gemini entry**

Insert a new entry immediately after the `google` entry:

```ts
  { key: 'gemini', label: 'Gemini (Google AI Studio)', placeholder: 'AIza...', icon: 'auto_awesome' },
```

- [ ] **Step 5.3: Verify the storage key matches the BE expectation**

The Settings page persists each key as `apiKeys.<key>` in localStorage. The provider-name → storage-key mapping in the dub forms expects `gemini` to align with the backend's `gemini_api_key`. Search the codebase for `'google'` → `apiKeys.google`-style usage to confirm the pattern, then ensure `apiKeys.gemini` flows the same way. (Existing code: `DownloadTranscribe.tsx:233` reads `apiKeys.google`; `DubTab.tsx` does the same lookup. We'll wire the same pattern for `apiKeys.gemini` in Task 6.)

- [ ] **Step 5.4: Commit**

```bash
git add ui-app/src/pages/settings/ApiKeysSection.tsx
git commit -m "feat(settings): Gemini API key field

Adds a fourth API-key input on the Settings page (Gemini, AI Studio).
Persists to apiKeys.gemini in localStorage; dub forms read it through
the same mapping path google/openai/elevenlabs already use."
```

---

### Task 6: Frontend — model dropdown + provider-aware API key wiring

**Files:**
- Create: `ui-app/src/constants/geminiModels.ts`
- Modify: `ui-app/src/api/client.ts`
- Modify: `ui-app/src/pages/videoDetail/DubTab.tsx`
- Modify: `ui-app/src/pages/DubStudio.tsx`
- Modify: `ui-app/src/pages/DownloadTranscribe.tsx`

- [ ] **Step 6.1: Create the shared models constant**

Create `ui-app/src/constants/geminiModels.ts`:

```ts
export const GEMINI_TTS_MODELS = [
  { id: 'gemini-2.5-flash-preview-tts', label: 'Gemini 2.5 Flash (faster, cheaper)' },
  { id: 'gemini-2.5-pro-preview-tts',   label: 'Gemini 2.5 Pro (higher quality)' },
] as const;

export type GeminiTTSModelId = (typeof GEMINI_TTS_MODELS)[number]['id'];

export const DEFAULT_GEMINI_TTS_MODEL: GeminiTTSModelId = 'gemini-2.5-flash-preview-tts';

/** localStorage key that holds the user's last picked Gemini model. */
export const GEMINI_MODEL_STORAGE_KEY = 'gemini_tts_model';
```

- [ ] **Step 6.2: Add `model?: string` to the TTS API client types**

Open `ui-app/src/api/client.ts`. Find the `runTts` / `startTts` / `previewTts` request types or function signatures (search for `provider:` in this file). For each TTS-call helper, add `model?: string` to its payload interface.

Concretely, if `previewTts` body shape is something like:
```ts
{ text, voice, provider, speed, pitch, playback_speed, api_key }
```
Update to:
```ts
{ text, voice, provider, speed, pitch, playback_speed, api_key, model }
```

Same for the dub-run TTS payload (`startTts` or equivalent — the function that posts to `/api/tts`). Pass `model` through to the JSON body.

- [ ] **Step 6.3: DubTab — model dropdown + API key + model in TTS calls**

In `ui-app/src/pages/videoDetail/DubTab.tsx`:

1. Import the new constant:
   ```ts
   import {
     GEMINI_TTS_MODELS,
     DEFAULT_GEMINI_TTS_MODEL,
     GEMINI_MODEL_STORAGE_KEY,
     type GeminiTTSModelId,
   } from '../../constants/geminiModels';
   ```

2. Add a state variable for the selected Gemini model, initialised from localStorage:
   ```ts
   const [geminiModel, setGeminiModel] = useState<GeminiTTSModelId>(
     (localStorage.getItem(GEMINI_MODEL_STORAGE_KEY) as GeminiTTSModelId | null) ?? DEFAULT_GEMINI_TTS_MODEL,
   );
   useEffect(() => {
     localStorage.setItem(GEMINI_MODEL_STORAGE_KEY, geminiModel);
   }, [geminiModel]);
   ```

3. Render the model dropdown ABOVE the voice picker, conditionally on `selectedTtsProvider === 'gemini'`. Place it in the same vertical column as the voice picker so the layout stays clean. Match the existing dropdown's tailwind classes (look at the provider dropdown around line 134 for the exact class string to reuse).

   ```tsx
   {selectedTtsProvider === 'gemini' && (
     <div className="flex items-center gap-2">
       <label className="text-xs text-on-surface-variant">Model</label>
       <select
         className={toolbarSelectClass()}
         value={geminiModel}
         onChange={(e) => setGeminiModel(e.target.value as GeminiTTSModelId)}
       >
         {GEMINI_TTS_MODELS.map((m) => (
           <option key={m.id} value={m.id}>{m.label}</option>
         ))}
       </select>
     </div>
   )}
   ```

   (If `toolbarSelectClass` isn't in this file, use whatever class string the provider `<select>` already uses.)

4. When calling `runTts`/`previewTts`, include `model: selectedTtsProvider === 'gemini' ? geminiModel : undefined`:
   ```ts
   await previewTts({ ..., model: selectedTtsProvider === 'gemini' ? geminiModel : undefined });
   ```

5. API-key lookup: the existing chain `ttsProviderName === 'google' ? apiKeys.google : ''` (or similar) needs a `gemini` arm. Find the existing chain (e.g. `DubTab.tsx` near `apiKey` resolution) and add:
   ```ts
   ttsProviderName === 'gemini' ? apiKeys.gemini :
   ```

6. The pitch slider should be hidden when `selectedTtsProvider === 'gemini'` (the API has no pitch knob). Find the pitch slider render block and wrap it in `selectedTtsProvider !== 'gemini' && (...)` or extend the existing `selectedTtsProvider !== 'elevenlabs'` guard:
   ```tsx
   {selectedTtsProvider !== 'elevenlabs' && selectedTtsProvider !== 'gemini' && (
     <PitchSlider ... />
   )}
   ```
   (If the pitch slider only lives behind a different conditional today, adapt accordingly.)

- [ ] **Step 6.4: DubStudio — same model dropdown + API key + model in TTS calls**

Open `ui-app/src/pages/DubStudio.tsx`. Apply the same set of changes (steps 1-6 from Step 6.3): model state, useEffect persistence, conditional dropdown, model in payload, gemini api_key arm, hide pitch.

If DubStudio has its own helper for resolving the api key per provider (e.g., a `resolveApiKey(provider, apiKeys)` function), add the `gemini` case there. Otherwise inline the conditional the same way as in DubTab.

- [ ] **Step 6.5: DownloadTranscribe (pipeline form) — same set of changes**

Open `ui-app/src/pages/DownloadTranscribe.tsx`. Same steps. The existing api-key resolution chain at line 231-233 currently reads:

```ts
ttsProviderName === 'elevenlabs' ? apiKeys.elevenlabs :
ttsProviderName === 'openai' ? apiKeys.openai :
ttsProviderName === 'google' ? apiKeys.google : '';
```

Add a gemini arm:

```ts
ttsProviderName === 'elevenlabs' ? apiKeys.elevenlabs :
ttsProviderName === 'openai' ? apiKeys.openai :
ttsProviderName === 'gemini' ? apiKeys.gemini :
ttsProviderName === 'google' ? apiKeys.google : '';
```

Same model-dropdown placement (above the voice picker, conditional on provider === 'gemini').

- [ ] **Step 6.6: UI typecheck + lint**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -5
npx eslint src/constants/geminiModels.ts src/api/client.ts src/pages/videoDetail/DubTab.tsx src/pages/DubStudio.tsx src/pages/DownloadTranscribe.tsx src/pages/settings/ApiKeysSection.tsx 2>&1 | tail -5
```
Expected: no errors in any of these files. Pre-existing errors elsewhere in the repo are out of scope.

- [ ] **Step 6.7: Manual smoke (dev server)**

```bash
make api    # in one terminal
make ui     # in another
```
Then open http://localhost:5173:
- Settings → see new "Gemini (Google AI Studio)" field. Paste a key, refresh, key persists.
- Dub Studio → provider dropdown shows "Gemini TTS". Selecting it reveals the Model dropdown above the voice picker.
- Voice dropdown populates with 29 prebuilt voices (Aoede, Puck, ...).
- Click Preview → audio plays. Network log shows POST to `generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent`.
- Switch model to Pro → click Preview → next request uses `gemini-2.5-pro-preview-tts`.
- Switch provider back to Google → Model dropdown disappears, voice list reloads as Cloud TTS voices.

- [ ] **Step 6.8: Commit**

```bash
git add ui-app/src/constants/geminiModels.ts ui-app/src/api/client.ts \
  ui-app/src/pages/videoDetail/DubTab.tsx ui-app/src/pages/DubStudio.tsx \
  ui-app/src/pages/DownloadTranscribe.tsx
git commit -m "feat(ui): Gemini TTS model picker + provider-aware API key

Adds a model dropdown above the voice picker on DubTab, DubStudio,
and DownloadTranscribe; it only renders when the selected provider
is 'gemini'. Selection persists to localStorage under
gemini_tts_model and is included in /api/tts and /api/tts/preview
request bodies as the new 'model' field.

The shared GEMINI_TTS_MODELS constant in
ui-app/src/constants/geminiModels.ts lists the two preview models
we surface today; future model additions are one line each.

The api-key resolution chain on each page gains a 'gemini' arm
that reads apiKeys.gemini (Settings → Gemini field from Task 5).
The pitch slider is hidden when provider=gemini because the API
has no speaking-pitch knob."
```

---

### Task 7: CHANGELOG + README rollup

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 7.1: CHANGELOG entry**

Open `CHANGELOG.md`. Find `## [Unreleased]` → `### Added`. Add this entry at the top of the `Added` block:

```markdown
- **Gemini TTS provider.** New `GeminiTTSProvider` (`src/tts/gemini_tts.py`) calls Google's Gemini Audio Generation API (`generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with `responseModalities=AUDIO` + prebuilt voice config). 24 kHz mono PCM response is wrapped to a WAV container in-memory (44-byte RIFF/WAVE header) so the assembler reads it through ffmpeg unchanged. Distinct from the existing `GoogleTTSProvider` (Cloud TTS / Wavenet voices) — both work side-by-side. Surface: new "Gemini TTS" entry in the provider dropdown on DubTab / DubStudio / Pipeline; conditional Model dropdown (Gemini 2.5 Flash Preview TTS / Gemini 2.5 Pro Preview TTS) above the voice picker; 29 hardcoded prebuilt voices (Aoede, Puck, Charon, Kore, ...) — not language-locked. Separate "Gemini (Google AI Studio)" API key field on Settings (it's a different key type from the Cloud Console one). Pitch slider hidden for this provider (no API support). `tts.gemini_api_key` + `tts.gemini_model` documented in `config/config.example.yaml`. 10 new tests (5 provider + 2 factory + 3 router).
```

- [ ] **Step 7.2: README progress entry**

Open `README.md`. Find the most recent dated subsection under Implementation Progress. Insert this new subsection IMMEDIATELY after that subsection's `---` separator:

```markdown
### Gemini TTS provider (2026-06-03)

> New TTS provider that calls Google's Gemini Audio Generation API (`generativelanguage.googleapis.com`), distinct from the existing Cloud TTS provider. Lets the user pick a Gemini model tier (Flash / Pro). See [`docs/superpowers/specs/2026-06-03-gemini-tts-provider-design.md`](docs/superpowers/specs/2026-06-03-gemini-tts-provider-design.md) and [`docs/superpowers/plans/2026-06-03-gemini-tts-provider.md`](docs/superpowers/plans/2026-06-03-gemini-tts-provider.md).

- [x] **Task 1** — `src/tts/gemini_tts.py::GeminiTTSProvider`: POSTs to `v1beta/models/{model}:generateContent`, wraps the 24 kHz mono PCM response to WAV in-memory. Static 29-name prebuilt voice list. 5 unit tests.
- [x] **Task 2** — Factory wire-up in `src/tts/__init__.py` reads `gemini_api_key` + `gemini_model` from the `tts` config section. 2 factory tests.
- [x] **Task 3** — API: `TTSRequest` / `TTSPreviewRequest` gain optional `model` field; `/api/tts/providers` returns the new entry; `start_tts` and `preview_tts` thread `gemini_model` into the config dict. 3 router tests.
- [x] **Task 4** — `config/config.example.yaml` documents `tts.gemini_api_key` + `tts.gemini_model`.
- [x] **Task 5** — Settings page gains "Gemini (Google AI Studio)" API key field, stored as `apiKeys.gemini`.
- [x] **Task 6** — Shared `ui-app/src/constants/geminiModels.ts` constant + provider-aware model dropdown on DubTab / DubStudio / Pipeline (only shown when provider === 'gemini'). Pitch slider hidden for this provider.
- [x] **Task 7** — CHANGELOG + README updates.

---
```

- [ ] **Step 7.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(gemini-tts): CHANGELOG + README rollup"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: Full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -5`
Expected: green. +10 tests over baseline.

- [ ] **Step F.2: BE lint on every touched file**

```bash
ruff check src/tts/gemini_tts.py src/tts/__init__.py src/api/models.py src/api/routers/tts.py \
  tests/test_gemini_tts.py tests/test_tts_factory_gemini.py tests/test_api_tts_gemini.py \
  2>&1 | tail -3
```
Expected: `All checks passed!`

- [ ] **Step F.3: FE typecheck + lint (touched files)**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | grep -E "(geminiModels|ApiKeysSection|DubTab|DubStudio|DownloadTranscribe|client\.ts)" | head -10
npx eslint src/constants/geminiModels.ts src/api/client.ts \
  src/pages/videoDetail/DubTab.tsx src/pages/DubStudio.tsx src/pages/DownloadTranscribe.tsx \
  src/pages/settings/ApiKeysSection.tsx 2>&1 | tail -5
```
Expected: no new issues in any touched file. Pre-existing lint errors elsewhere are out of scope.

- [ ] **Step F.4: Manual end-to-end smoke (after merge)**

1. Open Settings, paste Gemini API key, save → key persists across reload.
2. Open Dub Studio, provider = "Gemini TTS", model = Flash, voice = Kore, language = vi.
3. Preview a sentence → audio plays. Network log shows `generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent`.
4. Switch model to Pro → next Preview hits `gemini-2.5-pro-preview-tts`.
5. Switch provider to Google → model dropdown disappears, voice list reloads from Cloud TTS, network goes back to `texttospeech.googleapis.com`.
6. Run a full per-video dub end-to-end with provider=gemini → final `.wav` exists, plays back, is playable in ffmpeg/QuickTime.

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: each section in the spec maps to a task (provider → T1, factory → T2, API → T3, config → T4, Settings → T5, model picker → T6, docs → T7).
- [ ] No "TBD" / "implement later" / "similar to Task N" anywhere.
- [ ] Type/name consistency: `GeminiTTSProvider`, `gemini_api_key`, `gemini_model`, `apiKeys.gemini`, `GEMINI_TTS_MODELS`, `GEMINI_MODEL_STORAGE_KEY` used identically across tasks.
- [ ] All work lands on `feature/gemini-tts-provider`.
- [ ] No AI-attribution strings in any commit message.
- [ ] CHANGELOG entry under `Added` in `[Unreleased]`.
- [ ] README entry next to other dated subsections, not at the bottom.
