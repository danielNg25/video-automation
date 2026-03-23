# Plan: Phase 1 Tasks 1.26–1.32 — LLM Translation + Download Features

## Context

Whisper produces poor Vietnamese transcriptions. The solution: transcribe to Chinese/English with Whisper (which it handles well), then translate SRT to Vietnamese using an LLM with style-controlled "translation profiles." This also enables any target language with tone/personality control (funny, dramatic, neutral).

Tasks 1.31–1.32 (raw video download + SRT export) are smaller quality-of-life additions for the UI.

**Branch**: `feature/phase1-translation-profiles` (from `main`)

**Key finding**: `GET /api/videos/{video_id}/raw` already exists in `src/api/routers/editor.py:33`. Task 1.31 only needs a `Content-Disposition: attachment` header and an SRT download endpoint. CHANGELOG `[1.1.0]` already has entries for these tasks — verify/update those, don't duplicate.

---

## Task Order

Tasks 1.31–1.32 are independent of 1.26–1.30. Implementation order:

1. **1.26** Translation profiles (no deps)
2. **1.27** LLM translator (needs 1.26)
3. **1.28** Translator factory (needs 1.26, 1.27)
4. **1.29** Translation API (needs 1.28)
5. **1.30** Translation UI (needs 1.29)
6. **1.31** Raw video download endpoint (independent)
7. **1.32** Download raw video UI (needs 1.31)

---

## Task 1.26 — Translation Profile System

### Files to create
- `src/translator/__init__.py` (empty initially, populated in 1.28)
- `src/translator/profiles.py`
- `config/translation_profiles/funny-casual-vi.yaml`
- `config/translation_profiles/neutral-vi.yaml`
- `config/translation_profiles/dramatic-vi.yaml`
- `config/translation_profiles/custom.yaml.example`

### `src/translator/profiles.py`

```python
@dataclass
class TranslationProfile:
    name: str
    description: str
    style_guide: str
    target_language: str
    source_language: str       # "zh" or "en"
    example_pairs: list[dict]  # [{"source": "...", "target": "..."}]
```

Functions:
- `load_profile(name: str, profiles_dir: Path = None) -> TranslationProfile` — load YAML, return dataclass
- `list_profiles(profiles_dir: Path = None) -> list[str]` — glob `*.yaml`, exclude `*.example`
- `save_profile(profile: TranslationProfile, profiles_dir: Path = None) -> None` — write YAML
- `delete_profile(name: str, profiles_dir: Path = None) -> None` — remove file
- `get_default_profile(target_lang: str) -> str` — return first matching profile name

Default `profiles_dir`: `config/translation_profiles/`

### Profile YAML format
Follows the spec in `plans/phase1-core-download-transcribe.md:621-655` exactly. Three built-in profiles target Vietnamese with different tones.

---

## Task 1.27 — LLM Translator

### Files to create
- `src/translator/llm.py`

### Files to modify
- `pyproject.toml` — add `anthropic>=0.40.0` and `openai>=1.50.0` to dependencies

### `src/translator/llm.py`

Class `LLMTranslator`:

```python
class LLMTranslator:
    def __init__(self, backend: str, model: str, api_key: str | None = None,
                 max_segments_per_batch: int = 8, temperature: float = 0.7):
        ...

    async def translate_srt(
        self, srt_path: Path, profile: TranslationProfile, output_path: Path,
        progress_callback: Callable[[int, int, str], None] | None = None
    ) -> Path:
        ...
```

Implementation:
1. Parse source SRT using `src/processor/subtitle.parse_srt(srt_path)` — reuse existing
2. Group segments into batches of `max_segments_per_batch`
3. For each batch, build prompt:
   - System: profile `style_guide` + formatted `example_pairs`
   - User: numbered segment texts, ask for translations one-per-line
4. Call LLM (Anthropic or OpenAI) — use `httpx` via SDK
5. Parse response: split lines, validate count matches batch size
6. If count mismatch: retry batch once with explicit instruction
7. Call `progress_callback(batch_num, total_batches, message)` after each batch
8. Skip empty segments (preserve timing, use empty text)
9. Write output SRT using `src/processor/subtitle.write_srt()` — reuse existing
10. Return output path

Backend dispatch:
- `backend="anthropic"` → `anthropic.AsyncAnthropic().messages.create()`
- `backend="openai"` → `openai.AsyncOpenAI().chat.completions.create()`

Rate limiting: 1-second delay between batches via `asyncio.sleep(1)`.

### Config section to add to `config/config.example.yaml`
```yaml
translation:
  backend: "anthropic"
  model: "claude-sonnet-4-20250514"
  api_key: "${ANTHROPIC_API_KEY}"
  max_segments_per_batch: 8
  temperature: 0.7
  default_profile: "funny-casual-vi"
```

---

## Task 1.28 — Translator Factory

### Files to modify
- `src/translator/__init__.py`

```python
def get_translator(config: dict) -> LLMTranslator:
    """Factory: returns configured LLM translator."""

async def translate_with_profile(
    srt_path: Path, profile_name: str, config: dict, output_dir: Path,
    progress_callback: Callable | None = None
) -> Path:
    """High-level: load profile -> create translator -> translate -> return output path."""
```

The factory reads from `config["translation"]` section. The `translate_with_profile` convenience function handles the common workflow.

---

## Task 1.29 — Translation API

### Files to create
- `src/api/routers/translate.py`

### Files to modify
- `src/api/models.py` — add request/response models
- `src/api/task_manager.py` — add `run_translate()` method
- `src/api/__init__.py` — register translate router

### New models in `src/api/models.py`
```python
class TranslateRequest(BaseModel):
    video_id: str
    profile_name: str = "funny-casual-vi"
    source_language: str = "zh"

class TranslationProfileResponse(BaseModel):
    name: str
    description: str
    target_language: str
    source_language: str
    style_guide: str
    example_pairs: list[dict]

class TranslationProfileCreate(BaseModel):
    name: str
    description: str
    target_language: str
    source_language: str = "zh"
    style_guide: str
    example_pairs: list[dict] = []
```

### Router endpoints (`src/api/routers/translate.py`)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/translate` | Start translation → `{task_id}` |
| `GET` | `/api/profiles` | List profiles → `[{name, description, target_language}]` |
| `GET` | `/api/profiles/{name}` | Get full profile |
| `POST` | `/api/profiles` | Create profile |
| `PUT` | `/api/profiles/{name}` | Update profile |
| `DELETE` | `/api/profiles/{name}` | Delete profile |

### `run_translate()` in task_manager.py

Follows existing pattern from `run_transcribe()`:
1. Load source SRT from `data/srt/{video_id}_{source_lang}.srt`
2. Call `translate_with_profile()` in thread via `asyncio.to_thread()`
3. Progress callback emits SSE events: `"Translating batch 3/8..."`
4. On complete: update `video_index[video_id].srt_languages` to include target language
5. Result: `{video_id, srt_path, segment_count, profile_used, target_language}`

### App registration in `src/api/__init__.py`
Add `from src.api.routers import translate` to imports, `app.include_router(translate.router)`.

---

## Task 1.30 — Translation UI

### Files to modify
- `ui-app/src/api/types.ts` — add profile types
- `ui-app/src/api/client.ts` — add translation + profile API functions
- `ui-app/src/pages/DownloadTranscribe.tsx` — add translation section

### New TypeScript types
```typescript
interface TranslationProfile {
  name: string;
  description: string;
  target_language: string;
  source_language: string;
  style_guide: string;
  example_pairs: { source: string; target: string }[];
}

interface TranslationProfileSummary {
  name: string;
  description: string;
  target_language: string;
}
```

### New API client functions
```typescript
getProfiles(): Promise<TranslationProfileSummary[]>
getProfile(name: string): Promise<TranslationProfile>
createProfile(profile: TranslationProfile): Promise<TranslationProfile>
updateProfile(name: string, profile: TranslationProfile): Promise<TranslationProfile>
deleteProfile(name: string): Promise<void>
postTranslate(videoId: string, profileName: string, sourceLang: string): Promise<TaskResponse>
```

### UI additions on DownloadTranscribe.tsx

Add a **Translation section** that appears after transcription completes (below the transcribe controls, above the SRT preview):

1. **Profile selector** — dropdown listing profiles from `GET /api/profiles`, with description preview below
2. **Translate button** — triggers `POST /api/translate`, shows batch progress via SSE
3. **Profile editor** — collapsible section or modal for creating/editing profiles:
   - Name, description, target language, source language fields
   - Style guide textarea
   - Example pairs list (add/remove rows)
   - Save/delete buttons
4. **SRT preview language tabs** — already partially exists with language switcher. Ensure translated language appears as a tab after translation completes.

---

## Task 1.31 — Raw Video Download Endpoint

### Files to modify
- `src/api/routers/editor.py` — add `Content-Disposition: attachment` to existing `serve_raw_video`
- `src/api/routers/transcribe.py` — add SRT file download endpoint

### Changes

**`editor.py` line 45-49**: Add `headers` param to `FileResponse`:
```python
return FileResponse(
    path=str(video_path),
    media_type="video/mp4",
    filename=f"{video_id}.mp4",
    headers={"Content-Disposition": f'attachment; filename="{video_id}.mp4"'},
)
```

**New endpoint in `transcribe.py`**: `GET /api/videos/{video_id}/srt/download`
```python
@router.get("/api/videos/{video_id}/srt/download")
async def download_srt(video_id: str, language: str = "zh"):
    srt_path = Path("data/srt") / f"{video_id}_{language}.srt"
    if not srt_path.exists():
        raise HTTPException(status_code=404, detail="SRT file not found")
    return FileResponse(
        path=str(srt_path),
        media_type="text/plain",
        filename=f"{video_id}_{language}.srt",
        headers={"Content-Disposition": f'attachment; filename="{video_id}_{language}.srt"'},
    )
```

---

## Task 1.32 — Download Raw Video UI

### Files to modify
- `ui-app/src/api/client.ts` — add `getSrtDownloadUrl()` helper
- `ui-app/src/pages/DownloadTranscribe.tsx` — wire up download buttons

### Changes

**`client.ts`**: Add URL builder:
```typescript
export function getSrtDownloadUrl(videoId: string, language: string): string {
  return `${BASE}/videos/${videoId}/srt/download?language=${language}`;
}
```

**`DownloadTranscribe.tsx`**:
1. Wire the existing "Download Video" button (or add one) on the video result card → `<a href={getRawVideoUrl(videoId)} download>`
2. Wire the existing stub "Export SRT" button in the SRT preview header → `<a href={getSrtDownloadUrl(videoId, previewLanguage)} download>`
3. Both use `<a>` tags with `download` attribute for native browser download behavior

---

## Post-implementation

### README.md checklist updates
Mark `[x]` for tasks 1.26–1.32 and verification items V1.18–V1.25.

### CHANGELOG.md
Entries already exist in `[1.1.0]`. Verify they match the actual implementation; adjust wording if needed. Move to `[Unreleased]` if the 1.1.0 version block shouldn't include not-yet-released work.

### Commits
One commit per task (7 commits total). No AI mentions. Each commit updates README checklist + CHANGELOG.

### PR
After all tasks: `gh pr create` from `feature/phase1-translation-profiles` → `main`.

---

## Verification

After implementation, run through these checks:

```bash
# V1.18 — Profiles load
python3 -c "
from src.translator.profiles import list_profiles, load_profile
print(list_profiles())
p = load_profile('funny-casual-vi')
print(p.name, p.target_language, len(p.example_pairs))
"

# V1.19 — LLM translation (requires ANTHROPIC_API_KEY set)
# Test with a downloaded video that has zh SRT

# V1.20 — Profile CRUD API
curl http://localhost:8000/api/profiles
curl http://localhost:8000/api/profiles/funny-casual-vi

# V1.21 — Translation API with SSE
# POST /api/translate with video_id

# V1.22–V1.23 — UI: translation panel, profile editor
# Manual: open localhost:5173, download+transcribe, then translate

# V1.24 — Raw video download
curl -I http://localhost:8000/api/videos/{id}/raw
# Check Content-Disposition header

# V1.25 — SRT export
# Click export button in UI, verify file downloads

# Lint
make lint
```

---

## Critical files reference

| File | Action |
|------|--------|
| `src/translator/__init__.py` | Create (factory) |
| `src/translator/profiles.py` | Create (profile system) |
| `src/translator/llm.py` | Create (LLM translator) |
| `config/translation_profiles/*.yaml` | Create (3 profiles + example) |
| `config/config.example.yaml` | Modify (add translation section) |
| `src/api/routers/translate.py` | Create (API router) |
| `src/api/models.py` | Modify (add translate models) |
| `src/api/task_manager.py` | Modify (add run_translate) |
| `src/api/__init__.py` | Modify (register router) |
| `src/api/routers/editor.py` | Modify (Content-Disposition header) |
| `src/api/routers/transcribe.py` | Modify (SRT download endpoint) |
| `ui-app/src/api/types.ts` | Modify (profile types) |
| `ui-app/src/api/client.ts` | Modify (translation + download APIs) |
| `ui-app/src/pages/DownloadTranscribe.tsx` | Modify (translation UI + download buttons) |
| `pyproject.toml` | Modify (add anthropic, openai deps) |
| `README.md` | Modify (checklist updates) |
| `CHANGELOG.md` | Modify (verify/update entries) |

### Reusable existing code
- `src/processor/subtitle.parse_srt()` — parse SRT into segments
- `src/processor/subtitle.write_srt()` — write segments back to SRT
- `src/api/task_manager.TaskManager` — SSE pattern, `_emit()`, `subscribe()`
- `ui-app/src/api/client.subscribeSSE()` — SSE subscription in UI
