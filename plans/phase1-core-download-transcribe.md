# Phase 1 — Core: Download + Transcribe (Week 1-2)

> **Action**: Submit TikTok app for compliance audit at the start of this phase (takes 1-2 weeks).

---

## Task List

### 1.1 Project Scaffolding — `pyproject.toml`

- Define project metadata, Python >=3.11 requirement
- Split dependencies into groups: `[project.optional-dependencies]` with `linux` and `macos` extras
- Add `[project.scripts]` entry point: `douyin-repurpose = "src.cli:main"`
- **Dependencies**: None (first task)

### 1.2 Requirements Files

- Files: `requirements.txt`, `requirements-linux.txt`, `requirements-macos.txt`
- Common: httpx, pyyaml, click, yt-dlp, google-api-python-client, google-auth-oauthlib, authlib, tweepy, tenacity, rich
- Linux: `faster-whisper>=1.1.0`
- macOS: `mlx-whisper>=0.4.0`
- **Dependencies**: None (parallel with 1.1)

### 1.3 Directory Structure + Init Files

Create all directories and placeholder files:

```
src/__init__.py
src/downloader/__init__.py
src/transcriber/__init__.py
src/processor/__init__.py
src/uploader/__init__.py
src/utils/__init__.py
config/          (dir)
data/raw/.gitkeep
data/srt/.gitkeep
data/output/.gitkeep
data/logs/.gitkeep
tests/           (dir)
scripts/         (dir)
```

Create `.gitignore`:
```
data/raw/*.mp4
data/output/*.mp4
config/*_token.json
config/*_secrets.json
config/douyin_cookie.txt
__pycache__/
.venv/
*.egg-info/
```

- **Dependencies**: None

### 1.4 Configuration Files

- `config/config.yaml` — Main config (douyin, whisper, ffmpeg, platforms, pipeline sections)
- `config/platforms.yaml` — Per-platform subtitle language + video spec settings
- `config/subtitle_styles.yaml` — Default + per-platform subtitle styling (ASS format)
- **Dependencies**: 1.3

### 1.5 Config Loader — `src/utils/config.py`

- `load_config(path: str = "config/config.yaml") -> dict`
- Uses PyYAML
- Supports `${VAR}` environment variable interpolation in YAML values
- **Dependencies**: 1.4

### 1.6 Logger Utility — `src/utils/logger.py`

- Structured JSON logger using Python `logging` + custom JSON formatter
- Output to console (human-readable via `rich`) and file (JSON to `data/logs/pipeline.log`)
- `setup_logger(name: str, level: str = "INFO") -> logging.Logger`
- **Dependencies**: 1.3

### 1.7 Metadata Utility — `src/utils/metadata.py`

- `VideoMetadata` dataclass: `video_id`, `title`, `author`, `duration`, `resolution`, `description`, `hashtags`, `source_url`, `file_path`
- `extract_metadata_from_file(path: Path) -> dict` using ffprobe subprocess
- **Dependencies**: 1.3

### 1.8 Douyin Downloader — `src/downloader/douyin.py`

- Class `DouyinDownloader`
- `async download(share_url: str, output_dir: Path) -> VideoMetadata`
- Uses `httpx.AsyncClient` to call self-hosted API at `/api/hybrid/video_data`
- Stream-download MP4 to `data/raw/{video_id}.mp4`
- Error handling: API unreachable, cookie expired, invalid URL format
- **Dependencies**: 1.5, 1.6, 1.7

### 1.9 yt-dlp Fallback — `src/downloader/ytdlp.py`

- Class `YtDlpDownloader`
- `async download(url: str, output_dir: Path) -> VideoMetadata`
- Wraps `yt-dlp` via subprocess (CLI, not Python import)
- Output template: `{output_dir}/{video_id}.mp4`
- Extracts metadata from `yt-dlp --dump-json`
- **Dependencies**: 1.5, 1.6, 1.7

### 1.10 Downloader Factory — `src/downloader/__init__.py`

- `get_downloader(config: dict) -> DouyinDownloader | YtDlpDownloader`
- `download_with_fallback(url, output_dir, config)` — tries Douyin API first, falls back to yt-dlp on failure
- **Dependencies**: 1.8, 1.9

### 1.11 Base Transcriber — `src/transcriber/base.py`

- Abstract class `BaseTranscriber`:
  - `transcribe(video_path: str, language: str, task: str) -> list[dict]` (abstract)
  - `generate_srt(segments: list[dict], output_path: Path) -> Path` (concrete, shared)
  - `_format_timestamp(seconds: float) -> str` (static, shared)
- Factory: `get_transcriber(config: dict) -> BaseTranscriber` — checks `sys.platform`
- **Dependencies**: 1.6

### 1.12 faster-whisper Backend — `src/transcriber/faster.py`

- Class `FasterWhisperTranscriber(BaseTranscriber)`
- Uses `faster_whisper.WhisperModel`
- VAD filtering: `vad_filter=True`, `vad_parameters=dict(min_silence_duration_ms=500)`
- Supports `task="transcribe"` (Chinese) and `task="translate"` (zh→en)
- **Dependencies**: 1.11

### 1.13 mlx-whisper Backend — `src/transcriber/mlx.py`

- Class `MLXWhisperTranscriber(BaseTranscriber)`
- Uses `mlx_whisper` package
- Same interface, adapted to MLX API differences
- **Dependencies**: 1.11

### 1.14 Transcriber Factory — `src/transcriber/__init__.py`

- Wire `get_transcriber()`: `sys.platform == "darwin"` → MLX, else → faster-whisper
- Allow config override to force a specific backend
- **Dependencies**: 1.12, 1.13

### 1.15 Translation Support — `src/processor/subtitle.py` (started early)

- `translate_srt(srt_path: Path, method: str = "whisper") -> Path`
  - `"whisper"`: Re-transcribe with `task="translate"`
  - `"deepl"`: Parse SRT → DeepL API → translated SRT
- Output: `{video_id}_en.srt`
- **Dependencies**: 1.11

### 1.16 Cookie Refresh Script — `scripts/refresh_douyin_cookie.py`

- Standalone helper to refresh Douyin cookies
- Can be a placeholder with browser instructions
- **Dependencies**: None

### 1.17 Phase 1 Tests

- `tests/test_downloader.py` — URL parsing, metadata extraction, error handling (mock HTTP)
- `tests/test_transcriber.py` — SRT generation, timestamp formatting, VAD config
- Use `pytest` + `pytest-asyncio`
- **Dependencies**: 1.10, 1.14

---

## Dependency Graph

```
1.1, 1.2, 1.3 ──────── (parallel, no deps)
       │
       ▼
      1.4 ◄──────────── (needs 1.3)
       │
       ▼
      1.5               1.6              1.7
 (needs 1.4)       (needs 1.3)      (needs 1.3)
       │                │                │
       └────────────────┼────────────────┘
                        │
                        ▼
      1.8 ◄──── (needs 1.5, 1.6, 1.7)     1.11 ◄── (needs 1.6)
      1.9 ◄──── (needs 1.5, 1.6, 1.7)        │
       │                                    1.12, 1.13 ◄── (need 1.11)
       ▼                                       │
     1.10 ◄── (needs 1.8, 1.9)             1.14 ◄── (needs 1.12, 1.13)
                                               │
                                            1.15 ◄── (needs 1.11)
```

---

## Verification Checklist

### V1.1: Project scaffolding installs correctly

```bash
cd /Users/daniel/WorkStation/Personal/video/douyin-automation
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[macos]"
pip list | grep -E "mlx-whisper|httpx|click|pyyaml|yt-dlp"
```

**Expected**: All packages listed, no install errors.

### V1.2: Directory structure is correct

```bash
find . -name "__init__.py" | sort
```

**Expected**:
```
./src/__init__.py
./src/downloader/__init__.py
./src/processor/__init__.py
./src/transcriber/__init__.py
./src/uploader/__init__.py
./src/utils/__init__.py
```

### V1.3: Config loads with env var interpolation

```bash
python3 -c "
from src.utils.config import load_config
cfg = load_config('config/config.yaml')
print(cfg['douyin']['api_base'])
print(cfg['whisper']['model_size'])
"
```

**Expected**: `http://localhost:8080` and `large-v3`.

### V1.4: Douyin download (requires Docker container)

```bash
docker run -d --name douyin-api -p 8080:8080 evil0ctal/douyin_tiktok_download_api:latest

python3 -c "
import asyncio
from src.downloader.douyin import DouyinDownloader
from pathlib import Path

async def test():
    dl = DouyinDownloader('http://localhost:8080')
    result = await dl.download('https://v.douyin.com/iRNBho6t/', Path('data/raw'))
    print(f'Downloaded: {result.video_id}')
    print(f'File exists: {Path(result.file_path).exists()}')
    print(f'Title: {result.title}')
asyncio.run(test())
"
```

**Expected**: MP4 in `data/raw/`, metadata printed.

### V1.5: yt-dlp fallback

```bash
python3 -c "
import asyncio
from src.downloader.ytdlp import YtDlpDownloader
from pathlib import Path

async def test():
    dl = YtDlpDownloader()
    result = await dl.download('https://v.douyin.com/iRNBho6t/', Path('data/raw'))
    print(f'Downloaded: {result.video_id}')
asyncio.run(test())
"
```

**Expected**: Same MP4 downloaded via yt-dlp.

### V1.6: Download with automatic fallback

```bash
python3 -c "
import asyncio
from src.downloader import download_with_fallback
from pathlib import Path
from src.utils.config import load_config

cfg = load_config()
result = asyncio.run(download_with_fallback('https://v.douyin.com/iRNBho6t/', Path('data/raw'), cfg))
print(f'Success: {result.video_id}')
"
```

**Expected**: Downloads via primary; if API down, auto-falls back to yt-dlp.

### V1.7: Transcriber auto-selects correct backend

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
t = get_transcriber(load_config()['whisper'])
print(type(t).__name__)
"
```

**Expected on macOS**: `MLXWhisperTranscriber`

### V1.8: Transcription produces valid SRT

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
from pathlib import Path

t = get_transcriber(load_config()['whisper'])
segments = t.transcribe('data/raw/<video_id>.mp4', language='zh')
srt_path = t.generate_srt(segments, Path('data/srt/<video_id>.srt'))
with open(srt_path) as f:
    print(f.read()[:500])
"
```

**Expected**: SRT with numbered sequences, `HH:MM:SS,mmm --> HH:MM:SS,mmm` timestamps, Chinese text.

### V1.9: Timestamp formatting edge cases

```bash
python3 -c "
from src.transcriber.base import BaseTranscriber
print(BaseTranscriber._format_timestamp(0.0))       # 00:00:00,000
print(BaseTranscriber._format_timestamp(61.5))       # 00:01:01,500
print(BaseTranscriber._format_timestamp(3661.123))   # 01:01:01,123
"
```

### V1.10: Chinese → English translation

```bash
python3 -c "
from src.transcriber import get_transcriber
from src.utils.config import load_config
from pathlib import Path

t = get_transcriber(load_config()['whisper'])
segments = t.transcribe('data/raw/<video_id>.mp4', language='zh', task='translate')
srt_path = t.generate_srt(segments, Path('data/srt/<video_id>_en.srt'))
with open(srt_path) as f:
    print(f.read()[:500])
"
```

**Expected**: SRT with English text.

### V1.11: Unit tests pass

```bash
python3 -m pytest tests/test_downloader.py tests/test_transcriber.py -v
```

---

## Edge Cases

1. **Invalid Douyin URL**: Share links come in multiple formats (`v.douyin.com/xxx/`, `www.douyin.com/video/xxx`, raw text with embedded URL). Must extract actual URL.
2. **Cookie expiry**: API returns 403 or error JSON. Detect, log clearly, suggest `refresh_douyin_cookie.py`.
3. **Large files**: Stream download — never load entire file in memory. Use `httpx.stream()`.
4. **Slideshow videos**: Image slideshows may not have video URL. Detect and skip.
5. **No speech (music-only)**: VAD results in empty segments. Skip SRT generation, log warning.
6. **Unicode filenames**: Use `video_id` (numeric) for filenames, not titles.
7. **Network timeout**: 60s for API calls, 120s for downloads. Clear error messages.
8. **Model download on first run**: Whisper large-v3 is ~3GB. Log progress, handle interruption.
