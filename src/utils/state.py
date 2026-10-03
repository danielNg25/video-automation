"""Pipeline state persistence and duplicate detection.

State files: data/logs/{video_id}_state.json
Registry: data/logs/processed_videos.json
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

LOGS_DIR = Path("data/logs")
REGISTRY_PATH = LOGS_DIR / "processed_videos.json"

STAGES = ("download", "transcribe", "translate", "tts", "process", "upload")


def _atomic_write_json(path: Path, data) -> None:
    """Write JSON to a temp file in the same dir, fsync, then os.replace.

    Replaces the previous truncate-then-write-under-lock pattern, which let a
    concurrent reader observe a half-written (or empty) file. os.replace is
    atomic, so a reader always sees either the old or the new complete file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        # fsync the directory so the rename itself survives a crash — an
        # fsync of the file alone does not persist the new directory entry.
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass  # some platforms/filesystems don't support directory fsync
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


@contextlib.contextmanager
def _file_lock(path: Path):
    """Cross-process exclusive lock via a sidecar ``{path}.lock`` file.

    The lock is taken on a dedicated lock file, never the data file: the atomic
    os.replace swaps the data file's inode, so a lock on the old inode wouldn't
    guard the new one. Holding the sidecar lock across a read-modify-write
    serialises concurrent updaters and prevents lost updates.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / f"{path.name}.lock"
    with open(lock_path, "w") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN)


def _read_json(path: Path, default):
    """Lock-free read; safe because writers publish atomically via rename."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _update_json_transactional(path: Path, mutate: Callable, default):
    """Read-modify-write ``path`` under one exclusive lock.

    ``mutate(current)`` returns the value to persist. Doing the read and the
    write under the same lock means two processes can't both read the old value
    and clobber each other — the lost-update race the previous separate
    lock-per-op code allowed.
    """
    with _file_lock(path):
        current = default
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as read_err:
                # Preserve the unreadable file under a UNIQUE name, then
                # reinitialise. If we can't preserve it, ABORT rather than
                # overwrite — never destroy data we failed to back up.
                backup = path.with_suffix(
                    path.suffix + f".corrupt.{os.getpid()}.{uuid.uuid4().hex}"
                )
                try:
                    path.replace(backup)
                except OSError as move_err:
                    raise OSError(
                        f"Refusing to overwrite unreadable {path}: "
                        f"could not back it up ({move_err})"
                    ) from read_err
                logger.warning(f"Corrupt JSON at {path}; backed up to {backup.name}")
        new_value = mutate(current)
        _atomic_write_json(path, new_value)
        return new_value


@dataclass
class PipelineState:
    """Per-video pipeline state, persisted to JSON for crash recovery."""

    video_id: str
    url: str = ""
    status: str = "pending"  # pending|downloading|transcribing|processing|uploading|done|failed
    current_stage: str = ""  # current pipeline stage name
    progress: float = 0.0  # 0.0–1.0
    message: str = ""  # human-readable progress message
    completed_stages: list[str] = field(default_factory=list)
    stage_results: dict = field(default_factory=dict)
    timestamps: dict = field(default_factory=dict)
    error: str | None = None
    platforms: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def load(cls, video_id: str) -> PipelineState:
        """Load state from disk, or return a fresh state if none exists."""
        state_path = LOGS_DIR / f"{video_id}_state.json"
        data = _read_json(state_path, None)
        if data is None and state_path.exists():
            logger.warning(f"Unreadable state for {video_id}; using fresh state")
        if data is not None:
            try:
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except TypeError as e:
                logger.warning(f"Failed to load state for {video_id}: {e}")
        return cls(video_id=video_id)

    def save(self) -> None:
        """Persist state to disk atomically (temp file + os.replace)."""
        state_path = LOGS_DIR / f"{self.video_id}_state.json"
        self.updated_at = datetime.now(timezone.utc).isoformat()
        _atomic_write_json(state_path, asdict(self))

    def update_progress(self, stage: str, progress: float, message: str) -> None:
        """Update current progress and persist to disk (called frequently during execution)."""
        self.current_stage = stage
        self.progress = progress
        self.message = message
        self.save()

    def mark_stage_complete(self, stage: str, result: dict | None = None) -> None:
        """Mark a stage as complete and save."""
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        if result:
            self.stage_results[stage] = result
        self.timestamps[f"{stage}_end"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def mark_stage_start(self, stage: str) -> None:
        """Record stage start time and update status."""
        status_map = {
            "download": "downloading",
            "transcribe": "transcribing",
            "translate": "transcribing",
            "tts": "processing",
            "process": "processing",
            "upload": "uploading",
        }
        self.status = status_map.get(stage, "processing")
        self.timestamps[f"{stage}_start"] = datetime.now(timezone.utc).isoformat()
        self.save()

    def mark_failed(self, error: str) -> None:
        """Mark pipeline as failed with error message."""
        self.status = "failed"
        self.error = error
        self.message = f"Failed: {error[:100]}"
        self.save()

    def mark_done(self) -> None:
        """Mark pipeline as successfully completed."""
        self.status = "done"
        self.progress = 1.0
        self.message = "Pipeline complete"
        self.error = None
        self.save()

    def get_resume_stage(self) -> str | None:
        """Return the first incomplete stage, or None if all done."""
        for stage in STAGES:
            if stage not in self.completed_stages:
                return stage
        return None

    def is_stage_complete(self, stage: str) -> bool:
        """Check if a specific stage is already complete."""
        return stage in self.completed_stages

    def is_complete(self) -> bool:
        """Check if the pipeline has completed all stages or is marked done."""
        return self.status == "done"


# ---------- Duplicate Detection ----------


def _normalize_url(url: str) -> str:
    """Normalize different Douyin URL formats to a canonical form."""
    # Strip trailing slashes, query params, fragments
    url = url.strip().rstrip("/")
    # Remove tracking params (?xxx)
    url = re.sub(r"\?.*$", "", url)
    return url


def _load_registry() -> dict:
    """Load the processed videos registry (lock-free; writes are atomic)."""
    return _read_json(REGISTRY_PATH, {})


def _save_registry(registry: dict) -> None:
    """Save the processed videos registry atomically."""
    _atomic_write_json(REGISTRY_PATH, registry)


def is_duplicate(video_id: str, url: str | None = None) -> bool:
    """Check if a video has already been processed.

    Checks by video_id first, then by normalized URL if provided.
    """
    registry = _load_registry()

    # Check by video_id
    if video_id in registry:
        return True

    # Check by URL (different URL formats may point to same video)
    if url:
        normalized = _normalize_url(url)
        for entry in registry.values():
            if _normalize_url(entry.get("url", "")) == normalized:
                return True

    return False


def register_processed(video_id: str, result: dict) -> None:
    """Register a video as processed in the global registry.

    Args:
        video_id: The video identifier.
        result: Dict with keys like url, status, platforms, timestamp.
    """
    def mutate(registry: dict) -> dict:
        registry[video_id] = {
            "url": result.get("url", ""),
            "status": result.get("status", "done"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "platforms": result.get("platforms", []),
        }
        return registry

    _update_json_transactional(REGISTRY_PATH, mutate, {})
    logger.info(f"Registered video {video_id} as processed")


def unregister_processed(video_id: str) -> None:
    """Remove a video from the processed registry transactionally.

    Replaces the previous unlocked read→del→write_text in TaskManager.delete_video
    that could lose a concurrent registration or expose a truncated file.
    """

    def mutate(registry: dict) -> dict:
        registry.pop(video_id, None)
        return registry

    _update_json_transactional(REGISTRY_PATH, mutate, {})


def get_all_states() -> list[dict]:
    """Load all pipeline state files for status/history display."""
    states = []
    if not LOGS_DIR.exists():
        return states

    for state_file in LOGS_DIR.glob("*_state.json"):
        data = _read_json(state_file, None)
        if data is not None:
            states.append(data)

    # Sort by updated_at descending
    states.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return states


# ---------- Pipeline Run Log ----------

RUNS_PATH = LOGS_DIR / "pipeline_runs.json"


def _load_runs() -> list[dict]:
    """Load the run log (lock-free; writes are atomic)."""
    return _read_json(RUNS_PATH, [])


def _save_runs(runs: list[dict]) -> None:
    _atomic_write_json(RUNS_PATH, runs)


def create_pipeline_run(
    run_id: str,
    mode: str,
    urls: list[str],
    platforms: list[str],
    video_ids: list[str] | None = None,
) -> dict:
    """Create and persist a new pipeline run entry."""
    run = {
        "run_id": run_id,
        "mode": mode,  # "single" or "batch"
        "urls": urls,
        "platforms": platforms,
        "video_ids": video_ids or [],
        "status": "running",
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    def mutate(runs: list) -> list:
        runs.insert(0, run)
        return runs

    _update_json_transactional(RUNS_PATH, mutate, [])
    return run


def update_pipeline_run(run_id: str, updates: dict) -> None:
    """Update a pipeline run entry by run_id (read-modify-write under lock)."""

    def mutate(runs: list) -> list:
        for run in runs:
            if run.get("run_id") == run_id:
                run.update(updates)
                run["updated_at"] = datetime.now(timezone.utc).isoformat()
                break
        return runs

    _update_json_transactional(RUNS_PATH, mutate, [])


def get_pipeline_runs(limit: int = 50) -> list[dict]:
    """Get pipeline runs, most recent first."""
    runs = _load_runs()
    return runs[:limit]
