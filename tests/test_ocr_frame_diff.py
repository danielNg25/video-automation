"""Tests for the _FrameDiffer helper in src/transcriber/ocr.py.

The differ is what makes OCR fast — it lets the streaming OCR pipeline
skip frames whose subtitle strip looks identical to the previous one, so
we don't waste an OCR call on every consecutive frame of the same subtitle.
"""

import numpy as np


def _strip(value: int, shape: tuple[int, int] = (100, 800)) -> np.ndarray:
    """Solid-colour grayscale strip of `value` (0-255), default 100x800."""
    return np.full(shape, value, dtype=np.uint8)


class TestFrameDiffer:
    def test_first_call_is_never_same(self):
        """No previous frame cached → always 'different'."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=3.0)
        assert d.is_same(_strip(128)) is False

    def test_identical_frames_are_same(self):
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=3.0)
        d.update(_strip(128), "hello", [])
        assert d.is_same(_strip(128)) is True

    def test_50pct_pixel_flip_is_different(self):
        """Flipping half the pixels to black → mean diff ≈ 64, well above 3.0."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=3.0)
        a = _strip(128)
        b = a.copy()
        b[:, :400] = 0
        d.update(a, "x", [])
        assert d.is_same(b) is False

    def test_tiny_noise_is_same(self):
        """Mean diff of 1.0 should fall below the default 3.0 threshold."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=3.0)
        a = _strip(128)
        b = (a.astype(np.int16) + 1).astype(np.uint8)
        d.update(a, "x", [])
        assert d.is_same(b) is True

    def test_threshold_override_lets_large_diff_pass(self):
        """High threshold = permissive matcher: mean diff 64 still counts as same."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=100.0)
        a = _strip(0)
        b = _strip(64)
        d.update(a, "x", [])
        assert d.is_same(b) is True

    def test_shape_mismatch_returns_different(self):
        """Shape change (e.g., different video) → reset; treat as new."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=3.0)
        d.update(_strip(0, shape=(100, 800)), "x", [])
        assert d.is_same(_strip(0, shape=(50, 800))) is False

    def test_update_caches_text_and_bboxes(self):
        """After update(), prev_text + prev_bboxes are exposed for the
        caller to reuse on skipped frames."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        bboxes = [[[0, 0], [10, 0], [10, 10], [0, 10]]]
        d.update(_strip(50), "subtitle text", bboxes)
        assert d.prev_text == "subtitle text"
        assert d.prev_bboxes == bboxes
        assert d.prev_strip is not None and d.prev_strip.shape == (100, 800)

    def test_default_threshold_is_three(self):
        """Lock the default — it's tuned for typical Douyin subtitle strips."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        assert d.threshold == 3.0
