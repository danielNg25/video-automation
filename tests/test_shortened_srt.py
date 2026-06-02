"""Unit tests for the per-sentence-to-per-segment text redistribution
that powers the post-dub shortened-SRT auto-snapshot."""

from __future__ import annotations

from src.tts.shortened_srt import (
    build_shortened_srt,
    split_sentence_to_segments,
)


class TestSplitSentence:
    def test_single_segment_passthrough(self):
        """N=1 returns the input unchanged in a one-element list."""
        result = split_sentence_to_segments("Hello world.", ["original text"])
        assert result == ["Hello world."]

    def test_two_segments_proportional(self):
        """Two equally-sized originals get the two words 1:1."""
        result = split_sentence_to_segments("hello world", ["foo", "bar"])
        # 3-char + 3-char originals → 50/50 split → one word each.
        assert result == ["hello", "world"]

    def test_unbalanced_segments(self):
        """A tiny first segment + a huge second gets most of the words in
        the second slot."""
        result = split_sentence_to_segments(
            "the quick brown fox jumps",
            ["a", "the quick brown fox jumps over a lazy dog"],
        )
        # First original is 1 char of 42 total ≈ 2.4%. Round-half-up of
        # 5 words * 0.024 = 0 → first slot gets 0 words; all 5 land in
        # the second slot.
        assert result[0] == ""
        assert result[1] == "the quick brown fox jumps"

    def test_more_segments_than_words(self):
        """Trailing segments get '' once we run out of words."""
        result = split_sentence_to_segments("hi", ["a", "b", "c"])
        assert result == ["hi", "", ""]

    def test_empty_merged_text(self):
        """Empty input → empty string for every segment."""
        result = split_sentence_to_segments("", ["a", "b", "c"])
        assert result == ["", "", ""]

    def test_empty_segments_list(self):
        """No originals → empty list out. (Defensive; shouldn't fire.)"""
        result = split_sentence_to_segments("anything", [])
        assert result == []

    def test_originals_with_zero_total_length(self):
        """If every original is empty, split evenly by segment count."""
        result = split_sentence_to_segments("one two three", ["", "", ""])
        # No proportional signal → 3 words across 3 slots → 1 each.
        assert result == ["one", "two", "three"]


class TestBuildShortenedSrt:
    def _orig(self) -> list[dict]:
        """Five-segment fixture in the parse_srt() shape."""
        return [
            {"index": 1, "start": 0.0, "end": 1.0, "text": "alpha"},
            {"index": 2, "start": 1.0, "end": 2.0, "text": "beta"},
            {"index": 3, "start": 2.0, "end": 3.0, "text": "gamma"},
            {"index": 4, "start": 3.0, "end": 4.0, "text": "delta"},
            {"index": 5, "start": 4.0, "end": 5.0, "text": "epsilon"},
        ]

    def test_preserves_original_timings(self):
        """Output rows count + timings match the originals exactly."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1, 2], "text": "first sentence here"},
            {"segment_indices": [3, 4], "text": "second sentence"},
        ]
        result = build_shortened_srt(plan, original)
        assert len(result) == 5
        for i, seg in enumerate(result):
            assert seg["start"] == original[i]["start"]
            assert seg["end"] == original[i]["end"]

    def test_text_redistributed_per_plan_entry(self):
        """Plan entry [0,1,2] gets its 3 words distributed across rows 0-2."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1, 2], "text": "alpha beta gamma"},
            {"segment_indices": [3, 4], "text": "delta epsilon"},
        ]
        result = build_shortened_srt(plan, original)
        # alpha/beta/gamma are equal-length (5/4/5 ≈ third each) → one word
        # per slot; delta/epsilon are equal too.
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_segment_not_referenced_keeps_original_text(self):
        """If the plan doesn't cover segment N, that row's text is copied
        from the original unchanged. (Defensive; doesn't happen for
        successful dubs.)"""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1], "text": "alpha beta"},
            # segments 2, 3, 4 are NOT referenced
        ]
        result = build_shortened_srt(plan, original)
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_plan_entry_missing_text_field_skipped(self):
        """A plan entry without a 'text' key (malformed) is skipped without
        crashing; the segments it claimed keep their original text."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 1]},  # no 'text'
            {"segment_indices": [2, 3, 4], "text": "gamma delta epsilon"},
        ]
        result = build_shortened_srt(plan, original)
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        # The second entry still applies.
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_plan_entry_missing_segment_indices_skipped(self):
        """A plan entry without a 'segment_indices' key (malformed) is
        skipped without crashing; all originals keep their text."""
        original = self._orig()
        plan = [
            {"text": "stray text"},  # no segment_indices
            {"segment_indices": [0, 1], "text": "alpha beta"},
        ]
        result = build_shortened_srt(plan, original)
        # First entry skipped; second applies.
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        # Untouched segments keep originals.
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        assert result[4]["text"] == "epsilon"

    def test_plan_entry_with_any_out_of_range_index_skipped(self):
        """If even one of the entry's indices is out of range, the whole
        entry is skipped — no partial application across the valid ones."""
        original = self._orig()
        plan = [
            {"segment_indices": [0, 99], "text": "hello world"},
            {"segment_indices": [2, 3], "text": "gamma delta"},
        ]
        result = build_shortened_srt(plan, original)
        # First entry skipped because index 99 doesn't exist; segments 0,1
        # keep their original text.
        assert result[0]["text"] == "alpha"
        assert result[1]["text"] == "beta"
        # Second entry applies normally.
        assert result[2]["text"] == "gamma"
        assert result[3]["text"] == "delta"
        # Untouched.
        assert result[4]["text"] == "epsilon"
