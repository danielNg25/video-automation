"""Unit tests for get_translator wiring the skip_noise flag from config."""

from __future__ import annotations

from src.translator import get_translator


class TestSkipNoiseConfigWiring:
    def test_default_true_when_key_absent(self):
        """skip_noise defaults to True when the config doesn't set it."""
        cfg = {"translation": {"backend": "anthropic", "api_key": "x"}}
        t = get_translator(cfg)
        assert t.skip_noise is True

    def test_respects_explicit_false(self):
        """A user can opt out via translation.skip_noise: false."""
        cfg = {
            "translation": {
                "backend": "anthropic",
                "api_key": "x",
                "skip_noise": False,
            }
        }
        t = get_translator(cfg)
        assert t.skip_noise is False
