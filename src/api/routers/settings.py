"""Settings endpoints — config management, Douyin cookie, system info."""

from __future__ import annotations

import copy
import os
import re
import sys
from pathlib import Path

import httpx
import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import get_config, reload_config
from src.utils.config import load_raw_config, save_config

router = APIRouter()


# --- Models ---


class CookieStatus(BaseModel):
    exists: bool
    preview: str  # masked, e.g. "sid_gua...kd93x"
    length: int
    file_path: str
    helper_config_synced: bool = False  # True when douyin_web_config.yaml was updated too


class CookieUpdate(BaseModel):
    cookie: str


class CookieTestResult(BaseModel):
    success: bool
    message: str


# --- Helpers ---


def _cookie_path() -> Path:
    config = get_config()
    return Path(config.get("douyin", {}).get("cookie_file", "config/douyin_cookie.txt"))


def _helper_config_path() -> Path:
    """Path to the evil0ctal douyin-api container's bind-mounted config."""
    return Path("config/douyin_web_config.yaml")


def _splice_cookie_into_helper_config(cookie: str) -> bool:
    """Rewrite the `Cookie:` line in config/douyin_web_config.yaml in place.

    The helper API container reads its cookie from that YAML at startup, so
    keeping it in sync with the FE-managed cookie removes the "nano in WSL"
    setup step on fresh machines. Uses a regex line-rewrite to preserve
    comments and field ordering (yaml.dump would strip both).

    Returns True if the file existed and was rewritten, False if the file
    isn't present (e.g. user hasn't run `make setup` and the bind mount is
    disabled). Callers should not treat False as an error — the yt-dlp
    fallback still works without the helper config.
    """
    path = _helper_config_path()
    if not path.exists():
        return False

    text = path.read_text()
    # Match the indented `Cookie: ...` line under TokenManager.douyin.headers.
    # The cookie value is a single line of opaque token=value; pairs — anything
    # up to EOL after `Cookie:` is the payload.
    new_text, n = re.subn(
        r"(?m)^(\s*Cookie:\s*).*$",
        lambda m: m.group(1) + cookie,
        text,
        count=1,
    )
    if n == 0:
        # File exists but the marker line isn't where we expect — bail rather
        # than corrupting the YAML. The user can still hand-edit.
        return False
    path.write_text(new_text)
    return True


def _mask_cookie(raw: str) -> str:
    """Show first 8 and last 6 chars, mask the rest."""
    if len(raw) <= 20:
        return "***"
    return f"{raw[:8]}...{raw[-6:]}"


# --- Endpoints ---


@router.get("/api/settings/cookie", response_model=CookieStatus)
async def get_cookie_status():
    path = _cookie_path()
    helper_synced = _helper_config_has_real_cookie()
    if not path.exists():
        return CookieStatus(
            exists=False, preview="", length=0,
            file_path=str(path.resolve()),
            helper_config_synced=helper_synced,
        )
    raw = path.read_text().strip()
    return CookieStatus(
        exists=bool(raw),
        preview=_mask_cookie(raw) if raw else "",
        length=len(raw),
        file_path=str(path.resolve()),
        helper_config_synced=helper_synced,
    )


def _helper_config_has_real_cookie() -> bool:
    """True iff douyin_web_config.yaml exists and has a non-placeholder Cookie."""
    path = _helper_config_path()
    if not path.exists():
        return False
    m = re.search(r"(?m)^\s*Cookie:\s*(.+)$", path.read_text())
    if not m:
        return False
    value = m.group(1).strip()
    return bool(value) and value != "PASTE_YOUR_DOUYIN_COOKIE_HERE"


@router.put("/api/settings/cookie", response_model=CookieStatus)
async def update_cookie(body: CookieUpdate):
    cookie = body.cookie.strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie string cannot be empty")
    path = _cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookie + "\n")
    helper_synced = _splice_cookie_into_helper_config(cookie)
    return CookieStatus(
        exists=True,
        preview=_mask_cookie(cookie),
        length=len(cookie),
        file_path=str(path.resolve()),
        helper_config_synced=helper_synced,
    )


@router.post("/api/settings/cookie/test", response_model=CookieTestResult)
async def test_cookie():
    """Hit the Douyin API with the current cookie to verify it works."""
    path = _cookie_path()
    if not path.exists() or not path.read_text().strip():
        return CookieTestResult(success=False, message="No cookie file found")

    config = get_config()
    api_base = config.get("douyin", {}).get("api_base", "http://localhost:8080")
    cookie = path.read_text().strip()

    test_url = "https://www.douyin.com/video/7339929467978498304"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{api_base}/api/hybrid/video_data",
                params={"url": test_url},
                headers={"Cookie": cookie},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == 200:
                nickname = (
                    data.get("data", {}).get("author", {}).get("nickname", "unknown")
                )
                return CookieTestResult(
                    success=True,
                    message=f"Cookie valid — fetched video by {nickname}",
                )
            return CookieTestResult(
                success=False,
                message=data.get("message", "API returned non-200"),
            )
    except httpx.ConnectError:
        return CookieTestResult(
            success=False,
            message=f"Cannot connect to Douyin API at {api_base}",
        )
    except Exception as e:
        return CookieTestResult(success=False, message=str(e))


@router.get("/api/settings/platform")
async def get_platform():
    """Return server platform for UI to select correct local model presets."""
    return {"platform": sys.platform}  # "darwin" or "linux"


def _config_path() -> str:
    """Return the active config file path."""
    path = "config/config.yaml"
    if not os.path.exists(path):
        path = "config/config.example.yaml"
    return path


@router.get("/api/settings/config")
async def get_config_endpoint():
    """Return the raw config (without env var interpolation) for editing.

    Secrets are redacted: values matching ${...} patterns and known secret
    paths (tokens, keys, secrets) are replaced with '***'.
    """
    raw = load_raw_config(_config_path())
    return _redact_secrets(raw)


@router.get("/api/config")
async def get_config_alias():
    """Alias for /api/settings/config (plan specifies /api/config)."""
    raw = load_raw_config(_config_path())
    return _redact_secrets(raw)


@router.put("/api/settings/config")
async def update_config(body: dict):
    """Merge provided config sections into config.yaml and reload."""
    path = "config/config.yaml"
    # Load existing config (raw, no env interpolation)
    existing = load_raw_config(path) if os.path.exists(path) else load_raw_config(
        "config/config.example.yaml"
    )

    # Deep merge: update top-level sections, merge nested dicts
    _deep_merge(existing, body)

    save_config(existing, path)
    reload_config()
    return {"status": "ok", "message": "Config saved"}


@router.put("/api/config")
async def update_config_alias(body: dict):
    """Alias for /api/settings/config."""
    return await update_config(body)


@router.get("/api/config/platforms")
async def get_platform_configs():
    """Return platform configs from platforms.yaml."""
    platforms_path = Path("config/platforms.yaml")
    if not platforms_path.exists():
        return {}
    with open(platforms_path) as f:
        return yaml.safe_load(f) or {}


# --- Secret redaction ---

SECRET_KEYS = re.compile(
    r"(api_key|secret|token|password|credential|auth)",
    re.IGNORECASE,
)


def _redact_secrets(obj: dict | list | str, parent_key: str = "") -> dict | list | str:
    """Recursively redact secret values in a config dict."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            result[k] = _redact_secrets(v, k)
        return result
    elif isinstance(obj, list):
        return [_redact_secrets(item, parent_key) for item in obj]
    elif isinstance(obj, str):
        # Redact ${ENV_VAR} interpolation patterns
        if obj.startswith("${") and obj.endswith("}"):
            return "***"
        # Redact values under known secret keys
        if SECRET_KEYS.search(parent_key) and obj:
            return "***"
        return obj
    return obj


def _deep_merge(base: dict, override: dict) -> None:
    """Deep merge override into base dict, modifying base in place.

    Skips '***' values (redacted secrets that shouldn't overwrite real values).
    """
    for key, value in override.items():
        if value == "***":
            continue  # Don't overwrite real secrets with redacted placeholder
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
