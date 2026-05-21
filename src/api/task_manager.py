"""In-memory task store with background execution and SSE support."""

from __future__ import annotations

import asyncio
import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from src.api.models import VideoResponse
from src.utils.logger import setup_logger
from src.utils.metadata import extract_metadata_from_file

logger = setup_logger(__name__)


@dataclass
class Task:
    task_id: str
    task_type: str  # "download" | "transcribe"
    status: str = "queued"  # "queued" | "running" | "completed" | "failed"
    video_id: str | None = None
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    events: list[dict] = field(default_factory=list)


def _build_tts_mix_settings(
    platforms_cfg: dict,
    underlay_db: float | None,
) -> dict:
    """Build per-platform {original_volume, tts_volume} dict.

    If underlay_db is provided (dB scale), it overrides original_volume for
    ALL enabled platforms — the user's explicit preference wins over the
    per-platform YAML defaults. The conversion is: linear = 10 ** (dB / 20).

    When underlay_db is None the per-platform original_volume from
    tts_voices.yaml is used as-is.
    """
    result: dict[str, dict] = {}
    for platform_name, p in platforms_cfg.items():
        if not p.get("enabled", False):
            continue
        if underlay_db is not None:
            original_vol = 10 ** (underlay_db / 20)
        else:
            original_vol = p.get("original_volume", 0.3)
        result[platform_name] = {
            "original_volume": original_vol,
            "tts_volume": p.get("tts_volume", 1.0),
        }
    return result


def _detect_video_status(video_id: str, has_srt: bool, srt_langs: list[str]) -> str:
    """Detect video status from filesystem state."""
    from pathlib import Path
    # Exported?
    if (Path("data/output") / f"{video_id}_export.mp4").exists():
        return "exported"
    # Translated? (has non-Chinese SRT)
    if any(lang != "zh" for lang in srt_langs):
        return "translated"
    # Transcribed?
    if has_srt:
        return "transcribed"
    return "downloaded"


class TaskManager:
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.video_index: dict[str, VideoResponse] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}

    async def scan_existing_videos(self):
        """Scan data/raw/*.mp4 to build the initial video index."""
        raw_dir = Path("data/raw")
        if not raw_dir.exists():
            return

        for mp4 in raw_dir.glob("*.mp4"):
            video_id = mp4.stem
            if video_id in self.video_index:
                continue

            file_meta = extract_metadata_from_file(mp4)
            size_bytes = mp4.stat().st_size
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            srt_dir = Path("data/srt")
            srt_langs = sorted(
                f.stem.split("_")[-1]
                for f in srt_dir.glob(f"{video_id}_*.srt")
            )
            has_srt = len(srt_langs) > 0

            # Load saved metadata (title, author, etc.) if available
            saved_meta: dict = {}
            meta_path = raw_dir / f"{video_id}.json"
            if meta_path.exists():
                try:
                    saved_meta = json.loads(meta_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass

            # Thumbnail: check existing, or generate via ffmpeg
            thumb_path = raw_dir / f"{video_id}_thumb.jpg"
            if not thumb_path.exists():
                try:
                    subprocess.run(
                        [
                            "ffmpeg", "-y", "-i", str(mp4), "-ss", "00:00:01",
                            "-frames:v", "1", "-q:v", "5", str(thumb_path),
                        ],
                        capture_output=True,
                        timeout=10,
                    )
                except (subprocess.SubprocessError, FileNotFoundError):
                    pass  # ffmpeg not available, skip thumbnail

            thumbnail = f"/files/raw/{video_id}_thumb.jpg" if thumb_path.exists() else ""

            self.video_index[video_id] = VideoResponse(
                video_id=video_id,
                title=saved_meta.get("title", video_id),
                author=saved_meta.get("author", ""),
                duration=saved_meta.get("duration", file_meta.get("duration", 0.0)),
                resolution=file_meta.get("resolution", ""),
                size=size_str,
                codec=file_meta.get("codec", ""),
                description=saved_meta.get("description", ""),
                hashtags=saved_meta.get("hashtags", []),
                source_url=saved_meta.get("source_url", ""),
                file_path=str(mp4),
                thumbnail=thumbnail,
                has_srt=has_srt,
                srt_languages=srt_langs,
                status=_detect_video_status(video_id, has_srt, srt_langs),
            )

        logger.info(f"Scanned {len(self.video_index)} existing videos")

    def update_video_title(self, video_id: str, title: str) -> VideoResponse | None:
        """Update a video's title in the index and persist to disk."""
        video = self.video_index.get(video_id)
        if not video:
            return None

        video.title = title
        self.video_index[video_id] = video

        # Persist to metadata JSON
        meta_path = Path("data/raw") / f"{video_id}.json"
        saved: dict = {}
        if meta_path.exists():
            try:
                saved = json.loads(meta_path.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        saved["title"] = title
        meta_path.write_text(json.dumps(saved, ensure_ascii=False))

        return video

    def delete_video(self, video_id: str) -> bool:
        """Delete a video and all associated files."""
        if video_id not in self.video_index:
            return False

        raw_dir = Path("data/raw")
        srt_dir = Path("data/srt")
        proxy_dir = Path("data/proxy")
        output_dir = Path("data/output")

        # Raw files
        for path in [
            raw_dir / f"{video_id}.mp4",
            raw_dir / f"{video_id}.json",
            raw_dir / f"{video_id}_thumb.jpg",
        ]:
            if path.exists():
                path.unlink()

        # All per-video files in srt_dir: SRTs, OCR metadata, export ASS, style, etc.
        for path in srt_dir.glob(f"{video_id}_*"):
            try:
                path.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {path}: {e}")
        for path in srt_dir.glob(f"{video_id}.*"):
            try:
                path.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {path}: {e}")

        # Proxy video
        for proxy in proxy_dir.glob(f"{video_id}*"):
            try:
                proxy.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {proxy}: {e}")

        # Output videos (export + per-platform), plus the lone {video_id}.mp4 form
        for output in output_dir.glob(f"{video_id}_*"):
            try:
                output.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {output}: {e}")
        for output in output_dir.glob(f"{video_id}.*"):
            try:
                output.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {output}: {e}")

        # TTS audio files
        tts_dir = Path("data/tts")
        for tts in tts_dir.glob(f"{video_id}_*"):
            try:
                tts.unlink()
            except OSError as e:
                logger.warning(f"Failed to delete {tts}: {e}")

        # State + duplicate registry
        logs_dir = Path("data/logs")
        state_file = logs_dir / f"{video_id}_state.json"
        if state_file.exists():
            state_file.unlink()

        # Remove from processed_videos.json registry
        registry_path = logs_dir / "processed_videos.json"
        if registry_path.exists():
            try:
                import json
                registry = json.loads(registry_path.read_text())
                if video_id in registry:
                    del registry[video_id]
                    registry_path.write_text(json.dumps(registry, indent=2))
            except Exception:
                pass

        # Remove from index
        del self.video_index[video_id]
        logger.info(f"Deleted video {video_id} and all associated files")
        return True

    def create_task(self, task_type: str) -> Task:
        task = Task(task_id=str(uuid.uuid4()), task_type=task_type)
        self.tasks[task.task_id] = task
        return task

    def _emit(self, task_id: str, event: str, data: dict):
        """Emit an SSE event: append to task log + push to subscribers."""
        entry = {"event": event, "data": data}
        task = self.tasks.get(task_id)
        if task:
            task.events.append(entry)

        for queue in self._subscribers.get(task_id, []):
            queue.put_nowait(entry)

    async def subscribe(self, task_id: str):
        """Async generator that yields SSE events for a task."""
        queue: asyncio.Queue = asyncio.Queue()

        # Replay missed events
        task = self.tasks.get(task_id)
        if task:
            for event in task.events:
                yield event

            # If already done, no need to wait
            if task.status in ("completed", "failed"):
                return

        # Register subscriber
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield event
                    if event["event"] in ("complete", "error"):
                        break
                except asyncio.TimeoutError:
                    # Send keepalive to prevent connection drop, continue waiting
                    yield {"event": "keepalive", "data": {}}
        finally:
            self._subscribers.get(task_id, []).remove(queue) if queue in self._subscribers.get(
                task_id, []
            ) else None

    async def run_download(self, task_id: str, url: str, config: dict):
        """Execute a download task in the background."""
        from src.downloader import download_with_fallback

        task = self.tasks[task_id]
        task.status = "running"
        task.message = "Starting download..."
        self._emit(task_id, "progress", {"progress": 0.0, "message": "Starting download..."})

        try:
            output_dir = Path("data/raw")
            output_dir.mkdir(parents=True, exist_ok=True)

            metadata = await download_with_fallback(url, output_dir, config)
            video_id = metadata.video_id

            # Extract file metadata
            file_path = Path(metadata.file_path)
            file_meta = extract_metadata_from_file(file_path)
            size_bytes = file_path.stat().st_size
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            # Thumbnail
            thumb_path = output_dir / f"{video_id}_thumb.jpg"
            thumbnail = f"/files/raw/{video_id}_thumb.jpg" if thumb_path.exists() else ""

            # Update video index
            video_resp = VideoResponse(
                video_id=video_id,
                title=metadata.title,
                author=metadata.author,
                duration=metadata.duration or file_meta.get("duration", 0.0),
                resolution=metadata.resolution or file_meta.get("resolution", ""),
                size=size_str,
                codec=file_meta.get("codec", ""),
                description=metadata.description,
                hashtags=metadata.hashtags,
                source_url=metadata.source_url,
                file_path=str(file_path),
                thumbnail=thumbnail,
                has_srt=False,
                status="downloaded",
            )
            self.video_index[video_id] = video_resp

            # Persist metadata for reload after restart
            meta_path = output_dir / f"{video_id}.json"
            meta_path.write_text(json.dumps({
                "title": metadata.title,
                "author": metadata.author,
                "duration": metadata.duration,
                "description": metadata.description,
                "hashtags": metadata.hashtags,
                "source_url": metadata.source_url,
            }, ensure_ascii=False))

            task.status = "completed"
            task.video_id = video_id
            task.progress = 1.0
            task.message = "Download complete"
            task.result = video_resp.model_dump()
            self._emit(task_id, "complete", video_resp.model_dump())

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Download failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Download task {task_id} failed: {e}")

    async def run_transcribe(
        self,
        task_id: str,
        video_id: str,
        language: str,
        task_type: str,
        config: dict,
        ocr_region: dict | None = None,
        ocr_config: dict | None = None,
    ):
        """Execute an OCR transcription task in the background."""
        from src.transcriber import get_transcriber

        task = self.tasks[task_id]
        task.status = "running"
        task.video_id = video_id
        task.message = "Initializing OCR engine..."
        self._emit(task_id, "progress", {"progress": 0.0, "message": "Initializing OCR engine..."})

        try:
            video_info = self.video_index.get(video_id)
            if not video_info:
                raise ValueError(f"Video {video_id} not found")

            video_path = video_info.file_path

            # Build progress callback for OCR (thread-safe via call_soon_threadsafe)
            loop = asyncio.get_running_loop()

            def ocr_progress(progress: float, message: str):
                task.progress = progress
                task.message = message
                loop.call_soon_threadsafe(
                    self._emit, task_id, "progress", {"progress": progress, "message": message}
                )

            ocr_cfg = config.get("ocr", {})
            # Merge UI overrides into server config
            if ocr_config:
                ocr_cfg = {**ocr_cfg, **ocr_config}
                if "subtitle_region" in ocr_cfg and "subtitle_region" in ocr_config:
                    ocr_cfg["subtitle_region"] = {
                        **ocr_cfg.get("subtitle_region", {}),
                        **ocr_config["subtitle_region"],
                    }
            transcriber = get_transcriber(
                ocr_cfg,
                ocr_region=ocr_region,
                progress_callback=ocr_progress,
            )

            # Run CPU-bound transcription in a thread
            segments = await asyncio.to_thread(
                transcriber.transcribe, video_path, language, task_type
            )

            task.message = "Generating SRT file..."
            self._emit(
                task_id, "progress", {"progress": 0.9, "message": "Generating SRT file..."}
            )

            # Generate SRT
            srt_dir = Path("data/srt")
            srt_dir.mkdir(parents=True, exist_ok=True)
            lang_suffix = "en" if task_type == "translate" else language
            srt_path = srt_dir / f"{video_id}_{lang_suffix}.srt"
            transcriber.generate_srt(segments, srt_path)

            # Update video index
            video_info.has_srt = True
            if lang_suffix not in video_info.srt_languages:
                video_info.srt_languages.append(lang_suffix)
                video_info.srt_languages.sort()
            video_info.status = "transcribed"
            self.video_index[video_id] = video_info

            task.status = "completed"
            task.progress = 1.0
            task.message = "Transcription complete"
            task.result = {
                "video_id": video_id,
                "srt_path": str(srt_path),
                "segment_count": len(segments),
                "language": lang_suffix,
            }
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Transcription failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Transcribe task {task_id} failed: {e}")

    async def run_translate(
        self, task_id: str, video_id: str, profile_name: str, source_language: str, config: dict
    ):
        """Execute a translation task in the background."""
        from src.translator import translate_with_profile
        from src.translator.profiles import load_profile

        task = self.tasks[task_id]
        task.status = "running"
        task.video_id = video_id
        task.message = "Loading translation profile..."
        self._emit(
            task_id, "progress", {"progress": 0.0, "message": "Loading translation profile..."}
        )

        try:
            video_info = self.video_index.get(video_id)
            if not video_info:
                raise ValueError(f"Video {video_id} not found")

            srt_dir = Path("data/srt")
            srt_path = srt_dir / f"{video_id}_{source_language}.srt"
            if not srt_path.exists():
                raise FileNotFoundError(
                    f"Source SRT not found: {srt_path}. "
                    f"Transcribe the video first with language='{source_language}'."
                )

            profile = load_profile(profile_name)

            # Progress callback bridges LLM batch progress to SSE events
            # batch_num fires before processing, so use (batch_num-1) for accurate %
            def on_progress(batch_num: int, total_batches: int, message: str):
                pct = (batch_num - 1) / total_batches if total_batches else 0.0
                task.progress = pct
                task.message = message
                self._emit(
                    task_id,
                    "progress",
                    {"progress": pct, "message": message},
                )

            output_path = await translate_with_profile(
                srt_path, profile_name, config, srt_dir, progress_callback=on_progress
            )

            # Update video index with new language
            target_lang = profile.target_language
            if target_lang not in video_info.srt_languages:
                video_info.srt_languages.append(target_lang)
                video_info.srt_languages.sort()
            video_info.has_srt = True
            self.video_index[video_id] = video_info

            # Count segments
            from src.processor.subtitle import parse_srt

            segments = parse_srt(output_path)

            # Update video status to translated
            video_info = self.video_index.get(video_id)
            if video_info:
                video_info.status = "translated"
                self.video_index[video_id] = video_info

            task.status = "completed"
            task.progress = 1.0
            task.message = "Translation complete"
            task.result = {
                "video_id": video_id,
                "srt_path": str(output_path),
                "segment_count": len(segments),
                "target_language": target_lang,
                "profile_used": profile_name,
            }
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Translation failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Translate task {task_id} failed: {e}")

    async def run_tts(
        self,
        task_id: str,
        video_id: str,
        language: str,
        voice_profile_name: str,
        provider_override: str | None,
        config: dict,
        voice_override: str | None = None,
        api_key_override: str | None = None,
        llm_api_key: str | None = None,
        llm_backend: str | None = None,
        playback_speed: float | None = None,
    ):
        """Execute a TTS generation task in the background.

        Thin wrapper around `src.tts.runner.run_tts_track`: this handles the
        task-state transitions and SSE emits, but the actual TTS work is the
        same shared function the full pipeline calls.
        """
        from src.tts.runner import run_tts_track

        task = self.tasks[task_id]
        task.status = "running"
        task.video_id = video_id
        task.message = "Loading voice profile..."
        self._emit(task_id, "progress", {"progress": 0.0, "message": "Loading voice profile..."})

        try:
            video_info = self.video_index.get(video_id)
            if not video_info:
                raise ValueError(f"Video {video_id} not found")

            def on_progress(current: int, total: int, message: str):
                pct = current / total if total > 0 else 0.0
                task.progress = pct
                task.message = message
                self._emit(task_id, "progress", {"progress": pct, "message": message})

            result = await run_tts_track(
                video_id=video_id,
                video_path=Path(video_info.file_path),
                language=language,
                voice_profile_name=voice_profile_name,
                config=config,
                canonical_duration=video_info.duration,
                provider_override=provider_override,
                voice_override=voice_override,
                api_key_override=api_key_override,
                llm_api_key=llm_api_key,
                llm_backend=llm_backend,
                playback_speed=playback_speed,
                on_progress=on_progress,
            )

            task.status = "completed"
            task.progress = 1.0
            task.message = "TTS generation complete"
            task.result = {"video_id": video_id, **result}
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"TTS generation failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"TTS task {task_id} failed: {e}")

    async def run_process(
        self,
        task_id: str,
        video_id: str,
        platforms: list[str],
        style_overrides: dict | None,
        subtitle_language_overrides: dict[str, str] | None,
        config: dict,
        enable_tts: bool = False,
        tts_mix_settings: dict[str, dict] | None = None,
        blur_settings: dict | None = None,
        manual_region: dict | None = None,
        underlay_db: float | None = None,
    ):
        """Execute a video processing task in the background."""
        from src.processor import process_for_all_platforms

        task = self.tasks[task_id]
        task.status = "running"
        task.video_id = video_id
        task.message = "Starting video processing..."
        self._emit(
            task_id,
            "progress",
            {"progress": 0.0, "message": "Starting video processing..."},
        )

        try:
            video_info = self.video_index.get(video_id)
            if not video_info:
                raise ValueError(f"Video {video_id} not found")

            video_path = Path(video_info.file_path)
            srt_dir = Path("data/srt")
            output_dir = Path("data/output")
            output_dir.mkdir(parents=True, exist_ok=True)

            # Progress callback for per-platform updates
            def on_progress(platform: str, pct: float, message: str):
                task.progress = pct
                task.message = message
                self._emit(
                    task_id,
                    "progress",
                    {"progress": pct, "message": message, "platform": platform},
                )

            # Build TTS audio paths if TTS is enabled
            tts_audio_paths: dict[str, Path] | None = None
            if enable_tts:
                from src.tts import load_voice_profiles

                tts_dir = Path("data/tts")
                profiles_data = load_voice_profiles(config)
                tts_platforms = profiles_data.get("platforms", {})

                # Build per-platform mix settings from underlay_db (dB→linear)
                # or fall back to per-platform YAML defaults. The caller-supplied
                # tts_mix_settings dict (from ProcessRequest) still wins for any
                # platform it already contains — this only fills missing ones.
                derived_mix = _build_tts_mix_settings(tts_platforms, underlay_db)

                tts_audio_paths = {}
                for platform in platforms:
                    plat_cfg = tts_platforms.get(platform, {})
                    if not plat_cfg.get("enabled", False):
                        continue
                    # Determine language from profile
                    profile_name = plat_cfg.get("profile", "")
                    profile = profiles_data.get("profiles", {}).get(profile_name, {})
                    lang = profile.get("language", "vi")
                    tts_path = tts_dir / f"{video_id}_{lang}.wav"
                    if tts_path.exists():
                        tts_audio_paths[platform] = tts_path

                        # Fill mix settings: caller-supplied wins; derived_mix
                        # (from underlay_db) is the fallback.
                        if tts_mix_settings is None:
                            tts_mix_settings = {}
                        if platform not in tts_mix_settings:
                            tts_mix_settings[platform] = derived_mix.get(
                                platform,
                                {
                                    "original_volume": plat_cfg.get("original_volume", 0.3),
                                    "tts_volume": plat_cfg.get("tts_volume", 1.0),
                                },
                            )

            # Load subtitle region for blur if blur is enabled
            subtitle_region = None
            blur_kwargs: dict | None = None
            if blur_settings and blur_settings.get("enabled", True):
                from src.processor.region_detector import SubtitleRegion, load_subtitle_region

                if manual_region:
                    subtitle_region = SubtitleRegion(
                        x=manual_region["x"], y=manual_region["y"],
                        width=manual_region["width"], height=manual_region["height"],
                    )
                else:
                    subtitle_region = load_subtitle_region(srt_dir, video_id)

                if subtitle_region:
                    blur_kwargs = {
                        "blur_strength": blur_settings.get("strength", 15),
                        "blur_mode": blur_settings.get("mode", "blur"),
                        "fill_color": blur_settings.get("fill_color", "#000000"),
                        "enabled": True,
                        "auto_match_style": blur_settings.get("auto_match_style", True),
                    }

            # Run CPU-bound processing in a thread
            results = await asyncio.to_thread(
                process_for_all_platforms,
                video_id,
                video_path,
                srt_dir,
                output_dir,
                platforms,
                config,
                style_overrides,
                on_progress,
                subtitle_language_overrides,
                tts_audio_paths,
                tts_mix_settings,
                subtitle_region,
                blur_kwargs,
            )

            # Build result data from PlatformResult objects
            outputs = {p: str(r.output_path) for p, r in results.items()}
            subtitle_languages = {p: r.subtitle_language for p, r in results.items()}

            # Update video index
            video_info.status = "processed"
            self.video_index[video_id] = video_info

            task.status = "completed"
            task.progress = 1.0
            task.message = "Processing complete"
            task.result = {
                "video_id": video_id,
                "outputs": outputs,
                "subtitle_languages": subtitle_languages,
            }
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Processing failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Process task {task_id} failed: {e}")

    async def run_pipeline(
        self,
        task_id: str,
        url: str,
        translate_profile: str | None,
        source_language: str,
        config: dict,
    ):
        """Execute download → transcribe → translate pipeline in one task."""
        from src.downloader import download_with_fallback
        from src.transcriber import get_transcriber

        task = self.tasks[task_id]
        task.status = "running"
        task.message = "Starting pipeline..."

        def emit(stage: str, progress: float, message: str):
            task.progress = progress
            task.message = message
            self._emit(
                task_id,
                "progress",
                {"stage": stage, "progress": progress, "message": message},
            )

        try:
            # ── Stage 1: Download (0.00 – 0.30) ──
            emit("download", 0.0, "Starting download...")

            output_dir = Path("data/raw")
            output_dir.mkdir(parents=True, exist_ok=True)

            metadata = await download_with_fallback(url, output_dir, config)
            video_id = metadata.video_id

            # Extract file metadata and register in video index
            file_path = Path(metadata.file_path)
            file_meta = extract_metadata_from_file(file_path)
            size_bytes = file_path.stat().st_size
            size_str = f"{size_bytes / (1024 * 1024):.1f} MB"

            thumb_path = output_dir / f"{video_id}_thumb.jpg"
            thumbnail = f"/files/raw/{video_id}_thumb.jpg" if thumb_path.exists() else ""

            video_resp = VideoResponse(
                video_id=video_id,
                title=metadata.title,
                author=metadata.author,
                duration=metadata.duration or file_meta.get("duration", 0.0),
                resolution=metadata.resolution or file_meta.get("resolution", ""),
                size=size_str,
                codec=file_meta.get("codec", ""),
                description=metadata.description,
                hashtags=metadata.hashtags,
                source_url=metadata.source_url,
                file_path=str(file_path),
                thumbnail=thumbnail,
                has_srt=False,
                status="downloaded",
            )
            self.video_index[video_id] = video_resp
            task.video_id = video_id

            # Persist metadata
            meta_path = output_dir / f"{video_id}.json"
            meta_path.write_text(json.dumps({
                "title": metadata.title,
                "author": metadata.author,
                "duration": metadata.duration,
                "description": metadata.description,
                "hashtags": metadata.hashtags,
                "source_url": metadata.source_url,
            }, ensure_ascii=False))

            emit("download", 0.30, "Download complete")

            # ── Stage 2: Transcribe (0.30 – 0.70) ──
            emit("transcribe", 0.30, "Initializing transcriber...")

            loop = asyncio.get_running_loop()

            def transcribe_progress(progress: float, message: str):
                # Map OCR progress (0-1) to pipeline range (0.30-0.70)
                pct = 0.30 + progress * 0.40
                task.progress = pct
                task.message = message
                loop.call_soon_threadsafe(
                    self._emit, task_id, "progress",
                    {"stage": "transcribe", "progress": pct, "message": message},
                )

            ocr_config = config.get("ocr", {})
            transcriber = get_transcriber(
                ocr_config,
                progress_callback=transcribe_progress,
            )

            video_path = str(file_path)
            segments = await asyncio.to_thread(
                transcriber.transcribe, video_path, source_language, "transcribe"
            )

            # Generate SRT
            srt_dir = Path("data/srt")
            srt_dir.mkdir(parents=True, exist_ok=True)
            srt_path = srt_dir / f"{video_id}_{source_language}.srt"
            transcriber.generate_srt(segments, srt_path)

            # Update video index
            video_resp.has_srt = True
            if source_language not in video_resp.srt_languages:
                video_resp.srt_languages.append(source_language)
                video_resp.srt_languages.sort()
            video_resp.status = "transcribed"
            self.video_index[video_id] = video_resp

            emit("transcribe", 0.70, f"Transcription complete ({len(segments)} segments)")

            # ── Stage 3: Translate (0.70 – 1.00) ──
            if translate_profile:
                from src.translator import translate_with_profile

                emit("translate", 0.70, "Starting translation...")

                def on_translate_progress(batch_num: int, total_batches: int, message: str):
                    pct = 0.70 + ((batch_num - 1) / total_batches * 0.28 if total_batches else 0)
                    task.progress = pct
                    task.message = message
                    self._emit(
                        task_id, "progress",
                        {"stage": "translate", "progress": pct, "message": message},
                    )

                await translate_with_profile(
                    srt_path, translate_profile, config, srt_dir,
                    progress_callback=on_translate_progress,
                )

                # Update video index with translated language
                from src.translator.profiles import load_profile

                profile = load_profile(translate_profile)
                target_lang = profile.target_language
                if target_lang not in video_resp.srt_languages:
                    video_resp.srt_languages.append(target_lang)
                    video_resp.srt_languages.sort()
                self.video_index[video_id] = video_resp

                emit("translate", 0.98, "Translation complete")

            # ── Complete ──
            task.status = "completed"
            task.progress = 1.0
            task.message = "Pipeline complete"
            task.result = {
                "video_id": video_id,
                "video": video_resp.model_dump(),
                "stages_completed": ["download", "transcribe"]
                + (["translate"] if translate_profile else []),
            }
            self._emit(task_id, "complete", task.result)

        except Exception as e:
            task.status = "failed"
            task.error = str(e)
            task.message = f"Pipeline failed: {e}"
            self._emit(task_id, "error", {"message": str(e)})
            logger.error(f"Pipeline task {task_id} failed: {e}")

    def get_stats(self) -> dict:
        """Compute dashboard statistics."""
        total = len(self.video_index)
        today = date.today()

        processed_today = 0
        for vid in self.video_index.values():
            try:
                mtime = Path(vid.file_path).stat().st_mtime
                if datetime.fromtimestamp(mtime).date() == today:
                    processed_today += 1
            except (OSError, ValueError):
                pass

        failed = sum(1 for t in self.tasks.values() if t.status == "failed")
        total_tasks = max(len(self.tasks), 1)
        success_rate = ((total_tasks - failed) / total_tasks) * 100 if self.tasks else 100.0

        active = sum(1 for t in self.tasks.values() if t.status in ("queued", "running"))

        return {
            "totalVideos": total,
            "processedToday": processed_today,
            "successRate": round(success_rate, 1),
            "activeTasks": active,
        }
