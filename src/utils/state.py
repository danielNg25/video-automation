"""Pipeline state persistence and duplicate detection.

State files: data/logs/{video_id}_state.json
Registry: data/logs/processed_videos.json
"""

from __future__ import annotations

import fcntl
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

LOGS_DIR = Path("data/logs")
REGISTRY_PATH = LOGS_DIR / "processed_videos.json"

STAGES = ("download", "transcribe", "translate", "tts", "process", "upload")


@dataclass
class PipelineState:
    """Per-video pipeline state, persisted to JSON for crash recovery."""

    video_id: str
    url: str = ""
    status: str = "pending"  # pending|downloading|transcribing|processing|uploading|done|failed
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
        if state_path.exists():
            try:
                with open(state_path) as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    data = json.load(f)
                    fcntl.flock(f, fcntl.LOCK_UN)
                return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logger.warning(f"Failed to load state for {video_id}: {e}")
        return cls(video_id=video_id)

    def save(self) -> None:
        """Persist state to disk with file locking."""
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        state_path = LOGS_DIR / f"{self.video_id}_state.json"
        self.updated_at = datetime.now(timezone.utc).isoformat()

        data = json.dumps(asdict(self), ensure_ascii=False, indent=2)
        with open(state_path, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.write(data)
            fcntl.flock(f, fcntl.LOCK_UN)

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
        self.save()

    def mark_done(self) -> None:
        """Mark pipeline as successfully completed."""
        self.status = "done"
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
    """Load the processed videos registry."""
    if REGISTRY_PATH.exists():
        try:
            with open(REGISTRY_PATH) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                data = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            return data
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_registry(registry: dict) -> None:
    """Save the processed videos registry."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(REGISTRY_PATH, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        json.dump(registry, f, ensure_ascii=False, indent=2)
        fcntl.flock(f, fcntl.LOCK_UN)


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
    registry = _load_registry()
    registry[video_id] = {
        "url": result.get("url", ""),
        "status": result.get("status", "done"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "platforms": result.get("platforms", []),
    }
    _save_registry(registry)
    logger.info(f"Registered video {video_id} as processed")


def get_all_states() -> list[dict]:
    """Load all pipeline state files for status/history display."""
    states = []
    if not LOGS_DIR.exists():
        return states

    for state_file in LOGS_DIR.glob("*_state.json"):
        try:
            with open(state_file) as f:
                data = json.load(f)
            states.append(data)
        except (json.JSONDecodeError, OSError):
            continue

    # Sort by updated_at descending
    states.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return states
