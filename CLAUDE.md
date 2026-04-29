# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Session Startup

At the start of every session, before doing any work:

1. Read the **Implementation Progress** checklist in `README.md` to understand what's already done
2. Read the relevant phase plan in `plans/` for the current work
3. Read `CHANGELOG.md` to understand recent changes

When the user says "work on phase X" or "continue", identify the next unchecked task from the README checklist and read the corresponding phase plan for full context.

## Project Overview

Automated pipeline to download Douyin videos, generate AI subtitles (Chinese + English/Vietnamese), burn subtitles into video, TTS dubbing, and upload to YouTube, TikTok, Facebook, and X/Twitter. Development on macOS Apple Silicon, production on Linux.

## Architecture

Six-stage pipeline: **Download → Transcribe → Translate → TTS → Process → Upload**

- **Download**: Douyin API (self-hosted Evil0ctal container on :8080) with yt-dlp fallback
- **Transcribe**: mlx-whisper on macOS, faster-whisper on Linux (auto-selected via `sys.platform`), or PaddleOCR for burned-in subtitle extraction
- **Translate**: LLM-based translation (Anthropic/OpenAI) with configurable style profiles in `config/translation_profiles/`
- **TTS**: Multi-provider dubbing (Edge TTS free default, OpenAI, Google, ElevenLabs, Piper) with segment assembly and audio mixing
- **Process**: ffmpeg subtitle burn-in + per-platform video reformatting
- **Upload**: Platform-specific uploaders behind a common `BaseUploader` ABC

Data flows through: `data/raw/` → `data/srt/` → `data/tts/` → `data/output/` → `data/logs/`

File naming: `{video_id}.mp4`, `{video_id}_{lang}.srt`, `{video_id}_{lang}.wav`, `{video_id}_{platform}.mp4`

Each video's pipeline state is persisted to `data/logs/{video_id}_state.json` for crash recovery. Duplicate detection via `data/logs/processed_videos.json`.

### Web UI + API

- **API**: FastAPI at `:8000` with SSE for real-time progress. Routers in `src/api/routers/`. Run with `make api`.
- **UI**: React 19 + TypeScript + Tailwind CSS 4 + Vite at `:5173` (proxied to API). Pages in `ui-app/src/pages/`. Run with `make ui`.
- Key pages: Dashboard (pipeline monitoring), Download & Transcribe, Subtitle Editor (frame-by-frame with video player), Video Detail, Settings.

### Module Structure

Each module follows: `__init__.py` (factory), `base.py` (ABC), then provider/platform implementations. Factories auto-select backends: `get_transcriber()`, `get_translator()`, `get_tts_provider()`. Each module under `src/` has its own `CLAUDE.md` with module-specific context.

## Commands

Requires Python 3.11+ and ffmpeg with libx264 support.

```bash
# Install (macOS dev)
make install        # or: python3 -m venv .venv && pip install -e ".[macos]"

# Install (Linux prod)
make install-linux  # or: pip install -e ".[linux]"

# UI setup (first time)
cd ui-app && npm install

# Run CLI
python -m src --help
python -m src process "https://v.douyin.com/xxxxx" --platforms youtube,tiktok

# Run servers
make api            # uvicorn FastAPI at :8000 with reload
make ui             # Vite React dev server at :5173 (proxied to :8000)

# Tests
make test                                             # all tests
python -m pytest tests/test_downloader.py -v          # single file
python -m pytest tests/test_downloader.py::test_name  # single test
make test-unit                                        # skip integration tests
make test-integration                                 # integration only

# Lint & format
make lint           # ruff check src/ tests/
make format         # ruff format src/ tests/
make check          # lint + test

# UI lint
cd ui-app && npm run lint

# Docker (Douyin API)
make docker-up      # docker compose up -d
make docker-down

# Cleanup
make clean          # remove __pycache__, .pytest_cache, build artifacts

# OAuth setup per platform
python scripts/setup_oauth.py youtube
```

## Testing

- **Framework**: pytest with `pytest-asyncio` (auto mode — no `@pytest.mark.asyncio` needed)
- **Integration tests**: marked with `@pytest.mark.integration`, require Docker/external services
- **Mocking pattern**: `unittest.mock.AsyncMock` and `patch()` for external API/subprocess calls
- **Test files**: `tests/test_<module>.py` mirrors `src/<module>/`

## Key Design Decisions

- **Whisper backend abstraction**: `src/transcriber/base.py` defines the interface; `faster.py` and `mlx.py` implement it. Factory in `__init__.py` auto-selects by platform.
- **Download fallback chain**: Douyin API is primary but breaks often due to anti-scraping changes. yt-dlp is the automatic fallback. Both return the same `VideoMetadata` dataclass.
- **Subtitle language per platform**: Vietnamese for TikTok/Facebook, English for YouTube/X. Configured in `config/platforms.yaml`.
- **Stage-level state persistence**: Pipeline saves progress after each stage so interrupted runs resume from the last completed stage, not from scratch. File locking with `fcntl.flock()` for multi-instance safety.
- **X/Twitter is a stretch goal**: $100/mo API cost, most restrictive limits (2:20, 512MB). Disabled by default in config.

## Extending the Pipeline

- **New TTS provider**: Extend `BaseTTSProvider` in `src/tts/`, add to factory in `src/tts/__init__.py`, register voice in `config/tts_voices.yaml`
- **New platform uploader**: Extend `BaseUploader` in `src/uploader/`, add to factory in `src/uploader/__init__.py`
- **New translation profile**: Create YAML in `config/translation_profiles/`
- **New API endpoint**: Create router in `src/api/routers/`, include in `src/api/__init__.py`

## Git Workflow

- **Never commit directly to `main`**. Always create a branch first.
- **Branch naming**:
  - Features: `feature/<phase>-<short-description>` (e.g., `feature/phase1-downloader`)
  - Bugfixes: `bugfix/<short-description>` (e.g., `bugfix/srt-timestamp-overflow`)
  - Hotfixes: `hotfix/<short-description>` (e.g., `hotfix/cookie-expiry-handling`)
- **PR workflow**: After completing work on a branch, create a PR to `main` using `gh pr create`. Follow the PR template in `.github/pull_request_template.md`.
- **PR review**: When asked to review a PR, use `gh pr view <number>` and `gh pr diff <number>` to inspect changes, then provide feedback or approve.

## Commit Rules

- **No AI mentions**: Do not include "Co-Authored-By", "Generated by", "AI", "Claude", or any AI-related attribution in commit messages or code comments.
- **Update README checklist**: Every commit must update the relevant checkbox in `README.md` (under "Implementation Progress") to reflect completed tasks. Mark `- [ ]` → `- [x]` for any task or verification step finished in that commit.
- **Update CHANGELOG.md**: Every commit must add an entry to `CHANGELOG.md` under the `[Unreleased]` section. Use the appropriate subsection: `Added`, `Changed`, `Fixed`, `Removed`.

## Configuration

Environment: copy `.env.example` to `.env` and `config/config.example.yaml` to `config/config.yaml`, then edit with your API keys.

YAML files in `config/`:
- `config.yaml` — API endpoints, Whisper model settings, platform credentials (supports `${ENV_VAR}` interpolation)
- `platforms.yaml` — Per-platform subtitle language and video specifications
- `subtitle_styles.yaml` — ASS subtitle styling (font, color, position) with per-platform overrides
- `tts_voices.yaml` — Voice profiles, per-platform defaults, volume mix settings
- `translation_profiles/` — Translation style profiles (tone, terminology, examples)

## Implementation Plans

Detailed phase plans live in `plans/phase{1-7}-*.md`. Progress is tracked via the checklist in `README.md`.
