# Phase 2 — Subtitle Burn-in + Reformat (Week 2-3)

---

## Context

The source videos are from Douyin (Chinese audio). Phase 1 transcribes them to Chinese SRT, then translates to English and/or Vietnamese using LLM translation profiles. Phase 2 burns the **translated subtitles** (English, Vietnamese) into the video and reformats per platform. The burned-in subtitles are Latin-script (English, Vietnamese with diacritics) — not CJK.

**Subtitle language per platform** (configured in `config/platforms.yaml`):
- **TikTok**: Vietnamese subtitles (target audience)
- **YouTube**: English subtitles
- **Facebook**: Vietnamese subtitles
- **X/Twitter**: English subtitles

---

## Prerequisite

```bash
# macOS (development)
brew install ffmpeg

# Linux (production)
sudo apt install -y ffmpeg
```

No special fonts needed — English and Vietnamese render with standard system fonts (Arial, Helvetica, Roboto). Vietnamese diacritics (ă, ơ, ư, etc.) are fully supported by all common fonts.

---

## Task List

### 2.1 SRT Parser + ASS Converter — `src/processor/subtitle.py`

Functions to implement:

- `parse_srt(srt_path: Path) -> list[dict]` — Parse SRT into segments with `index`, `start`, `end`, `text`
- `srt_to_ass(srt_path: Path, style_config: dict, output_path: Path) -> Path` — Convert SRT to styled ASS format with `[Script Info]`, `[V4+ Styles]`, `[Events]` sections
- `merge_subtitles(primary_srt: Path, secondary_srt: Path, output_path: Path) -> Path` — Create dual-line subtitle (e.g., English top, Vietnamese bottom)
- `select_subtitle_for_platform(video_id: str, platform: str, srt_dir: Path, platform_config: dict) -> Path` — Return correct SRT/ASS path based on platform's configured subtitle language
- `break_long_lines(text: str, max_chars: int = 40) -> str` — Line-break text that exceeds max width (40 chars for English/Vietnamese is reasonable)

**Subtitle selection logic:**
```python
# platform_config from platforms.yaml
# e.g., tiktok.subtitle_language = "vi"
# Looks for: data/srt/{video_id}_vi.srt
# Falls back to: data/srt/{video_id}_en.srt → data/srt/{video_id}_zh.srt
```

**Dependencies**: Phase 1 task 1.4 (config files)

### 2.2 FFmpeg Processor — `src/processor/ffmpeg.py`

Class `FFmpegProcessor` with methods:

- `burn_subtitles(video_path, subtitle_path, output_path, style=None) -> Path` — Burn SRT or ASS into video using `-vf subtitles=` filter
- `reformat_for_platform(video_path, platform, output_path, platform_specs) -> Path` — Resize, re-encode, enforce duration/size limits
- `burn_and_reformat(video_path, subtitle_path, platform, output_path, style, platform_specs) -> Path` — Single-pass combined operation (more efficient)
- `get_video_info(video_path) -> dict` — Probe video metadata via ffprobe subprocess
- `_build_style_string(style: dict) -> str` — Convert style dict to ffmpeg ASS `force_style` string

Implementation details:
- Use `subprocess.run` with `check=True`, capture stderr
- H.264 output: `-c:v libx264 -preset medium -crf {crf}`
- Audio: `-c:a aac -b:a 128k`
- Faststart: `-movflags +faststart`
- For X/Twitter: inject `-t {max_duration}` to enforce duration limit
- Font for subtitle burn-in: `Arial` (default, available everywhere) or user-configured font that supports Vietnamese diacritics

**Dependencies**: 2.1, Phase 1 task 1.5

### 2.3 Platform Specs — `config/platforms.yaml` + `src/processor/ffmpeg.py`

Define `PLATFORM_SPECS` with per-platform video constraints:

| Platform        | Resolution  | CRF | Max Rate | Max Duration | Max Size | Subtitle Lang |
| --------------- | ----------- | --- | -------- | ------------ | -------- | ------------- |
| tiktok          | 1080x1920   | 23  | 8M       | 600s         | 4GB      | vi            |
| youtube         | 1080x1920   | 20  | 12M      | —            | 256GB    | en            |
| youtube_shorts  | 1080x1920   | 20  | 12M      | 60s          | 256GB    | en            |
| facebook_reels  | 1080x1920   | 23  | 8M       | 900s         | 4GB      | vi            |
| facebook_feed   | 1920x1080   | 23  | 8M       | 14400s       | 10GB     | vi            |
| x               | 1080x1920   | 26  | 4M       | 140s         | 512MB    | en            |

**Dependencies**: Phase 1 task 1.4

### 2.4 Subtitle Style Config — `config/subtitle_styles.yaml`

Update style config for English/Vietnamese subtitles:

```yaml
default:
  font_name: "Arial"           # Standard font, supports Vietnamese diacritics
  font_size: 24
  primary_color: "&H00FFFFFF"  # White
  outline_color: "&H00000000"  # Black
  outline_width: 2
  shadow_depth: 1
  bold: true
  alignment: 2                 # Bottom-center
  margin_v: 30                 # Vertical margin from bottom

# Per-platform overrides
platforms:
  tiktok:
    font_size: 28              # Larger for mobile
    margin_v: 80               # Higher to avoid TikTok UI elements
  youtube:
    font_size: 22              # Standard for desktop
  facebook:
    font_size: 26
  x:
    font_size: 22
```

**Dependencies**: Phase 1 task 1.4

### 2.5 Batch Processor — `src/processor/__init__.py`

Function `process_for_all_platforms(video_id, video_path, srt_dir, output_dir, platforms, config) -> dict[str, Path]`:
- For each platform:
  1. Select correct translated subtitle based on platform's `subtitle_language` config (vi or en)
  2. If translated SRT doesn't exist, fall back to next available language
  3. Apply platform-specific style from `subtitle_styles.yaml`
  4. Burn subtitles + reformat in single pass
- Output naming: `{video_id}_{platform}.mp4`
- Returns dict: `{platform_name: output_path}`
- Skip subtitle burn if no SRT exists (e.g., music-only video)
- Log which subtitle language was used for each platform

**Dependencies**: 2.1, 2.2, 2.3, 2.4

### 2.6 Phase 2 Tests — `tests/test_processor.py`

- SRT parsing with edge cases (empty lines, Vietnamese diacritics, multi-line text)
- ASS generation validation (required sections present)
- Style string building
- Platform specs validation
- Dual-line subtitle merging (English + Vietnamese)
- Subtitle language selection per platform
- Mock ffmpeg for unit tests; real ffmpeg for integration tests (`@pytest.mark.integration`)

**Dependencies**: 2.1, 2.2

---

## Dependency Graph

```
2.1 ◄──── (needs Phase 1: 1.4)     2.4 ◄── (needs 1.4)
 │                                    │
 ▼                                    │
2.2 ◄──── (needs 2.1, 1.5)           │
 │                                    │
 ▼                                    │
2.3 ◄──── (needs 1.4)                │
 │                                    │
 └──────────────┬─────────────────────┘
                │
                ▼
              2.5 ◄── (needs 2.1, 2.2, 2.3, 2.4)
                │
                ▼
              2.6 ◄── (needs 2.1, 2.2)
```

---

## Verification Checklist

### V2.1: ffmpeg is available

```bash
ffmpeg -version | head -1
ffprobe -version | head -1
```

**Expected**: Version strings (e.g., `ffmpeg version 7.x ...`).

### V2.2: SRT parsing

```bash
python3 -c "
from src.processor.subtitle import parse_srt
from pathlib import Path
segments = parse_srt(Path('data/srt/<video_id>_en.srt'))
print(f'Parsed {len(segments)} segments')
print(f'First: {segments[0]}')
print(f'Last: {segments[-1]}')
"
```

**Expected**: Correct segment count, each with `start`, `end`, `text`. English text renders correctly.

### V2.3: SRT → ASS conversion

```bash
python3 -c "
from src.processor.subtitle import srt_to_ass
from pathlib import Path
import yaml

with open('config/subtitle_styles.yaml') as f:
    styles = yaml.safe_load(f)

ass_path = srt_to_ass(
    Path('data/srt/<video_id>_en.srt'),
    styles['default'],
    Path('data/srt/<video_id>_en.ass')
)
with open(ass_path) as f:
    content = f.read()
assert '[Script Info]' in content
assert '[V4+ Styles]' in content
assert '[Events]' in content
print('ASS file is valid')
print(content[:500])
"
```

**Expected**: Valid ASS file with all three required sections, English text in events.

### V2.4: Subtitle burn-in produces viewable video

```bash
python3 -c "
from src.processor.ffmpeg import FFmpegProcessor
from pathlib import Path

proc = FFmpegProcessor()
output = proc.burn_subtitles(
    Path('data/raw/<video_id>.mp4'),
    Path('data/srt/<video_id>_en.srt'),
    Path('data/output/<video_id>_subtitled.mp4'),
    style={'font_name': 'Arial', 'font_size': 24,
           'primary_color': '&H00FFFFFF', 'outline_color': '&H00000000',
           'outline_width': 2}
)
print(f'Output: {output}')
print(f'Exists: {output.exists()}')
"
```

Then verify with ffprobe:
```bash
ffprobe -v quiet -print_format json -show_format -show_streams \
    data/output/<video_id>_subtitled.mp4 | python3 -m json.tool | head -20
```

**Expected**: Valid H.264 + AAC output. **Visual check**: English subtitles visible and readable.

### V2.5: Vietnamese subtitle burn-in

```bash
python3 -c "
from src.processor.ffmpeg import FFmpegProcessor
from pathlib import Path

proc = FFmpegProcessor()
output = proc.burn_subtitles(
    Path('data/raw/<video_id>.mp4'),
    Path('data/srt/<video_id>_vi.srt'),
    Path('data/output/<video_id>_vi_subtitled.mp4'),
    style={'font_name': 'Arial', 'font_size': 28,
           'primary_color': '&H00FFFFFF', 'outline_color': '&H00000000',
           'outline_width': 2}
)
print(f'Output: {output}')
"
```

**Expected**: **Visual check**: Vietnamese diacritics (ă, ơ, ư, ê, ộ) render correctly, no missing characters.

### V2.6: Platform reformatting meets X constraints (most restrictive)

```bash
python3 -c "
from src.processor.ffmpeg import FFmpegProcessor
from pathlib import Path
import json, subprocess

proc = FFmpegProcessor()
output = proc.reformat_for_platform(
    Path('data/output/<video_id>_subtitled.mp4'), 'x',
    Path('data/output/<video_id>_x.mp4')
)

info = json.loads(subprocess.check_output([
    'ffprobe', '-v', 'quiet', '-print_format', 'json',
    '-show_format', '-show_streams', str(output)
]))
duration = float(info['format']['duration'])
size_mb = int(info['format']['size']) / (1024*1024)
codec = info['streams'][0]['codec_name']

print(f'Duration: {duration:.1f}s (max 140s) — {\"PASS\" if duration <= 140 else \"FAIL\"}')
print(f'Size: {size_mb:.1f}MB (max 512MB) — {\"PASS\" if size_mb <= 512 else \"FAIL\"}')
print(f'Codec: {codec} — {\"PASS\" if codec == \"h264\" else \"FAIL\"}')
"
```

**Expected**: All PASS.

### V2.7: Batch processing — correct subtitle language per platform

```bash
python3 -c "
from src.processor import process_for_all_platforms
from pathlib import Path
from src.utils.config import load_config

cfg = load_config()
results = process_for_all_platforms(
    '<video_id>', Path('data/raw/<video_id>.mp4'), Path('data/srt'),
    Path('data/output'), ['tiktok', 'youtube', 'facebook', 'x'], cfg
)
for platform, path in results.items():
    print(f'{platform}: {path} — {\"EXISTS\" if path.exists() else \"MISSING\"}')
"
```

**Expected**: Four files created. TikTok + Facebook have Vietnamese subs, YouTube + X have English subs.

### V2.8: Dual-line subtitle merge

```bash
python3 -c "
from src.processor.subtitle import merge_subtitles
from pathlib import Path

merged = merge_subtitles(
    Path('data/srt/<video_id>_en.srt'),
    Path('data/srt/<video_id>_vi.srt'),
    Path('data/srt/<video_id>_dual.srt')
)
with open(merged) as f:
    print(f.read()[:500])
"
```

**Expected**: Each subtitle block has two lines (English above, Vietnamese below).

### V2.9: Unit tests pass

```bash
python3 -m pytest tests/test_processor.py -v
```

---

## Web UI + API (Phase 2)

### 2.7 Process Router + Service — `server/routers/process.py` + `server/services/process_service.py`

**API Endpoints:**

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/process` | Start processing `{video_id, platforms, subtitle_lang, subtitle_style}` → `{task_id}` |
| `GET` | `/api/process/{task_id}` | Get processing result (output paths per platform) |
| `GET` | `/api/subtitle-styles` | Get styles from `subtitle_styles.yaml` |
| `PUT` | `/api/subtitle-styles/{platform}` | Update platform-specific style |
| `GET` | `/api/platforms` | Get platform specs from `platforms.yaml` |
| `GET` | `/api/videos/{video_id}/output/{platform}` | Stream processed video file |

**Service layer** (`process_service.py`):
- Wraps `process_for_all_platforms()` from `src/processor/__init__.py`
- Progress tracking: parses ffmpeg stderr output (`time=HH:MM:SS.xx`) and computes percentage from total video duration
- Processes platforms sequentially; emits `stage_change` events between platforms ("Processing for YouTube (en)..." → "Processing for TikTok (vi)...")
- Subtitle style overrides: merges user-provided style with `subtitle_styles.yaml` defaults before calling processor
- **Dependencies**: 2.5, Phase 1 tasks 1.19, 1.20

### 2.8 Process Page — `web/src/pages/ProcessPage.tsx`

**Components:**

1. **VideoSelector** (top-left):
   - Dropdown or card list showing only videos that have translated SRT files
   - Each option shows: thumbnail, title, available subtitle languages (en, vi badges)
   - Fetches from `GET /api/videos` filtered by transcription/translation status

2. **SubtitleStyleEditor** (left panel, 40%):
   - Font selector dropdown: "Arial" (default), "Roboto", "Helvetica", etc.
   - Font size slider: 16–36px with number display
   - Color pickers (using shadcn Popover + color input):
     - Text color (default: white)
     - Outline color (default: black)
   - Outline width slider: 0–4px
   - Shadow toggle + depth slider
   - Position selector: bottom-center / top-center / middle
   - Vertical margin slider: 20–100px
   - Bold toggle
   - **Live preview**: dark rectangle simulating video frame with sample subtitle text (in selected language) styled using current CSS approximation of the settings

3. **PlatformSelector** (right panel, 60%):
   - Checkboxes for each platform with constraint badges + subtitle language:
     - TikTok: "9:16 · max 10min · 4GB · Vietnamese subs"
     - YouTube: "9:16 · max 60s (Shorts) · English subs"
     - Facebook: "9:16 · max 15min · 4GB · Vietnamese subs"
     - X/Twitter: "9:16 · max 2:20 · 512MB · English subs" (grayed if disabled)
   - Warning if required subtitle language isn't available: "⚠ Vietnamese SRT not found — translate first"
   - Subtitle language override: dropdown to force a different language for specific platforms
   - Disabled platforms if video doesn't meet constraints (e.g., too long for Shorts)
   - "Process" button (disabled until video + at least 1 platform selected)

4. **ProcessingProgress** (shown during processing):
   - Separate progress bar per platform
   - Active platform highlighted, others show queued/done state
   - Percentage from ffmpeg time parsing
   - Stage text per platform: "Burning English subs for YouTube..." → "Burning Vietnamese subs for TikTok..." → "Complete"

5. **OutputPreview** (shown after processing):
   - Tab bar for each platform (showing subtitle language: "YouTube (en)" / "TikTok (vi)")
   - HTML5 `<video>` player for each output
   - File size and resolution info per output
   - Fetches from `GET /api/videos/{video_id}/output/{platform}`

**Key interactions:**
- Style changes update live preview instantly (CSS only, no API call)
- Platform selection shows which subtitle language will be used for each
- "Process" button → POST `/api/process` → subscribe SSE → progress bars update per platform
- After completion, tabs auto-switch to show first completed output

- **Dependencies**: 2.7, Phase 1 task 1.23

---

### Web UI Verification Checklist (Phase 2)

### V2.10: Process API endpoint

```bash
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "platforms": ["youtube", "tiktok"]}'
# Returns: {"task_id": "..."}

curl -N http://localhost:8000/api/events/{task_id}
# Streams progress events with ffmpeg percentage
# Shows subtitle language per platform in stage events
```

**Expected**: Processing starts, YouTube gets English subs, TikTok gets Vietnamese subs.

### V2.11: Subtitle styles API

```bash
curl http://localhost:8000/api/subtitle-styles
curl http://localhost:8000/api/platforms
```

**Expected**: JSON with style config (Arial font default) and platform specs with subtitle_language field.

### V2.12: Serve processed video

```bash
curl -I http://localhost:8000/api/videos/<id>/output/youtube
```

**Expected**: `200 OK` with `Content-Type: video/mp4`.

### V2.13: Process page UI flow

1. Open Process page in browser
2. Select a video that has both English and Vietnamese translations
3. Adjust subtitle style → see live preview with sample text
4. Check YouTube (en) + TikTok (vi) → click Process
5. See per-platform progress bars fill up with subtitle language labels
6. After completion, switch tabs to preview: YouTube video has English subs, TikTok has Vietnamese

**Expected**: Full flow works, correct language per platform, progress is real-time.

---

## Edge Cases

1. **No translated SRT exists** (only Chinese): Warn user to translate first. Allow processing with Chinese SRT as fallback if user confirms.
2. **Missing subtitle for platform language**: TikTok needs Vietnamese but only English exists. Fall back to English with logged warning.
3. **Vietnamese diacritics**: Ensure font supports full Vietnamese character set (ă, â, ê, ô, ơ, ư + tone marks). Arial/Roboto/Helvetica all do.
4. **ffmpeg not found**: Detect early, give clear install instructions per platform.
5. **Video already in target resolution**: Skip scaling, only re-encode if codec/bitrate change needed.
6. **X duration truncation**: Video is 5min but X allows 2:20. Truncate with logged warning (not silent).
7. **ASS special characters**: Escape special chars in font names and subtitle text (curly braces, backslashes).
8. **Corrupt video input**: Catch `subprocess.CalledProcessError`, parse ffmpeg stderr, raise informative error.
9. **Very long subtitle lines**: English/Vietnamese can have long words. Break at word boundaries, not mid-word. Max ~40 chars per line.
10. **Dual-line subtitles**: If user wants both English + Vietnamese on screen, ensure proper line spacing and font sizing so both are readable.
