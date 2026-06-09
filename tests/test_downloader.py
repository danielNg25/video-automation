import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.downloader import download_with_fallback
from src.downloader.douyin import DouyinDownloader
from src.downloader.ytdlp import YtDlpDownloader


class TestDouyinDownloader:
    """Tests for DouyinDownloader."""

    def test_extract_url_short_link(self):
        dl = DouyinDownloader()
        url = dl._extract_url("Check this out https://v.douyin.com/iRNBho6t/ amazing")
        assert url == "https://v.douyin.com/iRNBho6t/"

    def test_extract_url_full_link(self):
        dl = DouyinDownloader()
        url = dl._extract_url("https://www.douyin.com/video/7123456789012345678")
        assert url == "https://www.douyin.com/video/7123456789012345678"

    def test_extract_url_invalid(self):
        dl = DouyinDownloader()
        with pytest.raises(ValueError, match="No valid Douyin URL"):
            dl._extract_url("not a valid url")

    def test_extract_url_bare_short_link(self):
        dl = DouyinDownloader()
        url = dl._extract_url("https://v.douyin.com/abc123/")
        assert url == "https://v.douyin.com/abc123/"

    def test_extract_url_short_link_with_dash(self):
        """Real Douyin short links can contain hyphens — the regex must
        include '-' in the ID character class or it truncates at the dash."""
        dl = DouyinDownloader()
        url = dl._extract_url("https://v.douyin.com/SeJ-W3i5s5s/")
        assert url == "https://v.douyin.com/SeJ-W3i5s5s/"

    def test_extract_url_short_link_with_dash_in_share_text(self):
        dl = DouyinDownloader()
        url = dl._extract_url(
            "1.95 复制打开抖音 https://v.douyin.com/SeJ-W3i5s5s/ 看看"
        )
        assert url == "https://v.douyin.com/SeJ-W3i5s5s/"

    @pytest.mark.asyncio
    async def test_download_success(self, tmp_path):
        dl = DouyinDownloader(api_base="http://test:8080")

        api_response = {
            "code": 200,
            "data": {
                "aweme_id": "7123456789",
                "desc": "Test video #cool #fun",
                "author": {"nickname": "testuser"},
                "video": {
                    "duration": 15000,
                    "play_addr": {"url_list": ["http://example.com/video.mp4"]},
                },
            },
        }

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_stream = MagicMock()
        mock_stream.raise_for_status = MagicMock()
        mock_stream.aiter_bytes = lambda chunk_size=8192: _async_iter([b"fake video data"])

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.stream = MagicMock(return_value=_async_context(mock_stream))

        with patch("src.downloader.douyin.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _async_context(mock_client)
            result = await dl.download("https://v.douyin.com/test/", tmp_path)

        assert result.video_id == "7123456789"
        assert result.author == "testuser"
        assert result.duration == 15.0
        assert "cool" in result.hashtags
        assert "fun" in result.hashtags
        assert Path(result.file_path).name == "7123456789.mp4"

    @pytest.mark.asyncio
    async def test_download_api_error(self, tmp_path):
        dl = DouyinDownloader(api_base="http://test:8080")

        api_response = {"code": 400, "message": "Invalid URL"}

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("src.downloader.douyin.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _async_context(mock_client)
            with pytest.raises(ValueError, match="Douyin API error"):
                await dl.download("https://v.douyin.com/test/", tmp_path)

    @pytest.mark.asyncio
    async def test_download_no_video_url(self, tmp_path):
        """Slideshow videos have no video URL."""
        dl = DouyinDownloader(api_base="http://test:8080")

        api_response = {
            "code": 200,
            "data": {
                "aweme_id": "123",
                "desc": "slideshow",
                "author": {},
                "video": {"play_addr": {"url_list": []}},
            },
        }

        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("src.downloader.douyin.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _async_context(mock_client)
            with pytest.raises(ValueError, match="slideshow"):
                await dl.download("https://v.douyin.com/test/", tmp_path)


class TestYtDlpDownloader:
    """Tests for YtDlpDownloader."""

    @pytest.mark.asyncio
    async def test_download_success(self, tmp_path):
        dl = YtDlpDownloader()

        meta_info = {
            "id": "987654321",
            "title": "Test Title",
            "uploader": "testuser",
            "duration": 30,
            "width": 1080,
            "height": 1920,
            "description": "A test #video",
        }

        async def mock_meta_communicate():
            return (json.dumps(meta_info).encode(), b"")

        async def mock_dl_communicate():
            # Create the output file to simulate download
            (tmp_path / "987654321.mp4").write_bytes(b"fake video")
            return (b"", b"")

        meta_proc = AsyncMock()
        meta_proc.returncode = 0
        meta_proc.communicate = mock_meta_communicate

        dl_proc = AsyncMock()
        dl_proc.returncode = 0
        dl_proc.communicate = mock_dl_communicate

        call_count = 0

        async def mock_create_subprocess(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return meta_proc
            return dl_proc

        with patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mock_create_subprocess):
            result = await dl.download("https://v.douyin.com/test/", tmp_path)

        assert result.video_id == "987654321"
        assert result.title == "Test Title"
        assert result.author == "testuser"
        assert result.duration == 30.0
        assert "video" in result.hashtags

    @pytest.mark.asyncio
    async def test_download_metadata_failure(self, tmp_path):
        dl = YtDlpDownloader()

        meta_proc = AsyncMock()
        meta_proc.returncode = 1

        async def mock_communicate():
            return (b"", b"Error: not found")

        meta_proc.communicate = mock_communicate

        with patch(
            "src.downloader.ytdlp.asyncio.create_subprocess_exec",
            return_value=meta_proc,
        ):
            with pytest.raises(RuntimeError, match="yt-dlp metadata failed"):
                await dl.download("https://v.douyin.com/bad/", tmp_path)


class TestDownloadWithFallback:
    """Tests for download_with_fallback."""

    @pytest.mark.asyncio
    async def test_primary_succeeds(self, tmp_path):
        from src.utils.metadata import VideoMetadata

        expected = VideoMetadata(video_id="123", file_path=str(tmp_path / "123.mp4"))

        with patch("src.downloader.DouyinDownloader.download", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = expected
            config = {"douyin": {"api_base": "http://test:8080"}}
            result = await download_with_fallback("https://v.douyin.com/test/", tmp_path, config)

        assert result.video_id == "123"

    @pytest.mark.asyncio
    async def test_fallback_on_primary_failure(self, tmp_path):
        from src.utils.metadata import VideoMetadata

        expected = VideoMetadata(video_id="456", file_path=str(tmp_path / "456.mp4"))

        with (
            patch(
                "src.downloader.DouyinDownloader.download",
                new_callable=AsyncMock,
                side_effect=Exception("API down"),
            ),
            patch(
                "src.downloader.YtDlpDownloader.download",
                new_callable=AsyncMock,
                return_value=expected,
            ),
        ):
            config = {"douyin": {"api_base": "http://test:8080"}}
            result = await download_with_fallback("https://v.douyin.com/test/", tmp_path, config)

        assert result.video_id == "456"

    @pytest.mark.asyncio
    async def test_both_fail(self, tmp_path):
        with (
            patch(
                "src.downloader.DouyinDownloader.download",
                new_callable=AsyncMock,
                side_effect=Exception("API down"),
            ),
            patch(
                "src.downloader.YtDlpDownloader.download",
                new_callable=AsyncMock,
                side_effect=Exception("yt-dlp failed"),
            ),
        ):
            config = {"douyin": {"api_base": "http://test:8080"}}
            with pytest.raises(RuntimeError, match="All downloaders failed"):
                await download_with_fallback("https://v.douyin.com/test/", tmp_path, config)


# --- Helpers ---


async def _async_iter(items):
    for item in items:
        yield item


class _async_context:
    """Helper to make a mock work as both async context manager and regular call."""

    def __init__(self, obj):
        self.obj = obj

    async def __aenter__(self):
        return self.obj

    async def __aexit__(self, *args):
        pass

    def __call__(self, *args, **kwargs):
        return self
