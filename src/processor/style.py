"""Canonical subtitle style schema.

This module is the single source of truth for subtitle styling. All
consumers (FE overlay renderer via TS mirror, ffmpeg renderer via
src/processor/style_render.py, both API routers) receive the same
SubtitleStyleSpec shape.

Storage convention: all spatial fields are PERCENTAGES of canvas dims
(height for vertical fields, width for horizontal). Renderers convert
to pixels against their target canvas. UI sliders show pixels in the
source video's coords for user intuition.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class TextStyle(BaseModel):
    font_name: Literal["Arial", "Roboto", "Impact", "Georgia", "Courier New", "Helvetica"] = "Arial"
    font_size: float = 3.0          # % of canvas height
    color: str = "#FFFFFF"
    bold: bool = True


class PositionStyle(BaseModel):
    alignment: Literal[
        "bottom-left", "bottom-center", "bottom-right",
        "center-left", "center-center", "center-right",
        "top-left",    "top-center",    "top-right",
    ] = "bottom-center"
    margin_v: float = 5.0           # % of canvas height, from anchor edge
    margin_h: float = 0.0           # % of canvas width, offset from anchor center


class OutlineStyle(BaseModel):
    width: float = 0.15             # % of canvas height
    color: str = "#000000"


class ShadowStyle(BaseModel):
    depth: float = 0.05             # % of canvas height; 0 = off
    color: str = "#000000"


class BackgroundStyle(BaseModel):
    shape: Literal["none", "rect", "rounded"] = "none"
    color: str = "#000000"
    opacity: int = Field(default=0, ge=0, le=100)
    radius: float = 0.94            # % of canvas height (only when shape=rounded)
    padding_x: float = 0.83         # % of canvas width
    padding_y: float = 0.5          # % of canvas height


class BlurStyle(BaseModel):
    enabled: bool = False           # OFF by default
    mode: Literal["blur", "pixelate", "fill"] = "blur"
    strength: int = Field(default=15, ge=5, le=30)


class SubtitleStyleSpec(BaseModel):
    text:       TextStyle       = Field(default_factory=TextStyle)
    position:   PositionStyle   = Field(default_factory=PositionStyle)
    outline:    OutlineStyle    = Field(default_factory=OutlineStyle)
    shadow:     ShadowStyle     = Field(default_factory=ShadowStyle)
    background: BackgroundStyle = Field(default_factory=BackgroundStyle)
    blur:       BlurStyle       = Field(default_factory=BlurStyle)


def _deep_merge(base: dict, delta: dict) -> dict:
    """Return a new dict where `delta` recursively overrides `base`.

    Nested dicts merge key-by-key. Scalars and lists in `delta` replace
    those in `base`. Neither input is mutated.
    """
    result = deepcopy(base)
    for key, value in delta.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


# Module-level path constants — overridden in tests via monkeypatch.
_GLOBAL_PATH: Path = Path("config/subtitle_styles.yaml")
_SRT_DIR: Path = Path("data/srt")


def _per_video_path(video_id: str) -> Path:
    return _SRT_DIR / f"{video_id}_style.json"


def load_style(video_id: str | None = None) -> SubtitleStyleSpec:
    """Return the merged spec for a video, or the pure global default.

    Reads `config/subtitle_styles.yaml` as the seed and (when video_id is
    given) deep-merges `data/srt/{video_id}_style.json` on top.
    """
    global_dict: dict = (yaml.safe_load(_GLOBAL_PATH.read_text()) or {}) if _GLOBAL_PATH.exists() else {}
    if video_id is None:
        return SubtitleStyleSpec.model_validate(global_dict)

    per_video = _per_video_path(video_id)
    if not per_video.exists():
        return SubtitleStyleSpec.model_validate(global_dict)

    delta: dict = json.loads(per_video.read_text())
    merged = _deep_merge(global_dict, delta)
    return SubtitleStyleSpec.model_validate(merged)


def save_style_delta(video_id: str, delta: dict) -> None:
    """Replace the per-video file with `delta`.

    The FE computes the diff client-side; this function just persists
    whatever delta the FE sent. Missing fields fall back to global at
    load time.
    """
    path = _per_video_path(video_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(delta, indent=2))


def save_global_default(spec: SubtitleStyleSpec) -> None:
    """Rewrite `config/subtitle_styles.yaml` with the full spec."""
    yaml_text = yaml.safe_dump(
        spec.model_dump(), sort_keys=False, default_flow_style=False,
    )
    _GLOBAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    _GLOBAL_PATH.write_text(yaml_text)
