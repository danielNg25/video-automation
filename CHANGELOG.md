# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Pipeline auto-blur: full pipeline (`Pipeline.process_single`) automatically detects OCR subtitle region and applies blur during the process stage — no manual config needed
- Pipeline stepper: added 5th "Process & Burn" step showing blur, subtitle burn-in, and platform reformat info; TTS and Process are now separate steps
- Phase 6 unit tests (`tests/test_subtitle_replacement.py`): 26 tests covering region detection, style matching, blur filter construction, single-pass blur+burn, OCR metadata persistence, and batch processor blur integration
- Region selector component (`ui-app/src/components/editor/RegionSelector.tsx`): interactive drag-to-resize/reposition overlay on video frame with coordinate display and auto-detect button
- Blur preview component (`ui-app/src/components/editor/BlurPreview.tsx`): before/after comparison with refresh button, toggle between original and blurred frame
- Subtitle replacement section on Video Studio: collapsible "Original Subtitle Removal" panel with enable toggle, region selector, blur mode/strength controls, and live blur preview
- TypeScript types for subtitle replacement: `SubtitleRegion`, `BlurSettings`, `PreviewBlurRequest`; `blur_settings` and `manual_region` on `ProcessRequest`
- API client functions: `getSubtitleRegion()`, `setSubtitleRegion()`, `postPreviewBlur()`
- Subtitle replacement router (`src/api/routers/replacement.py`): `GET/POST /api/videos/{id}/subtitle-region` (auto-detect and manual override), `POST /api/videos/{id}/preview-blur` (single-frame JPEG preview)
- Process endpoint blur integration: `blur_settings` and `manual_region` on `ProcessRequest`, task manager loads region and passes to batch processor
- Combined blur+burn+reformat pipeline: `blur_and_burn_subtitles()`, `blur_burn_and_reformat()`, `blur_burn_reformat_and_dub()` — single-pass ffmpeg for blur + subtitle burn + platform reformat + TTS mix
- Batch processor blur support: `process_for_all_platforms()` accepts `subtitle_region` and `blur_settings`, auto-selects blur methods with style matching
- Blur filter in FFmpeg (`src/processor/ffmpeg.py`): `apply_region_blur()`, `apply_blur_to_frame()`, `extract_single_frame()` with three modes — boxblur, solid fill, pixelate
- Subtitle style matcher (`src/processor/style_matcher.py`): derives font_size, margin_v, alignment from detected region dimensions
- Subtitle region detector (`src/processor/region_detector.py`): `SubtitleRegion` dataclass and `SubtitleRegionDetector` that loads from OCR metadata or computes from raw bounding boxes
- OCR metadata persistence: OCR transcriber now saves `{video_id}_ocr_meta.json` with subtitle region bounding box after transcription
- Subtitle replacement API models: `SubtitleRegionResponse`, `BlurSettings`, `SubtitleReplacementRequest`, `PreviewBlurRequest`
- `blur_settings` and `manual_region` fields on `ProcessRequest` for Phase 6 blur integration

### Changed
- Video Studio WYSIWYG redesign: editor now uses ffmpeg-rendered preview (blur + burned ASS subs + TTS audio) instead of HTML overlay — preview matches export exactly
- Editor panel merged with export: subtitle language, TTS file, volume sliders, "Render Preview" and "Export Full Video" buttons all in one panel

### Fixed
- Editor style now applies OCR-detected positioning (fontSize, marginV) on top of any saved style — previously the saved default style overwrote OCR values
- Subtitle overlay now scales proportionally to the video player size using ResizeObserver — previously used hardcoded pixel multipliers causing mismatched positioning between editor preview and ffmpeg export
- Subtitle editor auto-loads OCR region data to match subtitle position (marginV, fontSize) to where original Chinese subtitles were detected
- Video Studio panels (Translation, TTS Dubbing, Subtitle Replacement, Export) are now collapsible — click header to toggle open/closed

### Removed
- HTML SubtitleOverlay, StylePanel, Timeline, VideoPlayer from editor panel — replaced by ffmpeg-rendered preview
- Separate Export panel from Video Studio — merged into editor panel
- SubtitleReplacement panel from Video Studio — blur is auto-applied by backend
- Video info card (thumbnail, metadata grid) from Video Studio — replaced by compact header bar
- SRT Preview right column — replaced by editor's inline segment list
- Two-column grid layout on Video Studio — now single full-width column

### Fixed
- Blur region now expands to full video width (minus 3% margin) so translated text is fully covered even when longer than original Chinese
- Style matcher centers subtitle text vertically within the blur region (was aligned to bottom edge, causing text to appear below blur)
- Style matcher now scales region coordinates to ASS PlayRes (1080x1920) — fixes subtitle position on non-1080p videos like 576x1024 Douyin clips
- Export preview and full export now apply blur + style matching when OCR metadata exists — "Preview 5s" shows blurred original subs with translated subs burned in
- Subtitle editor video player no longer crops/stretches video to fill frame — shows full video with correct aspect ratio
- Video now appears on FE immediately after pipeline completes (was only visible after server restart)
- Pipeline TTS now matches Video Studio quality: LLM sentence detection, text shortening, and progress tracking

### Changed
- TTS endpoint and Video Studio now pass LLM API key/backend for sentence boundary detection during TTS generation
- TTS now merges subtitle segments into sentence groups before synthesis (LLM-detected boundaries, heuristic fallback), producing natural-sounding speech instead of choppy per-line audio
- Translation now sends all segments in a single LLM call for full narrative context (was batching 8 at a time)
- For videos >100 segments, uses smart chunking with full transcript as context per chunk
- Added robust numbered-response parser with positional fallback
- max_tokens scales dynamically with segment count

### Added
- Phase 6 plan: Subtitle replacement — blur original Chinese subs, auto-detect region from OCR, reposition translated subs to match original location/size
- Renamed Phase 6 (uploads) → Phase 7 to accommodate new phase
- TTS gap redistribution (`src/tts/assembler.py`): 3-phase timing pipeline — borrows unused gap time from adjacent segments, LLM-shortens text if ratio > 1.25x, hard-caps speedup at 1.5x with fade-out truncation
- `LLMTranslator.shorten_text()` method for condensing subtitle text while preserving meaning
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
- Config API: `GET /api/config` (secrets redacted), `PUT /api/config` (deep merge, skips redacted '***' values), `GET /api/config/platforms`
- Dashboard page upgrade: live pipeline table from history API, functional batch processing with concurrency slider and progress bar, platform checkboxes, expandable row details, real activity feed from pipeline history
- Settings page upgrade: Pipeline section wired to config API (data dir, max concurrent, retry attempts, retry delay, skip existing) — values persist on save/reload
- React Router navigation verified: all routes active with NavLink highlighting, lazy loading, browser back/forward support
- Integration tests (`tests/test_pipeline.py`): 32 tests covering retry decorator, state persistence, duplicate detection, metadata mapper, pipeline orchestrator (with mocks), CLI argument parsing, structured logging
- README finalized: updated architecture diagram, tech stack, project structure to reflect all phases
- Video list page (`ui-app/src/pages/VideoList.tsx`): grid view of all videos with thumbnails, status badges, language tags, search, filter, delete, and navigation to Video Studio
- `/videos` route in React Router for Video Studio sidebar link

- Video export API: `POST /api/videos/{id}/export` (full export with SSE progress), `POST /api/videos/{id}/export/preview` (5-second preview clip), `GET /api/videos/{id}/export` (serve exported file)
- Export UI on Video Studio: subtitle language selector, dub audio selector from generated TTS files, separate video/dub volume sliders (0-200%), preview player, export with progress bar and download link
- Multiple TTS dubs per video: files saved as `{id}_{lang}_{provider}_{profile}.wav` instead of overwriting
- TTS audio list API: `GET /api/videos/{id}/tts` lists all generated dubs with metadata
- TTS audio library panel on Video Studio: browse/play all generated dubs with provider, profile, size, and relative time
- Pipeline run persistence: `data/logs/pipeline_runs.json` tracks batch and single runs across server restarts
- Pipeline runs API: `GET /api/pipeline/runs` with stale run detection (interrupted runs auto-marked)
- Dashboard pipeline table: shows runs (batch/single) with expandable child videos, replaces per-video history
- Pipeline polling: frontend polls `GET /api/pipeline/{task_id}` instead of SSE for progress, survives page navigation and refresh
- OCR frame-level progress wired to pipeline: "Running OCR on frame 42/362..." visible on Pipeline page during transcription
- Translation batch progress wired to pipeline: "Translating batch 4/7..." visible during translation stage
- DeepSeek LLM backend support for translation
- LLM backend/model/API key passed from Pipeline UI to translation backend (previously ignored, defaulted to Anthropic)
- TTS volume boost: `loudnorm` normalization to -16 LUFS after `amix` volume compensation

### Changed
- Pipeline page URL input replaced with multi-URL textarea: paste multiple URLs (one per line) for batch processing with concurrency slider, or single URL for normal pipeline — auto-detects mode
- Single URL pipeline now uses `POST /api/pipeline/full` (same as batch children) instead of old `POST /api/pipeline`
- Dashboard: removed Success Rate card, Quick Process, and Batch Process sections (duplicated Pipeline page); pipeline table now full-width
- Upload page: replaced fake/hardcoded content with "Coming Soon" placeholder
- UI cleanup: removed non-functional bell/help/avatar from TopBar, "New Project" button and "Documentation" link from Sidebar, "VideoPrecision" branding replaced with "Douyin Auto"
- SSE keepalive: now loops with 30s timeout instead of disconnecting after one timeout

### Fixed
- Video Studio sidebar link (`/videos`) now renders a video list page instead of blank page
- Batch Process card on Dashboard highlighted with border accent and icon for better visibility
- Pipeline SIGINT handler now raises KeyboardInterrupt to break out of blocking calls immediately; second Ctrl+C force-exits
- Pipeline stepper stage tracking: `current_stage` now stored on in-memory Task object, available before video_id is resolved
- Batch children progress: uses average of children's progress for smooth % updates, shows per-child OCR frame messages
- `PipelineState.mark_done()` now sets `progress=1.0` so completed pipelines show 100%
- Subtitle editor back button navigates to Video Studio (`/videos/{id}`) instead of Pipeline page
- TTS audio persists across page refresh (detected via list API on mount)
- Video delete now cleans up TTS audio files
- ffmpeg subtitle filter quoting: commas in `force_style` escaped for chained `-vf` filters
- Dashboard Activity Feed: fixed crash from referencing removed `history` variable
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
