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

    def test_blur_strength_clamped_5_30(self):
        from src.processor.style import SubtitleStyleSpec
        # 5 and 30 OK (boundaries)
        SubtitleStyleSpec.model_validate({"blur": {"strength": 5}})
        SubtitleStyleSpec.model_validate({"blur": {"strength": 30}})
        # Out of range rejected
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"blur": {"strength": 4}})
        with pytest.raises(ValidationError):
            SubtitleStyleSpec.model_validate({"blur": {"strength": 31}})

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

    def test_delta_scalar_replaces_dict_in_base(self):
        from src.processor.style import _deep_merge
        base = {"text": {"color": "#FFFFFF", "bold": True}}
        delta = {"text": None}
        assert _deep_merge(base, delta) == {"text": None}


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
