"""Validation for user-supplied identifiers that become file paths.

Endpoints build SRT / TTS paths by interpolating ``video_id``, ``language``,
and ``version`` straight into filenames under ``data/``. Without a guard, a
crafted value like ``../../etc/passwd`` escapes that directory. These
allow-list patterns plus :func:`ensure_within` keep every such path inside
its intended base, independent of how the caller assembles it.
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException

# Match against the WHOLE string with fullmatch() — `re.match(... "$")` would
# also accept a trailing newline ("en\n"), which must not pass the allow-list.
# Douyin aweme ids are numeric; the ids we persist as filenames also use
# letters, '_' and '-'. Restrict to exactly those so '.', '/' and '\' can
# never enter an interpolated path. (This is the identifier the API echoes
# back for an already-downloaded video, not raw extractor output.)
_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,128}")
# BCP-47-ish: 'zh', 'en', 'vi', 'vi-VN', 'zh-Hans'. Lowercase primary subtag.
_LANGUAGE_RE = re.compile(r"[a-z]{2,3}(-[A-Za-z]{2,8})?")
# The working draft, or an immutable snapshot slot 'v{N}'. The digit bound
# matches the generator in versions.next_version_id (effectively unbounded;
# 9 digits is far beyond any real version count).
_VERSION_RE = re.compile(r"draft|v[0-9]{1,9}")
# A translation-profile name: it becomes `{name}.yaml` on disk. Slug chars
# only — no '.', '/' or '\' so it cannot escape the profiles directory.
_PROFILE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}")
# A generated dub UUID (uuid4, with dashes) used as a filename stem.
_UUID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


def validate_video_id(video_id: str) -> str:
    """Return ``video_id`` unchanged, or raise 422 if it is not an allowed id."""
    if not isinstance(video_id, str) or not _VIDEO_ID_RE.fullmatch(video_id):
        raise HTTPException(status_code=422, detail=f"Invalid video_id: {video_id!r}")
    return video_id


def validate_language(language: str) -> str:
    """Return ``language`` unchanged, or raise 422 if it is not a language tag."""
    if not isinstance(language, str) or not _LANGUAGE_RE.fullmatch(language):
        raise HTTPException(status_code=422, detail=f"Invalid language: {language!r}")
    return language


def validate_version(version: str) -> str:
    """Return ``version`` unchanged, or raise 422 if it is not 'draft'/'v{N}'."""
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise HTTPException(status_code=422, detail=f"Invalid version: {version!r}")
    return version


def validate_profile_name(name: str) -> str:
    """Return ``name`` unchanged, or raise 422 if it is not a safe profile slug."""
    if not isinstance(name, str) or not _PROFILE_NAME_RE.fullmatch(name):
        raise HTTPException(status_code=422, detail=f"Invalid profile name: {name!r}")
    return name


def validate_uuid(value: str) -> str:
    """Return ``value`` unchanged, or raise 422 if it is not a safe id token."""
    if not isinstance(value, str) or not _UUID_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"Invalid id: {value!r}")
    return value


def ensure_within(base: Path, candidate: Path) -> Path:
    """Return ``candidate`` resolved, or raise 422 if it escapes ``base``.

    A belt-and-braces check behind the allow-list validators: even if a future
    caller forgets to validate, the resolved path must still sit inside
    ``base`` (or equal it) before it is handed to the filesystem.
    """
    base_resolved = base.resolve()
    cand_resolved = candidate.resolve()
    if cand_resolved != base_resolved and base_resolved not in cand_resolved.parents:
        raise HTTPException(
            status_code=422, detail="Resolved path escapes the data directory"
        )
    return cand_resolved
