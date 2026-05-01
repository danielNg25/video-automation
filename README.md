# Douyin Video Repurposing Pipeline

Automated pipeline to download videos from Douyin, generate AI subtitles (Chinese transcription + English/Vietnamese translation), dub with TTS, and produce per-platform reformatted exports (YouTube, TikTok, Facebook, X aspect ratios and subtitle languages). Auto-posting is intentionally out of scope — exports are downloaded and uploaded manually.

## Architecture

```
┌──────────┐   ┌───────────┐   ┌───────────┐   ┌─────┐   ┌─────────┐
│ Download │──▶│Transcribe │──▶│ Translate │──▶│ TTS │──▶│ Process │
│ Douyin + │   │ OCR/SRT   │   │ LLM       │   │ Dub │   │ ffmpeg  │
│ yt-dlp   │   │ PaddleOCR │   │ Anthropic/│   │     │   │ burn-in │
└──────────┘   └───────────┘   │ DeepSeek  │   └─────┘   │+reformat│
     │              │          └───────────┘      │       └─────────┘
     ▼              ▼               ▼             ▼            ▼
 /data/raw/    /data/srt/     /data/srt/     /data/tts/  /data/output/
 {id}.mp4      {id}_zh.srt    {id}_vi.srt    {id}.wav    {id}_{plat}.mp4 {id}_state.json
```

**Orchestration**: Pipeline state persisted to `data/logs/{id}_state.json` for crash recovery. Duplicate detection via `processed_videos.json`. Batch processing with configurable concurrency.

## Tech Stack

| Component     | Tool                                           |
| ------------- | ---------------------------------------------- |
| Language      | Python 3.11+                                   |
| Download      | Self-hosted Douyin API + yt-dlp fallback       |
| Transcription | PaddleOCR (subtitle extraction from video frames) |
| Video Process | ffmpeg (subtitle burn-in + platform reformat)  |
| YouTube       | YouTube Data API v3 (OAuth 2.0)                |
| TikTok        | TikTok Content Posting API (OAuth 2.0 + PKCE)  |
| Facebook      | Facebook Graph API (Page token)                |
| X/Twitter     | X API v2 (OAuth 1.0a) — *stretch goal*         |
| Translation   | Anthropic/OpenAI LLM (profile-guided)          |
| TTS Dubbing   | Edge TTS (free), OpenAI, Google, ElevenLabs     |
| CLI           | Click + Rich                                   |
| Web UI        | React 19 + Tailwind CSS + Vite                 |
| API           | FastAPI + SSE for real-time progress             |
| Orchestration | Pipeline with state persistence + crash recovery |

## Prerequisites

- **Python** 3.11+
- **ffmpeg** with libx264 support
- **Docker** (for self-hosted Douyin Download API)
- **Noto Sans CJK** font (for Chinese subtitle rendering)

```bash
# macOS (development)
brew install ffmpeg python@3.11

# Linux (production)
sudo apt update && sudo apt install -y ffmpeg fonts-noto-cjk python3.11 python3.11-venv
```

## Installation

```bash
git clone <repo-url> && cd douyin-automation

python3 -m venv .venv
source .venv/bin/activate

# macOS (Apple Silicon)
pip install -e ".[macos]"
# or: pip install -r requirements-macos.txt

# Linux (CUDA)
pip install -e ".[linux]"
# or: pip install -r requirements-linux.txt
```

## Configuration

Copy and edit the config files:

```bash
cp config/config.example.yaml config/config.yaml
cp .env.example .env
# Edit both files with your API keys and preferences
```

Key configuration sections:

| Section    | File                          | Purpose                              |
| ---------- | ----------------------------- | ------------------------------------ |
| Main       | `config/config.yaml`          | API endpoints, model settings, paths |
| Platforms  | `config/platforms.yaml`       | Per-platform subtitle language, specs |
| Subtitles  | `config/subtitle_styles.yaml` | Font, size, color, position          |

### Platform Setup

Each platform requires a one-time OAuth setup:

```bash
python scripts/setup_oauth.py youtube   # Opens browser for Google OAuth
python scripts/setup_oauth.py tiktok    # Opens browser for TikTok OAuth
python scripts/setup_oauth.py facebook  # Guides through token exchange
python scripts/setup_oauth.py x         # Prompts for API keys
```

## Usage

### Full Pipeline (single video)

```bash
python -m src process "https://v.douyin.com/xxxxx" \
    --platforms youtube,tiktok,facebook \
    --subtitle-lang zh \
    --translate en \
    --privacy private
```

### Individual Steps

```bash
# Download only
python -m src download "https://v.douyin.com/xxxxx"

# Transcribe a local video
python -m src transcribe data/raw/video.mp4 --lang zh --translate en
```

### Batch Processing

```bash
# Process multiple URLs from a file (one URL per line)
python -m src batch urls.txt \
    --platforms youtube,tiktok,facebook \
    --concurrency 3
```

### Check Status

```bash
python -m src status              # Show all recent
python -m src status <video_id>   # Show specific video
```

### Web UI

```bash
python -m src server              # Start API + web server at :8000
cd ui-app && npm run dev          # Start React dev server at :5173
```

The web UI provides a Dashboard (pipeline monitoring, batch processing), Pipeline page (download + transcribe + translate + TTS), Video Studio (per-video workspace), Subtitle Editor, and Settings page.

## Project Structure

```
douyin-automation/
├── config/
│   ├── config.yaml              # Main configuration
│   ├── platforms.yaml           # Per-platform settings
│   └── subtitle_styles.yaml    # Subtitle styling (ASS format)
├── src/
│   ├── __main__.py            # Module entry (python -m src)
│   ├── cli.py                  # CLI entry point (Click + Rich)
│   ├── pipeline.py             # Pipeline orchestrator (crash recovery + batch)
│   ├── downloader/
│   │   ├── douyin.py           # Douyin API client
│   │   └── ytdlp.py           # yt-dlp fallback
│   ├── transcriber/
│   │   ├── base.py             # Common interface + SRT generator
│   │   └── ocr.py              # PaddleOCR (extracts burned-in subtitles)
│   ├── processor/
│   │   ├── subtitle.py         # SRT/ASS parsing, merging, styling
│   │   └── ffmpeg.py          # Subtitle burn-in + video reformat
│   ├── translator/
│   │   ├── llm.py             # LLM translator (Anthropic/OpenAI)
│   │   └── profiles.py        # Translation profile system
│   ├── tts/
│   │   ├── edge.py            # Edge TTS (free, default)
│   │   ├── openai_tts.py      # OpenAI TTS
│   │   ├── google_tts.py      # Google Cloud TTS
│   │   ├── elevenlabs.py      # ElevenLabs TTS
│   │   └── assembler.py       # Multi-segment TTS assembler
│   └── utils/
│       ├── config.py           # YAML config loader
│       ├── logger.py           # Structured JSON logging + per-video logs
│       ├── metadata.py         # Video metadata + per-platform mapping
│       ├── retry.py            # Exponential backoff decorator (tenacity)
│       └── state.py            # Pipeline state + duplicate detection
├── data/
│   ├── raw/                    # Downloaded original videos
│   ├── srt/                    # Generated subtitle files
│   ├── output/                 # Processed videos per platform
│   └── logs/                   # Pipeline logs + state files
├── scripts/
│   ├── setup_oauth.py          # One-time OAuth setup
│   └── refresh_douyin_cookie.py
├── tests/
├── plans/                      # Detailed implementation plans
└── pyproject.toml
```

## Platform Specifications

| Platform        | Max Duration | Aspect Ratio | Max Size | Subtitle Lang | Notes                |
| --------------- | ------------ | ------------ | -------- | ------------- | -------------------- |
| TikTok          | 10 min       | 9:16         | 4 GB     | Chinese       | Audit required       |
| YouTube Shorts  | 60 sec       | 9:16         | 256 GB   | English       | Auto-detected by YT  |
| YouTube         | 12 hrs       | Any          | 256 GB   | English       | ~6 uploads/day quota |
| Facebook Reels  | 15 min       | 9:16         | 4 GB     | English       |                      |
| Facebook Feed   | 240 min      | Any          | 10 GB    | English       |                      |
| X/Twitter       | 2 min 20 sec | Any          | 512 MB   | English       | $100/mo Basic plan   |

---

## Implementation Progress

### Phase 1 — Core: Download + Transcribe (Week 1-2)

> Detailed plan: [`plans/phase1-core-download-transcribe.md`](plans/phase1-core-download-transcribe.md)

- [x] **1.1** Project scaffolding — `pyproject.toml`
- [x] **1.2** Requirements files — `requirements.txt`, `requirements-linux.txt`, `requirements-macos.txt`
- [x] **1.3** Directory structure + `__init__.py` files + `.gitignore`
- [x] **1.4** Configuration files — `config/config.yaml`, `platforms.yaml`, `subtitle_styles.yaml`
- [x] **1.5** Config loader — `src/utils/config.py`
- [x] **1.6** Logger utility — `src/utils/logger.py`
- [x] **1.7** Metadata utility — `src/utils/metadata.py`
- [x] **1.8** Douyin downloader — `src/downloader/douyin.py`
- [x] **1.9** yt-dlp fallback — `src/downloader/ytdlp.py`
- [x] **1.10** Downloader factory — `src/downloader/__init__.py`
- [x] **1.11** Base transcriber — `src/transcriber/base.py`
- [x] **1.12** PaddleOCR transcriber — `src/transcriber/ocr.py`
- [x] **1.13** Transcriber factory — `src/transcriber/__init__.py`
- [x] **1.15** Translation support — `src/processor/subtitle.py`
- [x] **1.16** Cookie refresh script — `scripts/refresh_douyin_cookie.py`
- [x] **1.17** Phase 1 tests — `tests/test_downloader.py`, `tests/test_transcriber.py`
- [x] **1.18** FastAPI foundation — `src/api/__init__.py`, `deps.py`, `models.py`
- [x] **1.19** Task manager — `src/api/task_manager.py`
- [x] **1.20** SSE events router — `src/api/routers/events.py`
- [x] **1.21** Download router + service — `src/api/routers/download.py`
- [x] **1.22** Transcribe router + service — `src/api/routers/transcribe.py`
- [x] **1.23** React frontend foundation — `ui-app/` scaffold
- [x] **1.24** Download & Transcribe page — `ui-app/src/pages/DownloadTranscribe.tsx`
- [x] **1.25** Backend dependencies — `pyproject.toml` + `Makefile` updates
- [x] **1.26** Translation profile system — `src/translator/profiles.py` + `config/translation_profiles/`
- [x] **1.27** LLM translator — `src/translator/llm.py` (Anthropic/OpenAI/local backends)
- [x] **1.28** Translator factory — `src/translator/__init__.py`
- [x] **1.29** Translation API — `src/api/routers/translate.py` (profiles CRUD + translate endpoint)
- [x] **1.30** Translation UI — profile selector, translation progress, multi-language SRT preview
- [x] **1.31** Raw video download endpoint — `GET /api/videos/{video_id}/raw`
- [x] **1.32** Download raw video UI — download button on VideoCard + SRT export

**Verification (Backend):**
- [x] V1.1 — `pip install -e ".[macos]"` completes without errors
- [x] V1.2 — All `__init__.py` files in place
- [x] V1.3 — Config loads with env var interpolation
- [x] V1.4 — Douyin download produces MP4 + metadata
- [x] V1.5 — yt-dlp fallback downloads successfully
- [x] V1.6 — Fallback auto-triggers when primary API fails
- [x] V1.7 — Transcriber selects correct backend per platform
- [x] V1.8 — Transcription produces valid SRT with Chinese text
- [x] V1.9 — Timestamp formatting handles edge cases
- [x] V1.10 — Chinese → English translation produces English SRT
- [x] V1.11 — Unit tests pass

**Verification (Web UI):**
- [x] V1.12 — FastAPI server starts, Swagger UI at `/docs`
- [x] V1.13 — Download via API with SSE progress events
- [x] V1.14 — Transcribe via API returns SRT segments
- [x] V1.15 — Video list API returns all downloaded videos
- [x] V1.16 — React UI loads at `localhost:5173`
- [x] V1.17 — End-to-end: paste URL → download → transcribe → see SRT preview in browser

**Verification (Translation + Download):**
- [x] V1.18 — Translation profiles load from `config/translation_profiles/`
- [ ] V1.19 — LLM translation produces Vietnamese SRT with profile-guided style
- [x] V1.20 — Profile CRUD API: create, list, update, delete profiles
- [x] V1.21 — Translation API with batch progress via SSE
- [x] V1.22 — UI: select profile → translate → see multi-language SRT preview
- [x] V1.23 — UI: create/edit custom translation profile
- [x] V1.24 — Raw video download: browser downloads MP4 file
- [x] V1.25 — SRT export: download SRT file from UI

---

### Phase 2 — Subtitle Burn-in + Reformat (Week 2-3)

> Detailed plan: [`plans/phase2-subtitle-burnin-reformat.md`](plans/phase2-subtitle-burnin-reformat.md)

- [x] **2.1** SRT parser + ASS converter — `src/processor/subtitle.py`
- [x] **2.2** FFmpeg processor — `src/processor/ffmpeg.py`
- [x] **2.3** Platform specs — `config/platforms.yaml` + subtitle language per platform
- [x] **2.4** Subtitle style config — `config/subtitle_styles.yaml` (Arial default, per-platform overrides)
- [x] **2.5** Batch processor — `src/processor/__init__.py` (selects correct translated SRT per platform)
- [x] **2.6** Phase 2 tests — `tests/test_processor.py`
- [x] **2.7** Process router + service — `src/api/routers/process.py`
- [x] **2.8** Process page — `ui-app/src/pages/SubtitleProcess.tsx`
- [x] **2.9** Subtitle editor — `ui-app/src/pages/SubtitleEditor.tsx` (video player, inline editing, timeline, style panel)
- [x] **2.10** Editor API — `src/api/routers/editor.py` (save SRT, preview frame, preview clip)
- [x] **2.11** Editor entry point — "Edit Subtitles" button on Download & Transcribe page

**Verification (Backend):**
- [x] V2.1 — ffmpeg and ffprobe available
- [x] V2.2 — SRT parsing produces correct segments
- [x] V2.3 — SRT → ASS conversion has valid `[Script Info]`, `[V4+ Styles]`, `[Events]`
- [ ] V2.4 — English subtitle burn-in produces viewable video
- [ ] V2.5 — Vietnamese subtitle burn-in renders diacritics correctly (ă, ơ, ư, etc.)
- [ ] V2.6 — X/Twitter reformatted output meets constraints (≤140s, ≤512MB, H.264)
- [x] V2.7 — Batch processing: TikTok/Facebook get Vietnamese subs, YouTube/X get English subs
- [x] V2.8 — Dual-line subtitle merge (English + Vietnamese) works
- [x] V2.9 — Unit tests pass

**Verification (Web UI):**
- [x] V2.10 — Process API: correct subtitle language per platform in progress events
- [x] V2.11 — Subtitle styles and platform specs API (with subtitle_language field)
- [x] V2.12 — Serve processed video via API
- [ ] V2.13 — Process page: select video → see subtitle language per platform → process → preview

---

### Phase 3 — OCR Subtitle Extraction (Week 3)

> Detailed plan: [`plans/phase3-ocr-subtitle-extraction.md`](plans/phase3-ocr-subtitle-extraction.md)

- [x] **3.1** PaddleOCR dependencies — `pyproject.toml`
- [x] **3.2** Frame extraction — `src/processor/ffmpeg.py` (`extract_frames`)
- [x] **3.3** OCR transcriber with auto-detect — `src/transcriber/ocr.py` (PaddleOCR + region classification + dedup)
- [x] **3.4** Transcriber factory — `src/transcriber/__init__.py` (add "ocr" backend)
- [x] **3.5** OCR config — `config/config.example.yaml`
- [x] **3.6** API models — `src/api/models.py` (method + optional ocr_region override)
- [x] **3.7** Router + task manager — sample-frame endpoint, OCR routing with progress
- [x] **3.8** UI types + client — `ui-app/src/api/`
- [x] **3.9** DownloadTranscribe page — method toggle, auto-detect flow, optional manual region override
- [x] **3.10** Unit tests — auto-classification, watermark filtering, dedup logic, factory

**Verification:**
- [x] V3.1 — PaddleOCR installed and importable
- [x] V3.2 — Frame extraction produces correct frame count
- [x] V3.3 — Auto-detection filters watermarks (username/logo NOT in SRT, subtitles ARE)
- [x] V3.4 — OCR transcription produces SRT with Chinese text from burned-in subtitles
- [x] V3.5 — Manual region override works when provided
- [x] V3.7 — UI: toggle to OCR → click Transcribe → auto-detect → SRT preview
- [x] V3.8 — Unit tests pass

---

### Phase 4 — TTS Dubbing (Week 4)

> Detailed plan: [`plans/phase4-tts-dubbing.md`](plans/phase4-tts-dubbing.md)

- [x] **4.1** TTS base class — `src/tts/base.py`
- [x] **4.2** Edge TTS provider — `src/tts/edge.py` (free, default)
- [x] **4.3** OpenAI TTS provider — `src/tts/openai_tts.py`
- [x] **4.4** Google Cloud TTS provider — `src/tts/google_tts.py`
- [x] **4.5** TTS factory — `src/tts/__init__.py`
- [x] **4.6** Voice profiles config — `config/tts_voices.yaml`
- [x] **4.7** TTS audio assembler — `src/tts/assembler.py`
- [x] **4.8** Audio mixing in ffmpeg — `src/processor/ffmpeg.py`
- [x] **4.9** Update batch processor — `src/processor/__init__.py`
- [x] **4.10** Config + infra updates — pyproject.toml, .gitignore, config
- [x] **4.11** TTS unit tests — `tests/test_tts.py`
- [x] **4.12** TTS API models — `src/api/models.py`
- [x] **4.13** TTS router — `src/api/routers/tts.py`
- [x] **4.14** Task manager + app registration
- [x] **4.15** TTS TypeScript types
- [x] **4.16** TTS API client
- [x] **4.17** TTS section on Process page
- [x] **4.18** TTS preview component

**Verification:**
- [x] V4.1 — Edge TTS installed and importable
- [ ] V4.2 — Voice list API returns Vietnamese voices
- [ ] V4.3 — Voice preview returns playable audio
- [ ] V4.4 — TTS generation produces WAV matching video duration (±0.5s)
- [ ] V4.5 — Audio mixing: dubbed video has correct volume levels
- [ ] V4.6 — Per-platform voice: TikTok/FB get Vietnamese, YouTube/X get English
- [ ] V4.7 — UI: enable TTS → select voice → preview → generate → process
- [x] V4.8 — Segment duration fitting: long TTS clips speed up to fit time window
- [x] V4.9 — Unit tests pass

---

### Phase 5 — Orchestration + Batch Processing (Week 5-6)

> Detailed plan: [`plans/phase5-orchestration-batch.md`](plans/phase5-orchestration-batch.md)

- [x] **5.1** Retry utility — `src/utils/retry.py`
- [x] **5.2** State persistence — `src/utils/state.py`
- [x] **5.3** Duplicate detection — `src/utils/state.py`
- [x] **5.4** Pipeline orchestrator — `src/pipeline.py`
- [x] **5.5** Metadata mapper — `src/utils/metadata.py`
- [x] **5.6** CLI interface — `src/cli.py`
- [x] **5.7** Structured logging — `src/utils/logger.py` (finalize)
- [x] **5.8** Module entry point — `src/__main__.py`
- [x] **5.9** README.md (finalize)
- [x] **5.10** Integration tests — `tests/test_pipeline.py`
- [x] **5.11** Pipeline router + service — `server/routers/pipeline.py`
- [x] **5.12** Config router — `server/routers/config.py`
- [x] **5.13** Dashboard page — `web/src/pages/DashboardPage.tsx`
- [x] **5.14** Settings page — `web/src/pages/SettingsPage.tsx`
- [x] **5.15** React Router — route-based navigation

**Verification (CLI):**
- [ ] V5.1 — `python -m src --help` displays all commands
- [ ] V5.2 — `python -m src process --help` shows all options
- [ ] V5.3 — Full pipeline: URL → subtitled, dubbed, per-platform reformatted videos
- [ ] V5.4 — Crash recovery: interrupted pipeline resumes from last stage
- [ ] V5.5 — Duplicate detection: same URL skipped on second run
- [ ] V5.6 — Batch processing: multiple URLs with concurrency limit
- [ ] V5.7 — Retry: transient failures recovered with exponential backoff
- [ ] V5.8 — Structured JSON logs written to `data/logs/pipeline.log`
- [ ] V5.9 — `python -m src status` displays rich-formatted table
- [ ] V5.10 — All tests pass: `pytest tests/ -v`

**Verification (Web UI):**
- [ ] V5.11 — Pipeline API runs full pipeline with stage-level SSE events
- [ ] V5.12 — Batch API processes multiple URLs with concurrency control
- [ ] V5.13 — Dashboard stats API returns counts and success rate
- [ ] V5.14 — Pipeline history API with filtering
- [ ] V5.15 — Config API: read (secrets redacted) and update (partial merge)
- [ ] V5.16 — Dashboard UI: stats, quick process, pipeline table with live updates
- [ ] V5.17 — Batch processing UI: paste URLs → track per-video progress
- [ ] V5.18 — Settings UI: edit config → save → persists
- [ ] V5.19 — React Router: all routes work, sidebar highlights active page

---

### Phase 6 — Subtitle Replacement: Blur + Reposition (Week 6-7)

> Detailed plan: [`plans/phase6-subtitle-replacement.md`](plans/phase6-subtitle-replacement.md)

- [x] **6.1** Subtitle region detector — `src/processor/region_detector.py`
- [x] **6.2** Blur filter in ffmpeg — `src/processor/ffmpeg.py`
- [x] **6.3** Subtitle style matcher — `src/processor/style_matcher.py`
- [x] **6.4** Combined blur + burn pipeline — `src/processor/ffmpeg.py`
- [x] **6.5** Update batch processor — `src/processor/__init__.py`
- [x] **6.6** OCR metadata persistence — `src/transcriber/ocr.py` update
- [x] **6.7** Unit tests — `tests/test_subtitle_replacement.py`
- [x] **6.8** Subtitle replacement models — `src/api/models.py`
- [x] **6.9** Subtitle replacement router — `src/api/routers/replacement.py`
- [x] **6.10** Register router + update process flow
- [x] **6.11** TypeScript types
- [x] **6.12** API client functions
- [x] **6.13** Region selector component — `ui-app/src/components/editor/RegionSelector.tsx`
- [x] **6.14** Blur preview component — `ui-app/src/components/editor/BlurPreview.tsx`
- [x] **6.15** Subtitle replacement section on Video Studio page

**Verification:**
- [x] V6.1 — Region auto-detection returns correct bounding box from OCR metadata
- [ ] V6.2 — Blur preview: JPEG shows original subtitle area blurred out
- [ ] V6.3 — Three blur modes work (blur, fill, pixelate)
- [ ] V6.4 — Style matching: new subtitle appears at same position/size as original
- [ ] V6.5 — Single-pass processing (blur + burn in one ffmpeg call)
- [ ] V6.6 — Blur + TTS combined: blurred subs + new subs + dubbed audio
- [ ] V6.7 — Graceful fallback: no OCR data → skip blur, process normally
- [ ] V6.8 — Manual region override via UI
- [ ] V6.9 — UI flow: detect region → preview blur → process → clean output
- [x] V6.10 — Unit tests pass (incl. horizontal-video pad regression test)

---

### One-Time Setup Checklist

- [ ] Docker installed, Douyin API container running
- [ ] Python venv created, dependencies installed (or use Docker)
- [ ] ffmpeg installed + Noto CJK fonts available
- [ ] PaddleOCR models downloaded (~1 GB, fetched on first OCR run)
- [ ] Translation API key (Anthropic / DeepSeek / OpenAI) entered in the Settings UI

## Development

```bash
# Run tests
make test                                    # all tests
python -m pytest tests/test_downloader.py -v # single file
make test-integration                        # integration only

# Lint & format
make lint                                    # ruff check
make format                                  # ruff format
make check                                   # lint + test

# Docker (full stack: Douyin API + app)
make docker-up                               # build + start everything
make docker-down                             # stop everything
make docker-logs                             # tail app container logs
make docker-rebuild                          # no-cache rebuild of app
```

## Docker Quickstart

The full stack — Douyin API helper + FastAPI backend + React UI — runs as two containers via `docker compose`. Works on macOS, Linux, and Windows (Docker Desktop or Docker Engine). See [DOCKER.md](DOCKER.md) for the full operations guide (troubleshooting, persistence, upgrades, clean slate).

```bash
git clone <repo> && cd douyin-automation
cp config/config.example.yaml config/config.yaml      # app config (tweakable later in the UI)
# Create config/douyin_web_config.yaml with your Douyin cookie — see DOCKER.md §2.2
docker compose up -d --build
open http://localhost:8000
```

Then open **Settings** in the UI to enter your translation API key (Anthropic / DeepSeek / OpenAI) and your Douyin user cookie. Keys live in your browser only and are sent with each translate / TTS request.

Health check:

```bash
curl -fsS http://localhost:8000/api/health   # {"status":"ok"}
```

## License

Private — All rights reserved.
