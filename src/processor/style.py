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


def load_style(
    video_id: str | None = None,
    source_dims: tuple[int, int] | None = None,
    ocr_region: dict | None = None,
) -> SubtitleStyleSpec:
    """Return the merged spec for a video, or the pure global default.

    Migration of legacy per-video JSONs runs here when the on-disk file
    matches the legacy shape. If `ocr_region` is provided and the
    per-video delta has no `position` override, position is seeded from
    style_matcher.suggest_position(). The seed is in-memory only.
    """
    global_dict: dict = (yaml.safe_load(_GLOBAL_PATH.read_text()) or {}) if _GLOBAL_PATH.exists() else {}
    if video_id is None:
        return SubtitleStyleSpec.model_validate(global_dict)

    per_video = _per_video_path(video_id)
    delta: dict = {}
    if per_video.exists():
        delta = json.loads(per_video.read_text())
        if source_dims is not None:
            migrated = _migrate_if_legacy(delta, source_dims[0], source_dims[1])
        else:
            migrated = _migrate_if_legacy(delta, source_w=1080, source_h=1920)
        if migrated is not delta:
            # Rewrite on disk so this only runs once.
            per_video.write_text(json.dumps(migrated, indent=2))
            delta = migrated

    merged = _deep_merge(global_dict, delta)

    # Seed position from OCR region when no manual override is present.
    if ocr_region is not None and source_dims is not None and "position" not in delta:
        from src.processor.style_matcher import SubtitleStyleMatcher
        matcher = SubtitleStyleMatcher()
        seed = matcher.suggest_position(
            ocr_region,
            video_width=source_dims[0], video_height=source_dims[1],
            output_width=source_dims[0], output_height=source_dims[1],
        )
        merged["position"] = seed.model_dump()

    return SubtitleStyleSpec.model_validate(merged)


# Legacy snake_case → (new group, new key, scaling reference).
# scaling reference: "h" → divide by source_h * 100, "w" → divide by source_w * 100,
# "none" → pass scalar through.
_LEGACY_FIELD_MAP: dict[str, tuple[str, str, str]] = {
    "font_name":          ("text",       "font_name",   "none"),
    "font_size":          ("text",       "font_size",   "h"),
    "color":              ("text",       "color",       "none"),
    "primary_color":      ("text",       "color",       "none"),
    "bold":               ("text",       "bold",        "none"),
    "alignment":          ("position",   "alignment",   "none"),
    "margin_v":           ("position",   "margin_v",    "h"),
    "margin_h":           ("position",   "margin_h",    "w"),
    "outline_width":      ("outline",    "width",       "h"),
    "outline_color":      ("outline",    "color",       "none"),
    "shadow_depth":       ("shadow",     "depth",       "h"),
    "shadow_color":       ("shadow",     "color",       "none"),
    "background_color":   ("background", "color",       "none"),
    "background_opacity": ("background", "opacity",     "none"),
    "blur_enabled":       ("blur",       "enabled",     "none"),
    "blur_mode":          ("blur",       "mode",        "none"),
    "blur_strength":      ("blur",       "strength",    "none"),
}

_NEW_GROUPS = {"text", "position", "outline", "shadow", "background", "blur"}


def _migrate_if_legacy(delta: dict, source_w: int, source_h: int) -> dict:
    """Convert a flat px-based per-video JSON to nested percent-based shape.

    A delta is "legacy" if any top-level key is in the legacy map and not
    in the new group names. New-shape deltas are returned unchanged.

    The opacity-only legacy case (background_opacity > 0 but no
    background_color) means "yes, render a background" — map that to
    shape="rounded" (the current export behavior) so the visual output
    is preserved across the migration.
    """
    has_legacy = any(k in _LEGACY_FIELD_MAP for k in delta.keys())
    has_new_groups = any(k in _NEW_GROUPS for k in delta.keys())
    if has_new_groups or not has_legacy:
        return delta  # already new shape (or empty)

    out: dict = {}
    for key, raw in delta.items():
        if key not in _LEGACY_FIELD_MAP:
            continue  # ignore unknown legacy keys
        group, new_key, scale = _LEGACY_FIELD_MAP[key]
        if scale == "h":
            value = raw * 100 / source_h
        elif scale == "w":
            value = raw * 100 / source_w
        else:
            value = raw
        out.setdefault(group, {})[new_key] = value

    # Legacy "background_opacity > 0" implies the user wanted a bg drawn.
    # The old codebase rendered it via the rounded-rect PNG overlay.
    if "background" in out and out["background"].get("opacity", 0) > 0:
        out["background"].setdefault("shape", "rounded")
    elif "background" in out:
        out["background"].setdefault("shape", "none")

    return out


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
