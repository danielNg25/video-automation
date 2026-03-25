# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Retry utility (`src/utils/retry.py`): `retry` and `async_retry` decorators with exponential backoff, jitter, and configurable retryable exceptions
- State persistence (`src/utils/state.py`): `PipelineState` class with per-video JSON state files, stage tracking, crash recovery via `get_resume_stage()`
- Duplicate detection (`src/utils/state.py`): `is_duplicate()` and `register_processed()` with URL normalization, file-locked `processed_videos.json` registry
- Pipeline orchestrator (`src/pipeline.py`): `Pipeline` class with `process_single()` and `process_batch()`, crash recovery, duplicate detection, signal handling, concurrency control
- Metadata mapper (`src/utils/metadata.py`): `map_metadata()` with per-platform formatting (YouTube #Shorts, TikTok hashtags in description, X 280-char truncation)
- Per-video logging (`src/utils/logger.py`): `get_video_logger()` for per-video log files, structured JSON fields (video_id, stage, duration_ms, extra)
- CLI interface (`src/cli.py`): Click commands — process, download, transcribe, upload, batch, status, server — with Rich formatted output
- Module entry point (`src/__main__.py`): enables `python -m src` execution
- Pipeline API router: `POST /api/pipeline/full` (full pipeline), `POST /api/pipeline/batch` (batch with concurrency), `GET /api/pipeline/history` (filterable), `POST /api/pipeline/{task_id}/retry`, `GET /api/dashboard/stats`
- API models: `FullPipelineRequest`, `BatchPipelineRequest`, `PipelineHistoryEntry`
- TTS base class (`src/tts/base.py`): `BaseTTSProvider` ABC with `synthesize()`, `list_voices()`, `synthesize_segments()` and text cleanup
- Voice profiles config (`config/tts_voices.yaml`): per-platform voice/volume settings with Edge TTS defaults
- TTS infra: `edge-tts` dependency, `data/tts/` gitignore and data dir, TTS config section in `config.example.yaml`
- Edge TTS provider (`src/tts/edge.py`): free async TTS with Vietnamese/English voices, rate/pitch control
- TTS factory (`src/tts/__init__.py`): `get_tts_provider()`, `load_voice_profiles()`, `save_voice_profiles()`
- TTS audio assembler (`src/tts/assembler.py`): concurrent segment synthesis, ffmpeg atempo duration fitting, silence-padded concatenation
- Audio mixing in FFmpeg (`src/processor/ffmpeg.py`): `mix_audio()` and `burn_reformat_and_dub()` for TTS dubbing
- Batch processor TTS support: `tts_audio_paths` and `tts_mix_settings` params for per-platform TTS dubbing
- TTS API models (`src/api/models.py`): `TTSRequest`, `TTSPreviewRequest`, `VoiceInfo`, `VoiceProfileConfig`, `TTSResult`
- TTS router (`src/api/routers/tts.py`): generate TTS, list voices, CRUD profiles, preview audio, stream TTS track
- `run_tts()` in task manager with SSE progress per segment
- TTS-aware process endpoint: `enable_tts` + `tts_mix_settings` on `ProcessRequest`
- TTS static file mount at `/files/tts/`
- TTS TypeScript types (`ui-app/src/api/types.ts`): `TTSRequest`, `VoiceInfo`, `VoiceProfileConfig`, `TTSPlatformConfig`
- TTS API client (`ui-app/src/api/client.ts`): `postTTS`, `getTTSVoices`, `getTTSProfiles`, `postTTSPreview`, etc.
- TTS section on Process page: enable toggle, voice profile selector, per-platform volume sliders, generate button with SSE progress, audio playback
- TTS preview component (`ui-app/src/components/TTSPreview.tsx`): play/stop button with blob audio playback
- TTS unit tests (`tests/test_tts.py`): 24 tests covering text cleanup, ABC, factory, voice profiles, atempo filter, ffmpeg audio mix, and batch processor TTS integration
- OpenAI TTS provider (`src/tts/openai_tts.py`): `/v1/audio/speech` API, tts-1/tts-1-hd models, speed control
- Google Cloud TTS provider (`src/tts/google_tts.py`): REST API with Wavenet/Standard voices, Vietnamese and English

- ElevenLabs TTS provider (`src/tts/elevenlabs.py`): high-quality multilingual TTS with voice listing from API or curated defaults
- TTS provider selector on Pipeline page: switch between Edge (free), ElevenLabs, OpenAI, Google with per-request API key input
- TTS voice browser: "Profiles" tab for saved presets, "All Voices" tab for browsing provider's full voice list
- `GET /api/tts/providers` endpoint listing available providers with free/key metadata
- Per-request API key support on TTS generate, preview, and voice list endpoints
- gTTS provider (`src/tts/gtts_provider.py`): free Google Translate TTS, no API key, supports Vietnamese/English/10+ languages
- Piper TTS provider (`src/tts/piper_tts.py`): fully offline local neural TTS with auto-download of ONNX models from HuggingFace

### Changed
- TTS assembler: clips only speed up when they would overlap the next segment's start, not the current segment's end — produces more natural-sounding speech
- Renamed "Download & Transcribe" page to "Pipeline" in sidebar navigation

- Video Studio page (`ui-app/src/pages/VideoDetail.tsx`): per-video workspace at `/videos/:videoId` with transcribe, translate, TTS dubbing, process & export, and SRT preview panels
- "Video Studio" sidebar entry linking to video detail pages
- Stepper/wizard layout for Pipeline page: 4 numbered steps (Download, Extract, Translate, TTS) with expandable config panels, step state visualization (done/running/pending), inline progress bars during execution

### Removed
- `SubtitleProcess.tsx` page and `/process` route
- Individual video panels from Pipeline page — moved to Video Studio (`/videos/:videoId`)
- Whisper speech-to-text backends (`src/transcriber/faster.py`, `src/transcriber/mlx.py`) — OCR via PaddleOCR is the only transcription method
- `faster-whisper` and `mlx-whisper` dependencies from `pyproject.toml`
- Whisper config section from `config.yaml` and `config.example.yaml`
- Audio/OCR method toggle from Pipeline page UI — OCR is now the default and only option
- `translate_srt()` Whisper-based translation function from `src/processor/subtitle.py` (replaced by LLM translator)
- Moved TTS generation (voice profile selector, preview, generate button) from Subtitle Process page to Pipeline page
- Subtitle Process page now has a simplified "Mix TTS Audio" toggle with per-platform volume sliders only
- OCR subtitle extraction via PaddleOCR (`src/transcriber/ocr.py`): auto-detect subtitle regions, filter watermarks by position/frequency/size, two-pass approach (sample + full OCR), deduplication
- `extract_frames()` method on `FFmpegProcessor` for JPEG frame extraction at configurable FPS
- OCR transcriber factory integration: `get_transcriber(config, method="ocr")` with full config passthrough
- OCR config section in `config/config.example.yaml`: fps, confidence, similarity, subtitle region heuristics
- API: `method` and `ocr_region` fields on `TranscribeRequest` for OCR mode with optional manual region override
- API: `GET /api/videos/{video_id}/sample-frame` endpoint for frame preview (manual region override)
- Task manager OCR routing with per-frame SSE progress messages
- UI: Audio/OCR method toggle on DownloadTranscribe page with OCR-specific progress labels
- UI: `getSampleFrameUrl()` client function and `OcrRegion` type
- `paddlepaddle` and `paddleocr` dependencies in `pyproject.toml`
- Unit tests for OCR: auto-classification (5 tests), watermark filtering (3 tests), deduplication (6 tests), result parsing (2 tests), factory integration (4 tests), extract_frames (2 tests)
- Phase 3 plan: OCR subtitle extraction from burned-in Douyin subtitles via PaddleOCR
- Translation profile system (`src/translator/profiles.py`): load, list, save, delete profiles
- Built-in translation profiles: funny-casual-vi, neutral-vi, dramatic-vi
- Profile YAML config directory (`config/translation_profiles/`) with example template
- LLM translator (`src/translator/llm.py`): batch SRT translation via Anthropic/OpenAI with retry, rate limiting, context carryover
- Translation config section in `config/config.example.yaml`
- `anthropic` and `openai` SDK dependencies in `pyproject.toml`
- Translator factory (`src/translator/__init__.py`): `get_translator()` + `translate_with_profile()` convenience function
- Translation API router (`src/api/routers/translate.py`): `POST /api/translate` with SSE progress, profile CRUD endpoints
- Translation request/response models in `src/api/models.py`
- `run_translate()` in task manager with batch-level SSE progress events
- Translation UI on Download & Transcribe page: profile selector, translate button with SSE progress, profile editor (create/edit/delete)
- SRT file download endpoint: `GET /api/videos/{video_id}/srt/download`
- Content-Disposition attachment header on raw video download endpoint
- Download MP4 button on video result card
- SRT export button wired to download endpoint in SRT preview header
- LLM backend/model/API key selector on translation panel (overrides config per-request)

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
- Phase 4 plan: TTS dubbing with Edge TTS (free), OpenAI TTS, Google Cloud TTS providers
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
