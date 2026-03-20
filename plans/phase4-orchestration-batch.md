# Phase 4 — Orchestration + Batch Processing (Week 4-5)

---

## Task List

### 4.1 Retry Utility — `src/utils/retry.py`

- `retry` decorator using `tenacity`:
  - Configurable: `max_attempts`, `base_delay`, `max_delay`
  - Exponential backoff with jitter
  - Retry on specific exceptions (network errors, rate limits, 5xx)
  - Log each retry attempt with delay info
- `async_retry` variant for async functions
- **Dependencies**: Phase 1 task 1.6

### 4.2 State Persistence — `src/utils/state.py`

Class `PipelineState`:
- State file: `data/logs/{video_id}_state.json`
- Fields:
  - `video_id`, `url`, `status` (pending/downloading/transcribing/processing/uploading/done/failed)
  - `completed_stages: list[str]`
  - `stage_results: dict` (per-stage output metadata)
  - `timestamps: dict` (start/end per stage)
  - `error: str | None`
- Methods:
  - `load(video_id: str) -> PipelineState` (class method)
  - `save() -> None`
  - `mark_stage_complete(stage: str, result: dict) -> None`
  - `get_resume_stage() -> str | None` — returns first incomplete stage
  - `is_complete() -> bool`

On crash recovery: read state file, skip completed stages, resume from last incomplete.

**Dependencies**: Phase 1 task 1.3

### 4.3 Duplicate Detection — `src/utils/state.py`

Registry file: `data/logs/processed_videos.json` (dict of `video_id → {url, status, timestamp, platforms}`)

Functions:
- `is_duplicate(video_id: str) -> bool`
- `register_processed(video_id: str, result: dict) -> None`
- Also support URL-based dedup (normalize different URL formats for same video)

**Dependencies**: 4.2

### 4.4 Pipeline Orchestrator — `src/pipeline.py`

Class `Pipeline`:

**`async process_single(url, platforms, options) -> dict`**:
1. Parse URL → extract video_id (or let downloader do it)
2. Check duplicate → skip if already processed (unless `--force`)
3. Load or create `PipelineState`
4. **Download** (skip if state shows completed):
   - `download_with_fallback(url, data/raw, config)` → `VideoMetadata`
   - `state.mark_stage_complete("download", metadata)`
5. **Transcribe** (skip if completed):
   - `transcriber.transcribe(video_path, language)` → segments
   - `transcriber.generate_srt(segments, srt_path)` → SRT file
   - If translate requested: generate `_en.srt` too
   - `state.mark_stage_complete("transcribe", {srt_path, segments_count})`
6. **Process** (skip completed per-platform):
   - `process_for_all_platforms(video_path, srt_dir, output_dir, platforms, config)`
   - `state.mark_stage_complete("process", {platform: output_path})`
7. **Upload** (skip completed per-platform):
   - For each platform: `uploader.upload(output_path, mapped_metadata)`
   - `state.mark_stage_complete("upload", {platform: upload_result})`
8. Mark state as `done`, register in processed videos

**`async process_batch(urls, platforms, options) -> list[dict]`**:
- Read URLs, filter duplicates
- Process with `asyncio.Semaphore(max_concurrent)`
- Collect results, log summary

**Dependencies**: Phase 1 (1.10, 1.14), Phase 2 (2.5), Phase 3 (3.7), 4.1, 4.2, 4.3, 4.5

### 4.5 Metadata Mapper — `src/utils/metadata.py` (extend)

Function `map_metadata(douyin_meta, platform, overrides=None) -> VideoMetadata`:

Per-platform formatting:
- **YouTube**: Append `#Shorts` if short-form. Add hashtags to description. Title max 100 chars.
- **YouTube Shorts**: Same as YouTube with `#Shorts` forced.
- **TikTok**: Hashtags go in description (not separate field). Description max 2200 chars.
- **Facebook**: Standard title + description.
- **X/Twitter**: Tweet text max 280 chars. Truncate title with ellipsis.

Apply user overrides last. Enforce character limits per platform.

**Dependencies**: Phase 3 task 3.1

### 4.6 CLI Interface — `src/cli.py`

Click-based CLI with commands:

```
douyin-repurpose process <URL>
    --platforms youtube,tiktok,facebook,x
    --subtitle-lang zh
    --translate en
    --title "Custom Title"
    --tags "tag1,tag2"
    --privacy private|public|unlisted
    --force                          # ignore duplicate detection

douyin-repurpose download <URL>
    --output-dir data/raw

douyin-repurpose transcribe <VIDEO_PATH>
    --lang zh
    --translate en
    --model large-v3

douyin-repurpose upload <VIDEO_PATH>
    --platforms youtube,tiktok
    --title "Title"
    --description "Desc"
    --tags "tag1,tag2"

douyin-repurpose batch <URL_FILE>
    --platforms youtube,tiktok,facebook
    --concurrency 3
    --subtitle-lang zh
    --translate en

douyin-repurpose status [VIDEO_ID]
    # no args = show all recent; with ID = show specific
```

- Use `rich` for progress bars, tables, and colored output
- Entry point: `python -m src` or `douyin-repurpose` (if pip-installed)

**Dependencies**: 4.4

### 4.7 Structured Logging — `src/utils/logger.py` (finalize)

JSON log format fields: `timestamp` (ISO 8601 UTC), `level`, `video_id`, `stage`, `message`, `duration_ms`, `extra`

Output destinations:
- Console: human-readable with `rich` formatting
- File: JSON lines to `data/logs/pipeline.log`
- Per-video: `data/logs/{video_id}.log`

**Dependencies**: Phase 1 task 1.6 (extends existing)

### 4.8 Module Entry Point — `src/__main__.py`

```python
from src.cli import main
main()
```

Enables `python -m src` execution.

**Dependencies**: 4.6

### 4.9 README.md

Sections: Overview, Prerequisites, Installation (venv + pip), Configuration, Usage (with CLI examples), Architecture diagram, Development, Troubleshooting.

**Dependencies**: All prior tasks (write last)

### 4.10 Integration Tests — `tests/test_pipeline.py`

- Full pipeline with mocked external services
- Crash recovery: interrupt mid-pipeline, verify resume
- Batch mode: mixed success/failure URLs
- Duplicate detection: same URL twice
- CLI argument parsing
- State file creation and loading

**Dependencies**: 4.4, 4.6

---

## Dependency Graph

```
4.1 (retry)  ◄── (needs 1.6)
4.2 (state)  ◄── (needs 1.3)
4.3 (dedup)  ◄── (needs 4.2)
4.5 (metadata mapper) ◄── (needs 3.1)
                │
                ▼
4.4 (pipeline orchestrator) ◄── (needs 1.10, 1.14, 2.5, 3.7, 4.1, 4.2, 4.3, 4.5)
                │
        ┌───────┼───────┐
        ▼       ▼       ▼
      4.6     4.7     4.5
     (CLI)   (logs)  (metadata)
        │
        ▼
      4.8 (__main__)
        │
        ▼
     4.9 (README)
     4.10 (tests)
```

---

## Verification Checklist

### V4.1: CLI help displays correctly

```bash
python3 -m src --help
```

**Expected**:
```
Usage: python -m src [OPTIONS] COMMAND [ARGS]...

  Douyin Video Repurposing Pipeline

Commands:
  process     Process a single Douyin video URL
  download    Download a Douyin video
  transcribe  Transcribe a local video file
  upload      Upload a processed video
  batch       Process multiple URLs from a file
  status      Show processing status
```

### V4.2: CLI process subcommand shows options

```bash
python3 -m src process --help
```

**Expected**: All options listed with descriptions.

### V4.3: Full pipeline — single video end-to-end

```bash
python3 -m src process "https://v.douyin.com/iRNBho6t/" \
    --platforms youtube,tiktok,facebook \
    --subtitle-lang zh \
    --translate en \
    --privacy private
```

**Expected output** (rich-formatted):
```
[1/4] Downloading video... ✓ (video_id: 7xxxxxxxxx)
[2/4] Transcribing audio... ✓ (45 segments, lang: zh)
[3/4] Processing for 3 platforms... ✓
  - youtube: data/output/7xxx_youtube.mp4
  - tiktok: data/output/7xxx_tiktok.mp4
  - facebook: data/output/7xxx_facebook.mp4
[4/4] Uploading to 3 platforms... ✓
  - youtube: https://youtu.be/xxx (private)
  - tiktok: draft uploaded
  - facebook: https://facebook.com/xxx

Pipeline complete in 3m 42s
```

Verify files:
```bash
ls -la data/raw/*.mp4 data/srt/*.srt data/output/*.mp4
cat data/logs/<video_id>_state.json | python3 -m json.tool
```

### V4.4: State persistence + crash recovery

```bash
# Step 1: Start and interrupt
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube &
PID=$!; sleep 30; kill -INT $PID

# Step 2: Check state
python3 -c "
import json
from pathlib import Path
for sf in Path('data/logs').glob('*_state.json'):
    state = json.loads(sf.read_text())
    print(f'Video: {state[\"video_id\"]}')
    print(f'Status: {state[\"status\"]}')
    print(f'Completed: {state[\"completed_stages\"]}')
"

# Step 3: Resume
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube
```

**Expected**: Step 3 skips download ("already complete"), resumes from next stage.

### V4.5: Duplicate detection

```bash
# Process same URL twice
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube --privacy private
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube --privacy private
```

**Expected**: Second run outputs "Video 7xxxxxxxxx already processed, skipping".

```bash
# Force re-process
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube --force
```

**Expected**: Processes again despite duplicate.

### V4.6: Batch processing

```bash
# Create URL file
cat > /tmp/test_urls.txt << 'EOF'
https://v.douyin.com/iRNBho6t/
https://v.douyin.com/xxxxx2/
https://v.douyin.com/xxxxx3/
EOF

python3 -m src batch /tmp/test_urls.txt \
    --platforms youtube,tiktok \
    --concurrency 2 \
    --privacy private
```

**Expected summary**:
```
Batch complete: 3 videos
  Succeeded: 2
  Failed: 1 (video_id: xxx — reason: download timeout)
  Skipped: 0 (duplicates)
```

### V4.7: Retry logic

```bash
python3 -c "
from src.utils.retry import retry
attempt = 0

@retry(max_attempts=3, base_delay=1)
def flaky():
    global attempt
    attempt += 1
    if attempt < 3:
        raise ConnectionError(f'Attempt {attempt} failed')
    return 'success'

result = flaky()
print(f'Result: {result}, attempts: {attempt}')
"
```

**Expected**: `Result: success, attempts: 3`.

### V4.8: Structured JSON logs

```bash
python3 -m src process "https://v.douyin.com/iRNBho6t/" --platforms youtube --privacy private

# Verify log format
python3 -c "
import json
with open('data/logs/pipeline.log') as f:
    for line in f:
        entry = json.loads(line.strip())
        print(f'{entry[\"timestamp\"]} [{entry[\"level\"]}] {entry.get(\"stage\",\"\")} - {entry[\"message\"]}')
" | tail -10
```

**Expected**: Each line is valid JSON with `timestamp`, `level`, `video_id`, `stage`, `message`.

### V4.9: Status command

```bash
python3 -m src status
```

**Expected** (rich table):
```
┌──────────────┬────────────┬──────────────────────┬───────────┐
│ Video ID     │ Status     │ Platforms            │ Timestamp │
├──────────────┼────────────┼──────────────────────┼───────────┤
│ 7xxxxxxxxx1  │ done       │ youtube, tiktok      │ 2026-03-20│
│ 7xxxxxxxxx2  │ failed     │ youtube              │ 2026-03-20│
└──────────────┴────────────┴──────────────────────┴───────────┘
```

### V4.10: Integration tests

```bash
python3 -m pytest tests/ -v --tb=short
```

**Expected**: All tests pass.

---

## Edge Cases

1. **Empty URL file**: Exit gracefully: "No URLs to process."
2. **Malformed URLs**: Skip invalid, log warning, continue with valid ones.
3. **All platforms fail**: Mark video as `failed`, log all errors, continue batch.
4. **Disk space**: Check available space before download. Warn if < 1GB free.
5. **Concurrent state access**: Use `fcntl.flock` on state files for multi-instance safety.
6. **Missing config**: Clear error: "config/config.yaml not found. Copy config/config.example.yaml and edit."
7. **Partial platform success**: YouTube OK but TikTok fails. Mark upload as partial, don't re-upload YouTube on retry.
8. **Signal handling**: Catch SIGINT/SIGTERM → save state → clean exit. Enables resume on next run.
9. **Character limits**: YouTube title 100, TikTok desc 2200, X tweet 280. Truncate with `…` if exceeded.
10. **Timezone**: Store UTC (ISO 8601). Display local timezone in CLI output.

---

## Complete File Manifest (All Phases)

| File | Phase | Purpose |
|------|-------|---------|
| `pyproject.toml` | 1 | Project metadata + dependencies |
| `requirements.txt` | 1 | Common deps |
| `requirements-linux.txt` | 1 | faster-whisper |
| `requirements-macos.txt` | 1 | mlx-whisper |
| `.gitignore` | 1 | Ignore rules |
| `config/config.yaml` | 1 | Main config |
| `config/platforms.yaml` | 1+2 | Platform settings |
| `config/subtitle_styles.yaml` | 2 | Subtitle styling |
| `src/__init__.py` | 1 | Package init |
| `src/__main__.py` | 4 | Module entry |
| `src/cli.py` | 4 | CLI |
| `src/pipeline.py` | 4 | Orchestrator |
| `src/downloader/__init__.py` | 1 | Downloader factory |
| `src/downloader/douyin.py` | 1 | Douyin API client |
| `src/downloader/ytdlp.py` | 1 | yt-dlp fallback |
| `src/transcriber/__init__.py` | 1 | Transcriber factory |
| `src/transcriber/base.py` | 1 | Base interface + SRT gen |
| `src/transcriber/faster.py` | 1 | faster-whisper backend |
| `src/transcriber/mlx.py` | 1 | mlx-whisper backend |
| `src/processor/__init__.py` | 2 | Batch processor |
| `src/processor/subtitle.py` | 2 | SRT/ASS handling |
| `src/processor/ffmpeg.py` | 2 | FFmpeg wrapper |
| `src/uploader/__init__.py` | 3 | Uploader factory |
| `src/uploader/base.py` | 3 | ABC + dataclasses |
| `src/uploader/youtube.py` | 3 | YouTube Data API v3 |
| `src/uploader/tiktok.py` | 3 | TikTok Content Posting |
| `src/uploader/facebook.py` | 3 | Facebook Graph API |
| `src/uploader/x.py` | 3 | X/Twitter API v2 |
| `src/utils/__init__.py` | 1 | Utils package |
| `src/utils/config.py` | 1 | Config loader |
| `src/utils/logger.py` | 1+4 | Structured logging |
| `src/utils/metadata.py` | 1+4 | Metadata + mapping |
| `src/utils/retry.py` | 4 | Retry decorator |
| `src/utils/state.py` | 4 | State + dedup |
| `scripts/setup_oauth.py` | 3 | OAuth setup |
| `scripts/refresh_douyin_cookie.py` | 1 | Cookie helper |
| `tests/test_downloader.py` | 1 | Downloader tests |
| `tests/test_transcriber.py` | 1 | Transcriber tests |
| `tests/test_processor.py` | 2 | Processor tests |
| `tests/test_uploader.py` | 3 | Uploader tests |
| `tests/test_pipeline.py` | 4 | Integration tests |
| `README.md` | 4 | Documentation |
