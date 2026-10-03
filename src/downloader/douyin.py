import os
import re
import uuid
from pathlib import Path

import httpx

from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)

# Byte markers that mean the "video" body is really an HTML/JSON/text error
# or anti-scrape challenge page served with HTTP 200.
_ERROR_MARKERS = (
    b"<!doctype",
    b"<html",
    b"forbidden",
    b"not found",
    b"access denied",
    b"rate limit",
    b"blocked",
)


def _looks_textual(b: bytes) -> bool:
    """True only if every byte is printable ASCII or common whitespace.

    Binary media (an MP4 begins with NUL box-size bytes) is not textual, so the
    plaintext error-marker scan below never runs against it — a real video that
    happens to contain the bytes ``blocked`` in a binary box isn't rejected.
    """
    return bool(b) and all(c in b"\t\n\r\x0b\x0c " or 0x20 <= c <= 0x7E for c in b)


def _validate_download(prefix: bytes, size: int, content_type: str) -> None:
    """Raise ValueError if the downloaded bytes don't look like a real video.

    Deliberately a *negative* check (reject known error shapes) rather than a
    positive MP4 recognizer: box-size prefixes make ``ftyp`` sniffing
    unreliable, and legitimate bodies may arrive as ``application/octet-stream``.
    It does not guarantee every accepted body is a valid video — only that
    obvious HTML/JSON/text error pages are turned away so the fallback runs.
    """
    if size == 0:
        raise ValueError("Downloaded video is empty")
    ct = content_type.lower()
    if "text/html" in ct or "application/json" in ct:
        raise ValueError(f"Download has a non-video content type: {content_type}")
    p = prefix
    if p.startswith(b"\xef\xbb\xbf"):  # strip UTF-8 BOM (lstrip won't)
        p = p[3:]
    p = p.lstrip()
    if not p:
        raise ValueError("Download body is empty/whitespace, not a video")
    if p[:1] in (b"<", b"{", b"["):
        raise ValueError("Download looks like an error/challenge page, not a video")
    head = p[:64]
    # Only match error words in a prefix that is actually text; binary video
    # data must never be rejected on an incidental substring.
    if _looks_textual(head) and any(marker in head.lower() for marker in _ERROR_MARKERS):
        raise ValueError("Download looks like an error response, not a video")


class DouyinDownloader:
    """Downloads Douyin videos via the self-hosted Evil0ctal API."""

    def __init__(
        self,
        api_base: str = "http://localhost:8080",
        cookie_file: str | None = None,
        timeout: int = 120,
    ):
        self.api_base = api_base.rstrip("/")
        self.cookie_file = cookie_file
        self.timeout = timeout

    def _extract_url(self, text: str) -> str:
        """Extract a Douyin URL from share text that may contain extra content.

        Short-link IDs contain ASCII letters/digits/underscores AND dashes
        (e.g. 'SeJ-W3i5s5s'); the character class has to include '-' or
        the regex truncates at the first dash.
        """
        patterns = [
            r"(https?://v\.douyin\.com/[\w-]+/?)",
            r"(https?://www\.douyin\.com/video/\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1)
        raise ValueError(f"No valid Douyin URL found in: {text}")

    def _load_cookie(self) -> str | None:
        """Load cookie from file if configured."""
        if not self.cookie_file:
            return None
        cookie_path = Path(self.cookie_file)
        if cookie_path.exists():
            return cookie_path.read_text().strip()
        return None

    async def download(self, share_url: str, output_dir: Path) -> VideoMetadata:
        """Download a Douyin video.

        Args:
            share_url: Douyin share URL or text containing one.
            output_dir: Directory to save the video.

        Returns:
            VideoMetadata with download info.

        Raises:
            httpx.HTTPStatusError: If API returns error status.
            ValueError: If URL is invalid or video data unavailable.
        """
        url = self._extract_url(share_url)
        output_dir.mkdir(parents=True, exist_ok=True)

        headers = {}
        cookie = self._load_cookie()
        if cookie:
            headers["Cookie"] = cookie

        async with httpx.AsyncClient(
            timeout=self.timeout, headers=headers, follow_redirects=True
        ) as client:
            # Fetch video data from API
            logger.info(f"Fetching video data from Douyin API: {url}")
            api_url = f"{self.api_base}/api/hybrid/video_data"
            response = await client.get(api_url, params={"url": url})
            response.raise_for_status()

            data = response.json()

            # Handle error response format: {"detail": {"code": 400, "message": "..."}}
            if "detail" in data:
                detail = data["detail"]
                error_msg = detail.get("message", "Unknown API error")
                raise ValueError(f"Douyin API error: {error_msg}")

            if data.get("code") != 200:
                error_msg = data.get("message", "Unknown API error")
                raise ValueError(f"Douyin API error: {error_msg}")

            video_data = data.get("data", {})
            video_id = str(video_data.get("aweme_id", ""))
            if not video_id:
                raise ValueError("No video ID in API response")

            # Get watermark-free video URL
            video_url = None
            nwm_urls = video_data.get("video", {}).get("play_addr", {}).get("url_list", [])
            if nwm_urls:
                video_url = nwm_urls[0]

            if not video_url:
                raise ValueError("No video download URL found (may be a slideshow)")

            # Stream download to a unique temp file, validate, then atomically
            # publish. A mid-stream failure leaves only the .part file (cleaned
            # up below), never a truncated {video_id}.mp4 that the yt-dlp
            # fallback would mistake for a finished download.
            output_path = output_dir / f"{video_id}.mp4"
            tmp_path = output_dir / f".{video_id}.{uuid.uuid4().hex}.part"
            logger.info(f"Downloading video {video_id} to {output_path}")
            bytes_written = 0
            sniff = bytearray()  # first 512 bytes, for post-download validation
            try:
                content_type = ""
                async with client.stream("GET", video_url) as stream:
                    stream.raise_for_status()
                    try:
                        content_type = str(stream.headers.get("content-type", "") or "")
                    except Exception:
                        content_type = ""
                    with open(tmp_path, "wb") as f:
                        async for chunk in stream.aiter_bytes(chunk_size=8192):
                            if not chunk:
                                continue
                            if len(sniff) < 512:
                                sniff.extend(chunk[: 512 - len(sniff)])
                            f.write(chunk)
                            bytes_written += len(chunk)
                # Validate the buffered prefix (BOM/whitespace/HTML/JSON/text
                # errors) across chunk boundaries, then publish atomically.
                _validate_download(bytes(sniff), bytes_written, content_type)
                os.replace(tmp_path, output_path)
            except BaseException:
                Path(tmp_path).unlink(missing_ok=True)
                raise

            # Extract metadata
            desc = video_data.get("desc", "")
            hashtags = re.findall(r"#(\w+)", desc)
            author_info = video_data.get("author", {})

            # Extract cover image URL
            cover_urls = (
                video_data.get("video", {}).get("cover", {}).get("url_list", [])
            )
            thumbnail_url = cover_urls[0] if cover_urls else ""

            # Download thumbnail
            if thumbnail_url:
                try:
                    thumb_path = output_dir / f"{video_id}_thumb.jpg"
                    thumb_resp = await client.get(thumbnail_url)
                    thumb_resp.raise_for_status()
                    thumb_path.write_bytes(thumb_resp.content)
                except Exception:
                    thumbnail_url = ""  # Non-fatal, continue without thumbnail

            metadata = VideoMetadata(
                video_id=video_id,
                title=desc.split("#")[0].strip() if desc else "",
                author=author_info.get("nickname", ""),
                duration=video_data.get("video", {}).get("duration", 0) / 1000.0,
                description=desc,
                hashtags=hashtags,
                source_url=url,
                file_path=str(output_path),
                thumbnail_url=thumbnail_url,
            )
            logger.info(f"Downloaded: {metadata.video_id} by {metadata.author}")
            return metadata
