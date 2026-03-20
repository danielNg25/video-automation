# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Web UI + API layer plan: FastAPI backend + React/Vite/shadcn frontend, split per phase
- UI design prompt for generating mockups with LLM tools (`plans/ui-design-prompt.md`)
- Architecture diagram updated with Web UI and API layers
- Phase 1 implementation: download + transcribe pipeline
- Project scaffolding: `pyproject.toml`, requirements files, directory structure
- Config loader (`src/utils/config.py`) with `${ENV_VAR}` interpolation
- Structured JSON logger (`src/utils/logger.py`) with rich console + file output
- Video metadata dataclass and ffprobe extraction (`src/utils/metadata.py`)
- Douyin downloader (`src/downloader/douyin.py`) using self-hosted Evil0ctal API
- yt-dlp fallback downloader (`src/downloader/ytdlp.py`)
- Download factory with automatic fallback chain (`src/downloader/__init__.py`)
- Base transcriber ABC with SRT generation (`src/transcriber/base.py`)
- faster-whisper backend for Linux/CUDA (`src/transcriber/faster.py`)
- mlx-whisper backend for macOS Apple Silicon (`src/transcriber/mlx.py`)
- Transcriber factory with platform auto-selection (`src/transcriber/__init__.py`)
- SRT parser and translation support (`src/processor/subtitle.py`)
- Cookie refresh helper script (`scripts/refresh_douyin_cookie.py`)
- Platform config (`config/platforms.yaml`) and subtitle styles (`config/subtitle_styles.yaml`)
- Unit tests for downloader and transcriber (32 tests)
- Integration tests against real Douyin API container (8 tests)
- Docker cookie config mount for persistent API authentication

### Changed
- Docker compose port changed from 8080 to 8081, cookie config mounted as volume
- Updated `.gitignore` with pytest cache, SRT files, and JSON log exclusions

### Previously Added
- Project planning documents (`PLAN.md`, phase plans in `plans/`)
- `README.md` with architecture overview, usage guide, and implementation checklist
- `CLAUDE.md` with development guidance and commit rules
- `CHANGELOG.md` for tracking changes
- `.gitignore` for Python, data files, secrets, and IDE files
- `.env.example` documenting required environment variables
- `docker-compose.yml` for Douyin Download API container
- `config/config.example.yaml` as template for main configuration
- `Makefile` with shortcuts for install, test, lint, format, and Docker commands
- Initialized git repository on `main` branch
- Git workflow rules in `CLAUDE.md`: branch naming, PR creation, PR review
- Per-module `CLAUDE.md` files for downloader, transcriber, processor, uploader, utils
- GitHub PR template at `.github/pull_request_template.md`
- GitHub Actions workflow for automatic doc sync on PRs (`.github/workflows/doc-sync.yml`)
