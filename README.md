# Douyin Video Repurposing Pipeline

Automated pipeline to download videos from Douyin, generate AI subtitles (Chinese transcription + English translation), burn subtitles into the video, and upload to YouTube, TikTok, Facebook, and X (Twitter).

## Architecture

```
┌──────────────┐    ┌───────────────┐    ┌──────────────┐    ┌────────────────┐
│  1. Download │    │ 2. Transcribe │    │ 3. Process   │    │ 4. Upload      │
│              │───▶│               │───▶│              │───▶│                │
│  Douyin API  │    │ Whisper AI    │    │ ffmpeg burn  │    │ YT/TT/FB/X API │
│  + yt-dlp    │    │ SRT generate  │    │ + reformat   │    │ (per-platform) │
└──────────────┘    └───────────────┘    └──────────────┘    └────────────────┘
       │                    │                    │                    │
       ▼                    ▼                    ▼                    ▼
   /data/raw/          /data/srt/          /data/output/        /data/logs/
   {id}.mp4            {id}.srt            {id}_{platform}.mp4  {id}_state.json
```

## Tech Stack

| Component     | Tool                                           |
| ------------- | ---------------------------------------------- |
| Language      | Python 3.11+                                   |
| Download      | Self-hosted Douyin API + yt-dlp fallback       |
| Transcription | faster-whisper (Linux/CUDA), mlx-whisper (macOS) |
| Video Process | ffmpeg (subtitle burn-in + platform reformat)  |
| YouTube       | YouTube Data API v3 (OAuth 2.0)                |
| TikTok        | TikTok Content Posting API (OAuth 2.0 + PKCE)  |
| Facebook      | Facebook Graph API (Page token)                |
| X/Twitter     | X API v2 (OAuth 1.0a) — *stretch goal*         |
| CLI           | Click + Rich                                   |

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

# Upload a processed video
python -m src upload data/output/video_youtube.mp4 --platforms youtube
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

## Project Structure

```
douyin-automation/
├── config/
│   ├── config.yaml              # Main configuration
│   ├── platforms.yaml           # Per-platform settings
│   └── subtitle_styles.yaml    # Subtitle styling (ASS format)
├── src/
│   ├── cli.py                  # CLI entry point (Click)
│   ├── pipeline.py             # Pipeline orchestrator
│   ├── downloader/
│   │   ├── douyin.py           # Douyin API client
│   │   └── ytdlp.py           # yt-dlp fallback
│   ├── transcriber/
│   │   ├── base.py             # Common interface + SRT generator
│   │   ├── faster.py           # faster-whisper (Linux/CUDA)
│   │   └── mlx.py             # mlx-whisper (macOS)
│   ├── processor/
│   │   ├── subtitle.py         # SRT/ASS parsing, merging, styling
│   │   └── ffmpeg.py          # Subtitle burn-in + video reformat
│   ├── uploader/
│   │   ├── base.py             # Abstract uploader interface
│   │   ├── youtube.py          # YouTube Data API v3
│   │   ├── tiktok.py          # TikTok Content Posting API
│   │   ├── facebook.py        # Facebook Graph API
│   │   └── x.py               # X/Twitter API v2
│   └── utils/
│       ├── config.py           # YAML config loader
│       ├── logger.py           # Structured JSON logging
│       ├── metadata.py         # Video metadata + platform mapping
│       ├── retry.py            # Exponential backoff decorator
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
- [x] **1.12** faster-whisper backend — `src/transcriber/faster.py`
- [x] **1.13** mlx-whisper backend — `src/transcriber/mlx.py`
- [x] **1.14** Transcriber factory — `src/transcriber/__init__.py`
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
- [ ] **1.26** Translation profile system — `src/translator/profiles.py` + `config/translation_profiles/`
- [ ] **1.27** LLM translator — `src/translator/llm.py` (Anthropic/OpenAI/local backends)
- [ ] **1.28** Translator factory — `src/translator/__init__.py`
- [ ] **1.29** Translation API — `src/api/routers/translate.py` (profiles CRUD + translate endpoint)
- [ ] **1.30** Translation UI — profile selector, translation progress, multi-language SRT preview
- [ ] **1.31** Raw video download endpoint — `GET /api/videos/{video_id}/raw`
- [ ] **1.32** Download raw video UI — download button on VideoCard + SRT export

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
- [ ] V1.18 — Translation profiles load from `config/translation_profiles/`
- [ ] V1.19 — LLM translation produces Vietnamese SRT with profile-guided style
- [ ] V1.20 — Profile CRUD API: create, list, update, delete profiles
- [ ] V1.21 — Translation API with batch progress via SSE
- [ ] V1.22 — UI: select profile → translate → see multi-language SRT preview
- [ ] V1.23 — UI: create/edit custom translation profile
- [ ] V1.24 — Raw video download: browser downloads MP4 file
- [ ] V1.25 — SRT export: download SRT file from UI

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

### Phase 3 — Platform Upload Integrations (Week 3-4)

> Detailed plan: [`plans/phase3-platform-uploads.md`](plans/phase3-platform-uploads.md)

- [ ] **3.1** Base uploader interface — `src/uploader/base.py`
- [ ] **3.2** OAuth setup script — `scripts/setup_oauth.py`
- [ ] **3.3** YouTube uploader — `src/uploader/youtube.py`
- [ ] **3.4** TikTok uploader — `src/uploader/tiktok.py`
- [ ] **3.5** Facebook uploader — `src/uploader/facebook.py`
- [ ] **3.6** X/Twitter uploader *(stretch goal)* — `src/uploader/x.py`
- [ ] **3.7** Uploader factory — `src/uploader/__init__.py`
- [ ] **3.8** Phase 3 tests — `tests/test_uploader.py`
- [ ] **3.9** Auth router — `server/routers/auth.py`
- [ ] **3.10** Upload router + service — `server/routers/upload.py`
- [ ] **3.11** Upload page — `web/src/pages/UploadPage.tsx`

**Verification (Backend):**
- [ ] V3.1 — YouTube OAuth setup saves token with refresh_token
- [ ] V3.2 — YouTube upload (private) succeeds, video visible in Studio
- [ ] V3.3 — TikTok upload (draft) succeeds, video in inbox
- [ ] V3.4 — Facebook upload succeeds, video on Page
- [ ] V3.5 — X upload succeeds *(if enabled)*
- [ ] V3.6 — Uploader factory returns correct types, only enabled platforms
- [ ] V3.7 — Error handling returns `UploadResult(success=False)`, no crash
- [ ] V3.8 — Unit tests pass

**Verification (Web UI):**
- [ ] V3.9 — Auth status API returns per-platform connection status
- [ ] V3.10 — OAuth flow via API (start → authorize → callback → connected)
- [ ] V3.11 — Upload via API with per-platform progress
- [ ] V3.12 — Upload page: connect accounts → select video → upload → see result URLs
- [ ] V3.13 — Retry failed upload without re-uploading successful platforms

---

### Phase 4 — Orchestration + Batch Processing (Week 4-5)

> Detailed plan: [`plans/phase4-orchestration-batch.md`](plans/phase4-orchestration-batch.md)

- [ ] **4.1** Retry utility — `src/utils/retry.py`
- [ ] **4.2** State persistence — `src/utils/state.py`
- [ ] **4.3** Duplicate detection — `src/utils/state.py`
- [ ] **4.4** Pipeline orchestrator — `src/pipeline.py`
- [ ] **4.5** Metadata mapper — `src/utils/metadata.py`
- [ ] **4.6** CLI interface — `src/cli.py`
- [ ] **4.7** Structured logging — `src/utils/logger.py` (finalize)
- [ ] **4.8** Module entry point — `src/__main__.py`
- [ ] **4.9** README.md (finalize)
- [ ] **4.10** Integration tests — `tests/test_pipeline.py`
- [ ] **4.11** Pipeline router + service — `server/routers/pipeline.py`
- [ ] **4.12** Config router — `server/routers/config.py`
- [ ] **4.13** Dashboard page — `web/src/pages/DashboardPage.tsx`
- [ ] **4.14** Settings page — `web/src/pages/SettingsPage.tsx`
- [ ] **4.15** React Router — route-based navigation

**Verification (CLI):**
- [ ] V4.1 — `python -m src --help` displays all commands
- [ ] V4.2 — `python -m src process --help` shows all options
- [ ] V4.3 — Full pipeline: URL → subtitled video → uploaded to all platforms
- [ ] V4.4 — Crash recovery: interrupted pipeline resumes from last stage
- [ ] V4.5 — Duplicate detection: same URL skipped on second run
- [ ] V4.6 — Batch processing: multiple URLs with concurrency limit
- [ ] V4.7 — Retry: transient failures recovered with exponential backoff
- [ ] V4.8 — Structured JSON logs written to `data/logs/pipeline.log`
- [ ] V4.9 — `python -m src status` displays rich-formatted table
- [ ] V4.10 — All tests pass: `pytest tests/ -v`

**Verification (Web UI):**
- [ ] V4.11 — Pipeline API runs full pipeline with stage-level SSE events
- [ ] V4.12 — Batch API processes multiple URLs with concurrency control
- [ ] V4.13 — Dashboard stats API returns counts and success rate
- [ ] V4.14 — Pipeline history API with filtering
- [ ] V4.15 — Config API: read (secrets redacted) and update (partial merge)
- [ ] V4.16 — Dashboard UI: stats, quick process, pipeline table with live updates
- [ ] V4.17 — Batch processing UI: paste URLs → track per-video progress
- [ ] V4.18 — Settings UI: edit config → save → persists
- [ ] V4.19 — React Router: all routes work, sidebar highlights active page

---

### One-Time Setup Checklist

- [ ] Docker installed, Douyin API container running
- [ ] Python venv created, dependencies installed
- [ ] ffmpeg installed + Noto CJK fonts available
- [ ] Whisper model downloaded (~3GB for large-v3)
- [ ] Google Cloud: project created → YouTube Data API v3 enabled → OAuth credentials
- [ ] TikTok Developer: app registered → Content Posting API → **audit submitted early**
- [ ] Facebook Developer: app created → permissions requested → long-lived Page token
- [ ] X Developer *(optional)*: Basic plan ($100/mo) → API keys generated
- [ ] OAuth flows completed: `scripts/setup_oauth.py {platform}` for each platform

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

# Docker (Douyin API)
make docker-up                               # start API container
make docker-down                             # stop API container
```

## License

Private — All rights reserved.
