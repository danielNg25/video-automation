"""Standalone SRT → Dub IO module.

Pure-IO helpers for the data/standalone_dubs/ directory. Each generated
dub is one {uuid}.wav + one {uuid}.json sidecar with metadata. This
module owns the dataclass shape, the list/delete/path helpers, and the
on-disk schema.

The orchestration that actually runs the assembler lives on
TaskManager.run_standalone_dub — this module is pure IO and stays
FastAPI-free for clean unit testing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

STANDALONE_DIR = Path("data/standalone_dubs")


@dataclass
class StandaloneDubEntry:
    """One generated dub's metadata sidecar."""

    uuid: str
    original_filename: str
    provider: str
    voice: str
    language: str
    playback_speed: float
    enable_shortening: bool
    duration_seconds: float
    created_at: datetime
    file_size_bytes: int


def wav_path(dub_uuid: str) -> Path:
    """Resolve the WAV path for a uuid. Caller must check `.exists()`."""
    return STANDALONE_DIR / f"{dub_uuid}.wav"


def _meta_path(dub_uuid: str) -> Path:
    return STANDALONE_DIR / f"{dub_uuid}.json"


def list_dubs() -> list[StandaloneDubEntry]:
    """Return recent dubs newest-first by created_at.

    Scans every {uuid}.json in STANDALONE_DIR. Skips entries whose
    corresponding .wav file has been deleted out of band — only "complete"
    pairs (.wav + .json both present) are surfaced.
    """
    if not STANDALONE_DIR.exists():
        return []

    entries: list[StandaloneDubEntry] = []
    for json_path in STANDALONE_DIR.glob("*.json"):
        wav = json_path.with_suffix(".wav")
        if not wav.exists():
            continue
        try:
            data = json.loads(json_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        try:
            entries.append(StandaloneDubEntry(
                uuid=data["uuid"],
                original_filename=data["original_filename"],
                provider=data["provider"],
                voice=data["voice"],
                language=data["language"],
                playback_speed=float(data["playback_speed"]),
                enable_shortening=bool(data["enable_shortening"]),
                duration_seconds=float(data["duration_seconds"]),
                created_at=datetime.fromisoformat(data["created_at"]),
                file_size_bytes=int(data["file_size_bytes"]),
            ))
        except (KeyError, ValueError, TypeError):
            # Malformed metadata — skip silently.
            continue

    entries.sort(key=lambda e: e.created_at, reverse=True)
    return entries


def delete_dub(dub_uuid: str) -> bool:
    """Remove both {uuid}.wav and {uuid}.json. Returns True if at least
    one file was removed; False if neither existed."""
    wav = wav_path(dub_uuid)
    meta = _meta_path(dub_uuid)
    deleted_any = False
    if wav.exists():
        wav.unlink()
        deleted_any = True
    if meta.exists():
        meta.unlink()
        deleted_any = True
    return deleted_any


def save_meta(entry: StandaloneDubEntry) -> None:
    """Write the sidecar JSON for an entry."""
    STANDALONE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "uuid": entry.uuid,
        "original_filename": entry.original_filename,
        "provider": entry.provider,
        "voice": entry.voice,
        "language": entry.language,
        "playback_speed": entry.playback_speed,
        "enable_shortening": entry.enable_shortening,
        "duration_seconds": entry.duration_seconds,
        "created_at": entry.created_at.isoformat(),
        "file_size_bytes": entry.file_size_bytes,
    }
    _meta_path(entry.uuid).write_text(json.dumps(payload, indent=2))
