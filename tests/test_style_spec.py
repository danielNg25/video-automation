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
