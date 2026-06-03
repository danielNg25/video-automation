# Gemini TTS Provider — Design Spec

**Date:** 2026-06-03
**Status:** Draft

## Goal

Expose Google's Gemini Audio Generation API as a new TTS provider distinct from the existing "Google" provider (which calls the legacy Cloud Text-to-Speech `texttospeech.googleapis.com/v1/text:synthesize`).

The user wants to pick a Gemini model tier — e.g. `gemini-2.5-flash-preview-tts` vs `gemini-2.5-pro-preview-tts` — alongside a voice. The existing "Google" provider has no such notion (its quality tier is encoded in the voice name).

## Non-goals

- Removing or modifying the existing `GoogleTTSProvider`. The legacy Cloud TTS path stays intact.
- Multi-speaker prompts. Single-speaker only in v1.
- Style instructions ("Read this calmly"). Not in v1.
- Per-segment `speed` / `pitch` knobs. Gemini's audio API has no `speakingRate` / `pitch` fields. The assembler can still apply ffmpeg `atempo` post-synth for dub-shortening; the per-row pitch slider in the UI is hidden when provider = gemini.

---

## Architecture

Five layers, all already established in the codebase. Each new piece mirrors an existing precedent.

### 1. Backend provider — `src/tts/gemini_tts.py` (new)

```python
class GeminiTTSProvider(BaseTTSProvider):
    """Gemini Audio Generation TTS provider.

    Calls generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
    with responseModalities: ["AUDIO"] and a prebuilt voice config. Returns
    24 kHz mono PCM wrapped in a WAV container so the assembler reads it
    through ffmpeg like any other provider's output.
    """

    DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

    # 30 prebuilt voice names from the Gemini docs. Not language-locked.
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
        # POST {BASE_URL}/models/{self.model}:generateContent?key={api_key}
        # body: {
        #   "contents": [{"parts": [{"text": text}]}],
        #   "generationConfig": {
        #     "responseModalities": ["AUDIO"],
        #     "speechConfig": {
        #       "voiceConfig": {
        #         "prebuiltVoiceConfig": {"voiceName": voice}
        #       }
        #     }
        #   }
        # }
        # response.candidates[0].content.parts[0].inlineData.data is base64 PCM (24kHz mono s16le)
        # Wrap into a WAV (44-byte RIFF header) and return.
        ...

    async def list_voices(self, language: str | None = None) -> list[dict]:
        # Voices are not language-locked. Ignore `language`. Return the
        # static VOICES tuple as a list of dicts matching the same shape
        # the other providers return:
        #   {name, language, gender, provider, friendly_name}
        # gender is unknown for Gemini voices, so set "neutral".
        ...
```

WAV wrapping is a 44-byte little-endian RIFF header: `RIFF` + total size + `WAVE` + `fmt ` chunk (PCM, 1 channel, 24000 Hz, 16-bit) + `data` chunk size + payload. No deps.

**Error handling.** Same shape as `GoogleTTSProvider`: `raise ValueError("Gemini API key not configured for TTS")` when key is empty, `response.raise_for_status()` for HTTP errors, `raise RuntimeError("Gemini TTS returned empty audio")` when the response has no inlineData.

### 2. Factory — `src/tts/__init__.py` (modify)

Add a branch for `provider == "gemini"`:

```python
elif provider == "gemini":
    from src.tts.gemini_tts import GeminiTTSProvider
    return GeminiTTSProvider(tts_config)
```

`tts_config` already reaches the provider as a dict; `GeminiTTSProvider` reads `gemini_api_key` and `gemini_model` from it. No new factory-level field — just one new conditional.

### 3. API request models — `src/api/models.py` (modify)

Both request payloads gain a single optional field:

```python
class TTSRequest(BaseModel):
    ...
    model: str | None = None       # NEW — Gemini model ID (ignored by other providers)

class TTSPreviewRequest(BaseModel):
    ...
    model: str | None = None       # NEW
```

### 4. API routers — `src/api/routers/tts.py` (modify)

Where the routers currently inject `tts_section[f"{provider}_api_key"] = api_key`, add an analogous line for the model when `provider == "gemini"` and `request.model`:

```python
if request.provider == "gemini" and request.model:
    tts_section["gemini_model"] = request.model
```

The `/api/tts/voices/{provider}` endpoint already dispatches on `provider`; add a `gemini` branch that constructs a `GeminiTTSProvider` (or just imports `GeminiTTSProvider.VOICES` directly) and returns the static list as the same `[{name, language, gender, provider, friendly_name}]` shape the other providers use.

### 5. Config — `config/config.example.yaml` (modify)

Under the existing `tts:` block, after the `google_api_key:` line, add:

```yaml
    # Gemini Audio Generation API (separate from Google Cloud TTS).
    # Uses a Google AI Studio API key, not a Cloud Console key. Enable the
    # Generative Language API in your AI Studio project.
    gemini_api_key: ''
    # Default Gemini TTS model. Per-request override via the API/UI.
    gemini_model: 'gemini-2.5-flash-preview-tts'
```

### 6. Frontend — provider dropdown + model picker

Three places have voice/provider pickers:
- `ui-app/src/pages/videoDetail/DubTab.tsx` — per-video Dub tab
- `ui-app/src/pages/dubStudio/...` (Dub Studio standalone)
- `ui-app/src/pages/DownloadTranscribe.tsx` — pipeline form
- `ui-app/src/pages/videoDetail/EditorTab.tsx` — editor's dub picker

Each adds:

1. `gemini` to the `ttsProviders` array (label "Gemini TTS").
2. When the selected provider is `gemini`, render a **Model** dropdown above the voice picker. Options are a hardcoded constant list mirroring the backend's `DEFAULT_MODEL` + any others we want to surface:

   ```ts
   const GEMINI_MODELS = [
     { id: 'gemini-2.5-flash-preview-tts', label: 'Gemini 2.5 Flash (faster)' },
     { id: 'gemini-2.5-pro-preview-tts',   label: 'Gemini 2.5 Pro (higher quality)' },
   ] as const;
   ```

3. Model selection persists in localStorage as `gemini_model` (single key shared across pages, same pattern as the existing `tts_voice_id_{provider}` keys).
4. Voice picker calls `/api/tts/voices/gemini` and renders the same dropdown UX. No favorites integration in v1 (favorites already use voice name; they'll just work).
5. The TTS-call helper (wherever `runTts`/`previewTts` is constructed in the FE) gains a `model?: string` field on its payload and includes it when the selected provider is `gemini`.

### 7. Settings page

`ui-app/src/pages/Settings.tsx` already has a Google API Key field. Add a sibling **Gemini API Key** field, persisted to localStorage key `gemini_api_key` and to the backend config on save. Identical UX to the existing Google Cloud TTS key field — just the label and key differ.

---

## Behavior

| Provider in UI | API key used | Voices fetched from | Model dropdown shown |
|---|---|---|---|
| Google | `google_api_key` (Cloud Console) | `/v1/voices` (live) | No |
| Gemini TTS | `gemini_api_key` (AI Studio) | static 30-name list | Yes |
| OpenAI | `openai_api_key` | static (existing) | No (already has `openai_model` in config) |
| ElevenLabs | `elevenlabs_api_key` | live | No (already has `elevenlabs_model` in config) |

| Knob in DubTab | Honored by Gemini? |
|---|---|
| Voice | Yes — picked from prebuilt list. |
| Playback speed | Post-synth ffmpeg atempo. No change in code; works because the planner runs on top of any provider's WAV output. |
| Pitch | **Hidden** when provider = gemini (Gemini has no pitch knob). |
| API key | New "Gemini API Key" field on Settings page; per-request override on Dub forms (same pattern as the other providers). |

---

## Test plan

### Backend (Python / pytest)

`tests/test_gemini_tts.py` (new):

1. **`test_voices_static_list`** — `list_voices()` returns 29 entries (or whatever the final list length is), each with `provider="gemini"`, gender `"neutral"`, language `""`.
2. **`test_voices_ignores_language_filter`** — `list_voices(language="vi")` returns the same length as `list_voices(None)`.
3. **`test_synthesize_no_api_key_raises`** — empty key → `ValueError("Gemini API key not configured for TTS")`.
4. **`test_synthesize_happy_path_wraps_pcm_to_wav`** — patch `httpx.AsyncClient.post` to return a `{candidates: [{content: {parts: [{inlineData: {data: <base64 PCM>}}]}}]}` JSON. Assert returned bytes start with `b"RIFF"`, length = 44 + len(decoded PCM), correct sample-rate/channel bytes in header.
5. **`test_synthesize_empty_inlinedata_raises`** — patch returns a response with no `inlineData`. Assert `RuntimeError`.
6. **`test_factory_builds_provider`** — `get_tts_provider({"tts": {"provider": "gemini", "gemini_api_key": "x"}})` returns a `GeminiTTSProvider` with `api_key == "x"` and `model == DEFAULT_MODEL`.
7. **`test_factory_respects_model_override`** — config with `gemini_model: "gemini-2.5-pro-preview-tts"` → provider's `.model` matches.

### API router

`tests/test_api_tts_gemini.py` (or add to the existing `tests/test_api_tts.py`):

1. **`test_voices_endpoint_returns_gemini_list`** — `GET /api/tts/voices/gemini` returns the 29-voice list.
2. **`test_tts_request_threads_model_through`** — `POST /api/tts` with `{provider: "gemini", model: "gemini-2.5-pro-preview-tts", ...}`, mock `TaskManager.run_tts` to capture its config. Assert the config dict contains `tts.gemini_model == "gemini-2.5-pro-preview-tts"`.

### Frontend (vitest)

Optional v1 — defer unless a regression appears.

---

## Manual smoke checklist (post-merge)

1. Open Settings → paste a Gemini API key → save. Reload the page — key persists.
2. Open Dub Studio → provider dropdown shows "Gemini TTS" → select it.
3. A "Model" dropdown appears above the voice picker. Default = `gemini-2.5-flash-preview-tts`.
4. Voice picker populates with the 29 prebuilt voices.
5. Click Preview on a short Vietnamese sentence → audio plays.
6. Switch to `gemini-2.5-pro-preview-tts` → Preview re-synthesizes with the new model.
7. Run a full per-video dub with provider=gemini → final `.wav` exists and plays back; the assembled WAV reads cleanly.
8. Network log: every TTS call goes to `generativelanguage.googleapis.com/v1beta/models/<model>:generateContent`. Existing Google Cloud TTS calls (when "Google" is selected) still go to `texttospeech.googleapis.com`.

---

## Risks and open questions

- **Preview model availability.** Both `gemini-2.5-flash-preview-tts` and `gemini-2.5-pro-preview-tts` are preview models. If Google sunsets them, we update `GEMINI_MODELS` (frontend constant) and `DEFAULT_MODEL` (backend constant). No data-migration needed — model is just a string in localStorage / config.
- **Quota.** Gemini TTS counts against generative-language quota, separate from Cloud TTS quota. Surfacing quota errors gracefully is the same pattern as today (4xx surfaces as a toast on the FE).
- **Voice list staleness.** Hardcoded list could drift as Google adds voices. Acceptable — we update by editing one tuple in `gemini_tts.py` and one array in the frontend. Live voice listing isn't available for Gemini TTS today.
