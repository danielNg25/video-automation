# Douyin Video Repurposing Pipeline — Implementation Plan

## Overview

Automated pipeline to download videos from Douyin, generate AI subtitles (Chinese transcription + optional English translation), burn subtitles into the video, and upload to Facebook, X (Twitter), YouTube, and TikTok.

**Tech Stack**: Python 3.11+, faster-whisper (Linux) / mlx-whisper (macOS), ffmpeg, platform-native APIs
**Frontend**: React + Vite + Tailwind CSS + shadcn/ui
**API**: FastAPI + SSE (Server-Sent Events) for real-time progress
**Architecture**: Web UI + REST API + modular pipeline backend
**Environments**: macOS (Apple Silicon) for development, Linux for production
**Estimated Timeline**: 5 weeks

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [Project Structure](#2-project-structure)
3. [Phase 1 — Core: Download + Transcribe](#3-phase-1--core-download--transcribe-week-1-2)
4. [Phase 2 — Subtitle Burn-in + Reformat](#4-phase-2--subtitle-burn-in--reformat-week-2-3)
5. [Phase 3 — Platform Upload Integrations](#5-phase-3--platform-upload-integrations-week-3-4)
6. [Phase 4 — Orchestration + Batch Processing](#6-phase-4--orchestration--batch-processing-week-4-5)
7. [Phase 5 — TTS Dubbing](#7-phase-5--tts-dubbing-week-5-6)
8. [Platform API Reference](#8-platform-api-reference)
9. [Configuration](#9-configuration)
10. [Dependencies](#10-dependencies)
10. [Web UI + API Layer](#10-web-ui--api-layer)
11. [Risks & Mitigations](#11-risks--mitigations)

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Web UI (React + Vite)                           │
│  Download Page │ Process Page │ Upload Page │ Dashboard │ Settings     │
└────────┬───────┴──────┬───────┴──────┬──────┴─────┬─────┴──────┬──────┘
         │              │              │            │            │
         ▼              ▼              ▼            ▼            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    FastAPI + SSE (server/)                              │
│  /api/download  │ /api/process │ /api/upload │ /api/pipeline │ /api/  │
└────────┬────────┴──────┬───────┴──────┬──────┴──────┬────────┴────────┘
         │               │              │             │
         ▼               ▼              ▼             ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐
│  1. Download │  │ 2. Transcribe│  │ 3. Process   │  │ 4. Upload      │
│  Douyin API  │─▶│ faster-whisper│─▶│ ffmpeg burn  │─▶│ YT/TT/FB/X API│
│  + yt-dlp    │  │ SRT generate │  │ + reformat   │  │ (per-platform) │
└──────────────┘  └──────────────┘  └──────────────┘  └────────────────┘
       │                 │                 │                    │
       ▼                 ▼                 ▼                    ▼
   /data/raw/        /data/srt/       /data/output/        /data/logs/
```

**Data flow per video:**

1. Input: Douyin video URL or share link
2. Download watermark-free MP4 → `/data/raw/{video_id}.mp4`
3. Transcribe audio → `/data/srt/{video_id}.srt` (Chinese) + optional `/data/srt/{video_id}_en.srt` (English)
4. Burn subtitles into video + reformat per platform → `/data/output/{video_id}_{platform}.mp4`
5. Upload to target platform(s) → log result to `/data/logs/{video_id}.json`

---

## 2. Project Structure

```
douyin-repurpose/
├── config/
│   ├── config.yaml              # Main configuration (API keys, paths, defaults)
│   ├── platforms.yaml            # Per-platform upload settings
│   └── subtitle_styles.yaml     # Subtitle font, size, color, position
├── src/
│   ├── __init__.py
│   ├── cli.py                   # CLI entry point (click or argparse)
│   ├── pipeline.py              # Orchestrator — chains all stages
│   ├── downloader/
│   │   ├── __init__.py
│   │   ├── douyin.py            # Douyin download client (primary, via self-hosted API)
│   │   └── ytdlp.py             # Fallback downloader using yt-dlp
│   ├── transcriber/
│   │   ├── __init__.py
│   │   ├── base.py              # Common transcriber interface + auto-selection
│   │   ├── faster.py            # faster-whisper backend (Linux/CUDA)
│   │   └── mlx.py               # mlx-whisper backend (macOS Apple Silicon)
│   ├── processor/
│   │   ├── __init__.py
│   │   ├── subtitle.py          # SRT parsing, styling, translation
│   │   └── ffmpeg.py            # Subtitle burn-in + video reformatting
│   ├── uploader/
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract uploader interface
│   │   ├── youtube.py           # YouTube Data API v3
│   │   ├── tiktok.py            # TikTok Content Posting API
│   │   ├── facebook.py          # Facebook Graph API (Video)
│   │   └── x.py                 # X/Twitter API v2 media upload
│   └── utils/
│       ├── __init__.py
│       ├── logger.py            # Structured logging
│       ├── retry.py             # Exponential backoff retry decorator
│       └── metadata.py          # Video metadata extraction + mapping
├── data/
│   ├── raw/                     # Downloaded original videos
│   ├── srt/                     # Generated subtitle files
│   ├── output/                  # Processed videos ready for upload
│   └── logs/                    # Upload results + pipeline logs
├── tests/
│   ├── test_downloader.py
│   ├── test_transcriber.py
│   ├── test_processor.py
│   └── test_uploader.py
├── scripts/
│   ├── setup_oauth.py           # One-time OAuth setup for each platform
│   └── refresh_douyin_cookie.py # Helper to refresh Douyin cookies
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 3. Phase 1 — Core: Download + Transcribe (Week 1-2)

> **Action**: Submit TikTok app for compliance audit at the start of this phase — audit takes 1-2 weeks, so start early.

### 3.1 Douyin Download Module

**Primary tool**: Self-hosted [Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API)
**Fallback tool**: `yt-dlp` with Douyin extractors (in case the primary API breaks due to Douyin anti-scraping changes)

> **Note**: Douyin frequently changes their anti-scraping measures. Pin a known-working version of the Docker image (not `latest`) and maintain a yt-dlp fallback.

**Tasks**:

| #   | Task                               | Details                                                                                                           | Status |
| --- | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ------ |
| 1.1 | Deploy Douyin Download API         | Docker: `evil0ctal/douyin_tiktok_download_api:<pinned-version>`, expose on localhost:8080                         | ☐      |
| 1.2 | Configure Douyin cookies           | Obtain cookie from browser → set in `config.yaml` of the container                                                | ☐      |
| 1.3 | Implement `downloader/douyin.py`   | HTTP client to call the self-hosted API: parse share link → get watermark-free MP4 URL → download to `/data/raw/` | ☐      |
| 1.4 | Implement `downloader/ytdlp.py`   | Fallback downloader using `yt-dlp` — auto-triggered when primary API fails                                       | ☐      |
| 1.5 | Handle metadata extraction         | Extract from API response: video title, author, duration, resolution, original description, hashtags              | ☐      |
| 1.6 | Add cookie rotation strategy       | Detect cookie expiry (API returns error) → log warning → optionally trigger `refresh_douyin_cookie.py`            | ☐      |
| 1.7 | Test with 10 different video types | Short clips, long videos, slideshows, music-heavy, speech-heavy                                                   | ☐      |

**Key implementation detail — `downloader/douyin.py`:**

```python
import httpx
from pathlib import Path

class DouyinDownloader:
    def __init__(self, api_base: str = "http://localhost:8080"):
        self.api_base = api_base
        self.client = httpx.AsyncClient(timeout=60.0)

    async def download(self, share_url: str, output_dir: Path) -> dict:
        """
        1. POST share_url to the API to get parsed video info
        2. Extract watermark-free video URL
        3. Download MP4 to output_dir/{video_id}.mp4
        4. Return metadata dict
        """
        # Step 1: Parse the share URL
        resp = await self.client.post(
            f"{self.api_base}/api/hybrid/video_data",
            json={"url": share_url, "minimal": True}
        )
        data = resp.json()["data"]
        video_url = data["video"]["play_addr"]["url_list"][0]
        video_id = data["aweme_id"]

        # Step 2: Download the video
        output_path = output_dir / f"{video_id}.mp4"
        async with self.client.stream("GET", video_url) as stream:
            with open(output_path, "wb") as f:
                async for chunk in stream.aiter_bytes():
                    f.write(chunk)

        return {
            "video_id": video_id,
            "file_path": str(output_path),
            "title": data.get("desc", ""),
            "author": data.get("author", {}).get("nickname", ""),
            "duration": data.get("duration", 0),
        }
```

### 3.2 AI Transcription Module

**Linux (production)**: `faster-whisper` (CTranslate2 backend) — best performance with CUDA
**macOS (development)**: `mlx-whisper` (leverages Metal/Neural Engine on Apple Silicon)
**Model**: `large-v3` for best Chinese accuracy, `medium` for speed

> **Note**: The transcriber module should abstract over both backends with a common interface, auto-selecting based on the platform (`sys.platform`).

**Tasks**:

| #   | Task                                  | Details                                                                              | Status |
| --- | ------------------------------------- | ------------------------------------------------------------------------------------ | ------ |
| 2.1 | Install transcription backend         | `pip install faster-whisper` (Linux/CUDA) or `pip install mlx-whisper` (macOS)       | ☐      |
| 2.2 | Implement `transcriber/base.py`       | Common interface for transcription backends (auto-selects based on platform)         | ☐      |
| 2.3 | Implement `transcriber/faster.py`     | faster-whisper backend for Linux production                                          | ☐      |
| 2.4 | Implement `transcriber/mlx.py`        | mlx-whisper backend for macOS development                                            | ☐      |
| 2.5 | Support Chinese transcription         | `language="zh"`, task="transcribe"                                                   | ☐      |
| 2.6 | Support Chinese → English translation | Whisper built-in `task="translate"` as baseline; integrate DeepL/Google Translate API for higher-quality zh→en on the generated SRT | ☐      |
| 2.7 | Implement SRT generator               | Convert Whisper segments → properly formatted SRT with sequence numbers + timestamps | ☐      |
| 2.8 | Add VAD filtering                     | Enable `vad_filter=True` to skip non-speech segments and improve accuracy            | ☐      |
| 2.9 | Test accuracy on Douyin content       | Chinese speech with background music, fast speech, slang                             | ☐      |

**Key implementation detail — `transcriber/whisper.py`:**

```python
from faster_whisper import WhisperModel
from pathlib import Path

class WhisperTranscriber:
    def __init__(self, model_size: str = "large-v3", device: str = "auto", compute_type: str = "float16"):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, video_path: str, language: str = "zh", task: str = "transcribe") -> list[dict]:
        """Returns list of segments: [{start, end, text}, ...]"""
        segments, info = self.model.transcribe(
            video_path,
            language=language,
            task=task,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        print(f"Detected language: {info.language} (prob: {info.language_probability:.2f})")
        return [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]

    def generate_srt(self, segments: list[dict], output_path: Path) -> Path:
        """Write segments to SRT file."""
        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, 1):
                start = self._format_timestamp(seg["start"])
                end = self._format_timestamp(seg["end"])
                f.write(f"{i}\n{start} --> {end}\n{seg['text']}\n\n")
        return output_path

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds % 1) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
```

### 3.3 Phase 1 Verification

| #    | Verify                                  | Expected Result                                       |
| ---- | --------------------------------------- | ----------------------------------------------------- |
| V1.1 | Download 5 Douyin videos via share link | All download successfully as watermark-free MP4       |
| V1.2 | Transcribe a Chinese speech video       | SRT has accurate Chinese text with correct timestamps |
| V1.3 | Translate a Chinese video to English    | SRT has readable English translation                  |
| V1.4 | End-to-end: URL → SRT file              | Single command produces both MP4 and SRT              |

---

## 4. Phase 2 — Subtitle Burn-in + Reformat (Week 2-3)

### 4.1 Subtitle Language Strategy

Each platform can receive different subtitle languages. Configure per platform in `config/platforms.yaml`:

| Platform          | Default Subtitle | Rationale                                              |
| ----------------- | ---------------- | ------------------------------------------------------ |
| TikTok            | Chinese only     | Audience is Chinese-speaking; matches original content  |
| YouTube           | English          | Broader international audience                         |
| YouTube Shorts    | English          | Same as YouTube                                        |
| Facebook (Reels)  | English          | Broader international audience                         |
| Facebook (Feed)   | English          | Same as Facebook Reels                                 |
| X/Twitter         | English          | International audience, limited duration for dual subs |

Optionally support **dual-line subtitles** (Chinese on top, English below) for platforms where both audiences exist. This is configured per-platform in `config/platforms.yaml`.

### 4.2 Subtitle Styling

**Config file — `config/subtitle_styles.yaml`:**

```yaml
default:
    font_name: 'Noto Sans CJK SC' # Good CJK support
    font_size: 24
    primary_color: '&H00FFFFFF' # White (ASS format: BBGGRR)
    outline_color: '&H00000000' # Black outline
    outline_width: 2
    shadow_depth: 1
    alignment: 2 # Bottom center
    margin_v: 30 # Vertical margin from bottom (px)
    bold: 1

tiktok: # Override for TikTok (9:16 vertical)
    font_size: 20
    margin_v: 80 # Higher margin to avoid UI overlap

youtube_shorts:
    font_size: 22
    margin_v: 50
```

### 4.2 ffmpeg Processing

**Tasks**:

| #   | Task                            | Details                                                         | Status |
| --- | ------------------------------- | --------------------------------------------------------------- | ------ |
| 3.1 | Implement `processor/ffmpeg.py` | Wrapper around ffmpeg subprocess calls                          | ☐      |
| 3.2 | Burn subtitles (soft)           | Use ffmpeg `-vf subtitles=` filter to hardcode SRT into video   | ☐      |
| 3.3 | Burn subtitles (styled ASS)     | Convert SRT → ASS with styling from config, then burn           | ☐      |
| 3.4 | Platform-specific reformatting  | Resize/crop/compress per platform specs (see table below)       | ☐      |
| 3.5 | Handle CJK font embedding       | Ensure Noto Sans CJK is available in the processing environment | ☐      |
| 3.6 | Batch processing support        | Process one source video → multiple platform outputs            | ☐      |

**Platform video specifications:**

| Platform          | Max Duration | Aspect Ratio   | Max Resolution | Max File Size | Codec     | Notes                                   |
| ----------------- | ------------ | -------------- | -------------- | ------------- | --------- | --------------------------------------- |
| TikTok            | 10 min       | 9:16 preferred | 1080x1920      | 4 GB          | H.264/MP4 | Douyin videos already 9:16              |
| YouTube Shorts    | 60 sec       | 9:16           | 1080x1920      | 256 GB        | H.264/MP4 | Auto-detected by YT if ≤60s + 9:16      |
| YouTube (regular) | 12 hrs       | Any            | 3840x2160      | 256 GB        | H.264/MP4 | Good for longer compilations            |
| Facebook (Reels)  | 15 min       | 9:16           | 1080x1920      | 4 GB          | H.264/MP4 |                                         |
| Facebook (Feed)   | 240 min      | Any            | 1080p          | 10 GB         | H.264/MP4 |                                         |
| X/Twitter         | 2 min 20 sec | Any            | 1920x1200      | 512 MB        | H.264/MP4 | **Most restrictive on duration + size** |

**Key implementation detail — `processor/ffmpeg.py`:**

```python
import subprocess
from pathlib import Path

class FFmpegProcessor:

    def burn_subtitles(self, video_path: Path, srt_path: Path, output_path: Path,
                       style: dict = None) -> Path:
        """Burn SRT subtitles into video using ffmpeg."""
        # Build the subtitles filter with styling
        style_str = self._build_style_string(style or {})
        sub_filter = f"subtitles={srt_path}:force_style='{style_str}'"

        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", sub_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", str(output_path)
        ]
        subprocess.run(cmd, check=True)
        return output_path

    def reformat_for_platform(self, video_path: Path, platform: str, output_path: Path) -> Path:
        """Resize/compress video to meet platform requirements."""
        specs = PLATFORM_SPECS[platform]
        cmd = [
            "ffmpeg", "-i", str(video_path),
            "-vf", f"scale={specs['width']}:{specs['height']}:force_original_aspect_ratio=decrease,"
                   f"pad={specs['width']}:{specs['height']}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "medium",
            "-crf", str(specs.get("crf", 23)),
            "-maxrate", specs.get("maxrate", "5M"),
            "-bufsize", specs.get("bufsize", "10M"),
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            "-y", str(output_path)
        ]
        # For X/Twitter: also enforce max duration
        if platform == "x" and specs.get("max_duration"):
            cmd.insert(cmd.index("-y"), "-t")
            cmd.insert(cmd.index("-y"), str(specs["max_duration"]))
        subprocess.run(cmd, check=True)
        return output_path

    @staticmethod
    def _build_style_string(style: dict) -> str:
        """Convert style dict to ffmpeg ASS force_style string."""
        mapping = {
            "font_name": "FontName",
            "font_size": "FontSize",
            "primary_color": "PrimaryColour",
            "outline_color": "OutlineColour",
            "outline_width": "Outline",
            "shadow_depth": "Shadow",
            "bold": "Bold",
            "alignment": "Alignment",
            "margin_v": "MarginV",
        }
        parts = [f"{mapping[k]}={v}" for k, v in style.items() if k in mapping]
        return ",".join(parts)


PLATFORM_SPECS = {
    "tiktok": {"width": 1080, "height": 1920, "crf": 23, "maxrate": "8M", "bufsize": "16M"},
    "youtube": {"width": 1080, "height": 1920, "crf": 20, "maxrate": "12M", "bufsize": "24M"},
    "facebook": {"width": 1080, "height": 1920, "crf": 23, "maxrate": "8M", "bufsize": "16M"},
    "x": {"width": 1080, "height": 1920, "crf": 26, "maxrate": "4M", "bufsize": "8M", "max_duration": 140},
}
```

### 4.3 Phase 2 Verification

| #    | Verify                                       | Expected Result                                          |
| ---- | -------------------------------------------- | -------------------------------------------------------- |
| V2.1 | Burn Chinese subtitles onto a Douyin video   | Subtitles visible, correctly timed, CJK renders properly |
| V2.2 | Generate styled ASS subtitles                | Font, color, outline match config                        |
| V2.3 | Reformat for X/Twitter                       | Output ≤ 512MB, ≤ 2:20 duration, H.264                   |
| V2.4 | Reformat for all 4 platforms from one source | 4 output files, each meeting platform specs              |

---

## 5. Phase 3 — Platform Upload Integrations (Week 3-4)

> **Recommended order**: YouTube first (easiest API, best docs) → Facebook → TikTok → X (stretch goal)

### 5.1 Common Uploader Interface

```python
# src/uploader/base.py
from abc import ABC, abstractmethod
from pathlib import Path
from dataclasses import dataclass

@dataclass
class UploadResult:
    platform: str
    success: bool
    post_id: str | None = None
    post_url: str | None = None
    error: str | None = None

@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str]
    privacy: str = "public"  # public, private, unlisted

class BaseUploader(ABC):
    @abstractmethod
    async def authenticate(self) -> None: ...

    @abstractmethod
    async def upload(self, video_path: Path, metadata: VideoMetadata) -> UploadResult: ...

    @abstractmethod
    async def check_status(self, post_id: str) -> dict: ...
```

### 5.2 YouTube Upload

**API**: YouTube Data API v3  
**Auth**: OAuth 2.0 (requires `client_secrets.json` from Google Cloud Console)  
**Scope**: `https://www.googleapis.com/auth/youtube.upload`  
**Library**: `google-api-python-client`, `google-auth-oauthlib`

**Setup tasks**:

| #   | Task                                   | Details                                                       | Status |
| --- | -------------------------------------- | ------------------------------------------------------------- | ------ |
| 4.1 | Create Google Cloud project            | Enable YouTube Data API v3                                    | ☐      |
| 4.2 | Generate OAuth 2.0 credentials         | Download `client_secrets.json`                                | ☐      |
| 4.3 | Run one-time OAuth flow                | `scripts/setup_oauth.py youtube` → saves refresh token        | ☐      |
| 4.4 | Implement `uploader/youtube.py`        | Resumable upload with exponential backoff                     | ☐      |
| 4.5 | Handle Shorts vs regular               | If duration ≤ 60s + 9:16 → add `#Shorts` to title/description | ☐      |
| 4.6 | Test upload: private → public workflow | Upload as private first, verify, then update to public        | ☐      |

**Key notes**:

- YouTube has a daily upload quota (default ~6 uploads/day for unverified apps). Apply for quota increase if needed.
- Resumable uploads are critical — network interruptions are common for large files.
- `MediaFileUpload` with `chunksize=1024*1024` and `resumable=True`.

### 5.3 TikTok Upload

**API**: TikTok Content Posting API  
**Auth**: OAuth 2.0 (TikTok Developer Portal)  
**Endpoints**: Direct Post or Upload (draft) API

**Setup tasks**:

| #   | Task                                    | Details                                                                                        | Status |
| --- | --------------------------------------- | ---------------------------------------------------------------------------------------------- | ------ |
| 5.1 | Register app on TikTok Developer Portal | Add "Content Posting API" product                                                              | ☐      |
| 5.2 | Enable "Direct Post" configuration      | Required for publishing directly to profile                                                    | ☐      |
| 5.3 | Implement OAuth flow                    | TikTok uses standard OAuth 2.0 with PKCE                                                       | ☐      |
| 5.4 | Implement `uploader/tiktok.py`          | INIT upload → send video → poll for completion                                                 | ☐      |
| 5.5 | Handle the audit requirement            | **Critical**: unaudited apps can only post as private. Submit app for TikTok compliance audit. | ☐      |
| 5.6 | Implement draft upload fallback         | Use Upload API to send as draft if Direct Post is not yet approved                             | ☐      |

**Key notes**:

- Rate limit: 6 requests/minute per user access token.
- `upload_url` expires after 1 hour.
- Supports `PULL_FROM_URL` (TikTok fetches video from your URL) or `FILE_UPLOAD` (you send chunks).
- **Compliance audit is required** for public posts — plan for 1-2 weeks review time.

### 5.4 Facebook Upload

**API**: Facebook Graph API — Video endpoint  
**Auth**: OAuth 2.0 (Facebook Developer App)  
**Host**: `graph-video.facebook.com` (different from regular Graph API)

**Setup tasks**:

| #   | Task                                 | Details                                                                    | Status |
| --- | ------------------------------------ | -------------------------------------------------------------------------- | ------ |
| 6.1 | Create Facebook Developer App        | Configure for Page or personal posting                                     | ☐      |
| 6.2 | Request permissions                  | `pages_manage_engagement`, `pages_read_user_content`, `publish_video`      | ☐      |
| 6.3 | Generate Page Access Token           | Long-lived token via token exchange                                        | ☐      |
| 6.4 | Implement `uploader/facebook.py`     | Chunked upload: START → TRANSFER (chunks) → FINISH                         | ☐      |
| 6.5 | Support Reels vs Feed post           | Reels: POST to `/{page-id}/video_reels`; Feed: POST to `/{page-id}/videos` | ☐      |
| 6.6 | Test Page vs personal profile upload |                                                                            | ☐      |

**Key notes**:

- Chunked upload with 5MB chunks recommended.
- Page tokens need to be long-lived (60-day expiry, auto-refresh if `pages_manage_engagement` granted).
- For Reels, video must be 9:16 and ≤ 15 min.

### 5.5 X (Twitter) Upload — *Stretch Goal*

> **Note**: X API requires a Basic plan at $100/month, is the most restrictive platform (2:20 max, 512MB), and offers the least reach for this content type. Implement last, only if needed.

**API**: X API v2 — Media Upload (chunked)
**Auth**: OAuth 1.0a (for media upload) + OAuth 2.0 (for posting tweet)
**Library**: `tweepy` or raw `httpx` + `authlib`

**Setup tasks**:

| #   | Task                         | Details                                                             | Status |
| --- | ---------------------------- | ------------------------------------------------------------------- | ------ |
| 7.1 | Create X Developer account   | **Basic plan required** ($100/month) — Free plan cannot post tweets | ☐      |
| 7.2 | Generate API keys            | Consumer key/secret + access token/secret                           | ☐      |
| 7.3 | Implement `uploader/x.py`    | INIT → APPEND (chunks) → FINALIZE → poll STATUS → create tweet      | ☐      |
| 7.4 | Handle video processing wait | Poll `command=STATUS` until `processing_info.state == "succeeded"`  | ☐      |
| 7.5 | Enforce size/duration limits | Pre-check: ≤ 512MB, ≤ 2:20. Reject or auto-trim if exceeded.        | ☐      |
| 7.6 | Test with video tweet        |                                                                     | ☐      |

**Key notes**:

- X API v2 media upload now available (was v1.1 only before).
- Chunked upload flow: INIT → APPEND (≤5MB chunks) → FINALIZE → poll STATUS.
- Video processing on X side can take 30-120 seconds.
- **Basic plan ($100/mo)** is the minimum for posting. Free tier only allows reading.

### 5.6 Phase 3 Verification

| #    | Verify                               | Expected Result                                                    |
| ---- | ------------------------------------ | ------------------------------------------------------------------ |
| V3.1 | Upload subtitled video to YouTube    | Video visible on channel (private), correct title/description/tags |
| V3.2 | Upload to TikTok (draft)             | Video appears in TikTok inbox as draft                             |
| V3.3 | Upload to Facebook Page              | Video post visible on Page                                         |
| V3.4 | Upload to X with tweet text          | Tweet with embedded video visible                                  |
| V3.5 | Upload same video to all 4 platforms | All 4 succeed, results logged                                      |

---

## 6. Phase 4 — Orchestration + Batch Processing (Week 4-5)

### 6.1 CLI Interface

**Entry point — `src/cli.py`:**

```bash
# Process a single video (full pipeline)
python -m src.cli process "https://v.douyin.com/xxxxx" \
    --platforms youtube,tiktok,facebook,x \
    --subtitle-lang zh \
    --translate en \
    --title "My Video Title" \
    --tags "funny,viral"

# Download only
python -m src.cli download "https://v.douyin.com/xxxxx"

# Transcribe only (local file)
python -m src.cli transcribe /data/raw/video.mp4 --lang zh --translate en

# Upload only (already processed file)
python -m src.cli upload /data/output/video_subtitled.mp4 --platforms youtube,tiktok

# Batch process from a file of URLs
python -m src.cli batch urls.txt --platforms youtube,tiktok,facebook,x
```

### 6.2 Pipeline Orchestrator

**Tasks**:

| #   | Task                                | Details                                                                                       | Status |
| --- | ----------------------------------- | --------------------------------------------------------------------------------------------- | ------ |
| 8.1 | Implement `pipeline.py`             | Chain: download → transcribe → process → upload with error handling                           | ☐      |
| 8.2 | Add structured logging              | JSON logs with video_id, stage, status, timing                                                | ☐      |
| 8.3 | Add retry logic                     | Exponential backoff for API calls (upload, download)                                          | ☐      |
| 8.4 | Add progress tracking               | Per-video status: pending → downloading → transcribing → processing → uploading → done/failed | ☐      |
| 8.5 | Add stage-level state persistence   | Track which stages completed per video (in `/data/logs/{video_id}.json`). On restart/crash, resume from the last successful stage instead of re-downloading/re-transcribing | ☐      |
| 8.6 | Implement batch mode                | Read URLs from file, process sequentially or with concurrency limit                           | ☐      |
| 8.7 | Add duplicate detection             | Track processed video IDs to avoid re-processing                                              | ☐      |
| 8.8 | (Optional) Add Celery + Redis queue | For background processing with worker scaling                                                 | ☐      |
| 8.9 | (Optional) Add simple web dashboard | FastAPI + HTMX for monitoring pipeline status                                                 | ☐      |

### 6.3 Metadata Mapping

Map Douyin metadata to each platform's format:

```python
# src/utils/metadata.py
def map_metadata(douyin_meta: dict, platform: str, overrides: dict = None) -> VideoMetadata:
    """Map Douyin video metadata to platform-specific format."""
    base = VideoMetadata(
        title=douyin_meta.get("title", ""),
        description=douyin_meta.get("title", ""),  # Douyin "desc" is usually the title
        tags=douyin_meta.get("hashtags", []),
        privacy="public",
    )

    # Platform-specific adjustments
    if platform == "youtube":
        if is_short(douyin_meta):
            base.title += " #Shorts"
        base.description += "\n\n#douyin #viral"

    elif platform == "tiktok":
        # TikTok: description is limited, hashtags go in description
        base.description = " ".join(f"#{t}" for t in base.tags[:10])

    elif platform == "x":
        # X: tweet text is very limited (280 chars)
        base.description = base.title[:250]

    # Apply user overrides
    if overrides:
        for k, v in overrides.items():
            setattr(base, k, v)

    return base
```

### 6.4 Phase 4 Verification

| #    | Verify                               | Expected Result                                |
| ---- | ------------------------------------ | ---------------------------------------------- |
| V4.1 | Full pipeline: URL → all 4 platforms | Single command, video appears on all platforms |
| V4.2 | Batch process 5 URLs                 | All 5 processed, failures logged and skipped   |
| V4.3 | Retry on transient failure           | Simulated network error recovers after retry   |
| V4.4 | Duplicate detection                  | Re-running same URL skips processing           |
| V4.5 | Structured logs                      | JSON logs capture all stages with timing       |

---

## 7. Phase 5 — TTS Dubbing (Week 5-6)

Generate voiceover audio from translated subtitles and mix into video.

**Pipeline**: Download → Transcribe → Translate → **TTS Dubbing** → Process (burn subs + mix audio) → Upload

**Architecture**: `src/tts/` module with ABC + Edge TTS (free, default) + OpenAI TTS + Google Cloud TTS. Voice profiles in `config/tts_voices.yaml`. Audio mixing via ffmpeg `amix` filter.

**Key tasks** (18 total — see `plans/phase5-tts-dubbing.md`):
- TTS provider abstraction (base + 3 backends + factory)
- Audio assembler: segment-by-segment TTS → duration fitting → full-track concatenation
- Audio mixing in ffmpeg: configurable volume levels (e.g., 30% original + 100% TTS)
- Per-platform voice selection (Vietnamese for TikTok/FB, English for YouTube/X)
- Voice preview + profile management API
- TTS UI section on Process page with voice selector, volume sliders, preview playback

---

## 8. Platform API Reference

Quick reference for API endpoints and auth:

| Platform  | API               | Auth Type        | Key Endpoint                        | Rate Limit        | Cost                  |
| --------- | ----------------- | ---------------- | ----------------------------------- | ----------------- | --------------------- |
| YouTube   | Data API v3       | OAuth 2.0        | `youtube.videos().insert()`         | ~10,000 units/day | Free (quota)          |
| TikTok    | Content Posting   | OAuth 2.0 + PKCE | `POST /v2/post/publish/video/init/` | 6 req/min/user    | Free (audit required) |
| Facebook  | Graph API (Video) | OAuth 2.0        | `POST /{page-id}/videos`            | 200 calls/user/hr | Free                  |
| X/Twitter | API v2 Media      | OAuth 1.0a/2.0   | `POST /2/media/upload`              | 300 uploads/15min | **$100/mo (Basic)**   |

---

## 8. Configuration

**Main config — `config/config.yaml`:**

```yaml
# Douyin Download API
douyin:
    api_base: 'http://localhost:8080'
    cookie_file: 'config/douyin_cookie.txt'
    download_timeout: 120

# Whisper Transcription
whisper:
    model_size: 'large-v3' # tiny, base, small, medium, large-v3
    device: 'auto' # auto, cpu, cuda, mps
    compute_type: 'float16' # float16, int8, float32
    default_language: 'zh'
    vad_filter: true
    vad_min_silence_ms: 500

# ffmpeg Processing
ffmpeg:
    default_crf: 23
    preset: 'medium' # ultrafast, fast, medium, slow
    audio_bitrate: '128k'

# Upload Platforms
platforms:
    youtube:
        enabled: true
        credentials_file: 'config/youtube_client_secrets.json'
        token_file: 'config/youtube_token.json'
        default_privacy: 'private' # Upload as private first, review, then publish
        default_category: '22' # People & Blogs

    tiktok:
        enabled: true
        client_key: '${TIKTOK_CLIENT_KEY}'
        client_secret: '${TIKTOK_CLIENT_SECRET}'
        token_file: 'config/tiktok_token.json'
        post_mode: 'upload' # "direct" (publish) or "upload" (draft)

    facebook:
        enabled: true
        app_id: '${FB_APP_ID}'
        app_secret: '${FB_APP_SECRET}'
        page_id: '${FB_PAGE_ID}'
        token_file: 'config/facebook_token.json'
        post_type: 'reels' # "reels" or "feed"

    x:
        enabled: false # Disabled by default (requires paid plan)
        api_key: '${X_API_KEY}'
        api_secret: '${X_API_SECRET}'
        access_token: '${X_ACCESS_TOKEN}'
        access_secret: '${X_ACCESS_SECRET}'

# Pipeline
pipeline:
    data_dir: './data'
    max_concurrent: 3
    retry_max_attempts: 3
    retry_base_delay: 5
    skip_existing: true # Skip already-processed video IDs
```

---

## 9. Dependencies

**`requirements.txt`** (common):

```
# Core
httpx>=0.27.0                     # Async HTTP client
pyyaml>=6.0                       # Config parsing
click>=8.1                        # CLI framework

# Download
yt-dlp>=2024.01                   # Fallback downloader for Douyin

# YouTube upload
google-api-python-client>=2.100   # YouTube Data API
google-auth-oauthlib>=1.2         # OAuth flow
google-auth-httplib2>=0.2         # Auth transport

# TikTok upload
authlib>=1.3                      # OAuth 2.0 PKCE

# Facebook upload
python-facebook-api>=0.24         # Graph API wrapper (optional, can use httpx)

# X/Twitter upload (stretch goal — only if X integration enabled)
tweepy>=4.14                      # X API client

# Translation (optional, for higher-quality zh→en)
# deepl>=1.16                     # DeepL API client

# Utilities
tenacity>=8.2                     # Retry logic
rich>=13.0                        # Pretty CLI output + progress bars
```

**`requirements-linux.txt`** (production — Linux/CUDA):

```
-r requirements.txt
faster-whisper>=1.1.0             # Whisper CTranslate2 backend (CUDA)
```

**`requirements-macos.txt`** (development — macOS Apple Silicon):

```
-r requirements.txt
mlx-whisper>=0.4.0                # Whisper MLX backend (Metal/Neural Engine)
```

**System dependencies:**

```bash
# Ubuntu/Debian (production)
sudo apt update && sudo apt install -y ffmpeg fonts-noto-cjk

# macOS (development)
brew install ffmpeg
# Noto CJK fonts: download from https://github.com/googlefonts/noto-cjk
```

---

## 10. Web UI + API Layer

Each phase includes a web UI so the pipeline is usable without terminal commands. The UI is built incrementally — each phase adds its own page.

**Stack**: FastAPI (API) + React/Vite/Tailwind/shadcn/ui (UI) + SSE (real-time progress)

**Structure**: `server/` (FastAPI routers + services) and `web/` (React frontend) in the same repo.

### 10.1 Real-Time Progress via SSE

All long-running tasks follow this pattern:
1. Client POSTs to start operation → receives `{ "task_id": "uuid" }`
2. Client subscribes to `GET /api/events/{task_id}` (Server-Sent Events)
3. Server pushes progress events: `progress`, `stage_change`, `complete`, `error`
4. Client can also poll `GET /api/tasks/{task_id}` for final result

### 10.2 Phase 1 UI — Download + Transcribe

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/download` | Start download → `{task_id}` |
| GET | `/api/videos` | List downloaded videos |
| GET | `/api/videos/{video_id}` | Video detail + metadata |
| POST | `/api/transcribe` | Start transcription → `{task_id}` |
| GET | `/api/videos/{video_id}/srt` | Get SRT content |
| GET | `/api/events/{task_id}` | SSE progress stream |

**UI — Download Page:**
- URL input field + Download button
- Real-time download progress bar (bytes / total)
- Video card after download: thumbnail, title, author, duration
- Transcribe button with language selector (zh/en)
- SRT preview: scrollable timestamped subtitle segments

### 10.3 Phase 2 UI — Subtitle + Reformat

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/process` | Start processing → `{task_id}` |
| GET | `/api/subtitle-styles` | Get style config |
| PUT | `/api/subtitle-styles/{platform}` | Update style |
| GET | `/api/platforms` | Platform specs |
| GET | `/api/videos/{video_id}/output/{platform}` | Serve processed video |

**UI — Process Page:**
- Video selector (only videos with SRT)
- Subtitle style editor: font, size, color picker, outline, position
- Platform checkboxes with constraint badges (max duration, max size)
- Per-platform processing progress (from ffmpeg stderr)
- Output video player per platform

### 10.4 Phase 3 UI — Upload

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/auth/status` | OAuth status per platform |
| POST | `/api/auth/{platform}/start` | Start OAuth flow |
| POST | `/api/auth/{platform}/callback` | Handle callback |
| POST | `/api/upload` | Start upload → `{task_id}` |
| POST | `/api/upload/{task_id}/retry` | Retry failed platforms |

**UI — Upload Page:**
- Auth status panel: connection indicator per platform, Connect button
- Upload form: video selector, platform checkboxes, metadata editor with char counters
- Per-platform upload progress bars
- Results cards: post URL links, retry button for failures

### 10.5 Phase 4 UI — Dashboard + Settings

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/pipeline` | Full pipeline → `{task_id}` |
| POST | `/api/pipeline/batch` | Batch → `{batch_id}` |
| GET | `/api/pipeline/history` | List all runs |
| POST | `/api/pipeline/{task_id}/retry` | Retry from failed stage |
| GET | `/api/dashboard/stats` | Summary statistics |
| GET/PUT | `/api/config` | Read/update config |

**UI — Dashboard Page:**
- Stats cards: total videos, today's count, success rate, active tasks
- Batch input: textarea for multiple URLs, platform selector, Process All button
- Pipeline table: video, status with stage indicator, platforms, duration, retry action
- Expandable detail: 4-step progress (Download → Transcribe → Process → Upload)

**UI — Settings Page:**
- Structured config editor (not raw YAML): Douyin API, Whisper, FFmpeg, Pipeline sections

---

## 11. Risks & Mitigations

| Risk                            | Impact                    | Likelihood | Mitigation                                                                  |
| ------------------------------- | ------------------------- | ---------- | --------------------------------------------------------------------------- |
| Douyin cookie expiry            | Download fails            | High       | Cookie rotation script + monitoring; alert on failure                       |
| Douyin API blocks/rate limits   | Download fails            | Medium     | Add delays between downloads; rotate IP if needed                           |
| Whisper accuracy on noisy audio | Poor subtitles            | Medium     | Use `large-v3` model; add VAD filtering; manual review for important videos |
| TikTok audit rejection          | Can only post as drafts   | Medium     | Follow TikTok UX guidelines strictly; submit audit early                    |
| X API cost ($100/mo)            | Budget impact             | Low        | Disable X by default; enable only if needed                                 |
| YouTube upload quota            | Limited uploads/day       | Medium     | Apply for quota increase; stagger uploads                                   |
| Platform API changes            | Upload breaks             | Low        | Pin SDK versions; monitor changelogs; abstract behind interfaces            |
| CJK font not available          | Subtitles render as boxes | Low        | Bundle Noto CJK font; verify in Docker environment                          |
| Video copyright claims          | Platform takedown         | Medium     | Only repurpose original/licensed content; add source attribution            |

---

## Appendix A: One-Time Setup Checklist

Before running the pipeline, complete these one-time setup steps:

- [ ] **Docker**: Install Docker, pull Douyin API image, start container
- [ ] **Python**: Create venv, install requirements
- [ ] **ffmpeg**: Install ffmpeg + Noto CJK fonts
- [ ] **Whisper model**: Run once to download model (~3GB for large-v3)
- [ ] **Google Cloud**: Create project → enable YouTube Data API v3 → create OAuth credentials → download `client_secrets.json`
- [ ] **TikTok Developer**: Register app → add Content Posting API → enable Direct Post → submit for audit
- [ ] **Facebook Developer**: Create app → request permissions → generate long-lived Page token
- [ ] **X Developer**: Create account (Basic plan $100/mo) → generate API keys
- [ ] **OAuth flows**: Run `scripts/setup_oauth.py {platform}` for each enabled platform
- [ ] **Test**: Run `python -m src.cli process <test_url> --platforms youtube` to verify end-to-end
