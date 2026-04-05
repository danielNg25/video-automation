# Phase 7 — Platform Upload Integrations (Week 7-8)

> **Recommended order**: YouTube (easiest API, best docs) → Facebook → TikTok → X (stretch goal)

---

## Task List

### 7.1 Base Uploader Interface — `src/uploader/base.py`

Dataclasses:
- `UploadResult`: `platform`, `success`, `post_id`, `post_url`, `error`, `timestamp`
- `VideoMetadata`: `title`, `description`, `tags: list[str]`, `privacy: str`, `category: str`

Abstract class `BaseUploader(ABC)`:
- `async authenticate() -> None`
- `async upload(video_path: Path, metadata: VideoMetadata) -> UploadResult`
- `async check_status(post_id: str) -> dict`
- `async refresh_token() -> None`

**Dependencies**: Phase 1 task 1.6

### 7.2 OAuth Setup Script — `scripts/setup_oauth.py`

Click-based CLI: `python scripts/setup_oauth.py <platform>`

Subcommands:
- `youtube` — Open browser for Google OAuth → save token to `config/youtube_token.json`
- `tiktok` — Open browser for TikTok OAuth with PKCE → save token
- `facebook` — Guide through token exchange → save long-lived page token
- `x` — Prompt for API keys → verify with test call

**Dependencies**: 7.1

### 7.3 YouTube Uploader — `src/uploader/youtube.py`

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

**Dependencies**: 7.1, 7.2

### 7.4 TikTok Uploader — `src/uploader/tiktok.py`

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

**Dependencies**: 7.1, 7.2

### 7.5 Facebook Uploader — `src/uploader/facebook.py`

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

**Dependencies**: 7.1, 7.2

### 7.6 X/Twitter Uploader — `src/uploader/x.py` *(Stretch Goal)*

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

**Dependencies**: 7.1, 7.2

### 7.7 Uploader Factory — `src/uploader/__init__.py`

- `get_uploader(platform: str, config: dict) -> BaseUploader`
- `get_enabled_uploaders(config: dict) -> dict[str, BaseUploader]` — returns only `enabled: true` platforms

**Dependencies**: 7.3, 7.4, 7.5, 7.6

### 7.8 Phase 3 Tests — `tests/test_uploader.py`

- Mock API responses for each platform (use `httpx` mock or `responses` library)
- Test auth flow (token load, refresh, expiry handling)
- Test chunked upload logic (INIT/APPEND/FINALIZE sequencing)
- Test error handling (rate limits, expired tokens, network errors)
- Test `UploadResult` creation for success and failure

**Dependencies**: 7.3–7.6

---

## Dependency Graph

```
7.1 ◄── (base interface)
 │
 ├──▶ 7.2 ◄── (OAuth scripts)
 │
 ├──▶ 7.3 (YouTube)  ─┐
 ├──▶ 7.4 (TikTok)   ─┤  (can be done in parallel)
 ├──▶ 7.5 (Facebook)  ─┤
 └──▶ 7.6 (X)         ─┘
              │
              ▼
            7.7 ◄── (factory, needs all uploaders)
              │
              ▼
            7.8 ◄── (tests)
```

---

## Verification Checklist

### V7.1: OAuth setup for YouTube

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

### V7.2: YouTube upload (private)

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

### V7.3: TikTok upload (draft)

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

### V7.4: Facebook upload

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

### V7.5: X upload (if enabled)

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

### V7.6: Uploader factory returns correct types

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

### V7.7: Error handling — nonexistent file

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

### V7.8: Unit tests pass

```bash
python3 -m pytest tests/test_uploader.py -v
```

---

## Web UI + API (Phase 7)

### 7.9 Auth Router — `server/routers/auth.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/auth/status` | Check OAuth status for all platforms |
| `POST` | `/api/auth/{platform}/start` | Start OAuth flow → `{auth_url}` |
| `POST` | `/api/auth/{platform}/callback` | Handle OAuth callback `{code}` → save token |

**`GET /api/auth/status` response:**
```json
{
  "youtube": {"authenticated": true, "account": "user@gmail.com", "expires": "2026-04-19"},
  "tiktok": {"authenticated": false},
  "facebook": {"authenticated": true, "page": "My Page", "expires": "2026-05-20"},
  "x": {"authenticated": false, "enabled": false, "reason": "Disabled in config"}
}
```

**OAuth flow:**
1. Frontend calls `POST /api/auth/youtube/start`
2. Backend generates auth URL with redirect to `http://localhost:8000/api/auth/youtube/callback`
3. Backend returns `{auth_url}` → frontend opens in popup/new tab
4. User authorizes → redirected back to callback endpoint
5. Backend exchanges code for token, saves to `config/{platform}_token.json`
6. Frontend polls `/api/auth/status` or receives confirmation via redirect

- **Dependencies**: 7.2 (OAuth setup script logic, reused)

### 7.10 Upload Router + Service — `server/routers/upload.py` + `server/services/upload_service.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/upload` | Start upload `{video_id, platforms, metadata}` → `{task_id}` |
| `GET` | `/api/upload/{task_id}` | Get upload result per platform |
| `POST` | `/api/upload/{task_id}/retry` | Retry failed platforms `{platforms: [...]}` |

**Service layer** (`upload_service.py`):
- Wraps `get_uploader()` and individual platform uploaders from `src/uploader/`
- Progress tracking per platform:
  - YouTube: resumable upload reports bytes sent / total bytes
  - TikTok: chunk upload reports chunks sent / total chunks
  - Facebook: 3-phase upload reports phase transitions (START → TRANSFER → FINISH)
  - X: 4-phase upload reports phase transitions (INIT → APPEND → FINALIZE → STATUS)
- Uploads platforms in parallel via `asyncio.gather()` with per-platform error handling
- Retry: re-creates uploader for failed platforms only, preserves successful results
- **Dependencies**: 7.7, Phase 1 tasks 1.19, 1.20

### 7.11 Upload Page — `web/src/pages/UploadPage.tsx`

**Components:**

1. **AuthStatusPanel** (top):
   - Horizontal row of platform cards
   - Each card shows:
     - Platform icon (YouTube red, TikTok dark, Facebook blue, X black)
     - Platform name
     - Status indicator: green dot (connected) / red dot (disconnected) / gray (disabled)
     - Connected: account name, "Disconnect" link
     - Disconnected: "Connect" button → opens OAuth popup
     - Disabled: "Disabled in settings" text, grayed card
   - Fetches from `GET /api/auth/status`, polls every 30s or on focus

2. **UploadForm** (middle):
   - Video selector: dropdown of processed videos (only those with platform outputs)
   - Platform checkboxes: only platforms that are both connected AND have processed output for this video
   - Per-platform metadata editor (accordion or tabs):
     - **Title** field with character counter (YouTube: 100, X: 280)
     - **Description** textarea with counter
     - **Tags/hashtags** input (pill-style tag input with suggestions)
     - **Privacy** selector: Public / Private / Unlisted (YouTube), Draft (TikTok)
     - Pre-filled from video's original metadata with platform-specific formatting
     - Counter turns red when exceeding limit
   - "Upload to Selected Platforms" button

3. **UploadProgress** (shown during upload):
   - Per-platform progress cards:
     - Platform icon + name
     - Progress bar with percentage (for YouTube/TikTok chunked uploads)
     - Stage text: "Authenticating..." → "Uploading (45%)" → "Processing..." → "Complete" / "Failed"
     - Platform-specific notes: "TikTok: Video will appear as draft"
   - Overall summary line: "Uploading to 3 platforms..."

4. **UploadResults** (shown after completion):
   - Per-platform result cards:
     - Success: green checkmark, clickable post URL (opens in new tab), thumbnail if available
     - Failed: red X, error message, "Retry" button
   - Summary: "3/4 platforms succeeded"
   - "Retry Failed" button (retries all failed at once)

**Key interactions:**
- "Connect" button → `POST /api/auth/{platform}/start` → open auth URL in popup → poll status until connected
- Metadata fields pre-fill when video is selected (from `VideoMetadata`)
- Character counters update live; turn red on exceed
- "Upload" → `POST /api/upload` → subscribe SSE → per-platform progress bars
- "Retry" → `POST /api/upload/{task_id}/retry` with failed platform list

- **Dependencies**: 7.9, 7.10, Phase 1 task 1.23

---

### Web UI Verification Checklist (Phase 7)

### V7.9: Auth status API

```bash
curl http://localhost:8000/api/auth/status
```

**Expected**: JSON with auth status per platform (authenticated/expired/disabled).

### V7.10: OAuth flow via API

```bash
curl -X POST http://localhost:8000/api/auth/youtube/start
# Returns: {"auth_url": "https://accounts.google.com/..."}
# Open URL in browser, authorize, check:
curl http://localhost:8000/api/auth/status
```

**Expected**: YouTube status changes to `authenticated: true`.

### V7.11: Upload via API

```bash
curl -X POST http://localhost:8000/api/upload \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "platforms": ["youtube"], "metadata": {"title": "Test", "description": "Test", "tags": ["test"], "privacy": "private"}}'
```

**Expected**: Upload starts, task returns success with post URL.

### V7.12: Upload page UI flow

1. Open Upload page → see auth status for all platforms
2. Click "Connect" on YouTube → authorize in popup → status turns green
3. Select a processed video → checkboxes appear for connected platforms
4. Edit title/description per platform → character counters work
5. Click Upload → see per-platform progress → see result URLs

**Expected**: Full upload flow from UI with real-time progress.

### V7.13: Retry failed upload

1. Upload to YouTube + TikTok (with TikTok intentionally failing — e.g., no auth)
2. YouTube succeeds, TikTok shows "Failed" with error
3. Fix TikTok auth → click "Retry" on TikTok
4. TikTok re-uploads without re-uploading YouTube

**Expected**: Only failed platform retried, successful results preserved.

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
