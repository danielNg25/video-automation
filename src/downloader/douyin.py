import re
from pathlib import Path

import httpx

from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)


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
        """Extract a Douyin URL from share text that may contain extra content."""
        patterns = [
            r"(https?://v\.douyin\.com/[\w]+/?)",
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

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:
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

            # Stream download
            output_path = output_dir / f"{video_id}.mp4"
            logger.info(f"Downloading video {video_id} to {output_path}")
            async with client.stream("GET", video_url) as stream:
                stream.raise_for_status()
                with open(output_path, "wb") as f:
                    async for chunk in stream.aiter_bytes(chunk_size=8192):
                        f.write(chunk)

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
