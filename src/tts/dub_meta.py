"""Per-language dub metadata persistence.

`dub_meta_{lang}.json` captures the parameters of the most recent dub
generation for that language, plus the per-segment texts. Sync-Dub uses
this to: (a) detect which segments changed by comparing current SRT text
against the recorded `segment_texts`, and (b) replay the same provider /
voice / playback-speed / underlay parameters so synthesised cells match
their cached neighbours.

Layout: `{data_dir}/{video_id}/dub_meta_{language}.json`.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class DubMeta:
    video_id: str
    language: str
    provider: str
    voice_id: str
    playback_speed: float
    underlay_db: float
    segment_texts: list[str]


def _meta_path(data_dir: Path, video_id: str, language: str) -> Path:
    return data_dir / video_id / f"dub_meta_{language}.json"


def save_dub_meta(data_dir: Path, meta: DubMeta) -> Path:
    """Write metadata to disk. Creates parent dirs."""
    path = _meta_path(data_dir, meta.video_id, meta.language)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(meta), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load_dub_meta(data_dir: Path, video_id: str, language: str) -> DubMeta | None:
    """Return persisted metadata, or None if it doesn't exist."""
    path = _meta_path(data_dir, video_id, language)
    if not path.exists():
        return None
    blob = json.loads(path.read_text(encoding="utf-8"))
    return DubMeta(**blob)
