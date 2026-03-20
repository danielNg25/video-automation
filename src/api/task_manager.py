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
                status="transcribed" if has_srt else "downloaded",
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
        """Delete a video and all associated files (MP4, JSON, SRTs)."""
        if video_id not in self.video_index:
            return False

        # Delete files
        raw_dir = Path("data/raw")
        srt_dir = Path("data/srt")

        for path in [
            raw_dir / f"{video_id}.mp4",
            raw_dir / f"{video_id}.json",
            raw_dir / f"{video_id}_thumb.jpg",
        ]:
            if path.exists():
                path.unlink()

        for srt in srt_dir.glob(f"{video_id}_*.srt"):
            srt.unlink()

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
                event = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield event
                if event["event"] in ("complete", "error"):
                    break
        except asyncio.TimeoutError:
            # Send keepalive, then stop
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
        self, task_id: str, video_id: str, language: str, task_type: str, config: dict
    ):
        """Execute a transcription task in the background."""
        from src.transcriber import get_transcriber

        task = self.tasks[task_id]
        task.status = "running"
        task.video_id = video_id
        task.message = "Loading transcription model..."
        self._emit(
            task_id, "progress", {"progress": 0.0, "message": "Loading transcription model..."}
        )

        try:
            video_info = self.video_index.get(video_id)
            if not video_info:
                raise ValueError(f"Video {video_id} not found")

            video_path = video_info.file_path
            transcriber = get_transcriber(config.get("whisper", {}))

            task.message = "Transcribing audio..."
            self._emit(
                task_id, "progress", {"progress": 0.2, "message": "Transcribing audio..."}
            )

            # Run CPU-bound transcription in a thread
            segments = await asyncio.to_thread(
                transcriber.transcribe, video_path, language, task_type
            )

            task.message = "Generating SRT file..."
            self._emit(
                task_id, "progress", {"progress": 0.8, "message": "Generating SRT file..."}
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

    async def run_process(
        self,
        task_id: str,
        video_id: str,
        platforms: list[str],
        style_overrides: dict | None,
        subtitle_language_overrides: dict[str, str] | None,
        config: dict,
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
