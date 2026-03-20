# FastAPI Backend + React UI Integration Plan

> This plan is also saved to `plans/phase1-api-ui-integration.md` in the repo.

## Context

Phase 1 Python pipeline (download + transcribe) is complete and tested. A React UI (`ui-app/`) with 5 pages exists using mock data. We need to:
1. Build a FastAPI backend that wraps the existing pipeline code
2. Wire the React UI to call real API endpoints instead of mock data
3. Support real-time progress via SSE for long-running download/transcribe tasks

## Scope — Phase 1 API only

- Download endpoints (start download, list videos, video details)
- Transcribe endpoints (start transcription, get SRT)
- SSE event streaming for task progress
- Dashboard stats endpoint
- Wire DownloadTranscribe + Dashboard pages to real data

NOT in scope: process, upload, auth, settings save — those come in later phases.

---

## Step 1: Backend Foundation

### New files
```
src/api/__init__.py          # create_app() factory
src/api/main.py              # uvicorn entrypoint
src/api/models.py            # Pydantic request/response models
src/api/deps.py              # Shared deps: config, task_manager singleton
src/api/task_manager.py      # In-memory task store + background runner
src/api/routers/__init__.py  # empty
src/api/routers/download.py  # POST /api/download, GET /api/videos, GET /api/videos/{id}, GET /api/stats
src/api/routers/transcribe.py # POST /api/transcribe, GET /api/videos/{id}/srt
src/api/routers/events.py    # GET /api/events/{task_id} (SSE)
```

### `src/api/models.py` — Pydantic models (match UI mockData.ts shapes)

```python
# Requests
DownloadRequest:     { url: str }
TranscribeRequest:   { video_id: str, language: str = "zh", task: str = "transcribe" }

# Responses
TaskResponse:        { task_id: str, status: str }
VideoResponse:       { video_id, title, author, duration, resolution, size, codec,
                       description, hashtags, source_url, file_path, has_srt, status }
VideoListResponse:   { videos: list[VideoResponse], total: int }
SubtitleSegment:     { id: int, startTime: str, endTime: str, text: str, translation?: str }
SrtResponse:         { video_id: str, segments: list[SubtitleSegment], language: str }
DashboardStats:      { totalVideos: int, processedToday: int, successRate: float, activeTasks: int }
```

### `src/api/deps.py` — Dependency injection
- `get_config()` — calls `src.utils.config.load_config()`, caches result. Falls back to `config.example.yaml` if `config.yaml` missing
- `get_task_manager()` — returns singleton `TaskManager`

### `src/api/__init__.py` — App factory
- Creates FastAPI app with CORS middleware (allow `localhost:5173`)
- Includes download, transcribe, events routers
- On startup: `task_manager.scan_existing_videos()` to index `data/raw/*.mp4`
- Mounts static files: `/files/raw` → `data/raw/`, `/files/srt` → `data/srt/`

### `src/api/main.py` — Entry point
- `python -m src.api.main` or `uvicorn src.api.main:app --reload --port 8000`

---

## Step 2: Task Manager (`src/api/task_manager.py`)

In-memory task tracking + background execution. No database.

### Task dataclass
```python
@dataclass
class Task:
    task_id: str                # uuid4
    task_type: str              # "download" | "transcribe"
    status: str                 # "queued" | "running" | "completed" | "failed"
    video_id: str | None
    progress: float             # 0.0 - 1.0
    message: str                # human-readable status
    result: dict | None         # final payload
    error: str | None
    created_at: datetime
    events: list[dict]          # SSE event log for replay
```

### TaskManager class
- `tasks: dict[str, Task]` — all tasks
- `video_index: dict[str, VideoResponse]` — known videos (populated on startup scan)
- `_subscribers: dict[str, list[asyncio.Queue]]` — SSE subscriber queues per task_id

Key methods:
- `scan_existing_videos()` — walks `data/raw/*.mp4`, runs `extract_metadata_from_file()`, checks for `data/srt/{id}_zh.srt`, populates `video_index`
- `create_task(task_type) -> Task`
- `_emit(task_id, event, data)` — appends to `task.events`, pushes to all subscriber queues
- `run_download(task_id, url, config)` — calls `download_with_fallback()`, emits progress/complete/error
- `run_transcribe(task_id, video_id, language, task, config)` — calls `get_transcriber()` then `transcribe()` + `generate_srt()`. **Key: run `transcriber.transcribe()` via `asyncio.to_thread()` since it's CPU-bound**
- `subscribe(task_id) -> AsyncGenerator` — yields SSE events, replays missed events first

### Existing functions reused directly:
- `src.downloader.download_with_fallback(url, output_dir, config)` → returns `VideoMetadata`
- `src.transcriber.get_transcriber(config)` → returns `BaseTranscriber`
- `src.transcriber.base.BaseTranscriber.transcribe()` and `.generate_srt()`
- `src.processor.subtitle.parse_srt(srt_path)` → returns `list[dict]`
- `src.utils.metadata.extract_metadata_from_file(path)` → returns `dict`

---

## Step 3: API Routers

### `src/api/routers/download.py`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/download` | POST | Start download → `{task_id, status}` |
| `/api/videos` | GET | List all videos from `video_index` |
| `/api/videos/{video_id}` | GET | Single video detail |
| `/api/stats` | GET | Dashboard stats from `video_index` + `tasks` |

POST /api/download flow:
1. Create task via `task_manager.create_task("download")`
2. `asyncio.create_task(task_manager.run_download(task_id, url, config))`
3. Return `TaskResponse` immediately

GET /api/stats: counts from `video_index` (total, today's mtime, success rate) + active tasks

### `src/api/routers/transcribe.py`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/transcribe` | POST | Start transcription → `{task_id, status}` |
| `/api/videos/{video_id}/srt` | GET | Parsed SRT segments (uses `parse_srt()`) |

GET /api/videos/{id}/srt: reads `data/srt/{video_id}_zh.srt` (or `?language=en`), calls `parse_srt()`, maps to `SubtitleSegment` format

### `src/api/routers/events.py`
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/events/{task_id}` | GET | SSE stream |

Uses `StreamingResponse` with `text/event-stream` media type. Yields `event: {type}\ndata: {json}\n\n`.

---

## Step 4: Frontend API Layer

### New files
```
ui-app/src/api/types.ts      # TypeScript interfaces matching Pydantic models
ui-app/src/api/client.ts     # fetch-based API calls + SSE helper
```

### `ui-app/src/api/types.ts`
Mirror Pydantic models as TS interfaces:
- `TaskResponse`, `VideoMetadata`, `VideoListResponse`
- `SubtitleSegment`, `SrtResponse`, `DashboardStats`

### `ui-app/src/api/client.ts`
Native fetch wrappers (no axios):
- `postDownload(url: string): Promise<TaskResponse>`
- `getVideos(): Promise<VideoListResponse>`
- `getVideo(id: string): Promise<VideoMetadata>`
- `postTranscribe(videoId: string, language?: string, task?: string): Promise<TaskResponse>`
- `getSrt(videoId: string, language?: string): Promise<SrtResponse>`
- `getStats(): Promise<DashboardStats>`
- `subscribeSSE(taskId: string, onEvent: (type, data) => void): EventSource`

---

## Step 5: Vite Proxy Config

Edit `ui-app/vite.config.ts` — add dev proxy:
```typescript
server: {
  proxy: {
    '/api': 'http://localhost:8000',
    '/files': 'http://localhost:8000',
  }
}
```

---

## Step 6: Wire DownloadTranscribe Page

File: `ui-app/src/pages/DownloadTranscribe.tsx`

Currently: static mock data, no state, no handlers.

Changes:
1. **Add state**: `url`, `downloadTask`, `videoMeta`, `srtSegments`, `recentVideos`, `isDownloading`, `isTranscribing`, `downloadProgress`, `transcribeStatus`
2. **URL input + Download button**: `onClick` → call `postDownload(url)` → subscribe SSE → update progress bar → on complete, set `videoMeta`
3. **Transcribe button**: `onClick` → call `postTranscribe(videoMeta.video_id)` → subscribe SSE → on complete, call `getSrt()` → set `srtSegments`
4. **SRT Preview**: render from `srtSegments` state (empty state when no data)
5. **Recent Downloads**: `useEffect` on mount → `getVideos()` → map to grid
6. **Conditional rendering**: show/hide Active Download card, Video Result card, Transcription Progress based on current state
7. **Remove** imports of `srtSegments` and `recentDownloads` from `mockData.ts`

---

## Step 7: Wire Dashboard Page

File: `ui-app/src/pages/Dashboard.tsx`

Currently: hardcoded numbers, hardcoded table rows, hardcoded activity feed.

Changes:
1. **Stats row**: `useEffect` → `getStats()` → render real numbers
2. **Pipeline table**: `useEffect` → `getVideos()` → map to table rows with stage dots derived from video status
3. **Quick Process**: wire START button to `postDownload()` (same flow as DownloadTranscribe)
4. **Activity feed**: keep as mock for Phase 1 (real log tailing is out of scope)
5. **Batch Engine**: keep as mock for Phase 1 (batch processing is Phase 4)

---

## Step 8: Dependencies + Makefile

### pyproject.toml — add to `dependencies`:
```
"fastapi>=0.115.0",
"uvicorn[standard]>=0.30.0",
```

### Makefile — add targets:
```makefile
api:
	uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

ui:
	cd ui-app && npm run dev

dev:
	@echo "Run 'make api' and 'make ui' in separate terminals"
```

---

## Key Technical Decisions

1. **`src/api/` not `server/`** — keeps backend inside the existing `src` package so it can `from src.downloader import download_with_fallback` directly
2. **`asyncio.to_thread()`** for `transcriber.transcribe()` — Whisper inference is CPU-bound and would block the event loop otherwise
3. **No database** — `video_index` built on startup by scanning `data/raw/*.mp4` filesystem. In-memory `tasks` dict for active tasks
4. **SSE over WebSocket** — simpler, sufficient for unidirectional progress updates, no extra dependencies
5. **Coarse progress for Phase 1** — download emits start/complete (no byte-level progress since `download_with_fallback` doesn't expose callbacks). Fine-grained progress can be added later

---

## Files Modified (existing)

| File | Change |
|------|--------|
| `pyproject.toml` | Add fastapi, uvicorn deps |
| `Makefile` | Add `api`, `ui`, `dev` targets |
| `ui-app/vite.config.ts` | Add proxy config |
| `ui-app/src/pages/DownloadTranscribe.tsx` | Replace mock data with API calls + state |
| `ui-app/src/pages/Dashboard.tsx` | Wire stats + video list from API |

## Files Created (new)

| File | Purpose |
|------|---------|
| `src/api/__init__.py` | FastAPI app factory |
| `src/api/main.py` | Uvicorn entrypoint |
| `src/api/models.py` | Pydantic models |
| `src/api/deps.py` | Config + TaskManager DI |
| `src/api/task_manager.py` | Background task execution + SSE |
| `src/api/routers/__init__.py` | Empty |
| `src/api/routers/download.py` | Download + videos + stats endpoints |
| `src/api/routers/transcribe.py` | Transcribe + SRT endpoints |
| `src/api/routers/events.py` | SSE streaming endpoint |
| `ui-app/src/api/types.ts` | TS interfaces |
| `ui-app/src/api/client.ts` | Fetch wrappers + SSE helper |

---

## Verification

1. `pip install -e ".[macos]"` installs with fastapi/uvicorn
2. `make api` starts FastAPI at :8000, Swagger UI at `/docs`
3. `make ui` starts Vite dev server at :5173 with proxy
4. POST `/api/download` with real Douyin URL → returns task_id → SSE streams progress → video appears in `GET /api/videos`
5. POST `/api/transcribe` → SSE streams progress → `GET /api/videos/{id}/srt` returns segments
6. DownloadTranscribe page: paste URL → download → see video card → transcribe → see SRT preview
7. Dashboard: stats row shows real counts, pipeline table shows real videos
8. `pytest tests/ -v -m "not integration"` still passes
