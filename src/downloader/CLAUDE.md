# Downloader Module

Downloads Douyin videos and extracts metadata.

## Key Components

- `douyin.py` — `DouyinDownloader`: async HTTP client calling self-hosted Evil0ctal API at `localhost:8080`. Posts share URL to `/api/hybrid/video_data`, extracts watermark-free MP4 URL, stream-downloads to `data/raw/{video_id}.mp4`.
- `ytdlp.py` — `YtDlpDownloader`: fallback using `yt-dlp` CLI via subprocess. Auto-triggered when the Douyin API fails (cookie expiry, anti-scraping changes).
- `__init__.py` — `download_with_fallback()`: tries Douyin API first, falls back to yt-dlp. Both return the same `VideoMetadata` dataclass.

## Constraints

- Douyin API requires valid cookies (expire frequently). Cookie refresh script at `scripts/refresh_douyin_cookie.py`.
- Always stream-download large files — never load entire MP4 into memory.
- Video IDs (numeric) are used for filenames, not titles (which may contain special characters).
- Pin the Docker image version for the Douyin API — `latest` can break without warning.

## Connects To

- **Input**: Douyin share URLs from CLI or batch file
- **Output**: `VideoMetadata` dataclass → consumed by `transcriber` and `pipeline.py`
