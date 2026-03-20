# Processor Module

Parses/styles subtitles and burns them into video via ffmpeg, reformatting per platform.

## Key Components

- `subtitle.py` — SRT parsing, SRT→ASS conversion with styling, dual-line merging (zh+en), per-platform subtitle language selection, CJK line-breaking (~20 chars), `ensure_cjk_fonts()` check.
- `ffmpeg.py` — `FFmpegProcessor`: wraps ffmpeg subprocess calls. `burn_subtitles()`, `reformat_for_platform()`, `burn_and_reformat()` (single-pass), `get_video_info()` via ffprobe.
- `__init__.py` — `process_for_all_platforms()`: one source video → multiple platform outputs.

## Platform Specs

| Platform | Resolution | CRF | Max Duration | Max Size |
|----------|-----------|-----|-------------|---------|
| tiktok | 1080x1920 | 23 | 600s | 4GB |
| youtube | 1080x1920 | 20 | — | 256GB |
| facebook | 1080x1920 | 23 | 900s | 4GB |
| x | 1080x1920 | 26 | 140s | 512MB |

## Constraints

- Subtitle language per platform: Chinese for TikTok, English for others (configured in `config/platforms.yaml`).
- Noto Sans CJK font must be installed. `ensure_cjk_fonts()` checks and raises clear error if missing.
- X/Twitter: truncates video to 140s with a logged warning.
- Styling config from `config/subtitle_styles.yaml` (ASS format).

## Connects To

- **Input**: MP4 from `data/raw/`, SRT from `data/srt/`
- **Output**: Platform-specific MP4s in `data/output/{id}_{platform}.mp4` → consumed by `uploader`
