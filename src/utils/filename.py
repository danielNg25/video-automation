"""Filename sanitisation for user-facing downloads."""

from __future__ import annotations

import re

# Characters that are illegal in filenames on at least one major OS:
# Windows reserves \ / : * ? " < > | ; macOS/Linux reserve / and NUL.
# Control chars (U+0000..U+001F) are always unsafe.
_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

# Trailing dots and spaces break on Windows ("foo." is treated as "foo").
_TRAILING_RE = re.compile(r"[. ]+$")

# Cap at 200 chars: most filesystems allow 255 bytes for the basename, and
# we leave headroom for the extension we append later (.mp4 / .vi.srt / .wav).
_MAX_LEN = 200


def safe_filename(name: str | None, fallback: str) -> str:
    """Return a filesystem-safe basename derived from ``name``.

    Strips illegal characters, collapses whitespace, trims trailing dots
    and spaces, and caps length. If the result is empty (e.g. the input
    was only punctuation), returns ``fallback`` unchanged — callers
    should pass something they trust (typically the immutable video_id).

    The returned string does NOT include a file extension; callers append
    one (``.mp4``, ``.srt``, ``.wav``) themselves.
    """
    if not name:
        return fallback
    cleaned = _UNSAFE_RE.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = _TRAILING_RE.sub("", cleaned)
    if not cleaned:
        return fallback
    if len(cleaned) > _MAX_LEN:
        cleaned = cleaned[:_MAX_LEN].rstrip()
    return cleaned
