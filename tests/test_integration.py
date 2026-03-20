"""Integration tests using the real Douyin API container.

Requires:
    - Docker running with `docker compose up -d`
    - Douyin API available on localhost:8081

Run with:
    python -m pytest tests/test_integration.py -v -m integration
"""

import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from src.downloader.douyin import DouyinDownloader
from src.downloader.ytdlp import YtDlpDownloader
from src.downloader import download_with_fallback

# Real Douyin share URL for testing
TEST_DOUYIN_URL = "https://v.douyin.com/9FYptzbAPoY/"
API_BASE = "http://localhost:8081"


def api_is_running() -> bool:
    """Check if the Douyin API container is available."""
    try:
        r = httpx.get(f"{API_BASE}/", timeout=5)
        return r.status_code == 200
    except httpx.ConnectError:
        return False


# Skip all tests if API is not running
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not api_is_running(), reason="Douyin API container not running"),
]


@pytest.fixture
def output_dir(tmp_path):
    """Provide a temporary output directory, cleaned up after test."""
    d = tmp_path / "raw"
    d.mkdir()
    yield d


class TestDouyinAPI:
    """Tests that hit the real Douyin API container."""

    @pytest.mark.asyncio
    async def test_api_is_reachable(self):
        """Verify the API container responds."""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{API_BASE}/")
            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_api_hybrid_endpoint_exists(self):
        """Verify the hybrid video_data endpoint is available."""
        async with httpx.AsyncClient() as client:
            # Sending without URL param should still reach the endpoint (may return error)
            response = await client.get(f"{API_BASE}/api/hybrid/video_data")
            # Should get 422 (validation error) not 404
            assert response.status_code != 404

    @pytest.mark.asyncio
    async def test_api_returns_structured_error_for_bad_url(self):
        """API should return a structured error for an invalid URL."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{API_BASE}/api/hybrid/video_data",
                params={"url": "https://v.douyin.com/invalid123/"},
            )
            data = response.json()
            # Error responses use {"detail": {"code": 400, ...}} format
            assert "detail" in data or data.get("code") != 200

    @pytest.mark.asyncio
    async def test_downloader_error_handling_bad_url(self, output_dir):
        """DouyinDownloader should raise ValueError for URLs the API can't resolve."""
        dl = DouyinDownloader(api_base=API_BASE, timeout=60)
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            await dl.download("https://v.douyin.com/invalid123/", output_dir)

    @pytest.mark.asyncio
    async def test_downloader_extract_url_from_share_text(self):
        """URL extraction works with real share text formats."""
        dl = DouyinDownloader(api_base=API_BASE)
        url = dl._extract_url(
            f"7.49 复制打开抖音，看看【某某的作品】 {TEST_DOUYIN_URL} "
        )
        assert "douyin.com" in url

    @pytest.mark.asyncio
    async def test_download_real_video(self, output_dir):
        """Download a real Douyin video via the API.

        This test may fail if:
        - Cookies are expired (API returns empty response)
        - The test URL is no longer available
        - Network issues
        """
        dl = DouyinDownloader(api_base=API_BASE, timeout=120)
        try:
            metadata = await dl.download(TEST_DOUYIN_URL, output_dir)

            # Verify metadata
            assert metadata.video_id
            assert metadata.file_path
            assert Path(metadata.file_path).exists()
            assert Path(metadata.file_path).stat().st_size > 0

            # Verify it's a real video file (check magic bytes)
            with open(metadata.file_path, "rb") as f:
                header = f.read(12)
            # MP4 files contain 'ftyp' in first 12 bytes
            assert b"ftyp" in header, "Downloaded file is not a valid MP4"

        except ValueError as e:
            if "API error" in str(e) or "cookie" in str(e).lower():
                pytest.skip(f"API error (likely needs cookies): {e}")
            raise


class TestYtDlpIntegration:
    """Integration tests for yt-dlp fallback."""

    @pytest.mark.asyncio
    async def test_ytdlp_download(self, output_dir):
        """Download a real video via yt-dlp."""
        dl = YtDlpDownloader(timeout=120)
        try:
            metadata = await dl.download(TEST_DOUYIN_URL, output_dir)

            assert metadata.video_id
            assert metadata.file_path
            assert Path(metadata.file_path).exists()
            assert Path(metadata.file_path).stat().st_size > 0

        except RuntimeError as e:
            if "yt-dlp" in str(e).lower():
                pytest.skip(f"yt-dlp failed (may need cookies or URL expired): {e}")
            raise


class TestFallbackIntegration:
    """Integration tests for the download_with_fallback chain."""

    @pytest.mark.asyncio
    async def test_fallback_chain(self, output_dir):
        """Test the full fallback chain with a real URL.

        Should try Douyin API first, fall back to yt-dlp if needed.
        """
        config = {
            "douyin": {
                "api_base": API_BASE,
                "download_timeout": 120,
            }
        }
        try:
            metadata = await download_with_fallback(TEST_DOUYIN_URL, output_dir, config)

            assert metadata.video_id
            assert metadata.file_path
            assert Path(metadata.file_path).exists()

        except RuntimeError as e:
            pytest.skip(f"Both downloaders failed (may need cookies): {e}")
