# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `<PipelineRunsTable />` mounted at the bottom of the Pipeline page (`ui-app/src/pages/DownloadTranscribe.tsx`). The same expandable-rows table that Dashboard shows today now lives below the pipeline form on `/download`, paving the way for Dashboard's removal.
- `ui-app/src/lib/usePipelineRuns.ts`: hook that polls `GET /api/pipeline/runs` every 30s with a fallback to `/api/pipeline/history` for legacy per-video data. Exports `PipelineRun` interface plus `relativeTime` and `stageFromStatus` helpers. Standalone file — not yet wired into any page.
- `ui-app/src/components/PipelineRunsTable.tsx`: presentational component consuming `usePipelineRuns()`. Renders expandable rows (10 most recent) with All/Running/Completed/Failed filter tabs, View (single-video) and Retry (failed-run) actions matching today's Dashboard behavior. Standalone — mounted in Task 2.
- UI app overhaul spec (`docs/superpowers/specs/2026-05-22-ui-app-overhaul-design.md`). Removes the unreachable `/upload` nav item and the Dashboard page (`/` becomes the Pipeline launcher; run history migrates onto the Pipeline page as "Recent Runs" via a new `usePipelineRuns` hook + `PipelineRunsTable` component). Picks the standalone `/editor/:videoId` page as the canonical subtitle editor and deletes the duplicate `SubtitleEditorPanel` embedded in VideoDetail. Rebuilds VideoDetail (995 lines) as a tabbed page — Overview / Translate / Dub / Export — with tab state in `?tab=` query param; each tab gets its own component file (~120–250 lines). Rebuilds Settings (760 lines) as a two-level sidebar — SOURCES / PROCESSING / SYSTEM groups around 7 category files — with `?category=` deep-linking replacing the current `#hash` pattern, and adds a new Translation category for LLM defaults previously leaking into VideoDetail. Establishes a single-source-of-truth contract for TTS settings (`tts_playback_speed`, `tts_underlay_db`, provider/voice/language localStorage keys): Settings holds defaults; Pipeline Advanced and VideoDetail Dub pre-fill from those defaults and never auto-write back; an explicit "Save as default" button writes back. Drives ~1500 lines of net deletion across the UI (Dashboard, SubtitleEditorPanel, unused mockData exports).
- `ui-app/src/components/PipelineStageTracker.tsx`: pure presentational component that renders 5 rows (Download / Transcribe / Translate / TTS / Process) from a `PipelineStatus` prop. Each row shows status icon (done ✓ / running ● / pending ○ / skipped ⊖), label, per-stage progress bar, and the current message when running. Translate-skipped state is auto-detected when `currentStage` advances past translate without translate appearing in `completedStages`.
- `ui-app/src/lib/pipelineStatus.tsx`: new `PipelineStatusProvider` React Context + `usePipelineStatus()` hook. Owns the pipeline-polling loop at the app root so it survives page navigation. On mount, optimistically primes state from `sessionStorage['pipeline_active_task'].lastKnown` so the running-pipeline UI renders instantly on hard refresh while the reconnect fetch runs in the background. Standalone file — not wired into any page yet (Task 4 does that).
- `stage_progress: float` field on `GET /api/pipeline/{task_id}` (and per child in batch responses). Derived from the existing overall `progress` and `current_stage` via the new canonical `STAGE_RANGES` constant in `src/pipeline.py`. Lets the UI render per-stage progress without backend changes to `emit()`.
- Pipeline progress tracker + global store spec (`docs/superpowers/specs/2026-05-22-pipeline-progress-tracker-and-global-store.md`). Replaces the single 0-100% bar on the running pipeline UI with a per-stage tracker (5 rows: Download / Transcribe / Translate / TTS / Process), each showing its own status (done ✓ / running ● / pending ○) and its own progress bar. Backend `/api/pipeline/{task_id}` adds a derived `stage_progress: float` field (per-stage 0..1, computed from the existing overall `progress` + `current_stage` via `STAGE_RANGES`). Frontend lifts pipeline status to an app-level React Context that owns the polling loop — survives navigation between pages, so the tracker renders instantly on navigate-back instead of waiting for a reconnect fetch. Optimistic restore on first load via expanded `sessionStorage['pipeline_active_task']` payload (now carries `lastKnown` stage/progress/message alongside taskId).
- Pipeline launcher: "Save as Default" button at the bottom of the Configuration card. Persists the pipeline-specific fields (translation profile, blur original subtitles, subtitle background) to localStorage. Fields that are shared with VideoDetail/Settings (TTS provider, voice, playback speed, underlay, LLM prefs) keep auto-persisting on every change.
- Pipeline launcher: Subtitle Background preset selector in the Advanced panel. Three presets (Off / Subtle / Strong) map to ASS `background_color` + `background_opacity` values, sent on the pipeline POST as `subtitle_style`. The processor's existing `style_overrides` merging applies them per-platform. `FullPipelineRequest` and `BatchPipelineRequest` gain a `subtitle_style: dict | None = None` field.
- Pipeline page cleanup + dubsync-default spec (`docs/superpowers/specs/2026-05-21-pipeline-page-cleanup-and-dubsync-default.md`). Replaces the 5-step expandable stepper on `ui-app/src/pages/DownloadTranscribe.tsx` with a flat compact form (Translation Profile + LLM Backend on row 1, TTS Provider + Voice + Preview on row 2, an "Advanced" toggle for playback speed / underlay / model / blur / ElevenLabs Voice ID). Drops the Voice Profile dropdown (redundant after Tasks 3 + 5 of the providers cleanup). Configuration card is hidden during a pipeline run, replaced by a slim progress strip. Also makes `{video_id}_{lang}.dubsync.srt` the default subtitle returned by `GET/PUT /api/videos/{id}/srt` and the download endpoint when present; `SrtResponse` gains `is_dubsync: bool` so the editor can warn that re-running TTS overwrites manual edits.
- Pipeline launcher (DownloadTranscribe): voice preview button — same `<TTSPreview>` component as VideoDetail, placed next to the voice selector. Plays a 3-5s Vietnamese (or English, based on selected profile language) sample using the currently selected voice + saved API key, so users can sample voices before kicking off a full pipeline run.
- TTS providers cleanup spec (`docs/superpowers/specs/2026-05-21-tts-providers-cleanup-design.md`). Removes the free unreliable providers (`edge`, `gtts`, `piper`) — Edge TTS in particular caused ~40% per-sentence failures in production. Keeps only the three paid providers (Google Cloud TTS, ElevenLabs, OpenAI). Migrates all voice profiles from Edge voice names to Google Wavenet equivalents. Also fixes a pipeline-launcher bug where the voice override was only sent for ElevenLabs (so Google + OpenAI would inherit an Edge voice name from the profile and crash on the provider side). Per-provider localStorage keys (`tts_voice_id_google`, `tts_voice_id_openai`, `tts_voice_id_elevenlabs`) replace the shared `tts_voice_id` key.
- `<TTSPreview>` accepts an `underlayDb` prop and forwards it on the preview request. The `/api/tts/preview` endpoint applies a stand-in underlay (mixes the synthesized clip with itself at `underlay_db`) so the user can roughly hear the chosen level alongside the dub speed.
- Pipeline launcher (DownloadTranscribe): per-run underlay select alongside the playback-speed input. Both share `tts_underlay_db` / `tts_playback_speed` localStorage keys with Settings and VideoDetail.
- VideoDetail TTS panel: per-run "Original underlay" select beside the playback-speed input. Default reads from localStorage; selection persists and is forwarded on the TTS POST.
- Settings → TTS Dubbing: new sidebar entry and section with `Dub playback speed` and `Original-language underlay` controls. Both persist to localStorage (`tts_playback_speed`, `tts_underlay_db`) and are shared with VideoDetail and DownloadTranscribe.
- TTS dubbing redesign implementation plan (`docs/superpowers/plans/2026-05-20-tts-dubbing-redesign.md`). 18 task-by-task TDD steps derived from the spec, sequenced as: planner unit tests (Tasks 1–5) → assembler integration (Tasks 6–10) → API wiring (Tasks 11–13) → UI (Tasks 14–17) → QA + finalize (Task 18).
- TTS dubbing redesign spec (`docs/superpowers/specs/2026-05-20-tts-dubbing-redesign.md`). Replaces the current Stage 1.5 iterative shortening / Stage 4 atempo path in `src/tts/assembler.py` with a plan-then-emit architecture: a pure-function planner builds a `DubPlan` over `(sentences, natural_synth_durations, playback_speed, video_duration)`, picking the loosest shortening target that fits (try 85% → 75% → 65%, floor 60%) and pushing downstream only when shortening can't recover the deficit. Drift is recovered by reclaiming silent gaps ≥ 1 s (reserving 0.2 s) and reset to 0 at gaps ≥ 3 s; a 3 s drift cap triggers Phase C rebalancing that tightens the biggest-overrun upstream sentence. The output WAV gains the original Chinese voice as a uniform underlay at a configurable level (default -12 dB; settings + per-run override on Video Studio and Pipeline launcher), read directly from the source MP4 via ffmpeg without pre-extraction. Synthesis failures fall back to Chinese audio at 0 dB in that slot (underlay locally un-ducked via chained `volume=enable='between(...)'` filters) — no more silently dropped sentences. A new `{video_id}_{lang}.dubsync.srt` is emitted per-segment with proportionally redistributed text snapped to word boundaries and timings re-anchored to the actual dub positions; the burn-in step prefers it over the legacy `{video_id}_{lang}.srt` when present. The `tts.complete` SSE event gains a `review_reasons` histogram so the UI can show failure-mode counts (e.g. `synth_failed=1, drift_cap_hit=2`) at a glance.
- TTS LLM-driven shortening for sentences that overrun their source span at the configured `playback_speed`. After Stage 1 synth, any merged sentence whose `clip_duration / playback_speed > source_span` is sent to the LLM via the existing `LLMTranslator.shorten_texts_batch` with a `target_pct = (source_span × speed / clip_duration) × 100`. Up to `SHORTENING_MAX_PASSES = 3` passes, each 5 pp stricter than the last (clamped at 30%). The translator's existing per-item floor (`max(40, target_pct − 15)`) rejects over-aggressive responses so a stricter target on the next pass can take another shot. Shortened clips are swapped into the slot only when the new audio is actually shorter; the merged-sentence text is then updated so `.merged.srt` / `.merged.json` (and `sentence_plan` rows) reflect what was actually spoken. The plan file gains `original_text`, `was_shortened`, `shorten_passes` per row for audit. `_vi.srt` is still never overwritten by TTS. Skipped automatically when no LLM key is configured (logged once).
- Cross-platform Docker packaging. New multi-stage `Dockerfile` (Node 20 builds the React UI, Python 3.11-slim runs uvicorn with ffmpeg/libass/Noto-CJK + PaddlePaddle/PaddleOCR/llama-cpp-python preinstalled) and an `app` service in `docker-compose.yml` that runs alongside the existing `douyin-api` helper. FastAPI now serves the built UI from `ui-app/dist/` at `/` (with SPA fallback) when present, exposes a `/api/health` endpoint, and reads the Douyin API URL from `DOUYIN_API_BASE` (compose sets it to `http://douyin-api:80`). Config interpolation extended to support `${VAR:-default}` so `config/config.example.yaml` works for both Docker and bare-metal `make api`. PaddleOCR model files persist in a named volume; `data/` and `config/` are bind-mounted. New Make targets: `docker-build`, `docker-rebuild`, `docker-logs`. New `DOCKER.md` operations guide and a slimmer "Docker Quickstart" section in the README.
- TTS planner module skeleton — `src/tts/planner.py` (`DubPlan`, `SentencePlan`, constants). Pure module, no I/O. Tests in `tests/test_tts_planner.py` cover dataclass shape and constant values.
- Planner Phase A — sentence walk with drift accumulation, gap reclaim (≥1s gaps, reserve 0.2s), and reset at long pauses (≥3s). Three unit tests.
- Planner Phase B — picks loosest shortening target (0.85 / 0.75 / 0.65, floor 0.60) that fits the slot plus reclaimable gap. Five unit tests. `build_plan` refactored to a two-pass implementation: Phase B previews targets, then Phase A's walk runs against the post-shortening effective durations.
- Planner Phase C — drift-cap rebalance. When projected drift exceeds 3s, tightens the worst-overrun upstream sentence iteratively until drift ≤ cap or no more tightening budget; flags cap-hit sentences with `reason="drift_cap_hit"`. Introduces `_StaticsBundle` to share per-sentence pre-computed inputs across Phase B preview and Phase C rebalance iterations. Three unit tests.
- Planner scaling tests — verify the planner's decisions are deterministic functions of `playback_speed`. Three tests.
- Assembler wired to the planner. Stage 1.5 iterative-shortening loop replaced by one `Planner.build_plan` call followed by a single batched LLM shortening request via the new `TTSAssembler._apply_shortening`. The legacy `{stem}.merged.srt`/`.merged.json` artefacts are no longer written; their content is covered by the richer plan JSON / sentences.srt downstream. `generate_full_track` now accepts `underlay_db` and `video_path` arguments (used by Task 7+ for the Chinese underlay).
- Synth-failure fallback: when a sentence's TTS clip is missing or zero-duration, the source video's audio fills that slot at 0 dB instead of being silently dropped. The underlay (if active) is locally un-ducked over the failure window. Regression test pins the muting bug fix.
- End-to-end underlay test (`TestUnderlayLevels`): generates pink-noise source MP4, runs the assembler at underlay -12 dB vs underlay off (0 dB), and asserts the mean_volume of the -12 dB run is measurably louder. Verifies the underlay filter chain actually mixes source audio under the dub.
- `{video_id}_{lang}.dubsync.srt`: per-segment SRT written by the assembler with text proportionally redistributed across the original source segments at word boundaries and timings re-anchored to the dub's actual positions. `select_subtitle_for_platform` prefers it over the legacy SRT for the configured language.
- New `underlay_db: float | None` field on `TTSRequest`, `TTSPreviewRequest`, `FullPipelineRequest`, `BatchPipelineRequest`. Existing clients that omit it get the assembler default (-12 dB) via the runner.
- Wired `underlay_db` through the TTS and pipeline routers, task manager, and runner. Field-precedence order remains: request value → Settings localStorage (sent as request value by UI) → `config.yaml` → assembler default (-12 dB).
- `config/config.yaml` and `config.example.yaml` gain `tts.underlay_db: -12.0` (overridable via `TTS_UNDERLAY_DB` env var). The runner uses this as the default when the request omits `underlay_db`.
- `is_dubsync: bool` field on `SrtResponse`. The GET `/api/videos/{id}/srt` endpoint sets it to `true` when the served file is the dub-synced derivative; the editor banner uses this to warn users that re-running TTS overwrites the file.
- Subtitle Editor warning banner: when the editor is displaying the dub-synced SRT (the new default served by GET `/api/videos/{id}/srt`), an amber banner at the top of the editor warns that re-running TTS will overwrite manual edits. Driven by the new `is_dubsync` field on `SrtResponse`.

### Fixed
- Eliminated the "Chinese voice played twice" bug: the assembler was reading the source MP4's audio and baking a -18 dB underlay into the TTS WAV, while the processor's audio-mix stage independently mixed the source MP4 audio at its own `original_volume` (default 0.3 / ~-10 dB). The user heard both. Removed the assembler's underlay logic entirely — `_concatenate_with_silence` no longer accepts `video_path`, `underlay_db`, or `failure_windows`; the TTS WAV now contains only the Vietnamese dub on silence. The user's `underlay_db` setting (still configurable in Settings / VideoDetail / DownloadTranscribe) now routes to the processor's `original_volume` parameter via a dB→linear conversion at the pipeline boundary. Per-platform `original_volume` defaults in `tts_voices.yaml` remain as fallback when no `underlay_db` is set.

### Removed
- Assembler-side underlay feature (added in the 2026-05-20 dubbing redesign and shipped on this branch). The `underlay_db` and `video_path` parameters are gone from `TTSAssembler.generate_full_track`, `_concatenate_with_silence`, `Planner.build_plan`, `DubPlan`, `run_tts_track`, `tm.run_tts`, `TTSRequest`, and `TTSPreviewRequest`. The synth-failure-window un-ducking feature went with it — failure windows now inherit the same `original_volume` as the rest of the video; the listener still hears the original Chinese, just at the uniform level instead of locally boosted to 0 dB. With Google TTS being reliable, this trade-off is acceptable. `TestUnderlayLevels` and `TestRegressionMutingBug` deleted from `tests/test_tts.py`; `UNDERLAY_DB_DEFAULT` constant deleted from `src/tts/planner.py`.
- Three free TTS providers (`edge`, `gtts`, `piper`) deleted along with their dependencies (`edge-tts`, `piper-tts`). Edge TTS in particular dropped ~40% of Vietnamese requests in production with `NoAudioReceived` errors. The factory now only knows `google`, `elevenlabs`, and `openai`; default fallback changed from `edge` to `google`. `list_providers` no longer surfaces the deleted entries.
- Whisper transcription scaffolding. The audio-Whisper backends were already gone from `src/transcriber/` (only `OCRTranscriber` is wired in), but stale references lingered: a `faster-whisper` install in the Dockerfile, a "Transcription" panel in the Settings UI (Model Size / Device / Compute Type / Language / VAD toggle), the `whisper:` block in `config/config.yaml`, the `--model` flag on `python -m src transcribe`, and matching mentions across `CLAUDE.md`, `src/transcriber/CLAUDE.md`, `README.md`, and a few code docstrings. PaddleOCR is the sole transcription path now.
- Social-platform posting (YouTube, TikTok, Facebook, X) was scoped out of the product. Deleted the empty `src/uploader/` package, the unimplemented `upload` CLI command, the stubbed upload stage in `Pipeline.process_single`, the `Upload.tsx` "Coming Soon" page and its route, and `plans/phase7-platform-uploads.md`. Dropped four unused dependencies — `tweepy`, `google-api-python-client`, `google-auth-oauthlib`, `authlib` (zero imports across the codebase). Removed the `platforms:` credentials block from `config/config.example.yaml` and the matching `TIKTOK_*` / `FB_*` / `X_*` env vars from `.env.example`. Per-platform **video formatting** (resolution / subtitle language via `config/platforms.yaml` and the `platforms: list[str]` parameter on pipeline endpoints) is unchanged — only auto-posting is gone.
- `SHORTENING_MAX_PASSES` constant in `src/tts/assembler.py` and the test classes that asserted on the deleted iterative-shortening internals (`TestSentenceShortening` and the over-specific anchor-helper assertion `test_redistribute_and_split_back_helpers_are_gone`). The translator's `shorten_texts_batch` floor logic remains live and is covered by `TestShortenTextsBatchFloor` in `tests/test_tts.py`.

### Changed
- Pipeline launcher (DownloadTranscribe): replaced the slim single-bar progress strip with the per-stage `<PipelineStageTracker>` (5 rows showing each pipeline stage's status and individual progress). Lifted pipeline polling state to the new `PipelineStatusProvider` context at the app root — the polling loop survives navigation between pages, so the tracker renders instantly when returning to the Pipeline page mid-run instead of waiting for a reconnect fetch. `App.tsx` wraps the router tree in the provider. Local `pipelineStage`/`pipelineProgress`/`pipelineMessage`/`isPipeline` state + `startPolling`/`stopPolling`/`saveActiveTask`/`clearActiveTask` helpers + the mount-effect reconnect block were all deleted (~92 lines net removed).
- Pipeline launcher (`DownloadTranscribe.tsx`): dropped the 5-step expandable stepper UI. Replaced with a flat Configuration card containing two main rows (Translation Profile + LLM Backend; TTS Provider + Voice + Preview) and an Advanced toggle that expands to show playback speed, original underlay, LLM model, blur toggle, and the ElevenLabs Voice ID input. Voice Profile dropdown removed — the backend profile name is derived implicitly from the selected translation profile's target language (`female-vi-natural` for vi, `female-en-natural` for en). During a pipeline run, the Configuration card is hidden; a slim progress strip shows the current stage + percent + message. File size: 897 → ~804 lines.
- TTS Chinese underlay default lowered from -12 dB to -18 dB across `src/tts/planner.py::UNDERLAY_DB_DEFAULT`, `config/config.yaml`, `config/config.example.yaml`, and the three UI pages (Settings, VideoDetail, DownloadTranscribe). Existing users with `-12` saved in localStorage continue at -12 — only new users get the quieter default.
- Pipeline launcher (DownloadTranscribe) now supports voice override for all providers, not just ElevenLabs. Previously Google + OpenAI inherited the voice from the profile (which used Edge voice names), so the runner would pass an Edge name like `vi-VN-HoaiMyNeural` to Google's API and get rejected. The launcher gains a voice picker that mirrors VideoDetail: dropdown for Google/OpenAI (auto-loaded when the provider's API key is configured), free-text Voice ID input for ElevenLabs. Missing-API-key banner warns when the selected provider has no saved key. Voice IDs persist under per-provider localStorage keys; stale voices (saved with the old shared key, or for a different provider) are cleared automatically.
- VideoDetail TTS panel: voice IDs now stored under per-provider localStorage keys (`tts_voice_id_google`, `tts_voice_id_openai`, `tts_voice_id_elevenlabs`) instead of a single shared `tts_voice_id`. One-time migration on mount moves the legacy key to the per-provider slot matching the user's last-selected provider. Stale voice IDs (e.g. an Edge voice name saved before the provider cleanup) are auto-cleared when they don't match the loaded voice list.
- `config/tts_voices.yaml` migrated from Edge voice names to Google Wavenet equivalents. Profiles renamed: `female-en-edge` → `female-en-natural`, `male-en-edge` → `male-en-natural`. `platforms.youtube.profile` reference updated to match. `default_provider` changed from `edge` to `google`. `src/tts/CLAUDE.md` updated to mention Google as the factory default.
- `.env` is no longer required for normal Docker use. API keys (Anthropic / DeepSeek / OpenAI / ElevenLabs / Google) are entered in the Settings UI and stored in `localStorage`; they're sent per-request and never persisted on the server. `docker-compose.yml` no longer references `env_file: .env`. `.env.example` slimmed down to a single optional `DOUYIN_API_BASE` override.
- GET `/api/videos/{id}/srt` and GET `/api/videos/{id}/srt/download` now prefer `{video_id}_{language}.dubsync.srt` over `{video_id}_{language}.srt` when both exist. The download endpoint preserves the clean filename `{id}_{lang}.srt` (no `.dubsync` infix) for UX. Adds the shared `_resolve_srt_path(video_id, language)` helper in `src/api/routers/transcribe.py`.
- PUT `/api/videos/{id}/srt` (editor save) now writes to `{id}_{lang}.dubsync.srt` when it exists, falling back to the legacy SRT. The response includes `is_dubsync` so the editor can render the warning banner.
- Pipeline launcher defaults flipped: `Blur Original Subtitles` is now **off** by default (was on); `Subtitle Background` is now **Subtle** by default (was Off). Both the UI's first-load defaults (when no localStorage value exists) and the backend `FullPipelineRequest.blur_enabled` default were flipped. Users who saved different defaults via the "Save as Default" button keep their choices.

### Removed
- All environment-variable-based configuration paths. The server no longer reads `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, or any other API key from the environment or from `.env`. Settings → API Keys in the web UI is the single source of truth — keys are stored in browser localStorage and sent with each translation / TTS request. Removed the env-var fallback chain in `src/tts/runner.py::_build_llm_translator`, the `os` import there, the `${ANTHROPIC_API_KEY}` / `${DEEPSEEK_API_KEY}` interpolations from `config/config.example.yaml` and `config/config.yaml`, the env-var hint in the assembler's "shortening disabled" warning, and the env-var alternative in the LLM precheck error message. Deleted `.env.example` and the `cp .env.example .env` step in README setup. The `DOUYIN_API_BASE` env var stays — it's docker-compose-internal infrastructure (the inter-container hostname override), not user-facing config.
- TTS reduced to one clip per merged sentence, played at natural speed, anchored at the sentence's source `start`. Sentence-level merging (LLM + heuristic) stays so a sentence broken across multiple SRT lines remains a single dub clip — but the LLM merger now post-splits any group whose internal segments cross a gap > `MAX_MERGE_GAP_SECONDS` (1.5 s, mirroring the heuristic), so a long pause in the source can never be erased by a merger that's text-only and timestamp-blind. Sub-groups after a split fall back to raw joined segment text since the LLM's punctuated text covered the whole merged sentence and would be wrong on any single sub-group. Deleted: `_redistribute_slots`, `GAP_BORROW_FRACTION`, the iterative LLM shortening loop and `resynth` helper, the Stage 4 atempo / speed-cap path, the post-Stage-3 SRT split-back (so `_vi.srt` is no longer overwritten by TTS), `_speed_up_audio`, `_build_atempo_filter`, `_llm_split_subtitles`, `_naive_split_text`, `_fallback_split_subtitles`, `_segments_from_chunks`, the `effective_start/end` and `anchor` fields on `SegmentSlot`, and the constants `DEFAULT_DUB_PLAYBACK_SPEED` / `SHORTENING_MAX_PASSES` / `MAX_SAFE_SPEED_RATIO`. `playback_speed` and `srt_path` on the assembler / API / FE surface stay for back-compat but are now no-ops. `sentence_plan` rows changed to `{index, text, start, end, synth_duration, overrun_seconds}`. Tests: dropped `TestRedistributeAfterShortening`, `TestRedistributeBorrowAmount`, `TestStage4NoDrop`, `TestStage4SpeedCap`, `TestIterativeShortening`, `TestConfigurablePlaybackSpeed`, `TestSentencePlan`, `TestAssemblerHelpers`, `TestSourceAnchoredPlacement`; added `TestSentenceMergerGapSplit` (covers split / no-split / singleton / end-to-end) and `TestNaturalSpeedAnchoring` (locks the slim `SegmentSlot` shape and the absence of every removed helper). Tradeoff: long Vietnamese clips overrun their source span and overlap the next sentence via ffmpeg `amix`. We will iterate.
- PaddleOCR crashed under Paddle 3.x on x86_64 (Linux native + Rosetta) with `(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` raised inside the PIR new-executor's OneDNN instruction lowering. Setting `FLAGS_use_mkldnn` / `FLAGS_enable_pir_in_executor` via env had no effect — PaddleOCR builds its inference programs before those are read. The reliable kill-switch is `paddle.set_flags({"FLAGS_use_mkldnn": False})` plus `enable_mkldnn=False` on the `PaddleOCR(...)` constructor; both applied in `OCRTranscriber._get_ocr()` with a `TypeError` fallback for older paddleocr versions that don't accept the kwarg.

### Fixed
- `{video_id}_{lang}.dubsync.srt` was emitting the source SRT unchanged instead of the dub's redistributed text and pushed-back timings. Root cause: the assembler's `sentence_plan` dict was missing four keys the dubsync writer expects (`segment_indices`, `target_text`, `final_start`, `final_duration`); the writer's main loop skipped every sentence and the defensive `preserve source segments unchanged` branch emitted the original SRT. Fixed by adding the missing keys + a regression test that pins the contract.
- TTS pipeline crash when `tts.underlay_db` is read from `config/config.yaml`. The YAML env-var interpolator (`${VAR:-default}`) always returns strings, so the runner picked up `"-12.0"` instead of `-12.0`, which crashed the ffmpeg filter-graph builder with `TypeError: bad operand type for unary -: 'str'`. The runner now coerces the value to float on read (with a logged warning + fallback to None on malformed input), and the assembler defensively casts on entry to catch the same bug class entering through any other path. Two regression tests cover both the assembler-direct path and the runner-via-config path.
- Some dubbed sentences played at natural 1× speed instead of the configured `playback_speed`. Stage 4 had two early-return branches that appended raw clips to `fitted_clips` without going through `_speed_up_audio`: the zero-width-SRT-segment branch and the no-clip branch. Refactored Stage 4 so every non-None clip goes through one unified atempo-application block — no branch can bypass it. Audio is now uniformly at the chosen speed regardless of how the slot's window resolved.

### Changed
- Pipeline page (DownloadTranscribe) now exposes the same "Dub Playback Speed" input as Video Studio, persisted to localStorage via the shared `tts_playback_speed` key. The pipeline launcher and the per-video TTS button now drive the same control — identical pacing across both flows.
- Dub playback speed is now configurable per-request. Replaced the hard `MAX_DUB_SPEED=1.5` constant with `DEFAULT_DUB_PLAYBACK_SPEED=1.5` and a `playback_speed` parameter on every layer (`TTSAssembler.generate_full_track`, `run_tts_track`, `tm.run_tts`, `TTSRequest`, `FullPipelineRequest`, `BatchPipelineRequest`). The chosen speed is applied **uniformly to every sentence** (atempo at exactly that rate — uniform pacing). Stage 3 iterative shortening still runs whenever a sentence's natural synth would require a higher speed than the chosen one. Added a "Dub playback speed" input to the Video Studio TTS panel (1.0–2.0×, step 0.1, persisted in localStorage), wired through to the TTS POST and the pipeline launcher's `ttsOverrides`. The TTS preview button (`/api/tts/preview`) also accepts `playback_speed` and applies atempo to the synthesized snippet so you hear the chosen speed before generating the full dub. The `TTSPreview` React component takes a `playbackSpeed` prop and forwards it.
- Dub pacing redesigned around a hard 1.5× ceiling. Replaced `MAX_PLAYBACK_SPEED=1.8` (with overrun) with `MAX_DUB_SPEED=1.5`. Above this, the audio is hard-capped at 1.5× and the slot ends with a silent tail — no more overrun bleeding from sentence A into sentence B's slot, which was the root cause of the perceived "skipping". Sentences that need shortening go through up to 3 iterative LLM passes (`SHORTENING_MAX_PASSES=3`), each pass using a stricter `target_pct` (steps 5 pp tighter per round). The per-item floor in `shorten_texts_batch` was also tightened from `max(25%, target_pct-10%)` to `max(40%, target_pct-15%)` so over-aggressive single-pass responses get rejected and retried with a stricter target instead of stripping meaning.
- `TTSAssembler.generate_full_track` now returns a `(Path, sentence_plan)` tuple. The runner exposes `sentence_plan` and `review_count` on the TTS task result so the user knows which sentences hit the 1.5× cap (`needs_review=true`). Each row contains `{index, text, window_start, window_end, synth_duration, speed_ratio, requested_ratio, needs_review, reason}`. Stage 2 redistribute (borrow time from neighbors) is preserved before the cap kicks in.
- Pipeline no longer generates per-platform videos (_youtube.mp4, _tiktok.mp4, etc.) — export is handled via Video Studio's Export tab, producing a single _export.mp4

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
- Video Editor now has three tabs: Segments (edit text/timing), Style (font/position/outline), Export (dub selector, volumes, render preview with ffmpeg, export full video)
- Export tab renders ffmpeg preview with blur + burned ASS subs + TTS audio — shows exactly what the final export produces

### Changed
- Export now defaults to the **source video's native resolution** instead of forcing `1080×1920`. `ExportRequest.resolution` is now `str | None`; when omitted/null, `_run_export_ffmpeg` reads `width`/`height` via `ffprobe` and uses those. When output equals source the `scale=…force_original_aspect_ratio=decrease,pad=…` chain is replaced with `null` (no-op), so blur, burned subtitles, and rounded-rect background PNGs all live in one coordinate system — the source pixels — and the new Vietnamese subtitle lands directly on top of the blurred original Chinese subtitle on every frame, regardless of source aspect ratio. For odd-dim sources we crop to the nearest even pair so libx264/yuv420p still accepts the output. Callers that need a fixed target (e.g. TikTok 1080×1920) can still pass `resolution="1080x1920"` and the previous letterbox-aware code path runs.
- Pipeline TTS stage and per-video TTS endpoint now share one implementation. Extracted the body of `tm.run_tts` into `src/tts/runner.py::run_tts_track`; `tm.run_tts` is now a thin task-manager wrapper around it, and `Pipeline.process_single` calls the same function. Both flows go through the same voice-profile resolution, TTS-provider/API-key plumbing, LLM-translator setup with backend-aware default model and per-request override priority, video-duration fallback, and canonical output filename `{id}_{language}_{provider}_{profile}.wav`. Identical inputs now produce byte-identical TTS tracks regardless of which path generated them.
- `FullPipelineRequest` and `BatchPipelineRequest` accept `tts_provider`, `tts_voice`, `tts_api_key`, `llm_api_key`, `llm_backend` overrides (mirroring `TTSRequest`); the pipeline launcher UI plumbs the user's Settings/localStorage values (ElevenLabs voice ID, ElevenLabs/OpenAI/Google API key, LLM API key + backend) into both single and batch pipeline POSTs. Previously these per-request settings only reached the per-video TTS endpoint, so the pipeline silently fell back to env vars / config — and when none were present, ran without an LLM translator at all (no sentence-boundary detection, no text shortening), producing visibly worse dubs with skipped/chipmunked sentences.
- Pipeline TTS now uses the backend-aware default model (`deepseek-chat` / `claude-sonnet-4-20250514` / `gpt-4o-mini` based on backend) instead of always defaulting to `deepseek-chat`; sending `deepseek-chat` to Anthropic/OpenAI silently failed every LLM call, disabling shortening entirely.

### Fixed
- Horizontal source exported at vertical target (e.g. 1024×576 → 1080×1920) no longer renders the new burned-in subtitle in the black padding bar. The blur was always positioned correctly in source-pixel space (carried through ffmpeg's `scale=…force_original_aspect_ratio=decrease,pad=…`), but the burned subtitle was computed in a 1080×1920 ASS canvas with no awareness of the letterbox shift, so it landed ~400 px below the actual video content. Two surgical changes fix it: `srt_to_ass` now accepts `play_res_x`/`play_res_y` (defaulting to 1080×1920 to preserve every existing caller); the export router passes the actual output dimensions, making the ASS canvas match the output 1:1. `SubtitleStyleMatcher.match_style` accepts `output_width`/`output_height` and applies the same scale + letterbox-pad transform to the subtitle region before computing `font_size` / `margin_v`, so the new subtitle lands exactly on top of the blurred original regardless of source/target AR. `generate_subtitle_background_images` no longer double-scales `font_size` and `margin_v` by `target_height/1920` since they're already in output coords.
- Dub generation no longer silently skips sentences. Four causes addressed:
  1. **Re-redistribute after shortening** — `_redistribute_slots` now runs a second time once Stage 3 has reduced offending clip durations. Donors that fed an overflowing slot reclaim their windows; slots that still overflow get a fair retry at borrowing from now-freed neighbors. Previously donors stayed permanently squeezed even after the offender shrank.
  2. **No-drop fallback in Stage 4** — when an effective window collapses to ≤ 0 from cascading clamps, we now fall back to the slot's base `(window_start, window_end)` and emit audio anyway; truly zero-width SRT segments play at natural speed from `window_start`. Previously the slot was silently appended as `(start, None)` and dropped by `_concatenate_with_silence`.
  3. **Atempo speed cap** — added `MAX_PLAYBACK_SPEED = 1.8` in [src/tts/assembler.py](src/tts/assembler.py); above this we cap and let the audio overrun the slot rather than chipmunk into unintelligibility. Brief overlaps with the next sentence are mixed by `amix` and remain preferable to silent gaps.
  4. **Per-item floor in `shorten_texts_batch`** — the floor is now `max(25%, target_pct − 10%)` of original character length rather than a fixed 40%. The 30% target Stage 3 requests for tight slots is no longer rejected by the global floor (which forced the slot back to its long original audio and re-triggered the borrow cascade).
- Blur region is now the **largest single-frame** subtitle bbox instead of the union across all OCR frames. Previously `_save_ocr_metadata` flattened every frame's bboxes (`extend` at the accumulation site) and then took the global min/max, so any cross-frame drift, longer line, or stray detection inflated the saved rectangle far beyond any real subtitle. The new logic preserves per-frame grouping (`append`), unions the boxes within each frame to cover multi-line subs, then picks the frame with the largest area and saves it exactly. The 40%-of-`video_height` clamp was dropped — it was a guard against the union-inflation that no longer exists. Existing OCR meta files in `data/srt/` were saved by the old code and need to be regenerated by re-running OCR to benefit
- Delete-video now removes all per-video files in `data/srt/` (OCR metadata `_ocr_meta.json`, export ASS `_*.export.ass`, style JSON, every translated SRT) and in `data/output/` (including the `_export.mp4`) — previously the SRT-dir cleanup was scoped to `*.srt` only, leaving OCR metadata and export ASS files behind, and individual unlink failures could abort the rest of the cleanup
- OCR metadata and runtime detector no longer add 10px padding around the subtitle bbox — `_save_ocr_metadata` and `SubtitleRegionDetector(padding=…)` now default to no padding, so the saved subtitle region matches the OCR detection exactly
- Export "View" modal no longer reloads ~1s after opening: the export SSE EventSource was never closed after the `complete` event, so it auto-reconnected and re-fired `complete`, which re-ran `setExportTimestamp(Date.now())` and changed the modal video's cache-busted `src`. The handler now stores the EventSource ref and closes it on complete/error, matching the TTS handler pattern, plus a cleanup `useEffect` closes it on unmount.
- Blur region now matches the OCR-detected subtitle bbox exactly with no padding (was 5% of region width) — fixes horizontal videos where the blur covered the full frame
- LLM sentence-grouping no longer strands segments: previously a `[1,2,3] ` line with empty merged text marked indices as seen but never added them to the result list, dropping those sentences from synthesis entirely. Now the indices are only marked seen once the group is committed, and the empty-text path falls back to joining the cleaned originals like the comma-separated path does
- Added warnings for every silent skip path in TTS assembly: synthesis exceptions returned by `gather`, sentences with no usable text after cleaning, slots with zero-duration clips, and slots whose effective window collapsed during gap redistribution
- Dubbing skipped sentences: `_llm_split_subtitles` now always returns a list (deterministic punctuation/word fallback when the LLM call fails), so the original SRT is rewritten on every shortened sentence and on-screen subtitles stay in sync with the shortened TTS audio
- TTS shortening prompt softened to preserve full meaning and natural phrasing instead of being aggressive; `shorten_texts_batch` now rejects shortenings below 40% of the original character length and falls back to the original text
- Resynth gather in TTS assembler now uses `return_exceptions=True` to match the synthesis-stage gather and prevent a single resynth failure from tearing down the whole assembly
- Editor style now applies OCR-detected positioning (fontSize, marginV) on top of any saved style — previously the saved default style overwrote OCR values
- Subtitle overlay now scales proportionally to the video player size using ResizeObserver — previously used hardcoded pixel multipliers causing mismatched positioning between editor preview and ffmpeg export
- Live editor now shows CSS blur approximation over the OCR-detected subtitle region (backdrop-filter: blur) so the original Chinese subs are visually hidden during editing
- Dub audio playback in live editor: select a TTS file from the toolbar dropdown and hear it synced to video playback (play/pause/seek all stay in sync)
- TTS text shortening now writes back to original SRT — burned-in subtitles match the spoken dub instead of showing the original longer text
- LLM-powered subtitle segmentation: shortened sentences are split into ≤35-char segments at natural phrase boundaries (commas, clauses) instead of dumb word splitting — timings distributed proportionally
- Pipeline LLM init now checks env vars (`DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) as fallback, matching Video Studio behavior — text shortening no longer silently fails in pipeline mode
- Fixed subtitle overlay not appearing during video playback — overlay div now always renders so ResizeObserver can attach (previously returned null when no active segment, preventing height measurement)
- Subtitle editor auto-loads OCR region data to match subtitle position (marginV, fontSize) to where original Chinese subtitles were detected
- Video Studio panels (Translation, TTS Dubbing, Subtitle Replacement, Export) are now collapsible — click header to toggle open/closed

### Removed
- Separate Export panel from Video Studio — merged into editor's Export tab
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
