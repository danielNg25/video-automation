"""Tests for the _FrameDiffer helper in src/transcriber/ocr.py.

The differ uses a high-contrast binary text-mask: pixels brighter than 200
or darker than 50 are 'text-like'; everything mid-range is 'background'.
Comparing masks makes the diff robust to constant background motion under
the subtitle strip — which dominated the raw-pixel approach.
"""

import numpy as np


def _strip(value: int, shape: tuple[int, int] = (100, 800)) -> np.ndarray:
    """Solid-colour grayscale strip of `value` (0-255), default 100x800."""
    return np.full(shape, value, dtype=np.uint8)


class TestFrameDiffer:
    def test_first_call_is_never_same(self):
        """No previous frame cached → always 'different'."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        assert d.is_same(_strip(128)) is False

    def test_identical_frames_are_same(self):
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        d.update(_strip(128), "hello", [])
        assert d.is_same(_strip(128)) is True

    def test_mid_range_pixels_produce_empty_masks_and_match(self):
        """Mid-grey pixels (50 ≤ v ≤ 200) aren't text → mask is all zero.
        Two such frames look identical to the differ, regardless of grey value."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        d.update(_strip(100), "hello", [])
        # Different grey value, but still in the background range → same mask.
        assert d.is_same(_strip(150)) is True

    def test_text_appears_makes_frames_different(self):
        """Cached frame: all background. New frame: half of pixels become
        bright text (mask flips for half → mean diff = 0.5 ≫ threshold)."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        d.update(_strip(128), "", [])
        new = _strip(128)
        new[:, :400] = 255  # half the pixels are now bright text
        assert d.is_same(new) is False

    def test_same_text_in_same_position_is_same(self):
        """Two frames with the same text pattern (same bright/dark pixels)
        but different mid-range backgrounds match."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        a = _strip(128)
        a[:, :100] = 255  # text-like bright stripe
        b = _strip(80)
        b[:, :100] = 255  # same stripe, different background
        d.update(a, "hi", [])
        assert d.is_same(b) is True

    def test_threshold_override_is_strict(self):
        """A very tight threshold rejects even small mask flips."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=0.001)
        a = _strip(128)
        a[:, :100] = 255
        b = _strip(128)
        b[:, :101] = 255  # one extra column flipped → tiny diff
        d.update(a, "x", [])
        assert d.is_same(b) is False

    def test_threshold_override_is_permissive(self):
        """A very loose threshold accepts even big mask flips."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer(threshold=0.99)
        a = _strip(0)        # all dark → mask is all 1
        b = _strip(128)      # all mid → mask is all 0
        d.update(a, "x", [])
        # Mean diff is 1.0; threshold 0.99 — still treated as different
        # (the inequality is strict <), but anything else loose enough passes.
        assert d.is_same(b) is False  # boundary check
        d2 = _FrameDiffer(threshold=1.01)
        d2.update(a, "x", [])
        assert d2.is_same(b) is True

    def test_shape_mismatch_returns_different(self):
        """Shape change (e.g., different video) → reset; treat as new."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        d.update(_strip(0, shape=(100, 800)), "x", [])
        assert d.is_same(_strip(0, shape=(50, 800))) is False

    def test_update_caches_text_and_bboxes(self):
        """After update(), prev_text + prev_bboxes are exposed for the caller
        to reuse on skipped frames; prev_strip (mask) is also populated."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        bboxes = [[[0, 0], [10, 0], [10, 10], [0, 10]]]
        d.update(_strip(50), "subtitle text", bboxes)
        assert d.prev_text == "subtitle text"
        assert d.prev_bboxes == bboxes
        assert d.prev_strip is not None
        assert d.prev_strip.shape == (100, 800)

    def test_default_threshold(self):
        """Lock the default — tuned on real Douyin videos."""
        from src.transcriber.ocr import _FrameDiffer
        d = _FrameDiffer()
        assert d.threshold == 0.10
