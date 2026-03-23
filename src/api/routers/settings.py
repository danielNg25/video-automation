"""Settings endpoints — Douyin cookie management + system info."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.deps import get_config

router = APIRouter()


# --- Models ---


class CookieStatus(BaseModel):
    exists: bool
    preview: str  # masked, e.g. "sid_gua...kd93x"
    length: int
    file_path: str


class CookieUpdate(BaseModel):
    cookie: str


class CookieTestResult(BaseModel):
    success: bool
    message: str


# --- Helpers ---


def _cookie_path() -> Path:
    config = get_config()
    return Path(config.get("douyin", {}).get("cookie_file", "config/douyin_cookie.txt"))


def _mask_cookie(raw: str) -> str:
    """Show first 8 and last 6 chars, mask the rest."""
    if len(raw) <= 20:
        return "***"
    return f"{raw[:8]}...{raw[-6:]}"


# --- Endpoints ---


@router.get("/api/settings/cookie", response_model=CookieStatus)
async def get_cookie_status():
    path = _cookie_path()
    if not path.exists():
        return CookieStatus(exists=False, preview="", length=0, file_path=str(path.resolve()))
    raw = path.read_text().strip()
    return CookieStatus(
        exists=bool(raw),
        preview=_mask_cookie(raw) if raw else "",
        length=len(raw),
        file_path=str(path.resolve()),
    )


@router.put("/api/settings/cookie", response_model=CookieStatus)
async def update_cookie(body: CookieUpdate):
    cookie = body.cookie.strip()
    if not cookie:
        raise HTTPException(status_code=400, detail="Cookie string cannot be empty")
    path = _cookie_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookie + "\n")
    return CookieStatus(
        exists=True,
        preview=_mask_cookie(cookie),
        length=len(cookie),
        file_path=str(path.resolve()),
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
