"""Subtitle version model + on-disk IO.

Versions are immutable snapshots of a (video_id, language) working draft.
The working draft itself is NOT a version — it's the unsuffixed
`{video_id}_{language}.srt` file. Versions live next to it as
`{video_id}_{language}.v{N}.srt` and are indexed in a per-(video, language)
`{video_id}_{language}.versions.json`.

Migration from the legacy dubsync.srt / dub_meta layout lives in
`migration.py`; this module is pure version-set bookkeeping.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel

SRT_DIR = Path("data/srt")
TTS_DIR = Path("data/tts")
_VERSION_ID_RE = re.compile(r"^v(\d+)$")


class VersionEntry(BaseModel):
    """One immutable snapshot of a (video, language) working draft."""

    id: str
    name: str | None
    created_at: datetime


def _versions_path(video_id: str, language: str) -> Path:
    return SRT_DIR / f"{video_id}_{language}.versions.json"


def load_versions(video_id: str, language: str) -> list[VersionEntry]:
    """Return snapshots in their stored order (= insertion order, which
    is creation order under normal use), or [] if the file is missing."""
    path = _versions_path(video_id, language)
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    return [VersionEntry(**entry) for entry in raw]


def save_versions(
    video_id: str, language: str, entries: list[VersionEntry]
) -> None:
    """Write the entries to disk. Caller is responsible for ordering."""
    path = _versions_path(video_id, language)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": e.id,
            "name": e.name,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
    path.write_text(json.dumps(payload, indent=2))


def next_version_id(existing: list[VersionEntry]) -> str:
    """Return the next id of the form 'v{N}'.

    N is one more than the highest existing N (gaps are tolerated; we
    never reuse ids). When no entries match the `v{N}` pattern, returns
    `v1`.
    """
    max_n = 0
    for entry in existing:
        m = _VERSION_ID_RE.match(entry.id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"v{max_n + 1}"


def snapshot_working_draft(
    video_id: str, language: str, name: str | None = None
) -> VersionEntry:
    """Copy the current working-draft SRT to a new snapshot path and append
    an entry to versions.json. Raises FileNotFoundError if the working
    draft doesn't exist (caller should ensure_migrated first)."""
    working_draft = SRT_DIR / f"{video_id}_{language}.srt"
    if not working_draft.exists():
        raise FileNotFoundError(
            f"Working draft missing for {video_id}/{language}: {working_draft}"
        )
    entries = load_versions(video_id, language)
    new_id = next_version_id(entries)
    snap_path = SRT_DIR / f"{video_id}_{language}.{new_id}.srt"
    shutil.copy2(working_draft, snap_path)
    entry = VersionEntry(
        id=new_id, name=name, created_at=datetime.now(timezone.utc)
    )
    entries.append(entry)
    save_versions(video_id, language, entries)
    return entry


def delete_version(video_id: str, language: str, version_id: str) -> bool:
    """Delete the snapshot SRT and any dub WAVs for that version. Removes
    the entry from versions.json. Returns False if the version_id isn't in
    the list."""
    entries = load_versions(video_id, language)
    found = next((e for e in entries if e.id == version_id), None)
    if found is None:
        return False
    # Delete SRT.
    snap_path = SRT_DIR / f"{video_id}_{language}.{version_id}.srt"
    if snap_path.exists():
        snap_path.unlink()
    # Delete every dub WAV that names this version.
    for wav in TTS_DIR.glob(
        f"{video_id}_{language}_{version_id}_*.wav"
    ):
        wav.unlink()
    # Drop from versions.json.
    save_versions(
        video_id, language, [e for e in entries if e.id != version_id]
    )
    return True
