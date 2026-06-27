# Vbee TTS Provider — Design Spec

**Date:** 2026-06-20
**Status:** Approved (pending spec review)

## Goal

Add Vbee (vbee.vn / AIVoice) as a selectable TTS provider, alongside Google Cloud TTS, Gemini, OpenAI, and ElevenLabs. Vbee specialises in high-quality Vietnamese voices, which is the pipeline's primary dub target for TikTok/Facebook.

The challenge: Vbee's synthesis API is **asynchronous** (submit → poll → download a URL), but the project's `BaseTTSProvider.synthesize()` contract is **synchronous and returns audio bytes**. The design hides the entire async flow inside `synthesize()` so no other layer changes.

## Confirmed API contract (from `docs/vbee/`)

Source: `docs/vbee/batchapi.md`, `getrequest.md`, `callbackapi.md`.

### Submit — `POST https://api.vbee.vn/v1/tts`
Headers (all required):
- `Authorization: Bearer <access_token>`
- `App-Id: <app_id>`
- `Content-Type: application/json`

Body:
| Field | Required | Notes |
|---|---|---|
| `text` | yes | ≤ 100,000 chars; leading/trailing whitespace trimmed |
| `mode` | yes | must be `"async"` for the Batch API |
| `webhookUrl` | **yes** | required even when polling — `BAD_REQUEST: webhookUrl must be defined` if omitted |
| `voiceCode` | yes | e.g. `hn_female_ngochuyen_full_48k-fhg` |
| `outputFormat` | no | `mp3` (default) or `wav`; `pcm` errors |
| `bitrate` | no | one of 8/16/32/64/128 (default 128) |
| `speed` | no | 0.25–1.9 (default 1.0) |
| `sampleRate` | no | 8000/16000/22050/24000/32000/44100/48000; voice-dependent default |
| `emphasisIntensity` | no | 0–100 step 10; voice-dependent |
| `clientPause` | no | object of break-timing overrides |

Success response: `{ "requestId": "<uuid>", "status": "PROCESSING" }`
Failure response: `{ "error": { "code": "BAD_REQUEST", "message": "..." } }`

### Poll — `GET https://api.vbee.vn/v1/tts/requests/{requestId}`
Same `Authorization` + `App-Id` headers.
- In progress: `{ "requestId", "status": "PROCESSING" }`
- Done: `{ "requestId", "status": "COMPLETED", "audioLink": "https://.../audio/xxx.mp3" }`
- Failed: `{ "error": { "code", "message" } }`

`audioLink` **expires after 3 minutes** (audio retained server-side 3 days; re-poll for a fresh link). We download immediately, so expiry is a non-issue.

### Errors
HTTP-coded: `UNAUTHORIZED` 401 (bad/missing token or app_id), `BAD_REQUEST` 400 (bad body, unknown voiceCode), `INTERNAL_SERVER_ERROR` 500.

### Not in the fetched docs
- **No synchronous mode** — async is the only path. (Resolves the earlier "300-char sync cap" concern: irrelevant.)
- **No voice-list endpoint** — we bundle a curated list + allow manual custom codes (see §3).
- **No documented `pitch` request param** — ignored, like the Gemini provider.

---

## Architecture

### 1. Backend provider — `src/tts/vbee_tts.py` (new)

`VbeeTTSProvider(BaseTTSProvider)`. The whole async dance is buried inside `synthesize()` so the assembler, planner, runner, and `/api/tts/preview` are untouched.

```python
class VbeeTTSProvider(BaseTTSProvider):
    BASE_URL = "https://api.vbee.vn/v1"
    DEFAULT_VOICE = "hn_female_ngochuyen_full_48k-fhg"
    # Curated Vietnamese voices (code → friendly label). Extend by editing this.
    VOICES: tuple[tuple[str, str], ...] = (
        ("hn_female_ngochuyen_full_48k-fhg", "Ngọc Huyền (Hà Nội, nữ)"),
        ("hn_male_manhdung_news_48k-fhg",    "Mạnh Dũng (Hà Nội, nam)"),
        ("sg_female_thaotrinh_full_48k-fhg", "Thảo Trinh (Sài Gòn, nữ)"),
        ("sg_male_trungkien_full_48k-fhg",   "Trung Kiên (Sài Gòn, nam)"),
        # ... a handful more curated codes
    )

    def __init__(self, config: dict | None = None):
        config = config or {}
        self.api_key: str = config.get("vbee_api_key", "")      # bearer token
        self.app_id: str = config.get("vbee_app_id", "")
        self.default_voice: str = config.get("vbee_default_voice", self.DEFAULT_VOICE)
        self.bitrate: int = int(config.get("vbee_bitrate", 128))
        self.sample_rate = config.get("vbee_sample_rate")        # optional
        self.output_format: str = config.get("vbee_output_format", "mp3")
        # Placeholder webhook — required field, but we poll instead of receive.
        self.webhook_url: str = config.get("vbee_webhook_url", "https://example.com/vbee-callback")
        # Poll tuning
        self.poll_interval_s: float = float(config.get("vbee_poll_interval", 2.0))
        self.poll_timeout_s: float = float(config.get("vbee_poll_timeout", 90.0))

    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        # 0. validate creds → ValueError if missing
        # 1. POST submit → requestId   (429 → bounded backoff-retry)
        # 2. poll GET until COMPLETED/SUCCESS (→ audioLink) or FAILED/timeout
        # 3. GET audioLink → return mp3 bytes
        ...

    async def list_voices(self, language: str | None = None) -> list[dict]:
        # Returns the curated VOICES as the standard dict shape. language
        # ignored (all Vietnamese). Custom codes are handled FE-side.
        ...
```

**Behaviour details:**
- **Creds missing** → `raise ValueError("Vbee token/app_id not configured for TTS")`.
- **Speed** — read `kwargs.get("speed", 1.0)`; coerce `"+10%"`-style strings (mirror `openai_tts.py`); clamp to `[0.25, 1.9]`.
- **Pitch** — ignored (no API param), like Gemini.
- **`webhookUrl`** — always sent (required); a placeholder. The callback fires to it and is harmless; we poll `getrequest` regardless.
- **Status handling** — treat `COMPLETED` or `SUCCESS` as terminal success; `FAILED`/`FAILURE` or poll-timeout → `raise RuntimeError(...)`. Raising is correct: the assembler catches it (`return_exceptions=True`), flags `needs_review`, and falls back to source audio for that span.
- **429** (rate/concurrency, e.g. `TTS_CCR_MAX_LIMIT_REACHED`) — bounded retry (2–3 attempts, short sleep) inside `synthesize` on submit; if still failing, raise.
- **Return value** — raw bytes of the downloaded mp3 (a real container; the assembler ffprobes them, `assembler.py`). No PCM-wrapping needed (unlike Gemini).

### 2. Factory — `src/tts/__init__.py` (modify)

Add a branch before the `else: raise`:
```python
elif provider_name == "vbee":
    from src.tts.vbee_tts import VbeeTTSProvider
    logger.info("Using Vbee TTS provider")
    return VbeeTTSProvider(config=tts_config)
```
Docstring's provider list updated to include `"vbee"`.

### 3. Auth — two secrets via the proven Gemini-model rails

Vbee needs **token + app_id**. The token reuses the existing single-secret path; the app_id rides the exact rail we already built for Gemini's per-request `model`:

- **`src/api/models.py`** — `TTSRequest`, `TTSPreviewRequest`, `FullPipelineRequest`, `BatchPipelineRequest` gain `tts_app_id: str | None = None` (mirrors the existing `tts_model` / `model` field).
- **`src/api/routers/tts.py`** — `start_tts`, `preview_tts`, `list_voices` inject `tts_section["vbee_app_id"] = <app_id>` when `provider == "vbee"` and the value is present, right alongside the existing `{provider}_api_key` injection. `/api/tts/providers` adds `{id: "vbee", name: "Vbee (Vietnamese)", free: False, requires_key: True}`.
- **`src/api/routers/pipeline.py`** + **`src/pipeline.py`** — thread `tts_app_id` through `_run_full_pipeline` / `_run_batch_pipeline` into the options dict and into the TTS config, same pattern as `tts_model`.
- **`config/config.example.yaml`** — `tts:` block gains documented `vbee_app_id`, `vbee_default_voice`, optional `vbee_bitrate` / `vbee_sample_rate` / `vbee_webhook_url`. Precedence follows the existing per-request-override pattern: the router injects the UI-supplied app_id into `tts_config` before the factory reads it, so the **UI value wins**; the YAML `vbee_app_id` is just an optional fallback default. The **token** is entered in the UI only (never YAML), like the other provider keys.

### 4. Frontend

- **Settings** (`ui-app/src/pages/settings/ApiKeysSection.tsx`) — two new `PROVIDERS` entries: `{ key: "vbee", label: "Vbee Token", placeholder: "Bearer token", icon: "graphic_eq" }` and `{ key: "vbee_app_id", label: "Vbee App ID", placeholder: "app-id UUID", icon: "badge" }`. Stored as `api_key_vbee` / `api_key_vbee_app_id` in localStorage; `storage.ts::LLMApiKeys` + `loadApiKeys()` gain both fields.
- **Provider dropdown** — appears automatically (driven by `/api/tts/providers`).
- **Voices** — BE `list_voices` returns the curated set so the dropdown "just works" (like Gemini). **Plus** a vbee-only free-text **"Custom voiceCode"** input rendered beneath the voice dropdown on the three dub surfaces; when non-empty it overrides the dropdown selection. Satisfies "fixed list, add more manually."
- **API-key + app_id wiring** — DubTab (via VideoDetail), DubStudio, and DownloadTranscribe each:
  - add a `vbee` arm to the api-key resolution chain → `apiKeys.vbee` (token);
  - send `tts_app_id: apiKeys.vbee_app_id` when provider is `vbee` (mirrors how `tts_model`/`geminiModel` is sent);
  - thread the custom voiceCode into the `tts_voice` they already send.
- **API client** (`ui-app/src/api/client.ts`) — `postTTS` / `postTTSPreview` / `postPipeline` payload types gain optional `tts_app_id` (mirror `tts_model`). `LLMApiKeys` gains `vbee` + `vbee_app_id`.

### 5. Concurrency

The assembler synthesises with `asyncio.Semaphore(5)` → up to 5 concurrent `synthesize` calls = 5 concurrent poll loops. Vbee's concurrency cap on a given plan is unknown. The provider's 429 backoff-retry absorbs transient throttling. If Vbee throttles hard in practice, the single mitigation is lowering `max_concurrent` for this provider — noted, not pre-optimised.

---

## Behaviour table

| Scenario | Result |
|---|---|
| Token + app_id valid, voice valid | Submit → poll → download → mp3 bytes returned |
| Missing token or app_id | `ValueError` before any HTTP call |
| Poll returns `FAILED` | `RuntimeError`; assembler flags `needs_review`, source-audio fallback |
| Poll exceeds `poll_timeout_s` | `RuntimeError` (treated as synth failure) |
| HTTP 429 on submit | Bounded backoff-retry; raise if still failing |
| HTTP 401/400/500 | `RuntimeError` with vbee's `error.message` |
| `speed` out of range | Clamped to [0.25, 1.9] |
| Custom voiceCode entered in UI | Sent as `voiceCode`, overrides dropdown |
| provider=vbee, English target | Allowed but not recommended (Vietnamese is the strength) |

---

## Test plan

### Backend unit — `tests/test_vbee_tts.py`
Mock `httpx.AsyncClient` (`post` for submit, `get` for poll + audio download):
1. Happy path: submit → `PROCESSING` once → `COMPLETED` + `audioLink` → download → returns the mp3 bytes.
2. Immediate `COMPLETED` on first poll.
3. `FAILED` poll status → `RuntimeError`.
4. Poll timeout (always `PROCESSING`) → `RuntimeError`, bounded by a small injected `poll_timeout_s`.
5. Missing token → `ValueError`; missing app_id → `ValueError`.
6. 429 on submit then success → retried, returns bytes.
7. Speed clamping: `2.5` → `1.9`, `0.1` → `0.25`, `"+10%"` → `1.1`.
8. `list_voices()` returns the curated set with `provider="vbee"`, `language="vi"`.
9. Request body assertion: `mode=="async"`, `webhookUrl` present, headers carry `Authorization` + `App-Id`.

### Backend factory — `tests/test_tts_factory_vbee.py`
- `get_tts_provider({"tts": {"vbee_api_key": "t", "vbee_app_id": "a"}}, provider="vbee")` → `VbeeTTSProvider` with matching token/app_id.

### Backend router — `tests/test_api_tts_vbee.py`
- `/api/tts/providers` includes `vbee`.
- `/api/tts/voices?provider=vbee` returns the curated list.
- `POST /api/tts/preview` with `provider=vbee` + `tts_app_id` → provider built with that app_id (spy on factory).

### Frontend
- `npx tsc --noEmit` + `npx eslint` clean on touched files. (Vitest optional; mirror existing coverage.)

### Manual smoke (user, with real credentials)
1. Settings → enter Vbee Token + Vbee App ID → save → reload persists.
2. DubStudio → provider "Vbee (Vietnamese)" → voice dropdown populates; pick `hn_female_ngochuyen...`.
3. Preview a Vietnamese sentence → audio plays (network shows `api.vbee.vn/v1/tts` submit + `.../requests/{id}` polls + audioLink download).
4. Enter a custom voiceCode → preview uses it.
5. Full per-video dub with provider=vbee → final WAV plays; dubsync SRT saved.

---

## Risks & open questions
- **Concurrency cap** unknown — mitigated by 429 retry; may need `max_concurrent` lowering. Confirm during smoke.
- **`webhookUrl` placeholder** — relies on the documented requirement being satisfiable by a dummy (consistent with multiple real-world implementations). If Vbee validates reachability, we make it a real configurable URL; smoke test will reveal this.
- **Status vocabulary** — `getrequest.md` shows `COMPLETED`; `callbackapi.md` shows `SUCCESS`. The provider accepts both as terminal-success defensively.
- **Voice list staleness** — curated constant; extend by editing `VOICES`. Manual custom-code input is the escape hatch.

## Out of scope
- A real webhook receiver endpoint (we poll).
- `emphasisIntensity` / `clientPause` fine-tuning (defaults only; can add later).
- English-quality work — Vbee is positioned for Vietnamese; English keeps existing providers.
- Auto-selecting Vbee per platform — it's a manual provider choice with a Vietnamese recommendation.
