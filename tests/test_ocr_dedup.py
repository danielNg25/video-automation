"""Unit tests for OCR-stage consecutive-duplicate-segment merging.

The helper runs at the end of _build_segments_from_frames; it collapses
runs of adjacent segments whose text is identical (after .strip()) into
a single segment spanning start[first] to end[last]. Non-adjacent
duplicates are left alone — they're distinct spoken moments.
"""

from __future__ import annotations

from src.transcriber.ocr import _merge_consecutive_duplicates


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


class TestMergeConsecutiveDuplicates:
    def test_empty_input_returns_empty(self):
        assert _merge_consecutive_duplicates([]) == []

    def test_single_segment_returned_unchanged(self):
        segs = [_seg(0.0, 1.0, "a")]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_no_duplicates_passes_through(self):
        segs = [
            _seg(0.0, 1.0, "alpha"),
            _seg(1.0, 2.0, "beta"),
            _seg(2.0, 3.0, "gamma"),
        ]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_two_adjacent_dupes_merge_with_spanning_timing(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "你好"),
            _seg(2.0, 3.0, "你好"),
        ])
        assert out == [_seg(0.0, 3.0, "你好")]

    def test_three_plus_adjacent_dupes_collapse(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "你好"),
            _seg(1.0, 2.0, "你好"),
            _seg(2.0, 3.0, "你好"),
        ])
        assert out == [_seg(0.0, 3.0, "你好")]

    def test_non_adjacent_dupes_kept_separate(self):
        segs = [
            _seg(0.0, 1.0, "你好"),
            _seg(1.0, 2.0, "再见"),
            _seg(2.0, 3.0, "你好"),
        ]
        assert _merge_consecutive_duplicates(segs) == segs

    def test_strip_handles_whitespace_differences(self):
        out = _merge_consecutive_duplicates([
            _seg(0.0, 1.0, "hello"),
            _seg(1.0, 2.0, "hello "),
            _seg(2.0, 3.0, " hello"),
        ])
        assert out == [_seg(0.0, 3.0, "hello")]

    def test_empty_text_segments_not_merged(self):
        """Two adjacent empty-text segments stay as two entries. Empty
        matching empty isn't a meaningful 'duplicate spoken moment'; the
        existing downstream stages already filter empty text where
        appropriate, so leave them alone here."""
        segs = [
            _seg(0.0, 1.0, ""),
            _seg(1.0, 2.0, ""),
        ]
        assert _merge_consecutive_duplicates(segs) == segs
