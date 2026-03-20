# Phase 3 — Platform Upload Integrations (Week 3-4)

> **Recommended order**: YouTube (easiest API, best docs) → Facebook → TikTok → X (stretch goal)

---

## Task List

### 3.1 Base Uploader Interface — `src/uploader/base.py`

Dataclasses:
- `UploadResult`: `platform`, `success`, `post_id`, `post_url`, `error`, `timestamp`
- `VideoMetadata`: `title`, `description`, `tags: list[str]`, `privacy: str`, `category: str`

Abstract class `BaseUploader(ABC)`:
- `async authenticate() -> None`
- `async upload(video_path: Path, metadata: VideoMetadata) -> UploadResult`
- `async check_status(post_id: str) -> dict`
- `async refresh_token() -> None`

**Dependencies**: Phase 1 task 1.6

### 3.2 OAuth Setup Script — `scripts/setup_oauth.py`

Click-based CLI: `python scripts/setup_oauth.py <platform>`

Subcommands:
- `youtube` — Open browser for Google OAuth → save token to `config/youtube_token.json`
- `tiktok` — Open browser for TikTok OAuth with PKCE → save token
- `facebook` — Guide through token exchange → save long-lived page token
- `x` — Prompt for API keys → verify with test call

**Dependencies**: 3.1

### 3.3 YouTube Uploader — `src/uploader/youtube.py`

Class `YouTubeUploader(BaseUploader)`:

**`authenticate()`**:
- Load `client_secrets.json` from config path
- Load or refresh token from `youtube_token.json`
- Use `google_auth_oauthlib.flow.InstalledAppFlow` for initial auth

**`upload(video_path, metadata)`**:
- Build request body: snippet (title, description, tags, categoryId) + status (privacyStatus)
- Use `MediaFileUpload(chunksize=1024*1024, resumable=True)`
- Call `youtube.videos().insert()` with `media_body`
- Resumable upload loop with exponential backoff on `HttpError`
- Shorts detection: if duration ≤ 60s AND aspect ratio 9:16 → append `#Shorts`

**`check_status(video_id)`**:
- Call `youtube.videos().list(id=video_id, part="status,processingDetails")`

**Key constraints**:
- Daily quota: ~10,000 units/day (each upload costs 1600 units → ~6 uploads/day)
- Resumable uploads critical for large files

**Dependencies**: 3.1, 3.2

### 3.4 TikTok Uploader — `src/uploader/tiktok.py`

Class `TikTokUploader(BaseUploader)`:

**`authenticate()`**:
- Load token from `tiktok_token.json`
- Refresh if expired using refresh_token endpoint

**`upload(video_path, metadata)`**:
- Two upload modes:
  - **FILE_UPLOAD** (default):
    1. `POST /v2/post/publish/video/init/` with `source_info.source = "FILE_UPLOAD"` → get `upload_url`
    2. Upload video in chunks (max 64MB each) to `upload_url`
    3. Poll `POST /v2/post/publish/status/fetch/` until complete
  - **PULL_FROM_URL** (alternative):
    1. Provide public URL → TikTok fetches it
- **Draft mode** (for unaudited apps):
  - Use `POST /v2/post/publish/inbox/video/init/` instead
  - Video appears in inbox/drafts, not published

**`check_status(publish_id)`**:
- Poll `POST /v2/post/publish/status/fetch/` with `publish_id`

**Key constraints**:
- Rate limit: 6 requests/minute per user token → enforce with semaphore/sleep
- Upload URL expires after 1 hour
- Unaudited apps can only post as drafts (private)

**Dependencies**: 3.1, 3.2

### 3.5 Facebook Uploader — `src/uploader/facebook.py`

Class `FacebookUploader(BaseUploader)`:

**`authenticate()`**:
- Load page access token from `facebook_token.json`
- Verify with `GET /me?access_token=...`

**`upload(video_path, metadata)`**:
- Chunked upload protocol (3 phases):
  1. **START**: `POST graph-video.facebook.com/{page_id}/videos` with `upload_phase=start`, `file_size` → get `upload_session_id`, `start_offset`, `end_offset`
  2. **TRANSFER**: Loop `POST` with `upload_phase=transfer`, `start_offset`, `video_file_chunk` (5MB chunks) → repeat until all chunks sent
  3. **FINISH**: `POST` with `upload_phase=finish`, `upload_session_id`, `title`, `description`
- For **Reels**: `POST /{page_id}/video_reels` with same chunked protocol
- For **Feed**: `POST /{page_id}/videos`

**`check_status(video_id)`**:
- `GET /{video_id}?fields=status`

**Key constraints**:
- Use `graph-video.facebook.com` (not `graph.facebook.com`) for uploads
- Page tokens: 60-day expiry, auto-refresh if `pages_manage_engagement` granted
- 5MB chunk size recommended

**Dependencies**: 3.1, 3.2

### 3.6 X/Twitter Uploader — `src/uploader/x.py` *(Stretch Goal)*

Class `XUploader(BaseUploader)`:

**`authenticate()`**:
- OAuth 1.0a for media upload (consumer key/secret + access token/secret)

**`upload(video_path, metadata)`**:
- Pre-check: file size ≤ 512MB, duration ≤ 140s. Reject if exceeded.
- Chunked media upload (4 phases):
  1. **INIT**: `POST media/upload` with `command=INIT`, `total_bytes`, `media_type=video/mp4`, `media_category=tweet_video` → get `media_id`
  2. **APPEND**: Loop `POST media/upload` with `command=APPEND`, `media_id`, `segment_index`, chunk data (≤5MB) → repeat for all chunks
  3. **FINALIZE**: `POST media/upload` with `command=FINALIZE`, `media_id`
  4. **STATUS**: Poll `GET media/upload` with `command=STATUS`, `media_id` until `processing_info.state == "succeeded"` (can take 30-120s)
- Create tweet: `POST /2/tweets` with `{"media": {"media_ids": ["<media_id>"]}}`

**Key constraints**:
- **Basic plan required** ($100/month) — Free tier cannot post
- Processing can take 30-120s on X side
- 300 uploads per 15 minutes

**Dependencies**: 3.1, 3.2

### 3.7 Uploader Factory — `src/uploader/__init__.py`

- `get_uploader(platform: str, config: dict) -> BaseUploader`
- `get_enabled_uploaders(config: dict) -> dict[str, BaseUploader]` — returns only `enabled: true` platforms

**Dependencies**: 3.3, 3.4, 3.5, 3.6

### 3.8 Phase 3 Tests — `tests/test_uploader.py`

- Mock API responses for each platform (use `httpx` mock or `responses` library)
- Test auth flow (token load, refresh, expiry handling)
- Test chunked upload logic (INIT/APPEND/FINALIZE sequencing)
- Test error handling (rate limits, expired tokens, network errors)
- Test `UploadResult` creation for success and failure

**Dependencies**: 3.3–3.6

---

## Dependency Graph

```
3.1 ◄── (base interface)
 │
 ├──▶ 3.2 ◄── (OAuth scripts)
 │
 ├──▶ 3.3 (YouTube)  ─┐
 ├──▶ 3.4 (TikTok)   ─┤  (can be done in parallel)
 ├──▶ 3.5 (Facebook)  ─┤
 └──▶ 3.6 (X)         ─┘
              │
              ▼
            3.7 ◄── (factory, needs all uploaders)
              │
              ▼
            3.8 ◄── (tests)
```

---

## Verification Checklist

### V3.1: OAuth setup for YouTube

```bash
python3 scripts/setup_oauth.py youtube
```

Then verify:
```bash
python3 -c "
import json
with open('config/youtube_token.json') as f:
    token = json.load(f)
print('Has refresh_token:', 'refresh_token' in token)
"
```

**Expected**: Browser opens, user authorizes, `refresh_token` present in saved token.

### V3.2: YouTube upload (private)

```bash
python3 -c "
import asyncio
from src.uploader.youtube import YouTubeUploader
from src.uploader.base import VideoMetadata
from src.utils.config import load_config
from pathlib import Path

async def test():
    cfg = load_config()
    yt = YouTubeUploader(cfg['platforms']['youtube'])
    await yt.authenticate()
    result = await yt.upload(
        Path('data/output/<video_id>_youtube.mp4'),
        VideoMetadata(title='Test Upload', description='Testing pipeline',
                      tags=['test'], privacy='private')
    )
    print(f'Success: {result.success}')
    print(f'URL: {result.post_url}')
asyncio.run(test())
"
```

**Expected**: `Success: True`, video visible in YouTube Studio as private.

### V3.3: TikTok upload (draft)

```bash
python3 -c "
import asyncio
from src.uploader.tiktok import TikTokUploader
from src.uploader.base import VideoMetadata
from src.utils.config import load_config
from pathlib import Path

async def test():
    cfg = load_config()
    tt = TikTokUploader(cfg['platforms']['tiktok'])
    await tt.authenticate()
    result = await tt.upload(
        Path('data/output/<video_id>_tiktok.mp4'),
        VideoMetadata(title='Test', description='#test', tags=['test'])
    )
    print(f'Success: {result.success}')
    print(f'Post ID: {result.post_id}')
asyncio.run(test())
"
```

**Expected**: `Success: True`, video appears in TikTok inbox as draft.

### V3.4: Facebook upload

```bash
python3 -c "
import asyncio
from src.uploader.facebook import FacebookUploader
from src.uploader.base import VideoMetadata
from src.utils.config import load_config
from pathlib import Path

async def test():
    cfg = load_config()
    fb = FacebookUploader(cfg['platforms']['facebook'])
    await fb.authenticate()
    result = await fb.upload(
        Path('data/output/<video_id>_facebook.mp4'),
        VideoMetadata(title='Test', description='Testing', tags=['test'])
    )
    print(f'Success: {result.success}')
    print(f'URL: {result.post_url}')
asyncio.run(test())
"
```

**Expected**: `Success: True`, video visible on Facebook Page.

### V3.5: X upload (if enabled)

```bash
python3 -c "
import asyncio
from src.uploader.x import XUploader
from src.uploader.base import VideoMetadata
from src.utils.config import load_config
from pathlib import Path

async def test():
    cfg = load_config()
    x = XUploader(cfg['platforms']['x'])
    await x.authenticate()
    result = await x.upload(
        Path('data/output/<video_id>_x.mp4'),
        VideoMetadata(title='Test', description='Testing pipeline')
    )
    print(f'Success: {result.success}')
    print(f'Tweet URL: {result.post_url}')
asyncio.run(test())
"
```

**Expected**: `Success: True`, tweet with video visible on X.

### V3.6: Uploader factory returns correct types

```bash
python3 -c "
from src.uploader import get_uploader, get_enabled_uploaders
from src.utils.config import load_config

cfg = load_config()
yt = get_uploader('youtube', cfg)
print(type(yt).__name__)  # YouTubeUploader

enabled = get_enabled_uploaders(cfg)
print(list(enabled.keys()))  # ['youtube', 'tiktok', 'facebook']
"
```

**Expected**: Correct class names, X excluded (disabled by default).

### V3.7: Error handling — nonexistent file

```bash
python3 -c "
import asyncio
from src.uploader.youtube import YouTubeUploader
from src.uploader.base import VideoMetadata
from src.utils.config import load_config
from pathlib import Path

async def test():
    cfg = load_config()
    yt = YouTubeUploader(cfg['platforms']['youtube'])
    await yt.authenticate()
    result = await yt.upload(
        Path('nonexistent.mp4'),
        VideoMetadata(title='Test', description='Test', tags=[])
    )
    print(f'Success: {result.success}')  # False
    print(f'Error: {result.error}')
asyncio.run(test())
"
```

**Expected**: `Success: False`, meaningful error message (not unhandled exception).

### V3.8: Unit tests pass

```bash
python3 -m pytest tests/test_uploader.py -v
```

---

## Edge Cases

1. **Token expiry mid-upload**: Resumable uploads can take minutes. Refresh token and retry failed chunk.
2. **TikTok rate limit**: 6 req/min. Implement throttling with `asyncio.Semaphore` or token bucket.
3. **TikTok upload URL expiry**: Expires after 1 hour. If upload takes longer, re-init.
4. **Large file chunking**: Track chunk offsets, handle partial uploads and resume.
5. **Facebook token types**: Must use page token (not user token) for page posts.
6. **YouTube Shorts detection**: Check both duration (≤60s) AND aspect ratio (9:16).
7. **X API plan**: Verify Basic plan before upload attempt. Free tier returns auth errors.
8. **Network interruption**: Resume from last successful chunk (YouTube, Facebook).
9. **Duplicate upload**: Check by title+duration or hash before uploading again.
