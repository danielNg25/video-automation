from pathlib import Path

from src.downloader.douyin import DouyinDownloader
from src.downloader.ytdlp import YtDlpDownloader
from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)


def get_downloader(config: dict) -> DouyinDownloader | YtDlpDownloader:
    """Return the appropriate downloader based on config.

    Args:
        config: Full config dict (expects 'douyin' section).

    Returns:
        Configured downloader instance.
    """
    douyin_cfg = config.get("douyin", {})
    return DouyinDownloader(
        api_base=douyin_cfg.get("api_base", "http://localhost:8080"),
        cookie_file=douyin_cfg.get("cookie_file"),
        timeout=douyin_cfg.get("download_timeout", 120),
    )


async def download_with_fallback(url: str, output_dir: Path, config: dict) -> VideoMetadata:
    """Download a video, trying Douyin API first then falling back to yt-dlp.

    Args:
        url: Video URL or share text.
        output_dir: Directory to save the video.
        config: Full config dict.

    Returns:
        VideoMetadata from whichever downloader succeeds.

    Raises:
        RuntimeError: If both downloaders fail.
    """
    # Try Douyin API first
    try:
        downloader = get_downloader(config)
        return await downloader.download(url, output_dir)
    except Exception as e:
        logger.warning(f"Douyin API failed, falling back to yt-dlp: {e}")

    # Fallback to yt-dlp
    try:
        douyin_cfg = config.get("douyin", {})
        timeout = douyin_cfg.get("download_timeout", 120)
        cookie_file = douyin_cfg.get("cookie_file")
        fallback = YtDlpDownloader(timeout=timeout, cookie_file=cookie_file)
        return await fallback.download(url, output_dir)
    except Exception as e:
        error_str = str(e)
        if "cookie" in error_str.lower() or "Fresh cookies" in error_str:
            cookie_path = douyin_cfg.get("cookie_file", "config/douyin_cookie.txt")
            raise RuntimeError(
                f"Douyin cookies expired. Please refresh cookies in '{cookie_path}' "
                f"by logging into douyin.com and exporting fresh cookies."
            ) from e
        raise RuntimeError(f"All downloaders failed for {url}: {e}") from e
