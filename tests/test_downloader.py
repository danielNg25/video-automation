import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.downloader import _clean_url, download_with_fallback
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


    @staticmethod
    def _mock_douyin_client(aweme_id, chunks_or_raiser):
        api_response = {
            "code": 200,
            "data": {
                "aweme_id": aweme_id,
                "desc": "x",
                "author": {"nickname": "u"},
                "video": {"duration": 1000, "play_addr": {"url_list": ["http://e/v.mp4"]}},
            },
        }
        mock_response = MagicMock()
        mock_response.json.return_value = api_response
        mock_response.raise_for_status = MagicMock()

        mock_stream = MagicMock()
        mock_stream.raise_for_status = MagicMock()
        if callable(chunks_or_raiser):
            mock_stream.aiter_bytes = chunks_or_raiser
        else:
            mock_stream.aiter_bytes = lambda chunk_size=8192, _c=chunks_or_raiser: _async_iter(_c)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.stream = MagicMock(return_value=_async_context(mock_stream))
        return mock_client

    @pytest.mark.asyncio
    async def test_download_partial_failure_preserves_existing(self, tmp_path):
        """A mid-stream error must not truncate or remove an existing valid
        {id}.mp4 (which the yt-dlp fallback would otherwise skip)."""
        (tmp_path / "555.mp4").write_bytes(b"GOOD EXISTING VIDEO")
        dl = DouyinDownloader(api_base="http://test:8080")

        async def _boom(chunk_size=8192):
            yield b"partial bytes"
            raise OSError("connection reset mid-stream")

        mock_client = self._mock_douyin_client("555", _boom)
        with patch("src.downloader.douyin.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _async_context(mock_client)
            with pytest.raises(OSError):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        assert (tmp_path / "555.mp4").read_bytes() == b"GOOD EXISTING VIDEO"
        assert not list(tmp_path.glob("*.part"))

    @pytest.mark.parametrize(
        "chunks",
        [
            [b"<!DOCTYPE html><html>blocked</html>"],       # HTML
            [b"\xef\xbb\xbf<html>err</html>"],              # BOM then HTML
            [b"   \n  ", b"<html>later chunk</html>"],      # whitespace chunk, then HTML
            [b"Forbidden"],                                  # plaintext error
            [b"   \n\t  "],                                  # whitespace-only body
            [b'{"error":"nope"}'],                           # JSON error
            [b""],                                           # empty body
        ],
    )
    @pytest.mark.asyncio
    async def test_download_rejects_non_video_bodies(self, tmp_path, chunks):
        """A 200 whose body isn't a video (HTML/JSON/text/empty, with or
        without BOM/leading whitespace) is rejected; an existing file stays."""
        (tmp_path / "666.mp4").write_bytes(b"GOOD EXISTING VIDEO")
        dl = DouyinDownloader(api_base="http://test:8080")
        mock_client = self._mock_douyin_client("666", chunks)
        with patch("src.downloader.douyin.httpx.AsyncClient") as mock_cls:
            mock_cls.return_value = _async_context(mock_client)
            with pytest.raises(ValueError):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        assert (tmp_path / "666.mp4").read_bytes() == b"GOOD EXISTING VIDEO"
        assert not list(tmp_path.glob("*.part"))


class TestYtDlpDownloader:
    """Tests for YtDlpDownloader."""

    @pytest.mark.asyncio
    async def test_download_timeout_kills_subprocess(self, tmp_path):
        """A metadata call that overruns the timeout must kill + reap the child
        and raise, not orphan a running yt-dlp."""
        dl = YtDlpDownloader(timeout=1)

        async def hang():
            await asyncio.sleep(10)
            return (b"", b"")

        proc = AsyncMock()
        proc.returncode = None
        proc.communicate = hang
        proc.pid = 999999  # a real-looking but nonexistent pid
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def mock_create_subprocess(*args, **kwargs):
            return proc

        # Patch os.killpg so the test never signals a real process group.
        with (
            patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mock_create_subprocess),
            patch("src.downloader.ytdlp.os.killpg", side_effect=ProcessLookupError),
        ):
            with pytest.raises(RuntimeError, match="timed out"):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        proc.kill.assert_called_once()  # group-kill fell back to proc.kill
        proc.wait.assert_awaited()  # child is reaped, not orphaned

    @pytest.mark.asyncio
    async def test_download_cancellation_kills_and_propagates(self, tmp_path):
        """Cancellation must kill+reap the child and re-raise CancelledError."""
        dl = YtDlpDownloader(timeout=30)

        async def cancelled():
            raise asyncio.CancelledError()

        proc = AsyncMock()
        proc.returncode = None
        proc.communicate = cancelled
        proc.pid = 999999
        proc.kill = MagicMock()
        proc.wait = AsyncMock()

        async def mk(*a, **k):
            return proc

        with (
            patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mk),
            patch("src.downloader.ytdlp.os.killpg", side_effect=ProcessLookupError),
        ):
            with pytest.raises(asyncio.CancelledError):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        proc.kill.assert_called_once()
        proc.wait.assert_awaited()

    @pytest.mark.asyncio
    async def test_download_failure_cleans_staging_and_preserves_existing(self, tmp_path):
        """A non-zero yt-dlp exit must leave no staging artifacts and not
        clobber an existing final file."""
        (tmp_path / "987654321.mp4").write_bytes(b"GOOD EXISTING")
        dl = YtDlpDownloader()
        meta = {"id": "987654321", "title": "t", "uploader": "u", "duration": 1,
                "width": 1, "height": 1, "description": ""}

        async def meta_comm():
            return (json.dumps(meta).encode(), b"")

        async def dl_comm():
            return (b"", b"boom")

        captured = {}

        async def dl_comm_frag():
            # Simulate yt-dlp leaving its own partial/fragment files in staging.
            argv = list(captured["argv"])
            out = Path(argv[argv.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            (out.parent / (out.name + ".part")).write_bytes(b"frag")
            (out.parent / "987654321.info.json").write_text("{}")
            return (b"", b"boom")

        meta_proc = AsyncMock(); meta_proc.returncode = 0; meta_proc.communicate = meta_comm
        dl_proc = AsyncMock(); dl_proc.returncode = 1; dl_proc.communicate = dl_comm_frag
        n = 0

        async def mk(*a, **k):
            nonlocal n
            n += 1
            if n == 1:
                return meta_proc
            captured["argv"] = a
            return dl_proc

        with patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mk):
            with pytest.raises(RuntimeError, match="download failed"):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        assert (tmp_path / "987654321.mp4").read_bytes() == b"GOOD EXISTING"
        assert not list(tmp_path.glob(".ytdlp-*"))  # staging + fragments gone

    @pytest.mark.asyncio
    async def test_download_sidecar_only_output_rejected(self, tmp_path):
        """Exit zero but only a sidecar (no media file) must not publish."""
        (tmp_path / "987654321.mp4").write_bytes(b"GOOD EXISTING")
        dl = YtDlpDownloader()
        meta = {"id": "987654321", "title": "t", "uploader": "u", "duration": 1,
                "width": 1, "height": 1, "description": ""}
        captured = {}

        async def meta_comm():
            return (json.dumps(meta).encode(), b"")

        async def dl_comm():
            argv = list(captured["argv"])
            out = Path(argv[argv.index("-o") + 1])
            out.parent.mkdir(parents=True, exist_ok=True)
            (out.parent / "987654321.info.json").write_text("{}")  # sidecar only
            return (b"", b"")

        meta_proc = AsyncMock(); meta_proc.returncode = 0; meta_proc.communicate = meta_comm
        dl_proc = AsyncMock(); dl_proc.returncode = 0; dl_proc.communicate = dl_comm
        n = 0

        async def mk(*a, **k):
            nonlocal n
            n += 1
            if n == 1:
                return meta_proc
            captured["argv"] = a
            return dl_proc

        with patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mk):
            with pytest.raises(RuntimeError, match="no / empty output"):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        assert (tmp_path / "987654321.mp4").read_bytes() == b"GOOD EXISTING"
        assert not list(tmp_path.glob(".ytdlp-*"))

    @pytest.mark.asyncio
    async def test_download_empty_output_rejected(self, tmp_path):
        """Exit zero but an empty output file must not replace a real video."""
        (tmp_path / "987654321.mp4").write_bytes(b"GOOD EXISTING")
        dl = YtDlpDownloader()
        meta = {"id": "987654321", "title": "t", "uploader": "u", "duration": 1,
                "width": 1, "height": 1, "description": ""}
        captured = {}

        async def meta_comm():
            return (json.dumps(meta).encode(), b"")

        async def dl_comm():
            out = list(captured["argv"])[list(captured["argv"]).index("-o") + 1]
            Path(out).write_bytes(b"")  # zero-byte output
            return (b"", b"")

        meta_proc = AsyncMock(); meta_proc.returncode = 0; meta_proc.communicate = meta_comm
        dl_proc = AsyncMock(); dl_proc.returncode = 0; dl_proc.communicate = dl_comm
        n = 0

        async def mk(*a, **k):
            nonlocal n
            n += 1
            if n == 1:
                return meta_proc
            captured["argv"] = a
            return dl_proc

        with patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mk):
            with pytest.raises(RuntimeError, match="no / empty output"):
                await dl.download("https://v.douyin.com/test/", tmp_path)

        assert (tmp_path / "987654321.mp4").read_bytes() == b"GOOD EXISTING"
        assert not list(tmp_path.glob(".ytdlp-*"))

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

        captured = {}

        async def mock_dl_communicate():
            # Write to the unique temp path yt-dlp was told to use (-o), so the
            # downloader's atomic os.replace(tmp, final) has something to move.
            argv = list(captured["dl_argv"])
            out = argv[argv.index("-o") + 1]
            Path(out).write_bytes(b"fake video")
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
                captured["meta_argv"] = args
                return meta_proc
            captured["dl_argv"] = args
            return dl_proc

        with patch("src.downloader.ytdlp.asyncio.create_subprocess_exec", mock_create_subprocess):
            result = await dl.download("https://v.douyin.com/test/", tmp_path)

        assert result.video_id == "987654321"
        assert result.title == "Test Title"
        assert result.author == "testuser"
        assert result.duration == 30.0
        assert "video" in result.hashtags
        # Final file is published atomically; no .part left behind.
        assert (tmp_path / "987654321.mp4").exists()
        assert not list(tmp_path.glob("*.part.mp4"))
        # '--' terminates options before the URL in both invocations.
        assert "--" in captured["meta_argv"] and captured["meta_argv"][-1] == "https://v.douyin.com/test/"
        assert "--" in captured["dl_argv"] and captured["dl_argv"][-1] == "https://v.douyin.com/test/"

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


class TestCleanUrl:
    """Tests for _clean_url (share-text → bare URL for yt-dlp)."""

    def test_extracts_url_from_share_text(self):
        assert (
            _clean_url("1.95 复制打开抖音 https://v.douyin.com/SeJ-W3i5s5s/ 看看")
            == "https://v.douyin.com/SeJ-W3i5s5s/"
        )

    def test_passes_through_clean_url(self):
        assert _clean_url("https://www.douyin.com/video/7123") == "https://www.douyin.com/video/7123"

    def test_handles_cjk_punctuation_adjacent_to_douyin_url(self):
        # No space before the Chinese comma — the Douyin pattern stops cleanly.
        assert (
            _clean_url("复制 https://v.douyin.com/abc/，打开抖音")
            == "https://v.douyin.com/abc/"
        )

    def test_does_not_mangle_standalone_url_legal_chars(self):
        # Parentheses and semicolons are legal URL characters and must survive.
        assert (
            _clean_url("https://example.test/video_(2024)")
            == "https://example.test/video_(2024)"
        )
        assert (
            _clean_url("https://example.test/watch?token=abc;v=2")
            == "https://example.test/watch?token=abc;v=2"
        )

    def test_standalone_douyin_url_keeps_query(self):
        # A standalone Douyin URL with a query must not be truncated at the path.
        assert (
            _clean_url("https://v.douyin.com/abc/?token=abc;v=2")
            == "https://v.douyin.com/abc/?token=abc;v=2"
        )

    def test_standalone_url_with_embedded_douyin_is_not_rewritten(self):
        # The outer URL is standalone; the embedded Douyin URL must not win.
        url = "https://example.test/watch?redirect=https://www.douyin.com/video/123"
        assert _clean_url(url) == url

    def test_no_url_returns_stripped_input(self):
        assert _clean_url("  just text  ") == "just text"


class TestDownloadWithFallback:
    """Tests for download_with_fallback."""

    @pytest.mark.asyncio
    async def test_fallback_receives_cleaned_url(self, tmp_path):
        """When falling back to yt-dlp, the bare URL (not the share text) is
        passed."""
        from src.utils.metadata import VideoMetadata

        captured = {}

        async def fake_ytdlp_download(self, url, output_dir):
            captured["url"] = url
            return VideoMetadata(video_id="789", file_path=str(output_dir / "789.mp4"))

        with (
            patch(
                "src.downloader.DouyinDownloader.download",
                new_callable=AsyncMock,
                side_effect=Exception("API down"),
            ),
            patch("src.downloader.YtDlpDownloader.download", fake_ytdlp_download),
        ):
            config = {"douyin": {"api_base": "http://test:8080"}}
            await download_with_fallback(
                "1.9 复制打开抖音 https://v.douyin.com/abc/ 看", tmp_path, config
            )

        assert captured["url"] == "https://v.douyin.com/abc/"

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
