import asyncio
import json
import re
from pathlib import Path

from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)


class YtDlpDownloader:
    """Downloads videos using yt-dlp CLI as a fallback."""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout

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

        # First, dump JSON metadata
        logger.info(f"Fetching metadata via yt-dlp: {url}")
        meta_proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
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
        )
        logger.info(f"Downloaded via yt-dlp: {metadata.video_id}")
        return metadata
