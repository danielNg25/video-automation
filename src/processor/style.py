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

from copy import deepcopy
from typing import Literal

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
