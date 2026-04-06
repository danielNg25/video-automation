"""Pipeline orchestrator: chains download → transcribe → translate → TTS → process → upload.

Supports crash recovery via PipelineState and duplicate detection via processed_videos registry.
"""

from __future__ import annotations

import asyncio
import signal
from collections.abc import Callable
from pathlib import Path

from src.utils.config import load_config
from src.utils.logger import setup_logger
from src.utils.state import (
    PipelineState,
    is_duplicate,
    register_processed,
)

logger = setup_logger(__name__)


class Pipeline:
    """Full pipeline orchestrator with per-stage state tracking and crash recovery."""

    def __init__(self, config: dict | None = None):
        self.config = config or load_config()
        self._interrupted = False

    def _setup_signal_handlers(self):
        """Register signal handlers for graceful shutdown.

        First SIGINT/SIGTERM sets interrupted flag and raises KeyboardInterrupt
        to break out of blocking calls. Second signal force-exits.
        """

        def handler(signum, frame):
            if self._interrupted:
                # Second signal — force exit
                logger.warning("Force exit on second signal")
                raise SystemExit(130)
            logger.warning("Received interrupt, finishing current stage then exiting...")
            self._interrupted = True
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    async def process_single(
        self,
        url: str,
        platforms: list[str] | None = None,
        options: dict | None = None,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> dict:
        """Process a single video through the full pipeline.

        Args:
            url: Douyin video URL.
            platforms: List of target platforms (default: from config).
            options: Additional options (force, subtitle_lang, translate_profile,
                     tts_profile, privacy, title, tags).
            progress_callback: Optional callback(stage, progress, message).

        Returns:
            Dict with video_id, status, stages completed, and per-stage results.
        """
        options = options or {}
        force = options.get("force", False)
        platforms = platforms or ["youtube", "tiktok"]

        self._setup_signal_handlers()

        # --- Step 1: Extract video_id (attempt early dedup) ---
        video_id = options.get("video_id")

        # Load or create state early so emit() can persist progress
        state = PipelineState.load(video_id) if video_id else PipelineState(video_id="pending")

        def emit(stage: str, progress: float, message: str):
            logger.info(f"[{stage}] {message}")
            # Persist progress to state file for polling
            if state.video_id and state.video_id != "pending":
                state.update_progress(stage, progress, message)
            if progress_callback:
                progress_callback(stage, progress, message)

        if video_id and not force and is_duplicate(video_id, url):
            msg = f"Video {video_id} already processed, skipping (use --force to re-process)"
            emit("skip", 0.0, msg)
            return {"video_id": video_id, "status": "skipped", "message": msg}
        state.url = url
        state.platforms = platforms

        try:
            # --- Stage: Download ---
            if not state.is_stage_complete("download"):
                emit("download", 0.0, "Starting download...")
                state.mark_stage_start("download")

                from src.downloader import download_with_fallback

                metadata = await download_with_fallback(
                    url, Path("data/raw"), self.config
                )
                video_id = metadata.video_id
                state.video_id = video_id

                # Check dedup after we know the video_id
                if not force and is_duplicate(video_id, url):
                    msg = f"Video {video_id} already processed, skipping"
                    emit("skip", 0.0, msg)
                    state.status = "skipped"
                    state.save()
                    return {"video_id": video_id, "status": "skipped", "message": msg}

                state.mark_stage_complete("download", {
                    "file_path": str(metadata.file_path),
                    "title": metadata.title,
                    "author": metadata.author,
                    "duration": metadata.duration,
                })
                emit("download", 0.20, f"Download complete: {video_id}")
            else:
                video_id = state.video_id
                emit("download", 0.20, f"Download already complete: {video_id}")

            if self._interrupted:
                return self._make_result(state, "interrupted")

            # --- Stage: Transcribe ---
            if not state.is_stage_complete("transcribe"):
                emit("transcribe", 0.20, "Starting transcription...")
                state.mark_stage_start("transcribe")

                from src.transcriber import get_transcriber

                source_lang = options.get("subtitle_lang", "zh")
                video_path = state.stage_results.get("download", {}).get(
                    "file_path", f"data/raw/{video_id}.mp4"
                )

                # Wire OCR frame-level progress into pipeline emit
                # OCR runs in a thread, so bridge back to the event loop
                loop = asyncio.get_event_loop()

                def ocr_progress(progress: float, message: str):
                    # Map OCR's 0.0-1.0 range into pipeline's 0.20-0.45 range
                    mapped = 0.20 + progress * 0.25
                    loop.call_soon_threadsafe(emit, "transcribe", mapped, message)

                ocr_config = self.config.get("ocr", {})
                transcriber = get_transcriber(ocr_config, progress_callback=ocr_progress)

                segments = await asyncio.to_thread(
                    transcriber.transcribe, video_path, source_lang, "transcribe"
                )

                srt_dir = Path("data/srt")
                srt_dir.mkdir(parents=True, exist_ok=True)
                srt_path = srt_dir / f"{video_id}_{source_lang}.srt"
                transcriber.generate_srt(segments, srt_path)

                state.mark_stage_complete("transcribe", {
                    "srt_path": str(srt_path),
                    "segment_count": len(segments),
                    "language": source_lang,
                })
                emit("transcribe", 0.45, f"Transcription complete ({len(segments)} segments)")
            else:
                emit("transcribe", 0.45, "Transcription already complete")

            if self._interrupted:
                return self._make_result(state, "interrupted")

            # --- Stage: Translate (optional) ---
            translate_profile = options.get("translate_profile")
            if translate_profile and not state.is_stage_complete("translate"):
                emit("translate", 0.45, "Starting translation...")
                state.mark_stage_start("translate")

                from src.translator import translate_with_profile

                source_lang = state.stage_results.get("transcribe", {}).get("language", "zh")
                srt_path = Path(state.stage_results["transcribe"]["srt_path"])
                srt_dir = Path("data/srt")

                def translate_progress(batch_num: int, total_batches: int, message: str):
                    pct = 0.45 + (batch_num / total_batches) * 0.15
                    emit("translate", pct, f"Translating batch {batch_num}/{total_batches}...")

                output_path = await translate_with_profile(
                    srt_path, translate_profile, self.config, srt_dir,
                    progress_callback=translate_progress,
                )

                state.mark_stage_complete("translate", {
                    "output_path": str(output_path),
                    "profile": translate_profile,
                })
                emit("translate", 0.60, "Translation complete")
            elif translate_profile:
                emit("translate", 0.60, "Translation already complete")

            if self._interrupted:
                return self._make_result(state, "interrupted")

            # --- Stage: TTS (optional) ---
            tts_profile = options.get("tts_profile")
            if tts_profile and not state.is_stage_complete("tts"):
                emit("tts", 0.60, "Starting TTS generation...")
                state.mark_stage_start("tts")

                from src.processor.subtitle import parse_srt
                from src.tts import get_tts_provider, load_voice_profiles
                from src.tts.assembler import TTSAssembler
                from src.utils.metadata import extract_metadata_from_file

                profiles_data = load_voice_profiles(self.config)
                profiles = profiles_data.get("profiles", {})
                voice_profile = profiles.get(tts_profile, {})

                tts_lang = voice_profile.get("language", "vi")
                srt_path = Path("data/srt") / f"{video_id}_{tts_lang}.srt"
                segments = parse_srt(srt_path)

                video_path = state.stage_results.get("download", {}).get(
                    "file_path", f"data/raw/{video_id}.mp4"
                )
                file_meta = extract_metadata_from_file(Path(video_path))
                video_duration = file_meta.get("duration", 0.0)

                provider = get_tts_provider(self.config, voice_profile.get("provider"))

                # Create LLM translator for sentence detection + shortening
                translator = None
                llm_caller = None
                try:
                    import os
                    trans_cfg = self.config.get("translation", {})
                    api_key = (
                        trans_cfg.get("api_key")
                        or os.environ.get("DEEPSEEK_API_KEY")
                        or os.environ.get("ANTHROPIC_API_KEY")
                        or os.environ.get("OPENAI_API_KEY")
                    )
                    if api_key:
                        from src.translator.llm import LLMTranslator
                        backend = trans_cfg.get("backend", "deepseek")
                        model = trans_cfg.get("model", "deepseek-chat")
                        base_url = trans_cfg.get("base_url")
                        translator = LLMTranslator(
                            backend=backend, model=model,
                            api_key=api_key, base_url=base_url,
                            temperature=0.3,
                        )
                        llm_caller = translator._call_llm
                        logger.info(f"TTS LLM enabled ({backend}/{model}) for sentence detection + shortening")
                except Exception as e:
                    logger.warning(f"Could not init LLM for TTS: {e}")

                assembler = TTSAssembler(translator=translator)
                tts_dir = Path("data/tts")
                tts_dir.mkdir(parents=True, exist_ok=True)
                output_path = tts_dir / f"{video_id}_{tts_lang}.wav"

                def tts_progress(current, total, message):
                    pct = 0.60 + (current / max(total, 1)) * 0.10
                    emit("tts", pct, message)

                await assembler.generate_full_track(
                    provider=provider,
                    segments=segments,
                    voice_profile=voice_profile,
                    video_duration=video_duration,
                    output_path=output_path,
                    on_progress=tts_progress,
                    merge_sentences=True,
                    llm_caller=llm_caller,
                    srt_path=srt_path,
                )

                state.mark_stage_complete("tts", {
                    "audio_path": str(output_path),
                    "language": tts_lang,
                })
                emit("tts", 0.70, "TTS generation complete")
            elif tts_profile:
                emit("tts", 0.70, "TTS already complete")

            if self._interrupted:
                return self._make_result(state, "interrupted")

            # --- Stage: Process (subtitle burn-in + reformat) ---
            if not state.is_stage_complete("process"):
                emit("process", 0.70, f"Processing for {len(platforms)} platforms...")
                state.mark_stage_start("process")

                from src.processor import process_for_all_platforms

                video_path = Path(state.stage_results.get("download", {}).get(
                    "file_path", f"data/raw/{video_id}.mp4"
                ))
                srt_dir = Path("data/srt")
                output_dir = Path("data/output")
                output_dir.mkdir(parents=True, exist_ok=True)

                # Build TTS audio paths if TTS was run
                tts_audio_paths = None
                tts_mix_settings = None
                if state.is_stage_complete("tts"):
                    tts_result = state.stage_results.get("tts", {})
                    tts_path = Path(tts_result.get("audio_path", ""))
                    if tts_path.exists():
                        tts_audio_paths = {p: tts_path for p in platforms}

                # Auto-detect subtitle region for blur (from OCR metadata)
                subtitle_region = None
                blur_settings = None
                from src.processor.region_detector import load_subtitle_region

                subtitle_region = load_subtitle_region(srt_dir, video_id)
                if subtitle_region:
                    blur_settings = {
                        "enabled": True,
                        "blur_strength": 15,
                        "blur_mode": "blur",
                        "fill_color": "#000000",
                        "auto_match_style": True,
                    }
                    emit("process", 0.72, "Detected subtitle region — will blur original subs")

                results = await asyncio.to_thread(
                    process_for_all_platforms,
                    video_id,
                    video_path,
                    srt_dir,
                    output_dir,
                    platforms,
                    self.config,
                    None,  # style_overrides
                    None,  # on_progress
                    None,  # subtitle_language_overrides
                    tts_audio_paths,
                    tts_mix_settings,
                    subtitle_region,
                    blur_settings,
                )

                outputs = {p: str(r.output_path) for p, r in results.items()}
                state.mark_stage_complete("process", {"outputs": outputs})
                emit("process", 0.90, f"Processing complete for {len(outputs)} platforms")
            else:
                emit("process", 0.90, "Processing already complete")

            if self._interrupted:
                return self._make_result(state, "interrupted")

            # --- Stage: Upload (placeholder — uploaders in Phase 6) ---
            if not state.is_stage_complete("upload"):
                emit("upload", 0.90, "Upload stage (uploaders not yet implemented)")
                # Skip upload for now — Phase 6 will implement uploaders
                state.mark_stage_complete("upload", {"note": "uploaders pending Phase 6"})
                emit("upload", 1.0, "Pipeline complete")

            # --- Done ---
            state.mark_done()
            register_processed(video_id, {
                "url": url,
                "status": "done",
                "platforms": platforms,
            })

            return self._make_result(state, "done")

        except KeyboardInterrupt:
            state.save()
            logger.info(f"Pipeline interrupted for {video_id or url}, state saved")
            return self._make_result(state, "interrupted")

        except Exception as e:
            state.mark_failed(str(e))
            logger.error(f"Pipeline failed for {video_id or url}: {e}")
            return self._make_result(state, "failed", error=str(e))

    async def process_batch(
        self,
        urls: list[str],
        platforms: list[str] | None = None,
        options: dict | None = None,
        progress_callback: Callable[[str, float, str], None] | None = None,
    ) -> list[dict]:
        """Process multiple URLs with concurrency control.

        Args:
            urls: List of Douyin video URLs.
            platforms: Target platforms for all videos.
            options: Shared options (concurrency, force, etc.).
            progress_callback: Optional callback for batch-level progress.

        Returns:
            List of result dicts, one per URL.
        """
        options = options or {}
        concurrency = options.get("concurrency", 3)
        semaphore = asyncio.Semaphore(concurrency)

        results: list[dict] = []
        total = len(urls)

        async def process_one(idx: int, url: str) -> dict:
            async with semaphore:
                if progress_callback:
                    progress_callback("batch", idx / total, f"Processing {idx + 1}/{total}: {url}")
                return await self.process_single(url, platforms, options)

        tasks = [process_one(i, url) for i, url in enumerate(urls)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error dicts
        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append({
                    "url": urls[i],
                    "status": "failed",
                    "error": str(result),
                })
            else:
                processed.append(result)

        # Log summary
        succeeded = sum(1 for r in processed if r.get("status") == "done")
        failed = sum(1 for r in processed if r.get("status") == "failed")
        skipped = sum(1 for r in processed if r.get("status") == "skipped")
        logger.info(
            f"Batch complete: {total} videos — "
            f"succeeded: {succeeded}, failed: {failed}, skipped: {skipped}"
        )

        return processed

    @staticmethod
    def _make_result(state: PipelineState, status: str, error: str | None = None) -> dict:
        """Build a result dict from pipeline state."""
        return {
            "video_id": state.video_id,
            "url": state.url,
            "status": status,
            "completed_stages": list(state.completed_stages),
            "stage_results": dict(state.stage_results),
            "platforms": list(state.platforms),
            "error": error or state.error,
        }
