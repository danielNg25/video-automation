# Phase 1 — Core: Download + Transcribe (Week 1-2)

> **Action**: Submit TikTok app for compliance audit at the start of this phase (takes 1-2 weeks).

---

## Task List

### 1.1 Project Scaffolding — `pyproject.toml`

- Define project metadata, Python >=3.11 requirement
- Split dependencies into groups: `[project.optional-dependencies]` with `linux` and `macos` extras
- Add `[project.scripts]` entry point: `douyin-repurpose = "src.cli:main"`
- **Dependencies**: None (first task)

### 1.2 Requirements Files

- Files: `requirements.txt`, `requirements-linux.txt`, `requirements-macos.txt`
- Common: httpx, pyyaml, click, yt-dlp, google-api-python-client, google-auth-oauthlib, authlib, tweepy, tenacity, rich
- Linux: `faster-whisper>=1.1.0`
- macOS: `mlx-whisper>=0.4.0`
- **Dependencies**: None (parallel with 1.1)

### 1.3 Directory Structure + Init Files

Create all directories and placeholder files:

```
src/__init__.py
src/downloader/__init__.py
src/transcriber/__init__.py
src/processor/__init__.py
src/uploader/__init__.py
src/utils/__init__.py
config/          (dir)
data/raw/.gitkeep
data/srt/.gitkeep
data/output/.gitkeep
data/logs/.gitkeep
tests/           (dir)
scripts/         (dir)
```

Create `.gitignore`:
```
data/raw/*.mp4
data/output/*.mp4
config/*_token.json
config/*_secrets.json
config/douyin_cookie.txt
__pycache__/
.venv/
*.egg-info/
```

- **Dependencies**: None

### 1.4 Configuration Files

- `config/config.yaml` — Main config (douyin, whisper, ffmpeg, platforms, pipeline sections)
- `config/platforms.yaml` — Per-platform subtitle language + video spec settings
- `config/subtitle_styles.yaml` — Default + per-platform subtitle styling (ASS format)
- **Dependencies**: 1.3

### 1.5 Config Loader — `src/utils/config.py`

- `load_config(path: str = "config/config.yaml") -> dict`
- Uses PyYAML
- Supports `${VAR}` environment variable interpolation in YAML values
- **Dependencies**: 1.4

### 1.6 Logger Utility — `src/utils/logger.py`

- Structured JSON logger using Python `logging` + custom JSON formatter
- Output to console (human-readable via `rich`) and file (JSON to `data/logs/pipeline.log`)
- `setup_logger(name: str, level: str = "INFO") -> logging.Logger`
- **Dependencies**: 1.3

### 1.7 Metadata Utility — `src/utils/metadata.py`

- `VideoMetadata` dataclass: `video_id`, `title`, `author`, `duration`, `resolution`, `description`, `hashtags`, `source_url`, `file_path`
- `extract_metadata_from_file(path: Path) -> dict` using ffprobe subprocess
- **Dependencies**: 1.3

### 1.8 Douyin Downloader — `src/downloader/douyin.py`

- Class `DouyinDownloader`
- `async download(share_url: str, output_dir: Path) -> VideoMetadata`
- Uses `httpx.AsyncClient` to call self-hosted API at `/api/hybrid/video_data`
- Stream-download MP4 to `data/raw/{video_id}.mp4`
- Error handling: API unreachable, cookie expired, invalid URL format
- **Dependencies**: 1.5, 1.6, 1.7

### 1.9 yt-dlp Fallback — `src/downloader/ytdlp.py`

- Class `YtDlpDownloader`
- `async download(url: str, output_dir: Path) -> VideoMetadata`
- Wraps `yt-dlp` via subprocess (CLI, not Python import)
- Output template: `{output_dir}/{video_id}.mp4`
- Extracts metadata from `yt-dlp --dump-json`
- **Dependencies**: 1.5, 1.6, 1.7

### 1.10 Downloader Factory — `src/downloader/__init__.py`

- `get_downloader(config: dict) -> DouyinDownloader | YtDlpDownloader`
- `download_with_fallback(url, output_dir, config)` — tries Douyin API first, falls back to yt-dlp on failure
- **Dependencies**: 1.8, 1.9

### 1.11 Base Transcriber — `src/transcriber/base.py`

- Abstract class `BaseTranscriber`:
  - `transcribe(video_path: str, language: str, task: str) -> list[dict]` (abstract)
  - `generate_srt(segments: list[dict], output_path: Path) -> Path` (concrete, shared)
  - `_format_timestamp(seconds: float) -> str` (static, shared)
- Factory: `get_transcriber(config: dict) -> BaseTranscriber` — checks `sys.platform`
- **Dependencies**: 1.6

### 1.12 faster-whisper Backend — `src/transcriber/faster.py`

- Class `FasterWhisperTranscriber(BaseTranscriber)`
- Uses `faster_whisper.WhisperModel`
- VAD filtering: `vad_filter=True`, `vad_parameters=dict(min_silence_duration_ms=500)`
- Supports `task="transcribe"` (Chinese) and `task="translate"` (zh→en)
- **Dependencies**: 1.11

### 1.13 mlx-whisper Backend — `src/transcriber/mlx.py`

- Class `MLXWhisperTranscriber(BaseTranscriber)`
- Uses `mlx_whisper` package
- Same interface, adapted to MLX API differences
- **Dependencies**: 1.11

### 1.14 Transcriber Factory — `src/transcriber/__init__.py`

- Wire `get_transcriber()`: `sys.platform == "darwin"` → MLX, else → faster-whisper
- Allow config override to force a specific backend
- **Dependencies**: 1.12, 1.13

### 1.15 Translation Support — `src/processor/subtitle.py` (started early)

- `translate_srt(srt_path: Path, method: str = "whisper") -> Path`
  - `"whisper"`: Re-transcribe with `task="translate"`
  - `"deepl"`: Parse SRT → DeepL API → translated SRT
- Output: `{video_id}_en.srt`
- **Dependencies**: 1.11

### 1.16 Cookie Refresh Script — `scripts/refresh_douyin_cookie.py`

- Standalone helper to refresh Douyin cookies
- Can be a placeholder with browser instructions
- **Dependencies**: None

### 1.17 Phase 1 Tests

- `tests/test_downloader.py` — URL parsing, metadata extraction, error handling (mock HTTP)
- `tests/test_transcriber.py` — SRT generation, timestamp formatting, VAD config
- Use `pytest` + `pytest-asyncio`
- **Dependencies**: 1.10, 1.14

---

## Dependency Graph

```
1.1, 1.2, 1.3 ──────── (parallel, no deps)
       │
       ▼
      1.4 ◄──────────── (needs 1.3)
       │
       ▼
      1.5               1.6              1.7
 (needs 1.4)       (needs 1.3)      (needs 1.3)
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
      1.8 ◄──── (needs 1.5, 1.6, 1.7)     1.11 ◄── (needs 1.6)
      1.9 ◄──── (needs 1.5, 1.6, 1.7)        │
       │                                    1.12, 1.13 ◄── (need 1.11)
       ▼                                       │
     1.10 ◄── (needs 1.8, 1.9)             1.14 ◄── (needs 1.12, 1.13)
                                               │
                                            1.15 ◄── (needs 1.11)
```

---

## Verification Checklist

### V1.1: Project scaffolding installs correctly

```bash
cd /Users/daniel/WorkStation/Personal/video/douyin-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[macos]"
pip list | grep -E "mlx-whisper|httpx|click|pyyaml|yt-dlp"
```

**Expected**: All packages listed, no install errors.

### V1.2: Directory structure is correct

```bash
find . -name "__init__.py" | sort
```

**Expected**:
```
./src/__init__.py
./src/downloader/__init__.py
./src/processor/__init__.py
./src/transcriber/__init__.py
./src/uploader/__init__.py
./src/utils/__init__.py
```

### V1.3: Config loads with env var interpolation

```bash
python3 -c "
from src.utils.config import load_config
cfg = load_config('config/config.yaml')
print(cfg['douyin']['api_base'])
print(cfg['whisper']['model_size'])
"
```

**Expected**: `http://localhost:8080` and `large-v3`.

### V1.4: Douyin download (requires Docker container)

```bash
docker run -d --name douyin-api -p 8080:8080 evil0ctal/douyin_tiktok_download_api:latest

python3 -c "
import asyncio
from src.downloader.douyin import DouyinDownloader
from pathlib import Path

async def test():
    dl = DouyinDownloader('http://localhost:8080')
    result = await dl.download('https://v.douyin.com/iRNBho6t/', Path('data/raw'))
    print(f'Downloaded: {result.video_id}')
    print(f'File exists: {Path(result.file_path).exists()}')
    print(f'Title: {result.title}')
asyncio.run(test())
"
```

**Expected**: MP4 in `data/raw/`, metadata printed.

### V1.5: yt-dlp fallback

```bash
python3 -c "
import asyncio
from src.downloader.ytdlp import YtDlpDownloader
from pathlib import Path

async def test():
    dl = YtDlpDownloader()
    result = await dl.download('https://v.douyin.com/iRNBho6t/', Path('data/raw'))
    print(f'Downloaded: {result.video_id}')
asyncio.run(test())
"
```

**Expected**: Same MP4 downloaded via yt-dlp.

### V1.6: Download with automatic fallback

```bash
python3 -c "
import asyncio
from src.downloader import download_with_fallback
from pathlib import Path
from src.utils.config import load_config

cfg = load_config()
result = asyncio.run(download_with_fallback('https://v.douyin.com/iRNBho6t/', Path('data/raw'), cfg))
print(f'Success: {result.video_id}')
"
```

**Expected**: Downloads via primary; if API down, auto-falls back to yt-dlp.

### V1.7: Transcriber auto-selects correct backend

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
t = get_transcriber(load_config()['whisper'])
print(type(t).__name__)
"
```

**Expected on macOS**: `MLXWhisperTranscriber`

### V1.8: Transcription produces valid SRT

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
from pathlib import Path

t = get_transcriber(load_config()['whisper'])
segments = t.transcribe('data/raw/<video_id>.mp4', language='zh')
srt_path = t.generate_srt(segments, Path('data/srt/<video_id>.srt'))
with open(srt_path) as f:
    print(f.read()[:500])
"
```

**Expected**: SRT with numbered sequences, `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamps, Chinese text.

### V1.9: Timestamp formatting edge cases

```bash
python3 -c "
from src.transcriber.base import BaseTranscriber
print(BaseTranscriber._format_timestamp(0.0))       # 00:00:00,000
print(BaseTranscriber._format_timestamp(61.5))       # 00:01:01,500
print(BaseTranscriber._format_timestamp(3661.123))   # 01:01:01,123
"
```

### V1.10: Chinese → English translation

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
from pathlib import Path

t = get_transcriber(load_config()['whisper'])
segments = t.transcribe('data/raw/<video_id>.mp4', language='zh', task='translate')
srt_path = t.generate_srt(segments, Path('data/srt/<video_id>_en.srt'))
with open(srt_path) as f:
    print(f.read()[:500])
"
```

**Expected**: SRT with English text.

### V1.11: Unit tests pass

```bash
python3 -m pytest tests/test_downloader.py tests/test_transcriber.py -v
```

---

## Web UI + API (Phase 1)

### 1.18 FastAPI Foundation — `server/main.py`

Set up the FastAPI application:

- `server/__init__.py` — Package init
- `server/main.py` — FastAPI app with CORS (allow `localhost:5173`), lifespan for startup/shutdown
- `server/deps.py` — Shared dependencies: config loader, task manager singleton
- `server/models.py` — Pydantic schemas:
  - `DownloadRequest`: `url: str`
  - `TranscribeRequest`: `video_id: str`, `language: str = "zh"`, `task: str = "transcribe"`
  - `TaskResponse`: `task_id: str`
  - `VideoResponse`: mirrors `VideoMetadata` dataclass
  - `SRTSegment`: `index: int`, `start: str`, `end: str`, `text: str`
- **Dependencies**: None (can start in parallel with backend tasks)

### 1.19 Task Manager — `server/task_manager.py`

In-memory async task tracking with SSE support:

- `TaskInfo` dataclass: `task_id`, `status` (pending/running/completed/failed), `progress` (0.0–1.0), `stage`, `result`, `error`, `events: asyncio.Queue`
- `TaskManager` class:
  - `create_task(name: str) -> TaskInfo`
  - `update_progress(task_id, progress, stage, message)`
  - `complete_task(task_id, result)`
  - `fail_task(task_id, error)`
  - `get_task(task_id) -> TaskInfo`
  - `subscribe(task_id) -> AsyncGenerator[dict]` — yields SSE events from the queue
- **Dependencies**: 1.18

### 1.20 SSE Events Router — `server/routers/events.py`

- `GET /api/events/{task_id}` — SSE endpoint using `StreamingResponse` with `text/event-stream`
- Event types: `progress`, `stage_change`, `complete`, `error`
- Format: `event: {type}\ndata: {json}\n\n`
- Auto-closes when task completes or client disconnects
- **Dependencies**: 1.19

### 1.21 Download Router + Service — `server/routers/download.py` + `server/services/download_service.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/download` | Start download `{"url": "..."}` → `{"task_id": "..."}` |
| `GET` | `/api/download/{task_id}` | Get download result (metadata + file info) |
| `GET` | `/api/videos` | List all downloaded videos (scan `data/raw/`) |
| `GET` | `/api/videos/{video_id}` | Get single video detail |

**Service layer** (`download_service.py`):
- Wraps `download_with_fallback()` from `src/downloader/__init__.py`
- Adds progress tracking: intercepts the httpx stream to count bytes vs content-length
- Spawns download as `asyncio.Task`, pushes progress events to task manager
- Reports fallback activation: emits `stage_change` event when switching to yt-dlp
- **Dependencies**: 1.10, 1.19, 1.20

### 1.22 Transcribe Router + Service — `server/routers/transcribe.py` + `server/services/transcribe_service.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/transcribe` | Start transcription `{"video_id": "...", "language": "zh"}` → `{"task_id": "..."}` |
| `GET` | `/api/transcribe/{task_id}` | Get transcription result (segments + SRT path) |
| `GET` | `/api/videos/{video_id}/srt` | Get SRT content as JSON segments or raw text |

**Service layer** (`transcribe_service.py`):
- Wraps `get_transcriber()` from `src/transcriber/__init__.py`
- Runs transcription in thread via `asyncio.to_thread()` (CPU-bound)
- Progress: faster-whisper returns a generator (incremental progress possible); mlx-whisper returns all at once (0% → 100%)
- **Dependencies**: 1.14, 1.19, 1.20

### 1.23 React Frontend Foundation — `web/`

Scaffold the frontend:

```
web/
├── package.json
├── vite.config.ts           # proxy /api → localhost:8000
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── App.tsx              # Sidebar layout + page routing
│   ├── api/
│   │   └── client.ts        # fetch wrapper for API calls
│   ├── hooks/
│   │   ├── useTask.ts       # SSE subscription hook (manages EventSource lifecycle)
│   │   └── useApi.ts        # Generic API hook with loading/error states
│   ├── components/
│   │   ├── Sidebar.tsx      # Navigation sidebar
│   │   ├── ProgressBar.tsx  # Reusable progress bar with label
│   │   └── VideoCard.tsx    # Video metadata card
│   └── pages/
│       └── DownloadPage.tsx # Phase 1 page
```

**Setup commands:**
```bash
cd web && npm create vite@latest . -- --template react-ts
npm install tailwindcss @tailwindcss/vite
npx shadcn@latest init
npx shadcn@latest add button input card progress badge tabs scroll-area
```

- **Dependencies**: None (can start in parallel)

### 1.24 Download Page — `web/src/pages/DownloadPage.tsx`

**Components:**

1. **URLInput section** (top):
   - Large input field with placeholder: "Paste Douyin share link or URL"
   - "Download" button (disabled while active, shows spinner)
   - Error banner with retry button

2. **DownloadProgress** (middle, shown during download):
   - Progress bar with percentage
   - Speed + ETA text: "2.3 MB / 5.1 MB — 1.2 MB/s"
   - Fallback indicator badge: "Using yt-dlp fallback" (if applicable)

3. **VideoCard** (shown after download):
   - Left: video thumbnail (or placeholder icon)
   - Right: title, author, duration, resolution, file size
   - "Transcribe" button with dropdown: Chinese / Chinese + English

4. **TranscriptionProgress** (shown during transcription):
   - Indeterminate or determinate progress bar
   - Stage text: "Loading model..." → "Transcribing..." → "Generating SRT..."

5. **SRTPreview** (shown after transcription):
   - Scrollable list of segments
   - Each segment: timestamp range + Chinese text + English (lighter color, if available)

6. **RecentDownloads** (bottom):
   - Compact grid of previously downloaded videos
   - Status badges: Downloaded / Transcribed / Processed

**Key interactions:**
- Download button → POST `/api/download` → subscribe SSE `/api/events/{task_id}`
- Progress updates drive the progress bar in real-time
- After download, auto-fetch video metadata from GET `/api/videos/{video_id}`
- Transcribe button → POST `/api/transcribe` → subscribe SSE → show SRT preview on complete

- **Dependencies**: 1.21, 1.22, 1.23

### 1.25 Backend Dependencies — `pyproject.toml`

Add to `[project.dependencies]`:
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
```

Add to `Makefile`:
```makefile
server:
	uvicorn server.main:app --reload --port 8000

web:
	cd web && npm run dev

dev:
	make server & make web & wait
```

- **Dependencies**: 1.1

---

## Enhancement: LLM Translation with Profiles

### 1.26 Translation Profile System — `src/translator/profiles.py`

Whisper doesn't transcribe well for languages like Vietnamese. The workflow becomes:
1. Transcribe audio → Chinese or English SRT (Whisper is good at these)
2. Translate SRT → target language using an LLM with a **translation profile** for tone/style control

**Translation Profile** dataclass (`TranslationProfile`):
```python
@dataclass
class TranslationProfile:
    name: str              # e.g., "funny-gen-z", "formal-news", "sarcastic"
    description: str       # e.g., "Casual Gen-Z humor, uses slang and memes"
    style_guide: str       # Detailed prompt context for the LLM:
                           #   - Personality/tone (funny, sarcastic, wholesome)
                           #   - Characteristic phrases or catchwords
                           #   - Slang preferences ("lol", "bruh", Vietnamese internet slang)
                           #   - What to avoid (formal language, stiff translations)
    target_language: str   # e.g., "vi", "ko", "ja"
    source_language: str   # e.g., "zh" or "en" (what Whisper transcribed to)
    example_pairs: list[dict]  # Optional few-shot examples:
                               #   [{"source": "这太搞笑了", "target": "Ủa cái gì vậy trời 😂"}]
```

**Built-in profiles** stored in `config/translation_profiles/`:
```
config/translation_profiles/
├── funny-casual-vi.yaml     # Funny, casual Vietnamese (Gen-Z internet humor)
├── neutral-vi.yaml           # Neutral, natural Vietnamese
├── dramatic-vi.yaml          # Over-the-top dramatic narration style
├── custom.yaml.example       # Template for user-created profiles
```

**Profile YAML format** (`funny-casual-vi.yaml`):
```yaml
name: funny-casual-vi
description: "Casual Vietnamese with Gen-Z humor, internet slang, and meme references"
target_language: vi
source_language: zh  # or "en" — translate from whichever Whisper output is better
style_guide: |
  You are translating short video subtitles into Vietnamese for a young audience.

  Personality: Funny, relatable, slightly exaggerated reactions.

  Rules:
  - Use casual Vietnamese, not formal/literary style
  - Use internet slang naturally: "ủa", "trời ơi", "gì vậy ta", "chill", "flex"
  - Add light humor/exaggeration where the original is already playful
  - Keep subtitle length short — max 2 lines, prefer 1
  - Preserve the emotional beat of the original (if something is a punchline, make it land in Vietnamese)
  - Do NOT over-translate — if the original is simple, keep it simple
  - Do NOT add emojis unless the context really calls for it

  Avoid:
  - Stiff, textbook Vietnamese
  - Translating literally when a natural Vietnamese expression exists
  - Being try-hard funny — the humor should feel effortless

example_pairs:
  - source: "这太搞笑了吧"
    target: "Trời ơi cái gì vậy nè 😂"
  - source: "我真的服了"
    target: "Tui chịu luôn á"
  - source: "这个也太好吃了"
    target: "Ngon dữ vậy trời"
  - source: "你们觉得怎么样"
    target: "Mọi người thấy sao nè"
```

**Profile manager functions:**
- `load_profile(name: str) -> TranslationProfile` — load from YAML
- `list_profiles() -> list[str]` — list available profile names
- `save_profile(profile: TranslationProfile) -> None` — save custom profile
- `delete_profile(name: str) -> None` — delete custom profile
- `get_default_profile(target_lang: str) -> str` — return best default for a language

- **Dependencies**: 1.4

### 1.27 LLM Translator — `src/translator/llm.py`

Class `LLMTranslator`:

**`translate_srt(srt_path: Path, profile: TranslationProfile, output_path: Path) -> Path`**:
1. Parse source SRT into segments
2. Build translation prompt using the profile's `style_guide` + `example_pairs`
3. Send segments to LLM in batches (5-10 segments per request to maintain context)
4. Batch strategy:
   - Group consecutive segments for context continuity
   - Include 1-2 previous segments as context for each batch
   - LLM returns translated text for each segment
5. Write translated segments to output SRT: `{video_id}_{target_lang}.srt`

**Prompt structure:**
```
System: You are a subtitle translator. {profile.style_guide}

Here are example translations:
{profile.example_pairs formatted}

Translate the following subtitle segments from {source_language} to {target_language}.
Return ONLY the translations, one per line, matching the input order.

1. {segment_1_text}
2. {segment_2_text}
...
```

**LLM backend support** (configured in `config/config.yaml`):
```yaml
translation:
  backend: "anthropic"          # "anthropic" | "openai" | "local"
  model: "claude-sonnet-4-20250514"  # model ID
  api_key: "${ANTHROPIC_API_KEY}"
  max_segments_per_batch: 8     # segments sent per LLM call
  temperature: 0.7              # higher = more creative translations
  default_profile: "funny-casual-vi"
```

- Support multiple LLM providers: Anthropic (Claude), OpenAI (GPT), or local models
- Rate limiting: respect API limits, add delay between batches
- Cost tracking: log token usage per translation
- Fallback: if LLM fails on a batch, retry with smaller batch or fall back to literal translation

- **Dependencies**: 1.26, 1.15

### 1.28 Translator Factory — `src/translator/__init__.py`

```python
def get_translator(config: dict) -> LLMTranslator | WhisperTranslator:
    """Factory: returns configured translator based on config."""

def translate_with_profile(
    srt_path: Path,
    profile_name: str,
    config: dict,
    output_dir: Path
) -> Path:
    """High-level: load profile → create translator → translate → return output path."""
```

- `WhisperTranslator` wraps the existing `translate_srt()` for simple zh→en
- `LLMTranslator` uses profiles for any language with style control
- **Dependencies**: 1.26, 1.27

### 1.29 Translation API — `src/api/routers/translate.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/translate` | Start translation `{video_id, profile_name, source_lang}` → `{task_id}` |
| `GET` | `/api/translate/{task_id}` | Get translation result |
| `GET` | `/api/profiles` | List available translation profiles |
| `GET` | `/api/profiles/{name}` | Get profile details |
| `POST` | `/api/profiles` | Create custom profile |
| `PUT` | `/api/profiles/{name}` | Update profile |
| `DELETE` | `/api/profiles/{name}` | Delete custom profile |

**`POST /api/translate` request:**
```json
{
  "video_id": "7xxx",
  "profile_name": "funny-casual-vi",
  "source_language": "zh"
}
```

**Translation flow:**
1. Load source SRT (`data/srt/{video_id}_{source_lang}.srt`)
2. Load translation profile
3. Run LLM translation in background task with progress (batch X/N)
4. Save output to `data/srt/{video_id}_{target_lang}.srt`

- **Dependencies**: 1.28, 1.19, 1.20

### 1.30 Translation UI — Update `DownloadPage.tsx`

Add translation section after transcription:

1. **TranslationPanel** (shown after transcription completes):
   - Profile selector dropdown: lists profiles from `GET /api/profiles`
   - Profile preview card: shows selected profile's description + style_guide summary + example pairs
   - Source language indicator: "Translating from: Chinese SRT"
   - "Translate" button
   - Translation progress: "Translating batch 3/8..." with progress bar

2. **ProfileEditor** (accessible via "Create Profile" or "Edit" button):
   - Name field
   - Description textarea
   - Target language selector
   - Source language selector
   - Style guide textarea (large, with placeholder showing example)
   - Example pairs editor: add/remove rows with source + target text fields
   - "Save Profile" button
   - "Test Translation" button: translates first 3 segments as preview

3. **SRTPreview update**:
   - Language tabs: Chinese / English / Vietnamese (or whatever target language)
   - Side-by-side comparison mode: source + translated subtitle
   - "Re-translate" button on individual segments (sends single segment to LLM for retry)

**Key interactions:**
- Select profile → preview appears with style description
- Click Translate → POST `/api/translate` → SSE progress by batch → SRT preview updates
- Switch language tab to see translated subtitles
- Create/edit profile → POST/PUT `/api/profiles` → profile available in dropdown

- **Dependencies**: 1.29, 1.24

---

## Enhancement: Download Raw Video Feature

### 1.31 Raw Video Download Endpoint — `src/api/routers/download.py`

Add endpoint to serve the raw downloaded video file for user download:

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/videos/{video_id}/raw` | Stream raw MP4 file for browser download |
| `GET` | `/api/videos/{video_id}/thumbnail` | Serve video thumbnail image |

**Implementation:**
- Use FastAPI `FileResponse` with `media_type="video/mp4"`
- Set `Content-Disposition: attachment; filename="{title}.mp4"` for browser download
- Validate file exists in `data/raw/{video_id}.mp4`
- Support `Range` header for partial content (video seeking in browser)

- **Dependencies**: 1.21

### 1.32 Download Raw Video UI — Update `DownloadPage.tsx`

Add download button to VideoCard:

1. **VideoCard update**:
   - Add "Download Video" button (download icon) next to existing actions
   - Click triggers browser download via `GET /api/videos/{video_id}/raw`
   - Shows file size badge: "45.2 MB"

2. **SRTPreview update**:
   - "Export SRT" button: downloads SRT file via `GET /api/videos/{video_id}/srt?format=file&language=zh`
   - "Export All" dropdown: download raw video + all SRT files as individual downloads

- **Dependencies**: 1.31, 1.24

---

### Updated Dependency Graph (with Web UI + Enhancements)

```
1.1, 1.2, 1.3 ──────── (parallel, no deps)
       │
       ▼
      1.4 ◄──────────── (needs 1.3)
       │
       ▼
      1.5               1.6              1.7
 (needs 1.4)       (needs 1.3)      (needs 1.3)
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
      1.8 ◄──── (needs 1.5, 1.6, 1.7)     1.11 ◄── (needs 1.6)
      1.9 ◄──── (needs 1.5, 1.6, 1.7)        │
       │                                    1.12, 1.13 ◄── (need 1.11)
       ▼                                       │
     1.10 ◄── (needs 1.8, 1.9)             1.14 ◄── (needs 1.12, 1.13)
                                               │
                                            1.15 ◄── (needs 1.11)

                    --- Web UI ---

  1.18 (FastAPI) ────── (no deps, parallel with backend)
       │
       ▼
  1.19 (TaskManager) ◄── (needs 1.18)
       │
       ▼
  1.20 (SSE) ◄── (needs 1.19)
       │
       ├──▶ 1.21 (Download API) ◄── (needs 1.10, 1.19, 1.20)
       └──▶ 1.22 (Transcribe API) ◄── (needs 1.14, 1.19, 1.20)

  1.23 (React scaffold) ────── (no deps, parallel)
       │
       ▼
  1.24 (Download page) ◄── (needs 1.21, 1.22, 1.23)

              --- Translation + Download Enhancements ---

  1.26 (Profiles) ◄── (needs 1.4)
       │
       ▼
  1.27 (LLM Translator) ◄── (needs 1.26, 1.15)
       │
       ▼
  1.28 (Translator Factory) ◄── (needs 1.26, 1.27)
       │
       ▼
  1.29 (Translation API) ◄── (needs 1.28, 1.19, 1.20)
       │
       ▼
  1.30 (Translation UI) ◄── (needs 1.29, 1.24)

  1.31 (Raw download endpoint) ◄── (needs 1.21)
       │
       ▼
  1.32 (Download UI) ◄── (needs 1.31, 1.24)
```

---

### Web UI Verification Checklist

### V1.12: FastAPI server starts

```bash
make server
# In another terminal:
curl http://localhost:8000/docs
```

**Expected**: Swagger UI loads with all endpoints.

### V1.13: Download via API

```bash
curl -X POST http://localhost:8000/api/download \
  -H "Content-Type: application/json" \
  -d '{"url": "https://v.douyin.com/iRNBho6t/"}'
# Returns: {"task_id": "..."}

# Subscribe to progress:
curl -N http://localhost:8000/api/events/{task_id}
# Streams: event: progress, event: complete
```

**Expected**: Task starts, progress events stream, download completes.

### V1.14: Transcribe via API

```bash
curl -X POST http://localhost:8000/api/transcribe \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<video_id>", "language": "zh"}'

curl http://localhost:8000/api/videos/<video_id>/srt
```

**Expected**: Transcription starts, SRT content returned as JSON segments.

### V1.15: Video list API

```bash
curl http://localhost:8000/api/videos
```

**Expected**: JSON array of video metadata for all downloaded videos.

### V1.16: React UI loads

```bash
make web
# Open http://localhost:5173
```

**Expected**: Download page renders with URL input, sidebar navigation.

### V1.17: End-to-end UI flow

1. Open `http://localhost:5173`
2. Paste Douyin URL → click Download
3. See progress bar update in real-time
4. After download, see video card with metadata
5. Click Transcribe → see progress → see SRT preview

**Expected**: Full flow works without using terminal.

---

### Translation Verification Checklist

### V1.18: Translation profiles load

```bash
python3 -c "
from src.translator.profiles import list_profiles, load_profile
profiles = list_profiles()
print(f'Available profiles: {profiles}')
p = load_profile('funny-casual-vi')
print(f'Profile: {p.name}, target: {p.target_language}')
print(f'Examples: {len(p.example_pairs)}')
"
```

**Expected**: Profiles listed, `funny-casual-vi` loads with Vietnamese target and example pairs.

### V1.19: LLM translation produces styled output

```bash
python3 -c "
import asyncio
from src.translator.llm import LLMTranslator
from src.translator.profiles import load_profile
from pathlib import Path

async def test():
    profile = load_profile('funny-casual-vi')
    translator = LLMTranslator(backend='anthropic', model='claude-sonnet-4-20250514')
    output = await translator.translate_srt(
        Path('data/srt/<video_id>_zh.srt'),
        profile,
        Path('data/srt/<video_id>_vi.srt')
    )
    with open(output) as f:
        print(f.read()[:500])
asyncio.run(test())
"
```

**Expected**: Vietnamese SRT with casual/funny style matching the profile.

### V1.20: Profile CRUD API

```bash
# List profiles
curl http://localhost:8000/api/profiles

# Get specific profile
curl http://localhost:8000/api/profiles/funny-casual-vi

# Create custom profile
curl -X POST http://localhost:8000/api/profiles \
  -H "Content-Type: application/json" \
  -d '{"name": "test-vi", "description": "Test", "target_language": "vi", "source_language": "zh", "style_guide": "Translate naturally", "example_pairs": []}'

# Delete profile
curl -X DELETE http://localhost:8000/api/profiles/test-vi
```

**Expected**: All CRUD operations work, profiles persist in `config/translation_profiles/`.

### V1.21: Translation API with progress

```bash
curl -X POST http://localhost:8000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<video_id>", "profile_name": "funny-casual-vi", "source_language": "zh"}'

# Subscribe to progress:
curl -N http://localhost:8000/api/events/{task_id}
# Expect: "Translating batch 1/8...", "Translating batch 2/8...", etc.
```

**Expected**: Translation runs with batch-level progress, output SRT saved.

### V1.22: Translation UI flow

1. After transcription completes, see Translation panel
2. Select "funny-casual-vi" profile → see description preview
3. Click Translate → progress shows "Batch 3/8..."
4. After completion, SRT preview adds Vietnamese tab
5. Switch between Chinese / English / Vietnamese tabs

**Expected**: Multi-language SRT preview with profile-guided translation.

### V1.23: Custom profile creation UI

1. Click "Create Profile" button
2. Fill in name, description, target language, style guide
3. Add 3 example pairs (source → target)
4. Click "Test Translation" → see preview of first 3 segments translated
5. Click "Save Profile" → profile appears in dropdown

**Expected**: Custom profile persists and is usable for translation.

### V1.24: Raw video download

```bash
curl -I http://localhost:8000/api/videos/<video_id>/raw
```

**Expected**: `200 OK`, `Content-Type: video/mp4`, `Content-Disposition: attachment`.

### V1.25: SRT export from UI

1. After transcription, click "Export SRT" button
2. Browser downloads `{video_id}_zh.srt` file
3. Click "Export All" → downloads raw video + all SRT files

**Expected**: Files download correctly in browser.

---

## Edge Cases

1. **Invalid Douyin URL**: Share links come in multiple formats (`v.douyin.com/xxx/`, `www.douyin.com/video/xxx`, raw text with embedded URL). Must extract actual URL.
2. **Cookie expiry**: API returns 403 or error JSON. Detect, log clearly, suggest `refresh_douyin_cookie.py`.
3. **Large files**: Stream download — never load entire file in memory. Use `httpx.stream()`.
4. **Slideshow videos**: Image slideshows may not have video URL. Detect and skip.
5. **No speech (music-only)**: VAD results in empty segments. Skip SRT generation, log warning.
6. **Unicode filenames**: Use `video_id` (numeric) for filenames, not titles.
7. **Network timeout**: 60s for API calls, 120s for downloads. Clear error messages.
8. **Model download on first run**: Whisper large-v3 is ~3GB. Log progress, handle interruption.
9. **LLM API rate limits**: Batch translation may hit rate limits. Implement delay between batches, retry with exponential backoff.
10. **LLM output mismatch**: LLM returns wrong number of translations vs segments. Validate count, retry batch if mismatch.
11. **Mixed-language source**: Source video has both Chinese and English speech. Whisper may produce mixed SRT. Profile should handle gracefully.
12. **Empty segments**: Some SRT segments may be empty (music/silence). Skip these in LLM batches, preserve timing in output.
13. **Very long videos**: 100+ segments means many LLM batches. Track cost and warn user if estimated cost exceeds threshold.
14. **Profile YAML syntax errors**: Validate on load, return clear error about which field is invalid.
