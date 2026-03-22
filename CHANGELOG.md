# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Translation profile system (`src/translator/profiles.py`): load, list, save, delete profiles
- Built-in translation profiles: funny-casual-vi, neutral-vi, dramatic-vi
- Profile YAML config directory (`config/translation_profiles/`) with example template
- LLM translator (`src/translator/llm.py`): batch SRT translation via Anthropic/OpenAI with retry, rate limiting, context carryover
- Translation config section in `config/config.example.yaml`
- `anthropic` and `openai` SDK dependencies in `pyproject.toml`
- Translator factory (`src/translator/__init__.py`): `get_translator()` + `translate_with_profile()` convenience function

## [1.1.0] — 2026-03-22

### Added
- Cookie management UI on Settings page: view status, paste new cookie, test against Douyin API
- Settings API router (`src/api/routers/settings.py`): `GET/PUT /api/settings/cookie`, `POST /api/settings/cookie/test`
- LLM translation with profiles system (tasks 1.26-1.30): translate SRT via Anthropic/OpenAI with style-controlled profiles
- Translation profile config (`config/translation_profiles/`): funny-casual-vi, neutral-vi, dramatic-vi
- Profile CRUD API: `GET/POST/PUT/DELETE /api/profiles`
- Translation API: `POST /api/translate` with batch progress via SSE
- Raw video download endpoint: `GET /api/videos/{video_id}/raw`
- SRT export from UI with multi-language support
- Updated README checklist with new tasks (1.26-1.32) and verification items (V1.18-V1.25)
- SRT-to-ASS converter with configurable styling (`src/processor/subtitle.py`)
- Dual-line subtitle merging (English + Vietnamese) for bilingual burn-in
- Per-platform subtitle language selection with fallback chain (vi/en/zh)
- Line-breaking for long subtitle text at word boundaries
- FFmpeg processor (`src/processor/ffmpeg.py`): burn subtitles, reformat per platform, single-pass burn+reformat
- Batch processor (`src/processor/__init__.py`): process one video for all platforms in one call
- Process API endpoints: `POST /api/process`, `GET /api/subtitle-styles`, `GET /api/platforms`, `GET /api/videos/{id}/output/{platform}`
- Process page UI (`ui-app/src/pages/SubtitleProcess.tsx`): video selector, live style preview, platform selector with subtitle language badges, SSE progress, output video preview
- Phase 2 unit tests (28 tests): SRT parsing, ASS conversion, subtitle merging, FFmpeg mocking, batch processing
- Phase 2 implementation plan (`plans/phase2-implementation.md`)
- Subtitle editor page (`ui-app/src/pages/SubtitleEditor.tsx`): video player with live subtitle overlay, inline text editing, SVG timeline with draggable segment edges, style panel with background opacity and position controls
- Editor API endpoints: `PUT /api/videos/{id}/srt` (save edited SRT), `POST /api/videos/{id}/preview-frame` (render frame with burn-in), `POST /api/videos/{id}/preview-clip` (render clip via SSE)
- `write_srt()` function in `src/processor/subtitle.py` for writing edited segments back to SRT format
- `useVideoPlayer` hook for high-frequency video state (60fps via requestAnimationFrame)
- Editor components: `VideoPlayer`, `SubtitleOverlay` (with drag-to-reposition), `SegmentList` (split/merge/delete), `Timeline` (SVG with draggable edges), `StylePanel` (background opacity, horizontal margin)
- SRT timestamp utilities (`ui-app/src/utils/srtTime.ts`)
- "Edit Subtitles" button on Download & Transcribe page for quick navigation to editor
- Keyboard shortcuts in editor: Space/K (play/pause), J/L (±5s), arrows (±1 frame), Cmd+S (save)
- Subtitle style extensions: `background_color`, `background_opacity`, `margin_h` in config and ASS generation
- Low-res 360p video proxy for subtitle editor (`generate_proxy()` in FFmpegProcessor)
- Video serving endpoints: `GET /api/videos/{id}/raw` and `GET /api/videos/{id}/proxy` (on-demand transcoding with caching)
- Quality toggle in subtitle editor header (360p proxy vs full resolution)
- Per-video subtitle style storage (`data/srt/{video_id}_style.json`) with global default fallback
- Phase 5 plan: TTS dubbing with Edge TTS (free), OpenAI TTS, Google Cloud TTS providers
- Voice profiles system (`config/tts_voices.yaml`) with per-platform voice/volume config
- TTS audio assembler with segment-level duration fitting via ffmpeg `atempo`

### Changed
- Phase 2 plan: subtitles are now English/Vietnamese (translated), not Chinese. Removed CJK font handling as unnecessary
- Platform subtitle config: TikTok/Facebook use Vietnamese, YouTube/X use English
- Default subtitle font changed from "Noto Sans CJK SC" to "Arial" (supports Vietnamese diacritics)

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
