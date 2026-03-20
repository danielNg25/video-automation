# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-03-20

### Added

#### Download + Transcribe Pipeline
- Douyin downloader (`src/downloader/douyin.py`) using self-hosted Evil0ctal API with thumbnail download
- yt-dlp fallback downloader (`src/downloader/ytdlp.py`) with thumbnail support
- Download factory with automatic fallback chain (`src/downloader/__init__.py`)
- Base transcriber ABC with SRT generation (`src/transcriber/base.py`)
- faster-whisper backend for Linux/CUDA (`src/transcriber/faster.py`)
- mlx-whisper backend for macOS Apple Silicon (`src/transcriber/mlx.py`)
- Transcriber factory with platform auto-selection (`src/transcriber/__init__.py`)
- SRT parser and translation support (`src/processor/subtitle.py`)
- Config loader (`src/utils/config.py`) with `${ENV_VAR}` interpolation
- Structured JSON logger (`src/utils/logger.py`) with rich console + file output
- Video metadata dataclass with thumbnail URL and ffprobe extraction (`src/utils/metadata.py`)

#### FastAPI Backend
- App factory with CORS and static file serving (`src/api/__init__.py`)
- In-memory task manager with background execution and SSE streaming (`src/api/task_manager.py`)
- Download endpoints: POST /api/download, GET /api/videos, GET /api/videos/{id}, PATCH (rename), DELETE
- Transcribe endpoints: POST /api/transcribe, GET /api/videos/{id}/srt
- SSE event streaming: GET /api/events/{task_id}
- Dashboard stats: GET /api/stats
- Pydantic request/response models matching UI types (`src/api/models.py`)
- Video metadata persistence to JSON for server restart recovery
- FFmpeg fallback thumbnail generation on startup scan

#### React Web UI
- 5-page app: Dashboard, Download & Transcribe, Subtitle & Process, Upload, Settings
- Dark theme with Material Design 3 color tokens
- Download & Transcribe page with real-time SSE progress, video library, SRT preview
- Dashboard with live stats, pipeline table, quick process form
- Video thumbnails from Douyin cover images or ffmpeg extraction
- Inline title editing and video deletion with confirmation
- Multi-language SRT preview with language switcher (zh, en, vi)
- Vite dev proxy for API calls

#### Infrastructure
- Project scaffolding: `pyproject.toml`, requirements files, Makefile
- Docker compose for Douyin Download API with cookie config mount
- Platform config (`config/platforms.yaml`) and subtitle styles (`config/subtitle_styles.yaml`)
- Cookie refresh helper script (`scripts/refresh_douyin_cookie.py`)
- Unit tests (32) and integration tests (8) with pytest
- GitHub Actions workflow for doc sync on PRs
- Implementation plans for all 4 phases in `plans/`
