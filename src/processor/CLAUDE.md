# Processor Module

Parses/styles subtitles and burns them into video via ffmpeg, reformatting per platform.

## Key Components

- `subtitle.py` — SRT parsing, SRT→ASS conversion with styling, dual-line merging (en+vi), per-platform subtitle language selection, line-breaking (~40 chars for Latin text).
- `ffmpeg.py` — `FFmpegProcessor`: wraps ffmpeg subprocess calls. `burn_subtitles()`, `reformat_for_platform()`, `burn_and_reformat()` (single-pass), `get_video_info()` via ffprobe.
- `__init__.py` — `process_for_all_platforms()`: one source video → multiple platform outputs.

## Platform Specs

| Platform | Resolution | CRF | Max Bitrate | Max Duration | Max Size | Subtitle Lang |
|----------|-----------|-----|------------|-------------|---------|---------------|
| tiktok | 1080x1920 | 23 | 8M | 600s | 4GB | Vietnamese (vi) |
| youtube | 1080x1920 | 20 | 12M | — | 256GB | English (en) |
| facebook | 1080x1920 | 23 | 8M | 900s | 4GB | Vietnamese (vi) |
| x | 1080x1920 | 26 | 4M | 140s | 512MB | English (en) |

## Constraints

- Subtitle language per platform: Vietnamese for TikTok/Facebook, English for YouTube/X (configured in `config/platforms.yaml`).
- Default font: Arial (supports English + Vietnamese diacritics). No CJK fonts needed.
- X/Twitter: truncates video to 140s with a logged warning.
- Styling config from `config/subtitle_styles.yaml` (ASS format).

## Connects To

- **Input**: MP4 from `data/raw/`, SRT from `data/srt/`
- **Output**: Platform-specific MP4s in `data/output/{id}_{platform}.mp4` (downloaded/uploaded manually — auto-posting is out of scope)
