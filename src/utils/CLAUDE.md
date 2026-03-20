# Utils Module

Shared utilities used across all pipeline stages.

## Key Components

- `config.py` — `load_config()`: loads YAML config with `${ENV_VAR}` interpolation from `.env` and environment.
- `logger.py` — `setup_logger()`: structured JSON logging to console (rich) + file (`data/logs/pipeline.log`). Per-video logs at `data/logs/{video_id}.log`.
- `metadata.py` — `VideoMetadata` dataclass (shared across downloader/pipeline). `map_metadata()` converts Douyin metadata to per-platform format (YouTube title limits, TikTok hashtags, X 280-char limit).
- `retry.py` — `retry` / `async_retry` decorators using `tenacity`. Exponential backoff with jitter, retries on network errors and rate limits.
- `state.py` — `PipelineState`: per-video state persistence to `data/logs/{video_id}_state.json`. Tracks completed stages for crash recovery. Also handles duplicate detection via `data/logs/processed_videos.json`.

## Constraints

- Config supports env var interpolation (`${VAR}`) — secrets never hardcoded in YAML.
- All timestamps stored as UTC ISO 8601.
- State files use `fcntl.flock` for multi-instance safety.

## Connects To

- Used by every other module. `config.py` and `logger.py` are imported first in any pipeline stage.
