import re
from pathlib import Path

from src.downloader.douyin import DouyinDownloader
from src.downloader.ytdlp import YtDlpDownloader
from src.utils.logger import setup_logger
from src.utils.metadata import VideoMetadata

logger = setup_logger(__name__)

_DOUYIN_URL_RES = (
    re.compile(r"https?://v\.douyin\.com/[\w-]+/?"),
    re.compile(r"https?://www\.douyin\.com/video/\d+"),
)
_URL_RE = re.compile(r"https?://\S+")


def _clean_url(text: str) -> str:
    """Extract a bare URL from share text for yt-dlp.

    Douyin shares arrive as prose like '1.9 复制打开抖音 https://v.douyin.com/x/，看看';
    the Douyin-specific patterns stop at the real URL boundary (even when the
    following character is CJK punctuation with no space). A standalone URL is
    returned verbatim so legal characters like '(' ')' ';' in query strings or
    paths are never stripped. Only as a last resort does it grab the first
    whitespace-delimited http(s) token.
    """
    stripped = text.strip()
    # A standalone URL (no surrounding prose) is returned verbatim FIRST, so a
    # query string, embedded URL, or legal chars like '(' ')' ';' are never
    # truncated or rewritten.
    if stripped.startswith(("http://", "https://")) and not any(
        c.isspace() for c in stripped
    ):
        return stripped
    # Otherwise it's share prose: the Douyin patterns stop at the real URL
    # boundary even against adjacent CJK punctuation.
    for pat in _DOUYIN_URL_RES:
        m = pat.search(text)
        if m:
            return m.group(0)
    m = _URL_RE.search(text)
    return m.group(0) if m else stripped


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
        return await fallback.download(_clean_url(url), output_dir)
    except Exception as e:
        error_str = str(e)
        if "cookie" in error_str.lower() or "Fresh cookies" in error_str:
            cookie_path = douyin_cfg.get("cookie_file", "config/douyin_cookie.txt")
            raise RuntimeError(
                f"Douyin cookies expired. Please refresh cookies in '{cookie_path}' "
                f"by logging into douyin.com and exporting fresh cookies."
            ) from e
        raise RuntimeError(f"All downloaders failed for {url}: {e}") from e
