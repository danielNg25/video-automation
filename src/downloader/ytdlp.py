import asyncio
import json
import re
import tempfile
from pathlib import Path

import httpx

from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)


def _raw_cookies_to_netscape(raw_cookie: str, domain: str = ".douyin.com") -> str:
    """Convert a raw Cookie header string to Netscape cookie file format."""
    lines = ["# Netscape HTTP Cookie File"]
    for pair in raw_cookie.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, value = pair.split("=", 1)
        lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name.strip()}\t{value.strip()}")
    return "\n".join(lines) + "\n"


class YtDlpDownloader:
    """Downloads videos using yt-dlp CLI as a fallback."""

    def __init__(self, timeout: int = 120, cookie_file: str | None = None):
        self.timeout = timeout
        self.cookie_file = cookie_file

    def _build_cookie_args(self) -> tuple[list[str], str | None]:
        """Build yt-dlp cookie args from cookie file.

        Returns (args_list, temp_file_path_or_None).
        The caller must clean up the temp file if returned.
        """
        if not self.cookie_file:
            return [], None
        cookie_path = Path(self.cookie_file)
        if not cookie_path.exists():
            return [], None

        content = cookie_path.read_text().strip()
        if content.startswith("# Netscape") or content.startswith("# HTTP Cookie"):
            # Already in Netscape format
            return ["--cookies", str(cookie_path)], None

        # Raw header format — convert to Netscape temp file
        netscape = _raw_cookies_to_netscape(content)
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix="_cookies.txt", delete=False
        )
        tmp.write(netscape)
        tmp.close()
        logger.info(f"Converted raw cookies to Netscape format: {tmp.name}")
        return ["--cookies", tmp.name], tmp.name

    async def download(self, url: str, output_dir: Path) -> VideoMetadata:
        """Download a video using yt-dlp.

        Args:
            url: Video URL (Douyin or other supported sites).
            output_dir: Directory to save the video.

        Returns:
            VideoMetadata with download info.

        Raises:
            RuntimeError: If yt-dlp fails.
        """
        output_dir.mkdir(parents=True, exist_ok=True)

        cookie_args, tmp_cookie_path = self._build_cookie_args()
        try:
            return await self._do_download(url, output_dir, cookie_args)
        finally:
            if tmp_cookie_path:
                Path(tmp_cookie_path).unlink(missing_ok=True)

    async def _do_download(
        self, url: str, output_dir: Path, cookie_args: list[str]
    ) -> VideoMetadata:

        # First, dump JSON metadata
        logger.info(f"Fetching metadata via yt-dlp: {url}")
        meta_proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            *cookie_args,
            "--dump-json",
            "--no-download",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(meta_proc.communicate(), timeout=self.timeout)

        if meta_proc.returncode != 0:
            raise RuntimeError(f"yt-dlp metadata failed: {stderr.decode()}")

        info = json.loads(stdout.decode())
        video_id = str(info.get("id", "unknown"))
        output_path = output_dir / f"{video_id}.mp4"

        # Download video
        logger.info(f"Downloading video {video_id} via yt-dlp")
        dl_proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            *cookie_args,
            "-o",
            str(output_path),
            "--merge-output-format",
            "mp4",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(dl_proc.communicate(), timeout=self.timeout)

        if dl_proc.returncode != 0:
            raise RuntimeError(f"yt-dlp download failed: {stderr.decode()}")

        # Build metadata
        desc = info.get("description", "")
        hashtags = re.findall(r"#(\w+)", desc)

        # Download thumbnail
        thumbnail_url = info.get("thumbnail", "")
        if thumbnail_url:
            try:
                thumb_path = output_dir / f"{video_id}_thumb.jpg"
                async with httpx.AsyncClient() as client:
                    resp = await client.get(thumbnail_url)
                    resp.raise_for_status()
                    thumb_path.write_bytes(resp.content)
            except Exception:
                thumbnail_url = ""

        metadata = VideoMetadata(
            video_id=video_id,
            title=info.get("title", ""),
            author=info.get("uploader", ""),
            duration=float(info.get("duration", 0)),
            resolution=f"{info.get('width', 0)}x{info.get('height', 0)}",
            description=desc,
            hashtags=hashtags,
            source_url=url,
            file_path=str(output_path),
            thumbnail_url=thumbnail_url,
        )
        logger.info(f"Downloaded via yt-dlp: {metadata.video_id}")
        return metadata
