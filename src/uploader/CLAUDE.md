# Uploader Module

Uploads processed videos to social media platforms.

## Key Components

- `base.py` — `BaseUploader` ABC with `authenticate()`, `upload()`, `check_status()`, `refresh_token()`. Also defines `UploadResult` and `VideoMetadata` dataclasses.
- `youtube.py` — `YouTubeUploader`: Google OAuth 2.0, resumable upload via `MediaFileUpload`, Shorts detection (≤60s + 9:16).
- `tiktok.py` — `TikTokUploader`: OAuth 2.0 + PKCE, FILE_UPLOAD with chunked transfer, draft fallback for unaudited apps.
- `facebook.py` — `FacebookUploader`: Page token auth, 3-phase chunked upload (START→TRANSFER→FINISH), Reels vs Feed.
- `x.py` — `XUploader` *(stretch goal)*: OAuth 1.0a, 4-phase chunked media upload (INIT→APPEND→FINALIZE→STATUS).
- `__init__.py` — `get_uploader()` factory, `get_enabled_uploaders()` returns only `enabled: true` platforms.

## Constraints

- All uploads return `UploadResult(success, post_id, post_url, error)` — never raise on upload failure.
- Token files stored in `config/*_token.json` (gitignored).
- YouTube: ~6 uploads/day quota. Resumable uploads with exponential backoff.
- TikTok: 6 req/min rate limit. Upload URL expires after 1 hour. Audit required for public posts.
- Facebook: Use `graph-video.facebook.com` (not `graph.facebook.com`). 5MB chunk size.
- X: $100/mo Basic plan required. Pre-check file ≤512MB and duration ≤140s before uploading.

## Connects To

- **Input**: Platform-specific MP4s from `data/output/`, `VideoMetadata` from metadata mapper
- **Output**: `UploadResult` → logged to `data/logs/`
