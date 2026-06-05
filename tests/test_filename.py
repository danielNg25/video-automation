"""Unit tests for the safe_filename helper used by download routes."""

from __future__ import annotations

from src.utils.filename import safe_filename


class TestSafeFilename:
    def test_none_falls_back(self):
        assert safe_filename(None, "vid123") == "vid123"

    def test_empty_falls_back(self):
        assert safe_filename("", "vid123") == "vid123"

    def test_plain_string_returned_unchanged(self):
        assert safe_filename("My Cooking Vlog", "vid123") == "My Cooking Vlog"

    def test_slashes_replaced_with_space(self):
        assert safe_filename("a/b\\c", "vid") == "a b c"

    def test_windows_reserved_chars_replaced(self):
        assert safe_filename('a:b*c?d"e<f>g|h', "vid") == "a b c d e f g h"

    def test_control_chars_replaced(self):
        assert safe_filename("a\x00b\x1fc", "vid") == "a b c"

    def test_collapses_whitespace_runs(self):
        assert safe_filename("foo   bar\t\tbaz", "vid") == "foo bar baz"

    def test_trims_leading_and_trailing_whitespace(self):
        assert safe_filename("   hello   ", "vid") == "hello"

    def test_strips_trailing_dots_and_spaces(self):
        assert safe_filename("hello. .. ", "vid") == "hello"

    def test_only_unsafe_chars_falls_back(self):
        assert safe_filename("///***", "vid") == "vid"

    def test_unicode_preserved(self):
        # CJK, emoji, accented Latin — all valid in modern filesystems.
        assert safe_filename("Phở 🍜 ngon", "vid") == "Phở 🍜 ngon"

    def test_length_cap_applies(self):
        long_name = "a" * 300
        out = safe_filename(long_name, "vid")
        assert len(out) == 200
        assert out == "a" * 200
