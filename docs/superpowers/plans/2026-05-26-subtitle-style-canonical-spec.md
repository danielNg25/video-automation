# Subtitle Style — Canonical Spec & Unified Renderers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate three parallel subtitle-rendering paths (HTML overlay, libass `force_style`, ASS+PNG export) and the inconsistent persistence model behind a single `SubtitleStyleSpec` so every field the user sets in the editor flows through save → load → export with the same value, at any resolution.

**Architecture:** New `src/processor/style.py` owns the Pydantic schema, deep-merge loader, and legacy-JSON migration. New `src/processor/style_render.py` owns the ffmpeg-side renderer (ASS file + PNG overlays from one spec). The editor's HTML preview gets a parallel TS-side `specToOverlay()`. Per-video files store only the user's *delta* over `config/subtitle_styles.yaml`. `style_matcher` is narrowed from "force-override" to "one-shot OCR position seed."

**Tech Stack:** Python 3.11 + Pydantic 2.12, FastAPI, ffmpeg + libass, PIL, React 19 + TypeScript, Tailwind CSS, Vite, pytest, Vitest.

**Reference spec:** [docs/superpowers/specs/2026-05-26-subtitle-style-canonical-spec-design.md](../specs/2026-05-26-subtitle-style-canonical-spec-design.md)

---

## File layout

**New:**
- `src/processor/style.py` — `SubtitleStyleSpec` (nested Pydantic), `load_style`, `save_style_delta`, `save_global_default`, `_deep_merge`, `_migrate_if_legacy`.
- `src/processor/style_render.py` — `render_for_ffmpeg`, `_write_ass`, `_render_bg_pngs`, `_pct_to_px`, color converters.
- `ui-app/src/components/editor/SubtitleRenderer.tsx` — replaces `SubtitleOverlay.tsx`.
- `tests/test_style_spec.py`, `tests/test_style_render.py`, `tests/test_export_style.py` *(integration)*.
- `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx`.

**Modified:**
- `src/processor/style_matcher.py` — `match_style` renamed `suggest_position`, narrows return.
- `src/api/routers/process.py` — `_load_subtitle_style` deletes; `_run_export_ffmpeg` calls `render_for_ffmpeg`; `/api/subtitle-styles` endpoints take/return `SubtitleStyleSpec`.
- `src/api/routers/editor.py` — `_load_video_style` deletes; `preview_frame` + `preview_clip` call `render_for_ffmpeg`; style endpoints return `SubtitleStyleSpec`.
- `src/processor/subtitle.py` — `srt_to_ass` and `generate_subtitle_background_images` delete (moved to `style_render.py`). `parse_srt`, `select_subtitle_for_platform`, `merge_subtitles`, etc. stay.
- `src/processor/ffmpeg.py` — `_build_style_string` deletes.
- `config/subtitle_styles.yaml` — rewritten as full `SubtitleStyleSpec`.
- `ui-app/src/components/editor/StylePanel.tsx` — reorganized around schema nesting; new color pickers + alignment grid; blur lives in spec.
- `ui-app/src/pages/videoDetail/EditorTab.tsx` — new `globalDefault` / `savedSpec` / `draftSpec` state model; `diffSpec` for delta save.
- `ui-app/src/api/client.ts`, `ui-app/src/api/types.ts` — `SubtitleStyleSpec` TS types and updated endpoint signatures.
- `Dockerfile` — adds font packages.

---

## Phase 1: Schema, loader, migration (BE foundation)

### Task 1: `SubtitleStyleSpec` Pydantic models

**Files:**
- Create: `src/processor/style.py`
- Test: `tests/test_style_spec.py`

- [ ] **Step 1: Write failing tests for the schema**

Create `tests/test_style_spec.py`:

```python
"""Tests for the canonical SubtitleStyleSpec.

The spec is the single source of truth consumed by both the FE overlay
renderer and the ffmpeg renderer. Round-trip + default semantics are the
contract; renderers depend on every field being present after load.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestSubtitleStyleSpec:
    def test_default_spec_constructs(self):
        from src.processor.style import SubtitleStyleSpec
        spec = SubtitleStyleSpec()
        assert spec.text.font_name == "Arial"
        assert spec.text.font_size == 3.0
        assert spec.text.color == "#FFFFFF"
        assert spec.text.bold is True
        assert spec.position.alignment == "bottom-center"
        assert spec.position.margin_v == 5.0
        assert spec.position.margin_h == 0.0
        assert spec.outline.width == 0.15
        assert spec.outline.color == "#000000"
        assert spec.shadow.depth == 0.05
        assert spec.shadow.color == "#000000"
        assert spec.background.shape == "none"
        assert spec.background.opacity == 0
        assert spec.blur.enabled is False  # off by default per design
        assert spec.blur.mode == "blur"
        assert spec.blur.strength == 15

    def test_partial_init_uses_defaults(self):
        from src.processor.style import SubtitleStyleSpec
        spec = SubtitleStyleSpec.model_validate({"text": {"font_size": 5.0}})
        assert spec.text.font_size == 5.0
        assert spec.text.font_name == "Arial"  # default
        assert spec.position.alignment == "bottom-center"  # default group

    def test_json_round_trip(self):
        from src.processor.style import SubtitleStyleSpec
        original = SubtitleStyleSpec()
        original.background.shape = "rounded"
        original.background.color = "#FFFF00"
        original.background.opacity = 90
        dumped = original.model_dump()
        revived = SubtitleStyleSpec.model_validate(dumped)
        assert revived == original

    def test_invalid_font_name_rejected(self):
        from src.processor.style import SubtitleStyleSpec
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"text": {"font_name": "Comic Sans MS"}})

    def test_invalid_alignment_rejected(self):
        from src.processor.style import SubtitleStyleSpec
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"position": {"alignment": "diagonal"}})

    def test_invalid_shape_rejected(self):
        from src.processor.style import SubtitleStyleSpec
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"background": {"shape": "blob"}})

    def test_opacity_clamped_0_100(self):
        from src.processor.style import SubtitleStyleSpec
        # 0 and 100 OK
        SubtitleStyleSpec.model_validate({"background": {"opacity": 0}})
        SubtitleStyleSpec.model_validate({"background": {"opacity": 100}})
        # Out of range rejected
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"background": {"opacity": 150}})
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"background": {"opacity": -1}})
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_spec.py::TestSubtitleStyleSpec -v`
Expected: All 7 tests FAIL with `ImportError: cannot import name 'SubtitleStyleSpec'`.

- [ ] **Step 3: Implement the schema**

Create `src/processor/style.py`:

```python
"""Canonical subtitle style schema, loader, and persistence helpers.

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
```

- [ ] **Step 4: Run to verify tests pass**

Run: `python -m pytest tests/test_style_spec.py::TestSubtitleStyleSpec -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/processor/style.py tests/test_style_spec.py
git commit -m "feat(style): add SubtitleStyleSpec canonical schema"
```

---

### Task 2: `_deep_merge` helper

**Files:**
- Modify: `src/processor/style.py`
- Test: `tests/test_style_spec.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_style_spec.py`:

```python
class TestDeepMerge:
    def test_merge_disjoint_keys(self):
        from src.processor.style import _deep_merge
        base = {"a": 1, "b": 2}
        delta = {"c": 3}
        assert _deep_merge(base, delta) == {"a": 1, "b": 2, "c": 3}

    def test_delta_overwrites_scalar(self):
        from src.processor.style import _deep_merge
        base = {"a": 1, "b": 2}
        delta = {"b": 99}
        assert _deep_merge(base, delta) == {"a": 1, "b": 99}

    def test_nested_dicts_merge(self):
        from src.processor.style import _deep_merge
        base = {"text": {"font_size": 3.0, "color": "#FFFFFF", "bold": True}}
        delta = {"text": {"color": "#FFFF00"}}
        assert _deep_merge(base, delta) == {
            "text": {"font_size": 3.0, "color": "#FFFF00", "bold": True}
        }

    def test_two_level_nesting(self):
        from src.processor.style import _deep_merge
        base = {
            "text": {"font_size": 3.0},
            "background": {"shape": "none", "color": "#000000"},
        }
        delta = {"background": {"color": "#FFFF00"}}
        assert _deep_merge(base, delta) == {
            "text": {"font_size": 3.0},
            "background": {"shape": "none", "color": "#FFFF00"},
        }

    def test_delta_does_not_mutate_base(self):
        from src.processor.style import _deep_merge
        base = {"a": {"b": 1}}
        delta = {"a": {"b": 2}}
        _deep_merge(base, delta)
        assert base == {"a": {"b": 1}}  # base unchanged
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_spec.py::TestDeepMerge -v`
Expected: 5 FAIL with `ImportError: cannot import name '_deep_merge'`.

- [ ] **Step 3: Add the helper**

Append to `src/processor/style.py`:

```python
from copy import deepcopy


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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_style_spec.py::TestDeepMerge -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/processor/style.py tests/test_style_spec.py
git commit -m "feat(style): add _deep_merge helper for delta over global"
```

---

### Task 3: `load_style`, `save_style_delta`, `save_global_default`

**Files:**
- Modify: `src/processor/style.py`
- Test: `tests/test_style_spec.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_style_spec.py`:

```python
class TestLoadStyle:
    def _write_global(self, tmp_path, monkeypatch, content: dict):
        import yaml
        path = tmp_path / "subtitle_styles.yaml"
        path.write_text(yaml.safe_dump(content))
        monkeypatch.setattr("src.processor.style._GLOBAL_PATH", path)
        return path

    def _write_per_video(self, tmp_path, monkeypatch, video_id: str, content: dict):
        import json
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir(exist_ok=True)
        path = srt_dir / f"{video_id}_style.json"
        path.write_text(json.dumps(content))
        monkeypatch.setattr("src.processor.style._SRT_DIR", srt_dir)
        return path

    def test_load_returns_global_when_no_video_id(self, tmp_path, monkeypatch):
        from src.processor.style import load_style
        self._write_global(tmp_path, monkeypatch, {
            "text": {"font_size": 4.0},
            "background": {"shape": "rect"},
        })
        # _SRT_DIR must be set even when not used
        monkeypatch.setattr("src.processor.style._SRT_DIR", tmp_path / "srt")
        spec = load_style()
        assert spec.text.font_size == 4.0
        assert spec.background.shape == "rect"
        assert spec.text.color == "#FFFFFF"  # default fills in

    def test_load_returns_global_when_no_per_video_file(self, tmp_path, monkeypatch):
        from src.processor.style import load_style
        self._write_global(tmp_path, monkeypatch, {"text": {"font_size": 4.0}})
        monkeypatch.setattr("src.processor.style._SRT_DIR", tmp_path / "srt")
        (tmp_path / "srt").mkdir()
        spec = load_style("video123")
        assert spec.text.font_size == 4.0

    def test_per_video_delta_merges_over_global(self, tmp_path, monkeypatch):
        from src.processor.style import load_style
        self._write_global(tmp_path, monkeypatch, {
            "text": {"font_size": 4.0, "color": "#FFFFFF"},
            "background": {"shape": "none"},
        })
        self._write_per_video(tmp_path, monkeypatch, "video123", {
            "background": {"shape": "rounded", "color": "#FFFF00"},
        })
        spec = load_style("video123")
        assert spec.text.font_size == 4.0       # from global
        assert spec.text.color == "#FFFFFF"     # from global
        assert spec.background.shape == "rounded"  # from delta
        assert spec.background.color == "#FFFF00"  # from delta

    def test_save_delta_writes_partial_json(self, tmp_path, monkeypatch):
        import json
        from src.processor.style import save_style_delta
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.processor.style._SRT_DIR", srt_dir)
        save_style_delta("video123", {"background": {"color": "#FFFF00"}})
        path = srt_dir / "video123_style.json"
        assert path.exists()
        assert json.loads(path.read_text()) == {"background": {"color": "#FFFF00"}}

    def test_save_global_default_writes_yaml(self, tmp_path, monkeypatch):
        import yaml
        from src.processor.style import save_global_default, SubtitleStyleSpec
        path = tmp_path / "subtitle_styles.yaml"
        monkeypatch.setattr("src.processor.style._GLOBAL_PATH", path)
        spec = SubtitleStyleSpec()
        spec.text.font_size = 5.5
        save_global_default(spec)
        assert path.exists()
        loaded = yaml.safe_load(path.read_text())
        assert loaded["text"]["font_size"] == 5.5
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_spec.py::TestLoadStyle -v`
Expected: 5 FAIL with import errors.

- [ ] **Step 3: Implement the loader/saver**

Append to `src/processor/style.py`:

```python
import json
from pathlib import Path

import yaml

# Defaults — overridden in tests via monkeypatch. Module-level so the
# whole module sees the same paths after a test patches them.
_GLOBAL_PATH: Path = Path("config/subtitle_styles.yaml")
_SRT_DIR: Path = Path("data/srt")


def _per_video_path(video_id: str) -> Path:
    return _SRT_DIR / f"{video_id}_style.json"


def load_style(video_id: str | None = None) -> SubtitleStyleSpec:
    """Return the merged spec for a video, or the pure global default.

    Reads `config/subtitle_styles.yaml` as the seed and (when video_id is
    given) deep-merges `data/srt/{video_id}_style.json` on top.
    """
    global_dict: dict = yaml.safe_load(_GLOBAL_PATH.read_text()) if _GLOBAL_PATH.exists() else {}
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_style_spec.py::TestLoadStyle -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/processor/style.py tests/test_style_spec.py
git commit -m "feat(style): add load_style + save_style_delta + save_global_default"
```

---

### Task 4: Legacy migration `_migrate_if_legacy`

**Files:**
- Modify: `src/processor/style.py`
- Test: `tests/test_style_spec.py`

Context: existing per-video JSONs look like `{"font_size": 37, "margin_v": 393, "background_opacity": 90, "bold": true, ...}` — flat snake_case keys with pixel values. The migrator converts to the new nested shape with percentage values, using the source video's height/width as the conversion base.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_style_spec.py`:

```python
class TestMigrateIfLegacy:
    def test_new_shape_passes_through_unchanged(self):
        from src.processor.style import _migrate_if_legacy
        delta = {"text": {"font_size": 3.0}, "background": {"color": "#FFFF00"}}
        # Source dims irrelevant for already-new shape
        result = _migrate_if_legacy(delta, source_w=720, source_h=1280)
        assert result == delta

    def test_legacy_flat_px_to_nested_pct(self):
        from src.processor.style import _migrate_if_legacy
        legacy = {
            "font_name": "Arial",
            "font_size": 37,                  # px → pct of 1280
            "outline_width": 2,
            "margin_v": 393,                  # px → pct of 1280
            "margin_h": 0,
            "bold": True,
            "shadow_depth": 1,
            "background_color": "#FFFF00",
            "background_opacity": 90,
        }
        out = _migrate_if_legacy(legacy, source_w=720, source_h=1280)
        # Nested shape, percentages
        assert out["text"]["font_name"] == "Arial"
        assert out["text"]["font_size"] == pytest.approx(37 * 100 / 1280, abs=0.01)
        assert out["text"]["bold"] is True
        assert out["position"]["margin_v"] == pytest.approx(393 * 100 / 1280, abs=0.01)
        assert out["position"]["margin_h"] == 0
        assert out["outline"]["width"] == pytest.approx(2 * 100 / 1280, abs=0.01)
        assert out["shadow"]["depth"] == pytest.approx(1 * 100 / 1280, abs=0.01)
        assert out["background"]["color"] == "#FFFF00"
        assert out["background"]["opacity"] == 90
        # Legacy bg with opacity > 0 means "yes, render the bg" — set shape
        assert out["background"]["shape"] == "rounded"

    def test_legacy_no_bg_color_keeps_shape_none(self):
        from src.processor.style import _migrate_if_legacy
        legacy = {"font_size": 24, "background_opacity": 0}
        out = _migrate_if_legacy(legacy, source_w=720, source_h=1280)
        # opacity 0 → no background
        assert out["background"]["shape"] == "none"

    def test_partial_legacy_only_migrates_present_fields(self):
        from src.processor.style import _migrate_if_legacy
        legacy = {"font_size": 30}  # only one field
        out = _migrate_if_legacy(legacy, source_w=720, source_h=1280)
        assert "text" in out
        assert out["text"]["font_size"] == pytest.approx(30 * 100 / 1280, abs=0.01)
        assert "position" not in out  # margin_v not in legacy → don't fabricate
        assert "outline" not in out
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_spec.py::TestMigrateIfLegacy -v`
Expected: 4 FAIL with import errors.

- [ ] **Step 3: Implement the migrator**

Append to `src/processor/style.py`:

```python
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
```

Update `load_style` to call the migrator (and persist the migration so it only runs once):

```python
def load_style(video_id: str | None = None, source_dims: tuple[int, int] | None = None) -> SubtitleStyleSpec:
    """Return the merged spec for a video, or the pure global default.

    If a per-video JSON exists in the legacy flat-px shape, it's migrated
    to the new nested percent shape and rewritten to disk. `source_dims`
    is `(width, height)` of the source video and is required for migration
    of legacy files. Pass None if you don't have it (the migrator will
    fall back to 1080x1920 — best-effort).
    """
    global_dict: dict = yaml.safe_load(_GLOBAL_PATH.read_text()) if _GLOBAL_PATH.exists() else {}
    if video_id is None:
        return SubtitleStyleSpec.model_validate(global_dict)

    per_video = _per_video_path(video_id)
    if not per_video.exists():
        return SubtitleStyleSpec.model_validate(global_dict)

    delta: dict = json.loads(per_video.read_text())
    if source_dims is not None:
        migrated = _migrate_if_legacy(delta, source_dims[0], source_dims[1])
    else:
        migrated = _migrate_if_legacy(delta, source_w=1080, source_h=1920)
    if migrated is not delta:
        # Rewrite on disk so this only runs once.
        per_video.write_text(json.dumps(migrated, indent=2))
        delta = migrated

    merged = _deep_merge(global_dict, delta)
    return SubtitleStyleSpec.model_validate(merged)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_style_spec.py -v`
Expected: 21 passed (7 spec + 5 merge + 5 load + 4 migrate).

- [ ] **Step 5: Commit**

```bash
git add src/processor/style.py tests/test_style_spec.py
git commit -m "feat(style): migrate legacy flat-px per-video JSONs to nested percent shape"
```

---

## Phase 2: ffmpeg renderer

### Task 5: `render_for_ffmpeg` + ASS + PNG paths

**Files:**
- Create: `src/processor/style_render.py`
- Test: `tests/test_style_render.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_style_render.py`:

```python
"""Tests for the unified ffmpeg-side renderer.

`render_for_ffmpeg(spec, srt, canvas_w, canvas_h, output_dir)` produces:
- An ASS file with text styled from spec (font, color, outline, bold, position).
- A list of PNG overlay descriptors when background.shape == 'rounded'.
- No PNG list otherwise; the ASS file itself carries any rectangular bg.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def srt_file(tmp_path):
    path = tmp_path / "test.srt"
    path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nHello\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\nWorld\n",
        encoding="utf-8",
    )
    return path


class TestBackgroundShape:
    def test_shape_none_emits_no_box_no_pngs(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "none"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        assert "BorderStyle=3" not in ass_text  # no box in ASS
        assert out.bg_pngs is None

    def test_shape_rect_uses_libass_box(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "rect"
        spec.background.color = "#FFFF00"
        spec.background.opacity = 80
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # libass renders rect bg via BackColour + BorderStyle=3.
        assert "BorderStyle=3" in ass_text
        # Yellow #FFFF00 with 80% opacity → ASS alpha = 255 - 204 = 51 = 0x33,
        # ASS BBGGRR for yellow = 00FFFF; full literal &H3300FFFF.
        assert "&H3300FFFF" in ass_text
        assert out.bg_pngs is None

    def test_shape_rounded_no_libass_box_yes_pngs(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.background.shape = "rounded"
        spec.background.color = "#FFFF00"
        spec.background.opacity = 90
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        assert "BorderStyle=1" in ass_text  # no libass box
        assert out.bg_pngs is not None
        assert len(out.bg_pngs) == 2  # one per segment
        # Each PNG file actually exists on disk.
        for entry in out.bg_pngs:
            assert Path(entry["path"]).exists()


class TestPercentageToPixel:
    def test_margin_v_scales_with_canvas_height(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.position.margin_v = 30.7  # ≈ 393px on 1280-tall
        spec.position.alignment = "bottom-center"
        out = render_for_ffmpeg(spec, srt_file, 720, 1280, tmp_path)
        ass_text = out.ass_path.read_text()
        # 30.7% of 1280 ≈ 393
        assert "MarginV: 393" in ass_text or ",393," in ass_text or "393" in ass_text

    def test_margin_v_at_1920_canvas(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.position.margin_v = 30.7
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # 30.7% of 1920 ≈ 589
        assert "589" in ass_text or "590" in ass_text


class TestColors:
    def test_text_color_to_primary_colour(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.text.color = "#FF0000"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # #FF0000 (red) → ASS PrimaryColour &H000000FF (BGR order)
        assert "&H000000FF" in ass_text

    def test_outline_color_to_outline_colour(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.outline.color = "#00FF00"
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # #00FF00 (green) → ASS OutlineColour &H0000FF00
        assert "&H0000FF00" in ass_text

    def test_bold_emitted(self, srt_file, tmp_path):
        from src.processor.style import SubtitleStyleSpec
        from src.processor.style_render import render_for_ffmpeg
        spec = SubtitleStyleSpec()
        spec.text.bold = True
        out = render_for_ffmpeg(spec, srt_file, 1080, 1920, tmp_path)
        ass_text = out.ass_path.read_text()
        # ASS Bold = -1 (true) or 0 (false) in the Style line
        assert ",-1," in ass_text
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_render.py -v`
Expected: 7 FAIL with `ImportError: cannot import name 'render_for_ffmpeg'`.

- [ ] **Step 3: Implement the renderer**

Create `src/processor/style_render.py`:

```python
"""Unified ffmpeg-side subtitle renderer.

Single entry point `render_for_ffmpeg(spec, srt_path, canvas_w, canvas_h,
output_dir)` produces:
  - An ASS file with text styling baked into the [V4+ Styles] header.
  - When `spec.background.shape == "rounded"` and opacity > 0, a list of
    rounded-rectangle PNGs (one per SRT segment) for the ffmpeg overlay
    filter chain.

Replaces the previously split paths: `srt_to_ass` (in subtitle.py),
`generate_subtitle_background_images` (in subtitle.py), and
`FFmpegProcessor._build_style_string` (in ffmpeg.py). All three folded
into this single, spec-driven module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.processor.style import SubtitleStyleSpec
from src.processor.subtitle import _seconds_to_ass_timestamp, parse_srt
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class RenderArtifacts:
    ass_path: Path
    bg_pngs: list[dict[str, Any]] | None  # each entry: {path, start, end, x, y}


# ── ASS alignment numeric code per spec.position.alignment ──

_ALIGNMENT_TO_ASS = {
    "bottom-left":   1, "bottom-center": 2, "bottom-right":  3,
    "center-left":   4, "center-center": 5, "center-right":  6,
    "top-left":      7, "top-center":    8, "top-right":     9,
}


def render_for_ffmpeg(
    spec: SubtitleStyleSpec,
    srt_path: Path,
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> RenderArtifacts:
    """Produce ASS + (optional) PNG overlays from a single spec."""
    output_dir.mkdir(parents=True, exist_ok=True)
    px = _resolve_px(spec, canvas_w, canvas_h)
    ass_path = _write_ass(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    bg_pngs: list[dict[str, Any]] | None = None
    if spec.background.shape == "rounded" and spec.background.opacity > 0:
        bg_pngs = _render_bg_pngs(srt_path, spec, px, canvas_w, canvas_h, output_dir)
    return RenderArtifacts(ass_path=ass_path, bg_pngs=bg_pngs)


def _resolve_px(spec: SubtitleStyleSpec, w: int, h: int) -> dict[str, int]:
    """Convert all percentage fields to pixel values for this canvas."""
    return {
        "font_size":  max(1, int(round(spec.text.font_size  * h / 100))),
        "margin_v":   max(0, int(round(spec.position.margin_v * h / 100))),
        "margin_h":   int(round(spec.position.margin_h * w / 100)),
        "outline":    max(0, int(round(spec.outline.width * h / 100))),
        "shadow":     max(0, int(round(spec.shadow.depth * h / 100))),
        "radius":     max(0, int(round(spec.background.radius * h / 100))),
        "padding_x":  max(0, int(round(spec.background.padding_x * w / 100))),
        "padding_y":  max(0, int(round(spec.background.padding_y * h / 100))),
    }


def _hex_to_ass_bbggrr(hex_rgb: str, alpha: int = 0) -> str:
    """Convert #RRGGBB to ASS &HAABBGGRR. `alpha` is the ASS alpha byte
    (0 = fully opaque, 255 = fully transparent)."""
    if not (hex_rgb.startswith("#") and len(hex_rgb) == 7):
        # Fall back to opaque black if input is malformed.
        return f"&H{alpha:02X}000000"
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper().replace("&H", "&H")


def _bg_box_colour(spec: SubtitleStyleSpec) -> str:
    """ASS BackColour for shape='rect'. opacity is 0-100 percent."""
    ass_alpha = max(0, 255 - int(spec.background.opacity * 255 / 100))
    return _hex_to_ass_bbggrr(spec.background.color, ass_alpha)


def _write_ass(
    srt_path: Path,
    spec: SubtitleStyleSpec,
    px: dict[str, int],
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> Path:
    """Generate the ASS file with style baked into the [V4+ Styles] header."""
    segments = parse_srt(srt_path)

    primary_colour = _hex_to_ass_bbggrr(spec.text.color, alpha=0)       # opaque
    outline_colour = _hex_to_ass_bbggrr(spec.outline.color, alpha=0)
    bold_flag = -1 if spec.text.bold else 0
    alignment = _ALIGNMENT_TO_ASS[spec.position.alignment]

    if spec.background.shape == "rect":
        back_colour = _bg_box_colour(spec)
        border_style = 3
    else:
        # "none" and "rounded" — no libass-drawn box; PNG path handles rounded.
        back_colour = "&H00000000"
        border_style = 1

    margin_l = max(0, 10 + px["margin_h"])
    margin_r = max(0, 10 - px["margin_h"])

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {canvas_w}\n"
        f"PlayResY: {canvas_h}\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{spec.text.font_name},{px['font_size']},{primary_colour},&H000000FF,"
        f"{outline_colour},{back_colour},{bold_flag},0,0,0,100,100,0,0,{border_style},"
        f"{px['outline']},{px['shadow']},{alignment},{margin_l},{margin_r},{px['margin_v']},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    lines = [header]
    for seg in segments:
        start = _seconds_to_ass_timestamp(seg["start"])
        end = _seconds_to_ass_timestamp(seg["end"])
        text = seg["text"].replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}\n")

    out_path = output_dir / f"{srt_path.stem}.render.ass"
    out_path.write_text("".join(lines), encoding="utf-8")
    logger.info(f"Wrote ASS: {out_path} ({len(segments)} segments)")
    return out_path


def _render_bg_pngs(
    srt_path: Path,
    spec: SubtitleStyleSpec,
    px: dict[str, int],
    canvas_w: int,
    canvas_h: int,
    output_dir: Path,
) -> list[dict[str, Any]] | None:
    """Generate per-segment rounded-rect background PNGs for the overlay
    filter chain. Returns None if Pillow isn't installed (renderers should
    gracefully degrade to no bg)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed — skipping rounded-rect backgrounds")
        return None

    # Parse the background color (#RRGGBB) for PIL.
    bg = spec.background.color
    if bg.startswith("#") and len(bg) == 7:
        r = int(bg[1:3], 16); g = int(bg[3:5], 16); b = int(bg[5:7], 16)
    else:
        r, g, b = 0, 0, 0
    a = int(spec.background.opacity * 255 / 100)

    # Try to load a real font for text-bbox measurement; fall back to PIL default.
    try:
        import platform
        if platform.system() == "Darwin":
            font_path = (
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
                if spec.text.bold
                else "/System/Library/Fonts/Supplemental/Arial.ttf"
            )
        else:
            font_path = (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if spec.text.bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            )
        pil_font = ImageFont.truetype(font_path, px["font_size"])
    except Exception:
        pil_font = ImageFont.load_default()

    segments = parse_srt(srt_path)
    if not segments:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []

    pad_x = max(6, px["padding_x"])
    pad_y = max(4, px["padding_y"])

    for i, seg in enumerate(segments):
        text = seg["text"]
        bbox = pil_font.getbbox(text)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        img_w = text_w + 2 * pad_x
        img_h = text_h + 2 * pad_y

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [(0, 0), (img_w - 1, img_h - 1)],
            radius=max(2, px["radius"]),
            fill=(r, g, b, a),
        )
        png_path = output_dir / f"bg_{i:04d}.png"
        img.save(png_path)

        # Position: anchor decides bottom/top/center base.
        x = (canvas_w - img_w) // 2 + px["margin_h"]
        if spec.position.alignment.startswith("bottom"):
            text_center_y = canvas_h - px["margin_v"] - px["font_size"] // 2
        elif spec.position.alignment.startswith("top"):
            text_center_y = px["margin_v"] + px["font_size"] // 2
        else:
            text_center_y = canvas_h // 2
        y = text_center_y - img_h // 2

        results.append({
            "path": str(png_path),
            "start": seg["start"],
            "end":   seg["end"],
            "x": x,
            "y": y,
        })

    logger.info(f"Wrote {len(results)} bg PNGs to {output_dir}")
    return results
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_style_render.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add src/processor/style_render.py tests/test_style_render.py
git commit -m "feat(style): unified ffmpeg renderer (ASS + PNG overlays from one spec)"
```

---

## Phase 3: BE wiring

### Task 6: Update `config/subtitle_styles.yaml` to new shape

**Files:**
- Modify: `config/subtitle_styles.yaml`

- [ ] **Step 1: Replace the file with the new shape**

Overwrite `config/subtitle_styles.yaml` with:

```yaml
# Global default subtitle style. Per-video overrides at
# data/srt/{video_id}_style.json deep-merge over this.
# All spatial values are PERCENTAGES of canvas dimensions
# (height for vertical fields, width for horizontal).
text:
  font_name: Arial
  font_size: 3.0
  color: '#FFFFFF'
  bold: true
position:
  alignment: bottom-center
  margin_v: 5.0
  margin_h: 0.0
outline:
  width: 0.15
  color: '#000000'
shadow:
  depth: 0.05
  color: '#000000'
background:
  shape: none
  color: '#000000'
  opacity: 0
  radius: 0.94
  padding_x: 0.83
  padding_y: 0.5
blur:
  enabled: false
  mode: blur
  strength: 15
```

- [ ] **Step 2: Verify it parses into a valid spec**

Run:
```bash
python -c "from src.processor.style import load_style; print(load_style())"
```
Expected: prints `text=TextStyle(font_name='Arial', ...) ...` with all defaults.

- [ ] **Step 3: Commit**

```bash
git add config/subtitle_styles.yaml
git commit -m "feat(style): rewrite global default YAML in new SubtitleStyleSpec shape"
```

---

### Task 7: `style_matcher.match_style` → `suggest_position`

**Files:**
- Modify: `src/processor/style_matcher.py`
- Test: `tests/test_style_matcher.py` (existing if any; else create)

Context: today's `match_style` returns a flat dict overriding `{margin_v, ...}` plus other fields. The new contract: takes the same inputs, returns a `PositionStyle` (alignment + margin_v + margin_h) with values in percentages. Same math; narrower output.

- [ ] **Step 1: Inspect the existing function**

Run: `grep -n "def match_style\|def suggest_position" src/processor/style_matcher.py`

Note the current signature and the math that produces `margin_v`. The math stays — we just convert outputs to percentages of the OUTPUT canvas and wrap into `PositionStyle`.

- [ ] **Step 2: Write a failing test**

Add to `tests/test_style_matcher.py` (create if absent):

```python
"""Tests for the OCR-region position seeding helper."""

from __future__ import annotations


class TestSuggestPosition:
    def test_returns_position_style(self):
        from src.processor.style import PositionStyle
        from src.processor.style_matcher import SubtitleStyleMatcher
        matcher = SubtitleStyleMatcher()
        region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        result = matcher.suggest_position(
            region, video_width=1080, video_height=1920,
            output_width=1080, output_height=1920,
        )
        assert isinstance(result, PositionStyle)
        assert result.alignment in {
            "bottom-left", "bottom-center", "bottom-right",
            "center-left", "center-center", "center-right",
            "top-left",    "top-center",    "top-right",
        }
        # margin_v should be a positive percentage when text is near the bottom.
        assert 0 < result.margin_v < 100

    def test_margin_v_is_percentage_of_output_height(self):
        from src.processor.style_matcher import SubtitleStyleMatcher
        matcher = SubtitleStyleMatcher()
        # Region 80px tall centered at y=1000 in a 1920-tall canvas →
        # text center at y=1040 → distance from bottom = 880 → margin_v
        # encoded as (880 - half-text-height) / 1920 * 100 ≈ 44-ish %.
        region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        result = matcher.suggest_position(
            region, video_width=1080, video_height=1920,
            output_width=1080, output_height=1920,
        )
        # Sanity-check we're in the right band — exact value depends on
        # the matcher's math; assert it's near where the region sits.
        # Region top at y=1000, region bottom at y=1080 → margin_v from
        # bottom (alignment=bottom-*) ~ 1920 - 1080 = 840 → 43.75%.
        assert 35 < result.margin_v < 55
```

- [ ] **Step 3: Run to verify it fails**

Run: `python -m pytest tests/test_style_matcher.py::TestSuggestPosition -v`
Expected: FAIL with `AttributeError: 'SubtitleStyleMatcher' object has no attribute 'suggest_position'`.

- [ ] **Step 4: Add `suggest_position` to `SubtitleStyleMatcher`**

In `src/processor/style_matcher.py`, ADD (do not delete `match_style` yet — Task 12 cleanup):

```python
def suggest_position(
    self,
    region: dict,
    video_width: int,
    video_height: int,
    output_width: int,
    output_height: int,
) -> "PositionStyle":
    """Suggest a PositionStyle from the OCR-detected subtitle region.

    Same math as the old match_style, but returns only alignment +
    margin_v + margin_h as percentages of the OUTPUT canvas. The caller
    (load_style) uses this to seed position.* when the user hasn't
    customized it.
    """
    from src.processor.style import PositionStyle

    # Reuse the existing geometry math by calling match_style internally
    # and translating its result into the new shape. The legacy method's
    # returned dict has keys like `margin_v`, `margin_h`, `alignment` in
    # OUTPUT pixel coords; we convert to percentages.
    legacy = self.match_style(
        region, video_width, video_height,
        # match_style signature: (region, src_w, src_h, style, output_width, output_height)
        style={},
        output_width=output_width,
        output_height=output_height,
    )
    return PositionStyle(
        alignment=_ass_alignment_to_str(legacy.get("alignment", 2)),
        margin_v=float(legacy.get("margin_v", 30)) * 100.0 / output_height,
        margin_h=float(legacy.get("margin_h", 0)) * 100.0 / output_width,
    )
```

Add the helper at module level:

```python
def _ass_alignment_to_str(code: int) -> str:
    return {
        1: "bottom-left", 2: "bottom-center", 3: "bottom-right",
        4: "center-left", 5: "center-center", 6: "center-right",
        7: "top-left",    8: "top-center",    9: "top-right",
    }.get(code, "bottom-center")
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_style_matcher.py::TestSuggestPosition -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/processor/style_matcher.py tests/test_style_matcher.py
git commit -m "feat(style): add suggest_position returning PositionStyle in pct"
```

---

### Task 8: Wire `suggest_position` into `load_style`

**Files:**
- Modify: `src/processor/style.py`
- Test: `tests/test_style_spec.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_style_spec.py`:

```python
class TestPositionSeeding:
    """When no per-video position override exists and an OCR region is
    available, load_style auto-seeds position from style_matcher. The
    seed is in-memory only — not persisted."""

    def test_no_seeding_when_position_in_delta(self, tmp_path, monkeypatch):
        import json
        from src.processor.style import load_style
        # Global with no position group
        (tmp_path / "subtitle_styles.yaml").write_text(
            "text:\n  font_size: 4.0\n"
        )
        monkeypatch.setattr("src.processor.style._GLOBAL_PATH",
                            tmp_path / "subtitle_styles.yaml")
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.processor.style._SRT_DIR", srt_dir)
        # Per-video delta sets position.margin_v
        (srt_dir / "vid_style.json").write_text(json.dumps({
            "position": {"margin_v": 12.5}
        }))
        spec = load_style("vid")
        # Manual position wins; no seed
        assert spec.position.margin_v == 12.5

    def test_seeds_position_when_no_delta_position(self, tmp_path, monkeypatch):
        from src.processor.style import load_style
        (tmp_path / "subtitle_styles.yaml").write_text("text:\n  font_size: 4.0\n")
        monkeypatch.setattr("src.processor.style._GLOBAL_PATH",
                            tmp_path / "subtitle_styles.yaml")
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.processor.style._SRT_DIR", srt_dir)
        # No per-video file at all
        ocr_region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        spec = load_style("vid",
                          source_dims=(1080, 1920),
                          ocr_region=ocr_region)
        # Seeded margin_v should NOT be the default 5.0; it should reflect
        # the region's location (~43% from bottom).
        assert spec.position.margin_v != 5.0
        assert 35 < spec.position.margin_v < 55

    def test_seed_not_persisted(self, tmp_path, monkeypatch):
        from src.processor.style import load_style
        (tmp_path / "subtitle_styles.yaml").write_text("text:\n  font_size: 4.0\n")
        monkeypatch.setattr("src.processor.style._GLOBAL_PATH",
                            tmp_path / "subtitle_styles.yaml")
        srt_dir = tmp_path / "srt"
        srt_dir.mkdir()
        monkeypatch.setattr("src.processor.style._SRT_DIR", srt_dir)
        ocr_region = {"x": 100, "y": 1000, "width": 880, "height": 80}
        load_style("vid", source_dims=(1080, 1920), ocr_region=ocr_region)
        # No per-video file should be created
        assert not (srt_dir / "vid_style.json").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/test_style_spec.py::TestPositionSeeding -v`
Expected: 3 FAIL — `load_style` doesn't accept `ocr_region`.

- [ ] **Step 3: Update `load_style` signature**

In `src/processor/style.py`, update `load_style`:

```python
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
    global_dict: dict = yaml.safe_load(_GLOBAL_PATH.read_text()) if _GLOBAL_PATH.exists() else {}
    if video_id is None:
        return SubtitleStyleSpec.model_validate(global_dict)

    per_video = _per_video_path(video_id)
    delta: dict = {}
    if per_video.exists():
        delta = json.loads(per_video.read_text())
        if source_dims is not None:
            migrated = _migrate_if_legacy(delta, source_dims[0], source_dims[1])
        else:
            migrated = _migrate_if_legacy(delta, 1080, 1920)
        if migrated is not delta:
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
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_style_spec.py::TestPositionSeeding -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/processor/style.py tests/test_style_spec.py
git commit -m "feat(style): seed position from OCR region in load_style when no override"
```

---

### Task 9: Update process.py — `_run_export_ffmpeg` calls `render_for_ffmpeg`

**Files:**
- Modify: `src/api/routers/process.py`

Context: today `_run_export_ffmpeg` does:
1. `_load_subtitle_style(video_id)` → flat dict.
2. Possibly `SubtitleStyleMatcher.match_style(...)` to override style fields.
3. `srt_to_ass(...)` to write the ASS file.
4. `generate_subtitle_background_images(...)` for PNG overlays.
5. Builds the ffmpeg filter graph from those artifacts.

The new flow:
1. `load_style(video_id, source_dims=..., ocr_region=...)` → `SubtitleStyleSpec`.
2. `render_for_ffmpeg(spec, srt, w, h, bg_dir)` → `RenderArtifacts`.
3. Builds the filter graph from `artifacts.ass_path` and `artifacts.bg_pngs`.

Blur handling becomes independent: read `spec.blur.enabled` directly.

- [ ] **Step 1: Replace `_load_subtitle_style` and rewrite `_run_export_ffmpeg`'s style-loading + rendering block**

In `src/api/routers/process.py`:

1. **Delete** the existing `_load_subtitle_style` function (around line 163).
2. **Replace** the block in `_run_export_ffmpeg` that calls `_load_subtitle_style` + `style_matcher` + `srt_to_ass` + `generate_subtitle_background_images` with a single block that calls `load_style` + `render_for_ffmpeg`. Pseudo-diff:

```python
# BEFORE (delete these):
from src.processor.subtitle import srt_to_ass, generate_subtitle_background_images
style = _load_subtitle_style(video_id)
# ... blur block that may call SubtitleStyleMatcher.match_style ...
ass_path = subtitle_path.with_suffix(".export.ass")
srt_to_ass(subtitle_path, style, ass_path, play_res_x=int(w), play_res_y=int(h))
bg_images = generate_subtitle_background_images(subtitle_path, style, bg_dir, int(w), int(h))
```

```python
# AFTER:
from src.processor.style import load_style
from src.processor.style_render import render_for_ffmpeg
from src.processor.region_detector import load_subtitle_region

ocr_region = load_subtitle_region(Path("data/srt"), video_id) if video_id else None
spec = load_style(
    video_id=video_id,
    source_dims=(src_w, src_h),
    ocr_region=ocr_region,
)

artifacts = None
if subtitle_path and subtitle_path.exists():
    bg_dir = output_path.parent / "bg_tmp"
    artifacts = render_for_ffmpeg(spec, subtitle_path, int(w), int(h), bg_dir)

ass_path = artifacts.ass_path if artifacts else None
bg_images = artifacts.bg_pngs if artifacts else None
```

3. **Replace** the blur logic at lines ~221-242. Old code checks `style.get("blur_enabled", True)`; new code reads `spec.blur.enabled`. Position-override logic via `SubtitleStyleMatcher.match_style` is now gone (its job is done by `load_style`'s seeding):

```python
# AFTER:
blur_filter = None
if video_id and spec.blur.enabled and ocr_region is not None:
    blur_filter = FFmpegProcessor._build_blur_filter(
        ocr_region,
        blur_strength=spec.blur.strength,
        blur_mode=spec.blur.mode,
    )
```

4. Anywhere that did `style.get("blur_enabled", True)` etc. now reads `spec.blur.*` directly.

- [ ] **Step 2: Verify the export endpoint still runs**

Spin up the API and hit the export endpoint with a test video:

```bash
# In one terminal:
make api
# In another:
curl -X POST http://localhost:8000/api/videos/<vid>/export \
     -H 'Content-Type: application/json' \
     -d '{"subtitle_language":"vi","tts_file":null,"resolution":null,
          "video_volume":1.0,"tts_volume":1.0}'
```

Expected: 200 OK with `{"task_id": "...", "status": "..."}`. Tail logs and confirm no AttributeError on `spec.blur.enabled`.

- [ ] **Step 3: Run the full unit suite to catch regressions**

Run: `python -m pytest tests/ -q --ignore=tests/integration`
Expected: all passing (≥291 from current main + new style tests).

- [ ] **Step 4: Commit**

```bash
git add src/api/routers/process.py
git commit -m "feat(export): _run_export_ffmpeg uses load_style + render_for_ffmpeg"
```

---

### Task 10: Update editor.py — `preview_frame` + `preview_clip` call `render_for_ffmpeg`

**Files:**
- Modify: `src/api/routers/editor.py`

- [ ] **Step 1: Replace the libass-only `_build_style_string` path in both preview endpoints with `render_for_ffmpeg`**

In `src/api/routers/editor.py`:

1. **Delete** the existing `_load_video_style` function (around line 184).
2. **Update** `preview_frame` (around line 320) to use the new render path:

```python
# AFTER:
from src.processor.style import load_style
from src.processor.style_render import render_for_ffmpeg
from src.processor.ffmpeg import FFmpegProcessor

# Use the request body's style as a delta over the global default.
# When request.subtitle_style is provided, it represents the live editor
# state (already in the new nested shape); merge by constructing the
# spec from it on top of the global.
proc = FFmpegProcessor()
info = proc.get_video_info(video_path)
src_w, src_h = info["width"], info["height"]

spec = load_style()  # start from global default
if request.subtitle_style:
    # Live editor sends a full SubtitleStyleSpec dict.
    from src.processor.style import SubtitleStyleSpec
    spec = SubtitleStyleSpec.model_validate(request.subtitle_style)

# Single-frame preview uses source dims as canvas.
with tempfile.TemporaryDirectory() as tmp:
    artifacts = render_for_ffmpeg(spec, srt_path, src_w, src_h, Path(tmp))
    vf_parts = [f"ass='{proc._escape_filter_path(artifacts.ass_path)}'"]
    # Note: rounded-PNG overlays aren't applied in single-frame preview
    # (too complex for the one-shot ffmpeg command). The live HTML overlay
    # in the editor already shows the rounded look; the trusted-fidelity
    # check for rounded bg is preview_clip / export.
    if spec.background.shape == "rect":
        # libass renders rect bg inside the ASS file; no extra filter needed.
        pass
    vf = ",".join(vf_parts)

    # ... existing ffmpeg single-frame extraction with -vf "$vf" ...
```

3. **Update** `preview_clip` (around line 386) similarly — but here we CAN do PNG overlays since we run a multi-frame ffmpeg command. Mirror the export's filter-chain logic from `_run_export_ffmpeg` (Task 9) for the bg_pngs branch.

Concretely, the easiest path is to extract the export's filter-chain assembly into a helper used by both endpoints. The current filter-graph assembly lives in [src/api/routers/process.py:291-349](src/api/routers/process.py#L291-L349) (`_run_export_ffmpeg`, the block guarded by `if bg_images: ... elif blur_filter: ... else:`). The existing helper `build_background_overlay_filter` from [src/processor/subtitle.py](src/processor/subtitle.py) (find via `grep -n "def build_background_overlay_filter" src/processor/subtitle.py`) already produces the bg-overlay portion of the chain.

Two options — pick one:

**Option A — keep the helper inline in process.py + duplicate into editor.py.** Lower-effort; ~30 lines duplicated. Acceptable in a personal codebase.

**Option B — extract into `src/processor/ffmpeg_filters.py`:**

```python
"""Shared filter-chain builders for export + preview-clip endpoints.

build_export_filter_complex composes the same chain that _run_export_ffmpeg
uses today: optional blur → scale/pad → optional bg-PNG overlay chain →
optional `ass=` burn-in. Returns the filter_complex string and the number
of extra `-i` inputs the caller must add (one per bg PNG).
"""

from __future__ import annotations

from pathlib import Path


def build_export_filter_complex(
    *,
    scale_pad: str,             # e.g. "scale=1080:1920:...,pad=..." or "null"
    blur_filter: str | None,    # e.g. "[0:v]boxblur=..." or None
    bg_pngs: list[dict] | None, # each: {path, start, end, x, y}
    ass_path: Path | None,
) -> tuple[str, int]:
    """Returns (filter_complex_string, extra_input_count).

    The caller already adds `-i <video>`; this function tells the caller
    how many additional `-i <bg_png>` inputs to append in the same order
    as `bg_pngs`.
    """
    # Body: lift verbatim from src/api/routers/process.py:291-349 (the
    # three branches: `if bg_images:`, `elif blur_filter:`, `else:`).
    # Replace `cmd1 += [...]` calls with string-building; return the
    # composed filter_complex string + len(bg_pngs).
    ...
```

The implementer extracts the existing branches by copy-paste, changes `cmd1 += [...]` calls into appending to a list of filter strings, and returns the joined result. Both `_run_export_ffmpeg` and `preview_clip` call this helper and assemble their full `ffmpeg ...` argv around it. Pick A if the refactor feels invasive — the goal is two endpoints producing identical filter graphs, not maximum DRY.

- [ ] **Step 2: Verify both endpoints still work**

Manual:
1. Start API: `make api`
2. Hit `/api/videos/<vid>/preview-frame` with a body like `{"timestamp": 2.0, "language": "vi", "subtitle_style": {...spec...}}`.
3. Hit `/api/videos/<vid>/preview-clip` with a body like `{"language": "vi", "start": 0, "duration": 5, "subtitle_style": {...spec...}}`.

Expected: both return 200 with the JPEG/MP4. Tail logs for errors.

- [ ] **Step 3: Commit**

```bash
git add src/api/routers/editor.py src/processor/ffmpeg_export_filters.py
git commit -m "feat(editor): preview_frame + preview_clip use render_for_ffmpeg"
```

---

### Task 11: Update style endpoints — `/api/subtitle-styles` and `/api/videos/{id}/style`

**Files:**
- Modify: `src/api/routers/process.py` (the `/api/subtitle-styles` endpoints)
- Modify: `src/api/routers/editor.py` (the `/api/videos/{id}/style` endpoints)

- [ ] **Step 1: Rewrite `/api/subtitle-styles` GET + PUT**

In `src/api/routers/process.py`, replace the existing endpoints (around lines 88-130):

```python
from src.processor.style import SubtitleStyleSpec, load_style, save_global_default


@router.get("/api/subtitle-styles", response_model=SubtitleStyleSpec)
async def get_subtitle_styles():
    """Return the global default subtitle style."""
    return load_style()


@router.put("/api/subtitle-styles", response_model=SubtitleStyleSpec)
async def put_subtitle_styles(spec: SubtitleStyleSpec):
    """Replace the global default. Body must be a full SubtitleStyleSpec."""
    save_global_default(spec)
    return spec


# DELETE the old `/api/subtitle-styles/{platform}` endpoint entirely —
# per-platform overrides are out of scope per the spec.
```

- [ ] **Step 2: Rewrite `/api/videos/{id}/style` GET + PUT + DELETE**

In `src/api/routers/editor.py`, replace existing handlers (around lines 220-242):

```python
from src.processor.style import SubtitleStyleSpec, load_style, save_style_delta
from src.processor.region_detector import load_subtitle_region


@router.get("/api/videos/{video_id}/style")
async def get_video_style(video_id: str):
    """Merged spec (global + per-video delta) plus a flag for whether the
    user has any per-video customizations."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    video = tm.video_index[video_id]
    ocr_region = load_subtitle_region(Path("data/srt"), video_id)
    spec = load_style(
        video_id=video_id,
        source_dims=(video.width, video.height) if video.width else None,
        ocr_region=ocr_region,
    )
    delta_path = Path("data/srt") / f"{video_id}_style.json"
    return {
        "video_id": video_id,
        "style": spec.model_dump(),
        "is_custom": delta_path.exists(),
    }


@router.put("/api/videos/{video_id}/style")
async def put_video_style(video_id: str, delta: dict):
    """Replace the per-video delta. Body is a partial SubtitleStyleSpec
    (FE-computed diff vs the global default)."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    save_style_delta(video_id, delta)
    return await get_video_style(video_id)


@router.delete("/api/videos/{video_id}/style")
async def delete_video_style(video_id: str):
    """Remove the per-video delta entirely. Subsequent GETs return global."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    delta_path = Path("data/srt") / f"{video_id}_style.json"
    if delta_path.exists():
        delta_path.unlink()
    return await get_video_style(video_id)
```

- [ ] **Step 3: Smoke-test all 5 endpoints**

```bash
curl http://localhost:8000/api/subtitle-styles | jq '.text.font_name'
# Expected: "Arial"

curl -X PUT http://localhost:8000/api/subtitle-styles \
     -H 'Content-Type: application/json' \
     -d '@-' <<'JSON' | jq '.text.font_size'
{"text":{"font_name":"Arial","font_size":5.5,"color":"#FFFFFF","bold":true},
 "position":{"alignment":"bottom-center","margin_v":5.0,"margin_h":0.0},
 "outline":{"width":0.15,"color":"#000000"},
 "shadow":{"depth":0.05,"color":"#000000"},
 "background":{"shape":"none","color":"#000000","opacity":0,
               "radius":0.94,"padding_x":0.83,"padding_y":0.5},
 "blur":{"enabled":false,"mode":"blur","strength":15}}
JSON
# Expected: 5.5

curl http://localhost:8000/api/videos/<vid>/style | jq '.is_custom'
# Expected: false (or true if a per-video file exists)

curl -X PUT http://localhost:8000/api/videos/<vid>/style \
     -H 'Content-Type: application/json' \
     -d '{"background":{"color":"#FFFF00","opacity":90,"shape":"rounded"}}'
# Expected: 200, response shows merged spec with bg yellow

curl -X DELETE http://localhost:8000/api/videos/<vid>/style
# Expected: 200, response shows is_custom: false
```

Reset the global back to defaults via PUT before continuing.

- [ ] **Step 4: Commit**

```bash
git add src/api/routers/process.py src/api/routers/editor.py
git commit -m "feat(api): style endpoints return/accept SubtitleStyleSpec"
```

---

### Task 12: Remove dead code — `_build_style_string`, `srt_to_ass`, `generate_subtitle_background_images`, both `_load_video_style`

**Files:**
- Modify: `src/processor/ffmpeg.py`
- Modify: `src/processor/subtitle.py`
- (already removed from `src/api/routers/process.py` in Task 9, `src/api/routers/editor.py` in Task 10)

- [ ] **Step 1: Confirm nothing imports these anymore**

```bash
grep -rn "_build_style_string\|srt_to_ass\|generate_subtitle_background_images\|_load_video_style" \
     src/ tests/ 2>&1 | grep -v ".pyc"
```

Expected: only matches inside `src/processor/ffmpeg.py` (the def of `_build_style_string`) and `src/processor/subtitle.py` (the defs). Any matches in callers indicate a missed migration — go back to Task 9 or 10.

- [ ] **Step 2: Remove the functions**

- `src/processor/ffmpeg.py`: delete `_build_style_string` (around line 198).
- `src/processor/subtitle.py`: delete `srt_to_ass` (around line 131) and `generate_subtitle_background_images` (around line 213). Keep `parse_srt`, `_seconds_to_ass_timestamp`, and any other helpers used elsewhere.

Also delete their tests in `tests/test_processor.py` (`TestBuildStyleString`, `TestSrtToAss`) — the behavior is now covered by `tests/test_style_render.py`.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest tests/ -q --ignore=tests/integration`
Expected: all passing (delta from previous run = the dropped tests).

- [ ] **Step 4: Commit**

```bash
git add src/processor/ffmpeg.py src/processor/subtitle.py tests/test_processor.py
git commit -m "refactor(style): remove _build_style_string, srt_to_ass, generate_subtitle_background_images"
```

---

## Phase 4: FE — types, client, components

### Task 13: TS types for `SubtitleStyleSpec`

**Files:**
- Modify: `ui-app/src/api/types.ts`

- [ ] **Step 1: Add the types**

Append to `ui-app/src/api/types.ts`:

```ts
// Mirror of src/processor/style.py::SubtitleStyleSpec. Keep in sync.
// All spatial fields are PERCENTAGES of canvas dims.

export interface TextStyle {
  font_name: 'Arial' | 'Roboto' | 'Impact' | 'Georgia' | 'Courier New' | 'Helvetica';
  font_size: number;
  color: string;       // '#RRGGBB'
  bold: boolean;
}

export interface PositionStyle {
  alignment:
    | 'bottom-left' | 'bottom-center' | 'bottom-right'
    | 'center-left' | 'center-center' | 'center-right'
    | 'top-left'    | 'top-center'    | 'top-right';
  margin_v: number;
  margin_h: number;
}

export interface OutlineStyle {
  width: number;
  color: string;
}

export interface ShadowStyle {
  depth: number;
  color: string;
}

export interface BackgroundStyle {
  shape: 'none' | 'rect' | 'rounded';
  color: string;
  opacity: number;     // 0-100
  radius: number;
  padding_x: number;
  padding_y: number;
}

export interface BlurStyle {
  enabled: boolean;
  mode: 'blur' | 'pixelate' | 'fill';
  strength: number;
}

export interface SubtitleStyleSpec {
  text: TextStyle;
  position: PositionStyle;
  outline: OutlineStyle;
  shadow: ShadowStyle;
  background: BackgroundStyle;
  blur: BlurStyle;
}

// Partial<...> would lose deep-partial; we hand-roll the delta type.
export interface SubtitleStyleDelta {
  text?:       Partial<TextStyle>;
  position?:   Partial<PositionStyle>;
  outline?:    Partial<OutlineStyle>;
  shadow?:     Partial<ShadowStyle>;
  background?: Partial<BackgroundStyle>;
  blur?:       Partial<BlurStyle>;
}
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd ui-app && npx tsc -b --noEmit
```

Expected: any errors are pre-existing (Timeline/SegmentList unused imports — known). No NEW errors from the additions.

- [ ] **Step 3: Commit**

```bash
git add ui-app/src/api/types.ts
git commit -m "feat(fe): SubtitleStyleSpec TS types mirror Pydantic schema"
```

---

### Task 14: Update API client (`getVideoStyle`, `putVideoStyle`, `getSubtitleStyleDefault`, `putSubtitleStyleDefault`)

**Files:**
- Modify: `ui-app/src/api/client.ts`

- [ ] **Step 1: Update the client functions**

In `ui-app/src/api/client.ts`, find the existing style functions and replace:

```ts
import type { SubtitleStyleSpec, SubtitleStyleDelta } from './types';

export function getSubtitleStyleDefault(): Promise<SubtitleStyleSpec> {
  return request('/subtitle-styles');
}

export function putSubtitleStyleDefault(spec: SubtitleStyleSpec): Promise<SubtitleStyleSpec> {
  return request('/subtitle-styles', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(spec),
  });
}

export interface VideoStyleResponse {
  video_id: string;
  style: SubtitleStyleSpec;
  is_custom: boolean;
}

export function getVideoStyle(videoId: string): Promise<VideoStyleResponse> {
  return request(`/videos/${videoId}/style`);
}

export function putVideoStyle(
  videoId: string,
  delta: SubtitleStyleDelta,
): Promise<VideoStyleResponse> {
  return request(`/videos/${videoId}/style`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(delta),
  });
}

export function deleteVideoStyle(videoId: string): Promise<VideoStyleResponse> {
  return request(`/videos/${videoId}/style`, { method: 'DELETE' });
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd ui-app && npx tsc -b --noEmit
```

Expected: build error in `EditorTab.tsx` referencing the old style shape — that's Task 17. Other files should not regress.

- [ ] **Step 3: Commit**

```bash
git add ui-app/src/api/client.ts
git commit -m "feat(fe): style API client uses SubtitleStyleSpec types"
```

---

### Task 15: `diffSpec` helper

**Files:**
- Create: `ui-app/src/utils/diffSpec.ts`
- Test: `ui-app/src/utils/__tests__/diffSpec.test.ts`

- [ ] **Step 1: Write failing test**

Create `ui-app/src/utils/__tests__/diffSpec.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { diffSpec } from '../diffSpec';
import type { SubtitleStyleSpec } from '../../api/types';

const baseSpec: SubtitleStyleSpec = {
  text:       { font_name: 'Arial', font_size: 3.0, color: '#FFFFFF', bold: true },
  position:   { alignment: 'bottom-center', margin_v: 5.0, margin_h: 0.0 },
  outline:    { width: 0.15, color: '#000000' },
  shadow:     { depth: 0.05, color: '#000000' },
  background: { shape: 'none', color: '#000000', opacity: 0, radius: 0.94, padding_x: 0.83, padding_y: 0.5 },
  blur:       { enabled: false, mode: 'blur', strength: 15 },
};

describe('diffSpec', () => {
  it('returns empty object when draft equals global', () => {
    expect(diffSpec(baseSpec, baseSpec)).toEqual({});
  });

  it('emits a single changed leaf', () => {
    const draft = structuredClone(baseSpec);
    draft.text.font_size = 5.5;
    expect(diffSpec(draft, baseSpec)).toEqual({ text: { font_size: 5.5 } });
  });

  it('emits multiple changed leaves in same group', () => {
    const draft = structuredClone(baseSpec);
    draft.background.color = '#FFFF00';
    draft.background.opacity = 90;
    expect(diffSpec(draft, baseSpec)).toEqual({
      background: { color: '#FFFF00', opacity: 90 },
    });
  });

  it('drops empty groups', () => {
    const draft = structuredClone(baseSpec);
    draft.text.color = '#FF0000';
    const result = diffSpec(draft, baseSpec);
    expect(result.position).toBeUndefined();
    expect(result.outline).toBeUndefined();
    expect(result).toEqual({ text: { color: '#FF0000' } });
  });
});
```

- [ ] **Step 2: Run test, expect failure**

Run: `cd ui-app && npx vitest run src/utils/__tests__/diffSpec.test.ts`
Expected: FAIL with module not found.

- [ ] **Step 3: Implement `diffSpec`**

Create `ui-app/src/utils/diffSpec.ts`:

```ts
import type { SubtitleStyleSpec, SubtitleStyleDelta } from '../api/types';

/** Returns only the fields where `draft` differs from `global`. Drops empty groups. */
export function diffSpec(draft: SubtitleStyleSpec, global: SubtitleStyleSpec): SubtitleStyleDelta {
  const delta: SubtitleStyleDelta = {};
  for (const group of Object.keys(draft) as (keyof SubtitleStyleSpec)[]) {
    const draftGroup = draft[group] as Record<string, unknown>;
    const globalGroup = global[group] as Record<string, unknown>;
    const changed: Record<string, unknown> = {};
    for (const key of Object.keys(draftGroup)) {
      if (draftGroup[key] !== globalGroup[key]) changed[key] = draftGroup[key];
    }
    if (Object.keys(changed).length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (delta as any)[group] = changed;
    }
  }
  return delta;
}
```

- [ ] **Step 4: Run test**

Run: `cd ui-app && npx vitest run src/utils/__tests__/diffSpec.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ui-app/src/utils/diffSpec.ts ui-app/src/utils/__tests__/diffSpec.test.ts
git commit -m "feat(fe): diffSpec helper computes per-video delta vs global"
```

---

### Task 16: `SubtitleRenderer` component (replaces `SubtitleOverlay`)

**Files:**
- Create: `ui-app/src/components/editor/SubtitleRenderer.tsx`
- Test: `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx`

- [ ] **Step 1: Write a unit test for spec→CSS conversion**

Create `ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { specToCss } from '../SubtitleRenderer';
import type { SubtitleStyleSpec } from '../../../api/types';

const baseSpec: SubtitleStyleSpec = {
  text:       { font_name: 'Arial', font_size: 3.0, color: '#FFFFFF', bold: true },
  position:   { alignment: 'bottom-center', margin_v: 5.0, margin_h: 0.0 },
  outline:    { width: 0.15, color: '#000000' },
  shadow:     { depth: 0.05, color: '#000000' },
  background: { shape: 'none', color: '#000000', opacity: 0, radius: 0.94, padding_x: 0.83, padding_y: 0.5 },
  blur:       { enabled: false, mode: 'blur', strength: 15 },
};

describe('specToCss', () => {
  it('scales font_size by canvas height', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    // 3.0% of 1920 = 57.6px
    expect(css.fontSize).toBeCloseTo(57.6, 1);
  });

  it('places subtitle at bottom for bottom-center alignment', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    expect(css.bottom).toBeCloseTo(5.0 * 1920 / 100, 1);
    expect(css.top).toBeUndefined();
  });

  it('places subtitle at top for top-center alignment', () => {
    const spec = structuredClone(baseSpec);
    spec.position.alignment = 'top-center';
    const css = specToCss(spec, 1080, 1920);
    expect(css.top).toBeCloseTo(5.0 * 1920 / 100, 1);
    expect(css.bottom).toBeUndefined();
  });

  it('hides background when shape is none', () => {
    const css = specToCss(baseSpec, 1080, 1920);
    expect(css.backgroundColor).toBeFalsy();
  });

  it('emits rgba background when shape is rounded', () => {
    const spec = structuredClone(baseSpec);
    spec.background.shape = 'rounded';
    spec.background.color = '#FFFF00';
    spec.background.opacity = 90;
    const css = specToCss(spec, 1080, 1920);
    expect(css.backgroundColor).toBe('rgba(255,255,0,0.9)');
    expect(css.borderRadius).toBe(`${0.94 * 1920 / 100}px`);
  });
});
```

- [ ] **Step 2: Run, expect failure**

Run: `cd ui-app && npx vitest run src/components/editor/__tests__/SubtitleRenderer.test.tsx`
Expected: FAIL with module not found.

- [ ] **Step 3: Implement `SubtitleRenderer` and `specToCss`**

Create `ui-app/src/components/editor/SubtitleRenderer.tsx`:

```tsx
import { useMemo, useCallback, useRef, useState, useEffect } from 'react';
import type { CSSProperties } from 'react';
import type { SubtitleSegment } from '../../api/types';
import type { SubtitleStyleSpec } from '../../api/types';
import { srtTimestampToSeconds } from '../../utils/srtTime';

interface Props {
  segments: SubtitleSegment[];
  currentTime: number;
  spec: SubtitleStyleSpec;
  onDragPosition?: (marginH_pct: number, marginV_pct: number) => void;
  videoRect?: { offsetX: number; offsetY: number; width: number; height: number };
}

/** Pure-function spec → text-element CSS. Exported for testing. */
export function specToCss(spec: SubtitleStyleSpec, videoW: number, videoH: number): CSSProperties {
  const px = {
    fontSize:  spec.text.font_size       * videoH / 100,
    marginV:   spec.position.margin_v    * videoH / 100,
    marginH:   spec.position.margin_h    * videoW / 100,
    outline:   spec.outline.width        * videoH / 100,
    radius:    spec.background.radius    * videoH / 100,
    padX:      spec.background.padding_x * videoW / 100,
    padY:      spec.background.padding_y * videoH / 100,
  };

  const hexToRgb = (hex: string): [number, number, number] => {
    if (!hex.startsWith('#') || hex.length !== 7) return [0, 0, 0];
    return [
      parseInt(hex.slice(1, 3), 16),
      parseInt(hex.slice(3, 5), 16),
      parseInt(hex.slice(5, 7), 16),
    ];
  };

  const [tr, tg, tb] = hexToRgb(spec.text.color);
  const [or, og, ob] = hexToRgb(spec.outline.color);
  const [br, bg_, bb] = hexToRgb(spec.background.color);
  const bgAlpha = spec.background.opacity / 100;

  const showBg = spec.background.shape !== 'none' && spec.background.opacity > 0;
  const css: CSSProperties = {
    fontFamily: spec.text.font_name,
    fontSize: px.fontSize,
    fontWeight: spec.text.bold ? 'bold' : 'normal',
    color: `rgb(${tr},${tg},${tb})`,
    WebkitTextStroke: `${px.outline}px rgb(${or},${og},${ob})`,
    textShadow: spec.shadow.depth > 0
      ? `0 0 ${spec.shadow.depth * videoH / 100}px rgb(${or},${og},${ob})`
      : undefined,
    backgroundColor: showBg ? `rgba(${br},${bg_},${bb},${bgAlpha})` : undefined,
    borderRadius: showBg && spec.background.shape === 'rounded' ? `${px.radius}px` : undefined,
    padding: showBg ? `${px.padY}px ${px.padX}px` : undefined,
    lineHeight: '1.4',
    textAlign: 'center',
    whiteSpace: 'pre-wrap',
    userSelect: 'none',
  };

  // Anchor by alignment
  const isBottom = spec.position.alignment.startsWith('bottom');
  const isTop = spec.position.alignment.startsWith('top');
  if (isBottom) css.bottom = px.marginV;
  else if (isTop) css.top = px.marginV;
  else css.top = videoH / 2;

  return css;
}

export function SubtitleRenderer({ segments, currentTime, spec, onDragPosition, videoRect }: Props) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0, marginH_pct: 0, marginV_pct: 0 });

  const activeSegment = useMemo(() => {
    if (segments.length === 0) return null;
    let lo = 0, hi = segments.length - 1;
    while (lo <= hi) {
      const mid = Math.floor((lo + hi) / 2);
      const s = segments[mid];
      const start = srtTimestampToSeconds(s.startTime);
      const end = srtTimestampToSeconds(s.endTime);
      if (currentTime >= start && currentTime < end) return s;
      if (currentTime < start) hi = mid - 1; else lo = mid + 1;
    }
    return null;
  }, [segments, currentTime]);

  const videoW = videoRect?.width ?? 0;
  const videoH = videoRect?.height ?? 0;
  const css = useMemo(
    () => (videoW > 0 && videoH > 0 ? specToCss(spec, videoW, videoH) : {}),
    [spec, videoW, videoH],
  );

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (!onDragPosition || videoH === 0) return;
    e.preventDefault(); e.stopPropagation();
    setIsDragging(true);
    dragStart.current = {
      x: e.clientX, y: e.clientY,
      marginH_pct: spec.position.margin_h,
      marginV_pct: spec.position.margin_v,
    };
    const handleMove = (ev: MouseEvent) => {
      const dxPx = ev.clientX - dragStart.current.x;
      const dyPx = -(ev.clientY - dragStart.current.y); // up = increase margin_v
      onDragPosition(
        dragStart.current.marginH_pct + (dxPx * 100 / videoW),
        Math.max(0, dragStart.current.marginV_pct + (dyPx * 100 / videoH)),
      );
    };
    const handleUp = () => {
      setIsDragging(false);
      window.removeEventListener('mousemove', handleMove);
      window.removeEventListener('mouseup', handleUp);
    };
    window.addEventListener('mousemove', handleMove);
    window.addEventListener('mouseup', handleUp);
  }, [onDragPosition, spec.position.margin_h, spec.position.margin_v, videoW, videoH]);

  useEffect(() => {
    // ResizeObserver pattern kept for parent-rect tracking if needed later
  }, []);

  const overlayStyle: CSSProperties = videoRect
    ? { position: 'absolute', top: videoRect.offsetY, left: videoRect.offsetX,
        width: videoRect.width, height: videoRect.height, pointerEvents: 'none' }
    : { position: 'absolute', inset: 0, pointerEvents: 'none' };

  return (
    <div ref={overlayRef} style={overlayStyle}>
      {activeSegment && (
        <div style={{ position: 'absolute', left: '50%', transform: `translateX(-50%) translateX(${spec.position.margin_h * videoW / 100}px)`, ...css }}
             className="pointer-events-auto"
             onMouseDown={handleMouseDown}>
          {activeSegment.text}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd ui-app && npx vitest run src/components/editor/__tests__/SubtitleRenderer.test.tsx`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ui-app/src/components/editor/SubtitleRenderer.tsx \
        ui-app/src/components/editor/__tests__/SubtitleRenderer.test.tsx
git commit -m "feat(fe): SubtitleRenderer consumes SubtitleStyleSpec, drag writes percent"
```

---

### Task 17: Reorganized `StylePanel`

**Files:**
- Modify: `ui-app/src/components/editor/StylePanel.tsx`

Sections (collapsible) mirror the spec's nesting: Text, Position, Outline, Shadow, Background, Blur. New controls: text color picker, outline color picker, shadow color picker, alignment 3×3 grid.

- [ ] **Step 1: Replace the file with the spec-driven version**

```tsx
// ui-app/src/components/editor/StylePanel.tsx — full replacement
import { useState } from 'react';
import type { SubtitleStyleSpec } from '../../api/types';

interface Props {
  spec: SubtitleStyleSpec;
  onChange: (next: SubtitleStyleSpec) => void;
  sourceW: number;   // source video width  (px)
  sourceH: number;   // source video height (px)
  hasOcrRegion?: boolean;
  onResetField?: (groupKey: keyof SubtitleStyleSpec) => void;
  onRealignToOcr?: () => void;
}

const FONTS: SubtitleStyleSpec['text']['font_name'][] = [
  'Arial', 'Roboto', 'Impact', 'Georgia', 'Courier New', 'Helvetica',
];

const ALIGN: SubtitleStyleSpec['position']['alignment'][] = [
  'top-left',    'top-center',    'top-right',
  'center-left', 'center-center', 'center-right',
  'bottom-left', 'bottom-center', 'bottom-right',
];

export function StylePanel({ spec, onChange, sourceW, sourceH, hasOcrRegion, onResetField, onRealignToOcr }: Props) {
  const [open, setOpen] = useState({ text: true, position: true, outline: false, shadow: false, background: false, blur: false });

  // Helpers: percentage → px (display); px → percentage (write back).
  const pctToPx = (pct: number, base: number) => Math.round(pct * base / 100);
  const pxToPct = (px: number, base: number) => px * 100 / base;

  const patch = <K extends keyof SubtitleStyleSpec>(group: K, partial: Partial<SubtitleStyleSpec[K]>) =>
    onChange({ ...spec, [group]: { ...spec[group], ...partial } });

  return (
    <div className="space-y-4 pr-1 text-on-surface">
      {/* TEXT */}
      <Section title="Text" open={open.text} onToggle={() => setOpen({ ...open, text: !open.text })}>
        <Row label="Font">
          <select value={spec.text.font_name} onChange={(e) => patch('text', { font_name: e.target.value as SubtitleStyleSpec['text']['font_name'] })}
                  className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
            {FONTS.map(f => <option key={f} value={f}>{f}</option>)}
          </select>
        </Row>
        <SliderRow label="Size" min={12} max={120}
                   value={pctToPx(spec.text.font_size, sourceH)}
                   onChange={(px) => patch('text', { font_size: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.text.color}
                 onChange={(e) => patch('text', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
        <Row label="Bold">
          <Toggle on={spec.text.bold} onClick={() => patch('text', { bold: !spec.text.bold })} />
        </Row>
      </Section>

      {/* POSITION */}
      <Section title="Position" open={open.position} onToggle={() => setOpen({ ...open, position: !open.position })}>
        <Row label="Alignment">
          <div className="grid grid-cols-3 gap-1">
            {ALIGN.map(a => (
              <button key={a}
                onClick={() => patch('position', { alignment: a })}
                className={`w-6 h-6 rounded border ${spec.position.alignment === a ? 'bg-primary border-primary' : 'border-outline-variant/15'}`}
                title={a} />
            ))}
          </div>
        </Row>
        <SliderRow label="Vertical" min={0} max={Math.round(sourceH * 0.95)}
                   value={pctToPx(spec.position.margin_v, sourceH)}
                   onChange={(px) => patch('position', { margin_v: pxToPct(px, sourceH) })} />
        <SliderRow label="Horizontal" min={-Math.round(sourceW * 0.4)} max={Math.round(sourceW * 0.4)}
                   value={pctToPx(spec.position.margin_h, sourceW)}
                   onChange={(px) => patch('position', { margin_h: pxToPct(px, sourceW) })} />
        {hasOcrRegion && onRealignToOcr && (
          <button onClick={onRealignToOcr}
                  className="text-[10px] text-on-surface-variant hover:text-on-surface mt-1">
            ↺ Re-align to OCR region
          </button>
        )}
      </Section>

      {/* OUTLINE */}
      <Section title="Outline" open={open.outline} onToggle={() => setOpen({ ...open, outline: !open.outline })}>
        <SliderRow label="Width" min={0} max={Math.round(sourceH * 0.01)}
                   step={1}
                   value={pctToPx(spec.outline.width, sourceH)}
                   onChange={(px) => patch('outline', { width: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.outline.color}
                 onChange={(e) => patch('outline', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
      </Section>

      {/* SHADOW */}
      <Section title="Shadow" open={open.shadow} onToggle={() => setOpen({ ...open, shadow: !open.shadow })}>
        <SliderRow label="Depth" min={0} max={Math.round(sourceH * 0.01)}
                   value={pctToPx(spec.shadow.depth, sourceH)}
                   onChange={(px) => patch('shadow', { depth: pxToPct(px, sourceH) })} />
        <Row label="Color">
          <input type="color" value={spec.shadow.color}
                 onChange={(e) => patch('shadow', { color: e.target.value })}
                 className="w-8 h-7 rounded cursor-pointer" />
        </Row>
      </Section>

      {/* BACKGROUND */}
      <Section title="Background" open={open.background} onToggle={() => setOpen({ ...open, background: !open.background })}>
        <Row label="Shape">
          <select value={spec.background.shape}
                  onChange={(e) => patch('background', { shape: e.target.value as SubtitleStyleSpec['background']['shape'] })}
                  className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
            <option value="none">None</option>
            <option value="rect">Rectangle</option>
            <option value="rounded">Rounded</option>
          </select>
        </Row>
        {spec.background.shape !== 'none' && (
          <>
            <Row label="Color">
              <input type="color" value={spec.background.color}
                     onChange={(e) => patch('background', { color: e.target.value })}
                     className="w-8 h-7 rounded cursor-pointer" />
            </Row>
            <SliderRow label="Opacity" min={0} max={100} unit="%"
                       value={spec.background.opacity}
                       onChange={(v) => patch('background', { opacity: v })} />
            {spec.background.shape === 'rounded' && (
              <SliderRow label="Radius" min={0} max={Math.round(sourceH * 0.05)}
                         value={pctToPx(spec.background.radius, sourceH)}
                         onChange={(px) => patch('background', { radius: pxToPct(px, sourceH) })} />
            )}
            <SliderRow label="Padding X" min={0} max={Math.round(sourceW * 0.05)}
                       value={pctToPx(spec.background.padding_x, sourceW)}
                       onChange={(px) => patch('background', { padding_x: pxToPct(px, sourceW) })} />
            <SliderRow label="Padding Y" min={0} max={Math.round(sourceH * 0.05)}
                       value={pctToPx(spec.background.padding_y, sourceH)}
                       onChange={(px) => patch('background', { padding_y: pxToPct(px, sourceH) })} />
          </>
        )}
      </Section>

      {/* BLUR */}
      <Section title="Blur" open={open.blur} onToggle={() => setOpen({ ...open, blur: !open.blur })}>
        <Row label="Enabled">
          <Toggle on={spec.blur.enabled} onClick={() => patch('blur', { enabled: !spec.blur.enabled })} />
        </Row>
        {spec.blur.enabled && (
          <>
            <Row label="Mode">
              <select value={spec.blur.mode}
                      onChange={(e) => patch('blur', { mode: e.target.value as SubtitleStyleSpec['blur']['mode'] })}
                      className="bg-surface-container-lowest border border-outline-variant/15 text-xs rounded h-7 px-2">
                <option value="blur">Gaussian</option>
                <option value="pixelate">Pixelate</option>
                <option value="fill">Solid Fill</option>
              </select>
            </Row>
            <SliderRow label="Strength" min={5} max={30}
                       value={spec.blur.strength}
                       onChange={(v) => patch('blur', { strength: v })} />
          </>
        )}
      </Section>
    </div>
  );
}

// ── Small inline components ──────────────────────────────────────────

function Section({ title, open, onToggle, children }: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div className="space-y-2">
      <button onClick={onToggle} className="w-full flex items-center gap-2 text-[10px] uppercase font-mono tracking-tighter font-bold text-on-surface">
        <span className="material-symbols-outlined text-sm">{open ? 'expand_more' : 'chevron_right'}</span>
        {title}
      </button>
      {open && <div className="space-y-2 pl-2">{children}</div>}
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="font-mono text-[9px] uppercase text-on-surface-variant w-20">{label}</label>
      <div className="flex-1 flex justify-end">{children}</div>
    </div>
  );
}

function SliderRow({ label, value, min, max, step = 1, unit = 'px', onChange }: { label: string; value: number; min: number; max: number; step?: number; unit?: string; onChange: (v: number) => void }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between">
        <label className="font-mono text-[9px] uppercase text-on-surface-variant">{label}</label>
        <span className="font-mono text-[9px] text-primary">{value}{unit}</span>
      </div>
      <input type="range" min={min} max={max} step={step} value={value}
             onChange={(e) => onChange(Number(e.target.value))}
             className="w-full h-1 accent-primary bg-zinc-700 rounded-full appearance-none cursor-pointer" />
    </div>
  );
}

function Toggle({ on, onClick }: { on: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick}
            className={`w-7 h-3.5 rounded-full relative cursor-pointer ${on ? 'bg-primary' : 'bg-surface-container-highest'}`}>
      <div className={`absolute top-0.5 w-2.5 h-2.5 bg-white rounded-full transition-all ${on ? 'right-0.5' : 'left-0.5'}`} />
    </button>
  );
}
```

- [ ] **Step 2: TypeScript check**

```bash
cd ui-app && npx tsc -b --noEmit
```

Expected: only `EditorTab.tsx` errors (Task 18 next).

- [ ] **Step 3: Commit**

```bash
git add ui-app/src/components/editor/StylePanel.tsx
git commit -m "feat(fe): StylePanel reorganized around SubtitleStyleSpec sections + new color/alignment controls"
```

---

### Task 18: `EditorTab` — state model + delta save + new components

**Files:**
- Modify: `ui-app/src/pages/videoDetail/EditorTab.tsx`

- [ ] **Step 1: Update imports + state**

Replace the existing style imports and state with:

```tsx
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import {
  // … existing imports unchanged …
  getSubtitleStyleDefault, getVideoStyle, putVideoStyle, putSubtitleStyleDefault, deleteVideoStyle,
} from '../../api/client';
import type { SubtitleStyleSpec } from '../../api/types';
import { diffSpec } from '../../utils/diffSpec';
import { SubtitleRenderer } from '../../components/editor/SubtitleRenderer';
import { StylePanel } from '../../components/editor/StylePanel';

// … inside EditorTab():
const [globalDefault, setGlobalDefault] = useState<SubtitleStyleSpec | null>(null);
const [savedSpec, setSavedSpec] = useState<SubtitleStyleSpec | null>(null);
const [draftSpec, setDraftSpec] = useState<SubtitleStyleSpec | null>(null);
```

Delete the old `style`/`originalStyle`/`setStyle` state and any code that maps the old flat shape.

- [ ] **Step 2: Load both global and video style on mount**

```tsx
useEffect(() => {
  if (!videoId) return;
  let cancelled = false;
  (async () => {
    try {
      const [globalRes, videoRes] = await Promise.all([
        getSubtitleStyleDefault(),
        getVideoStyle(videoId),
      ]);
      if (cancelled) return;
      setGlobalDefault(globalRes);
      setSavedSpec(videoRes.style);
      setDraftSpec(structuredClone(videoRes.style));
    } catch (e) {
      console.error('Failed to load style', e);
    }
  })();
  return () => { cancelled = true; };
}, [videoId]);
```

- [ ] **Step 3: Save flow uses delta**

```tsx
const handleSave = useCallback(async () => {
  if (!videoId || saving || !draftSpec || !globalDefault) return;
  setSaving(true); setSaveStatus('idle');
  try {
    const delta = diffSpec(draftSpec, globalDefault);
    const [res] = await Promise.all([
      putSrt(videoId, { language: activeLang, segments }),
      putVideoStyle(videoId, delta),
    ]);
    setSegments(res.segments); setOriginalSegments(res.segments);
    setSavedSpec(structuredClone(draftSpec));
    setSaveStatus('saved');
    setTimeout(() => setSaveStatus('idle'), 3000);
  } catch { setSaveStatus('error'); }
  finally { setSaving(false); }
}, [videoId, activeLang, segments, saving, draftSpec, globalDefault]);

const handleSaveAsDefault = useCallback(async () => {
  if (styleSaving || !draftSpec) return;
  setStyleSaving(true); setStyleSaveStatus('idle');
  try {
    const next = await putSubtitleStyleDefault(draftSpec);
    setGlobalDefault(next);
    setStyleSaveStatus('saved');
    setTimeout(() => setStyleSaveStatus('idle'), 3000);
  } catch { setStyleSaveStatus('error'); }
  finally { setStyleSaving(false); }
}, [styleSaving, draftSpec]);

const handleResetToGlobal = useCallback(async () => {
  if (!videoId || !globalDefault) return;
  if (!confirm('Reset all per-video style overrides? This clears every customization for this video.')) return;
  const res = await deleteVideoStyle(videoId);
  setSavedSpec(res.style);
  setDraftSpec(structuredClone(res.style));
}, [videoId, globalDefault]);

const handleRealignToOcr = useCallback(async () => {
  if (!videoId || !draftSpec || !globalDefault) return;
  if (!confirm('Re-align subtitle position to the OCR-detected region? Your current vertical/horizontal/alignment values will be lost.')) return;
  const delta = diffSpec(draftSpec, globalDefault);
  delete (delta as Record<string, unknown>).position;
  const res = await putVideoStyle(videoId, delta);
  setSavedSpec(res.style);
  setDraftSpec(structuredClone(res.style));
}, [videoId, draftSpec, globalDefault]);
```

- [ ] **Step 4: Render new `SubtitleRenderer` + `StylePanel`**

```tsx
{draftSpec && videoMeta && (
  <SubtitleRenderer
    segments={segments}
    currentTime={playerState.currentTime}
    spec={draftSpec}
    onDragPosition={(mh, mv) =>
      setDraftSpec(s => s ? { ...s, position: { ...s.position, margin_h: mh, margin_v: mv } } : s)
    }
    videoRect={videoRect}
  />
)}
{draftSpec && videoMeta && (
  <StylePanel
    spec={draftSpec}
    onChange={setDraftSpec}
    sourceW={videoMeta.width || 1080}
    sourceH={videoMeta.height || 1920}
    hasOcrRegion={!!subtitleRegion}
    onRealignToOcr={handleRealignToOcr}
  />
)}
```

Wire up the existing Save / Save as Default / Reset buttons to `handleSave`, `handleSaveAsDefault`, `handleResetToGlobal`. Update the inline Preview-Clip stylePayload to send the full `draftSpec` (now nested, not flat):

```tsx
const { task_id } = await postPreviewClip(videoId, {
  language: activeLang,
  start: Math.max(0, playerState.currentTime - 2),
  duration: 10,
  subtitle_style: draftSpec,  // full spec; matches request body shape
});
```

- [ ] **Step 5: TypeScript check + build**

```bash
cd ui-app && npx tsc -b --noEmit && npx vite build
```

Expected: no TS errors except pre-existing ones noted on the branch. Vite produces a clean bundle.

- [ ] **Step 6: Commit**

```bash
git add ui-app/src/pages/videoDetail/EditorTab.tsx
git commit -m "feat(fe): EditorTab uses draftSpec/savedSpec model and delta save"
```

---

## Phase 5: Dockerfile + integration test + final polish

### Task 19: Add font packages to Dockerfile

**Files:**
- Modify: `Dockerfile`

- [ ] **Step 1: Add the font install block**

Insert after the existing system-packages `RUN apt-get install` in the runtime stage:

```dockerfile
# Subtitle fonts. fonts-liberation provides Arial/Helvetica/Courier
# substitutes; fonts-roboto + fonts-dejavu fill the rest. fonts-noto-cjk
# is already present for CJK ranges.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    fonts-roboto \
    fonts-dejavu \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

# Optional: real Microsoft fonts (Impact, Georgia). Requires accepting
# the EULA and enabling the `contrib` apt component. Comment this RUN
# out if you'd rather not redistribute MS fonts in the image — libass
# will silently fall back to Liberation/DejaVu for those names.
RUN sed -i 's/main$/main contrib/' /etc/apt/sources.list.d/debian.sources || true && \
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" \
      | debconf-set-selections && \
    apt-get update && apt-get install -y --no-install-recommends ttf-mscorefonts-installer \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Rebuild and verify fonts are present in the container**

```bash
docker compose build app
docker compose up -d --force-recreate app
docker exec douyin-app fc-list | grep -iE "liberation|roboto|impact|georgia" | head -10
```

Expected: at least Liberation and Roboto entries visible. Impact/Georgia present if the second RUN succeeded; absent (with no error) if you commented it out.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat(docker): ship subtitle fonts (Liberation, Roboto, DejaVu; optional MS fonts)"
```

---

### Task 20: Integration test — `test_export_honors_full_spec`

**Files:**
- Create: `tests/test_export_style.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_export_style.py`:

```python
"""Integration: export endpoint honors every spec field end-to-end.

Marked `integration` because it builds a tiny fixture video on disk and
runs the full export pipeline (fastapi route → asyncio.to_thread →
ffmpeg). Slow-ish (~10s) but it's the only test that catches "schema +
renderer math are correct but the wiring drops a field somewhere."
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_export_honors_full_spec(tmp_path, monkeypatch):
    # Lay out the fixture directories the loaders expect:
    #   config/subtitle_styles.yaml           ← global default
    #   data/raw/{vid}.mp4                    ← source video
    #   data/srt/{vid}_vi.srt                 ← subtitles
    #   data/srt/{vid}_style.json             ← per-video delta
    #   data/output/{vid}_export.mp4          ← export result
    # We chdir to tmp_path so the relative paths in src/processor/style.py
    # and src/processor/region_detector.py resolve under tmp_path.
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "subtitle_styles.yaml").write_text(
        (repo_root / "config" / "subtitle_styles.yaml").read_text()
    )
    raw_dir = tmp_path / "data" / "raw"; raw_dir.mkdir(parents=True)
    srt_dir = tmp_path / "data" / "srt"; srt_dir.mkdir(parents=True)
    out_dir = tmp_path / "data" / "output"; out_dir.mkdir(parents=True)

    # 1. Create a 3-second fixture video (silent black, 720x1280).
    video_id = "test_export_spec"
    video_path = raw_dir / f"{video_id}.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=black:s=720x1280:r=24:d=3",
         "-pix_fmt", "yuv420p", str(video_path)],
        check=True, capture_output=True,
    )

    # 2. Write a tiny SRT.
    srt = srt_dir / f"{video_id}_vi.srt"
    srt.write_text(
        "1\n00:00:00,500 --> 00:00:02,500\nXin chào\n",
        encoding="utf-8",
    )

    # 3. Write a per-video style delta with every visible field set.
    delta = {
        "text": {"font_size": 4.0, "color": "#FF0000", "bold": True},
        "position": {"alignment": "bottom-center", "margin_v": 20.0},
        "outline": {"width": 0.2, "color": "#00FF00"},
        "background": {"shape": "rounded", "color": "#FFFF00",
                       "opacity": 80, "radius": 1.5,
                       "padding_x": 1.0, "padding_y": 0.5},
    }
    (srt_dir / f"{video_id}_style.json").write_text(json.dumps(delta))

    # 5. Run the export ffmpeg helper directly (avoids spinning up the API).
    from src.api.routers.process import _run_export_ffmpeg
    output = out_dir / f"{video_id}_export.mp4"
    _run_export_ffmpeg(
        video_path=video_path,
        subtitle_path=srt,
        tts_path=None,
        output_path=output,
        style={},                # ignored — _run_export_ffmpeg now calls load_style
        resolution=None,
        video_volume=1.0,
        tts_volume=1.0,
        video_id=video_id,
    )
    assert output.exists(), "export did not produce an output file"

    # 6. Extract a frame at t=1.5s (segment is active 0.5–2.5).
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "1.5", "-i", str(output),
         "-frames:v", "1", str(frame)],
        check=True, capture_output=True,
    )

    # 7. Inspect with PIL: assert there's a yellow band near the bottom
    #    (bg color #FFFF00) and red text pixels (color #FF0000) within it.
    from PIL import Image
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    pixels = img.load()

    # The bg should sit at ~20% from bottom (margin_v=20% of 1280 = 256px).
    # Allow a generous y-band because of padding + text height.
    yellow_count = 0
    red_count = 0
    for y in range(int(h * 0.6), int(h * 0.95)):
        for x in range(0, w):
            r, g, b = pixels[x, y]
            if r > 200 and g > 200 and b < 80:
                yellow_count += 1
            elif r > 200 and g < 80 and b < 80:
                red_count += 1
    assert yellow_count > 1000, f"expected yellow bg pixels in lower band, got {yellow_count}"
    assert red_count > 50, f"expected red text pixels in lower band, got {red_count}"
```

- [ ] **Step 2: Run the test**

Run: `python -m pytest tests/test_export_style.py -v -m integration`
Expected: passes in ~10s.

If yellow/red counts miss the thresholds, inspect the extracted frame manually (`open tmp_path/frame.png`) — it's likely either (a) the spec didn't propagate (a wiring bug elsewhere — go back to Task 9) or (b) the y-band is wrong (adjust the bands).

- [ ] **Step 3: Commit**

```bash
git add tests/test_export_style.py
git commit -m "test(export): integration test for full spec → exported MP4"
```

---

### Task 21: Manual smoke + CHANGELOG + ship

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: Manual smoke test (3 minutes)**

Rebuild and recreate:
```bash
make docker-rebuild
```

In the UI:
1. Open a video → editor tab. Confirm style panel shows the new sections (Text / Position / Outline / Shadow / Background / Blur).
2. Drag the subtitle to a new position → click Save → reload page → position persists at the dragged location.
3. Pick a yellow rounded background at 70% opacity → click **Preview Frame** → click **Preview Clip** → click **Export**. All three should show yellow rounded bg in the same place.
4. Toggle blur ON → blur applies in export. Toggle blur OFF → blur disappears. Position unchanged across the toggle.
5. Hit **Save as Default** → open a different (fresh) video → that video's defaults include the saved values.

If any step fails, add a follow-up task; do not check this box until the path is clean.

- [ ] **Step 2: Update CHANGELOG**

Append to `CHANGELOG.md` `## [Unreleased]` section:

```markdown
### Changed
- Subtitle style is now a single canonical `SubtitleStyleSpec` (nested Pydantic) consumed by every renderer. Storage is in percentages of canvas dims so the same spec produces visually-equivalent output at any resolution. Per-video files store only the user's delta over `config/subtitle_styles.yaml`; loader deep-merges. Editor's HTML overlay, libass force_style preview, and ffmpeg export all read from the same spec — no more silent field drops or scale mismatches. Migration: existing flat px-based per-video JSONs auto-convert on first load post-upgrade.
- Blur is now part of the style spec (off by default). Toggling blur off in the editor actually disables blur in the export — previously the FE never persisted blur fields and the BE defaulted them on.
- `style_matcher.match_style` (which forcibly overrode position whenever blur was on) is replaced by `suggest_position`, a one-shot OCR-region seed that runs only when no per-video position override exists. Position and blur are now decoupled.

### Added
- StylePanel controls for text color, outline color, shadow color, and 9-way alignment (previously only editable by hand-writing the YAML).
- `POST /api/videos/{id}/style` accepts a delta (partial spec); FE computes the diff vs global default and persists only changed fields.
- "Re-align to OCR region" button in StylePanel (visible when an OCR region exists) resets `position.*` to the auto-seeded suggestion.

### Removed
- `_build_style_string` (replaced by `style_render.render_for_ffmpeg`).
- `srt_to_ass` and `generate_subtitle_background_images` (folded into `style_render`).
- Two duplicate `_load_video_style` implementations.
- Per-platform style overrides (the `platforms:` section of `subtitle_styles.yaml`).
```

- [ ] **Step 3: Mark the matching README checklist item**

In `README.md` under "Implementation Progress", add (or check) a row for this work:

```markdown
- [x] **Subtitle Style Canonical Spec** — single SubtitleStyleSpec consumed by HTML overlay and ffmpeg renderer; percent-based storage; per-video deltas merge over global YAML; blur in spec (off by default); OCR position seeding via suggest_position. (Spec: docs/superpowers/specs/2026-05-26-subtitle-style-canonical-spec-design.md, Plan: docs/superpowers/plans/2026-05-26-subtitle-style-canonical-spec.md)
```

- [ ] **Step 4: Commit and open PR**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: subtitle style canonical spec — CHANGELOG + README checklist"
git push -u origin <branch>
gh pr create --title "Subtitle style canonical spec + unified renderers" \
             --body "$(cat <<'EOF'
## Summary

Implements [docs/superpowers/specs/2026-05-26-subtitle-style-canonical-spec-design.md](docs/superpowers/specs/2026-05-26-subtitle-style-canonical-spec-design.md).

Three parallel rendering paths (HTML overlay, libass force_style, ASS+PNG export) collapse behind a single `SubtitleStyleSpec`. Persistence moves to `delta + global` deep-merge. Storage is percentage-based so the spec is resolution-independent. Blur joins the spec (off by default). `style_matcher` becomes a one-shot OCR seed instead of a forced override.

## Test plan

- [x] Unit tests for schema, loader, migration, deep-merge (`tests/test_style_spec.py`)
- [x] Unit tests for the ffmpeg renderer (`tests/test_style_render.py`)
- [x] FE unit tests for diffSpec + specToCss (Vitest)
- [x] Integration test: export honors every spec field (`tests/test_export_style.py`)
- [x] Manual smoke: drag-position persists; yellow rounded bg renders consistently across editor / preview-frame / preview-clip / export; blur toggle works
EOF
)"
```

---

## Spec coverage check

| Spec section | Implemented in |
|---|---|
| §1 Canonical schema | Task 1 |
| §2 Persistence (loader, save, migration) | Tasks 3, 4, 8 |
| §3a HTML renderer | Task 16 |
| §3b ffmpeg renderer | Task 5 |
| §3 Renderer wiring | Tasks 9, 10 |
| §3c Dead code removal | Task 12 |
| §4a State model | Task 18 |
| §4b StylePanel UI | Task 17 |
| §4d Live preview | Task 16 |
| §4e Font availability | Task 19 |
| §5 Blur & style_matcher rework | Tasks 6, 7, 8, 9 |
| §6a Schema tests | Tasks 1, 2, 3, 4, 8 |
| §6b Renderer tests | Task 5; Task 16 (FE) |
| §6c E2E integration | Task 20 |
| §6c Manual smoke | Task 21 |
| Migration impact (CHANGELOG) | Task 21 |
