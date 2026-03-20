# Phase 2 — Subtitle Burn-in + Reformat (Week 2-3)

---

## Prerequisite

```bash
# macOS (development)
brew install ffmpeg

# Linux (production)
sudo apt install -y ffmpeg fonts-noto-cjk
```

---

## Task List

### 2.1 SRT Parser + ASS Converter — `src/processor/subtitle.py`

Functions to implement:

- `parse_srt(srt_path: Path) -> list[dict]` — Parse SRT into segments with `index`, `start`, `end`, `text`
- `srt_to_ass(srt_path: Path, style_config: dict, output_path: Path) -> Path` — Convert SRT to styled ASS format with `[Script Info]`, `[V4+ Styles]`, `[Events]` sections
- `merge_subtitles(zh_srt: Path, en_srt: Path, output_path: Path) -> Path` — Create dual-line subtitle (Chinese top, English bottom)
- `select_subtitle_for_platform(video_id: str, platform: str, srt_dir: Path, platform_config: dict) -> Path` — Return correct SRT/ASS path based on platform language config
- `break_long_lines(text: str, max_chars: int = 20) -> str` — Line-break CJK text that exceeds max width

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

**Dependencies**: 2.1, Phase 1 task 1.5

### 2.3 Platform Specs — `config/platforms.yaml` + `src/processor/ffmpeg.py`

Define `PLATFORM_SPECS` with per-platform video constraints:

| Platform        | Resolution  | CRF | Max Rate | Max Duration | Max Size |
| --------------- | ----------- | --- | -------- | ------------ | -------- |
| tiktok          | 1080x1920   | 23  | 8M       | 600s         | 4GB      |
| youtube         | 1080x1920   | 20  | 12M      | —            | 256GB    |
| youtube_shorts  | 1080x1920   | 20  | 12M      | 60s          | 256GB    |
| facebook_reels  | 1080x1920   | 23  | 8M       | 900s         | 4GB      |
| facebook_feed   | 1920x1080   | 23  | 8M       | 14400s       | 10GB     |
| x               | 1080x1920   | 26  | 4M       | 140s         | 512MB    |

**Dependencies**: Phase 1 task 1.4

### 2.4 CJK Font Handling — `src/processor/subtitle.py`

Function `ensure_cjk_fonts() -> str`:
- Check if Noto Sans CJK is installed:
  - macOS: `/Library/Fonts/`, `~/Library/Fonts/`, brew font dirs
  - Linux: `/usr/share/fonts/`, `fc-list | grep -i "noto.*cjk"`
- Return font path on success
- Raise clear error with install instructions on failure

**Dependencies**: None

### 2.5 Batch Processor — `src/processor/__init__.py`

Function `process_for_all_platforms(video_path, srt_dir, output_dir, platforms, config) -> dict[str, Path]`:
- For each platform:
  1. Select correct subtitle (language per platform config)
  2. Apply platform-specific style from `subtitle_styles.yaml`
  3. Burn subtitles + reformat in single pass
- Output naming: `{video_id}_{platform}.mp4`
- Returns dict: `{platform_name: output_path}`
- Skip subtitle burn if no SRT exists (e.g., music-only video)

**Dependencies**: 2.1, 2.2, 2.3, 2.4

### 2.6 Phase 2 Tests — `tests/test_processor.py`

- SRT parsing with edge cases (empty lines, special chars, multi-line text)
- ASS generation validation (required sections present)
- Style string building
- Platform specs validation
- Dual-line subtitle merging
- Mock ffmpeg for unit tests; real ffmpeg for integration tests (`@pytest.mark.integration`)

**Dependencies**: 2.1, 2.2

---

## Dependency Graph

```
2.1 ◄──── (needs Phase 1: 1.4)     2.4 ◄── (no deps)
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

### V2.2: CJK font is available

```bash
python3 -c "
from src.processor.subtitle import ensure_cjk_fonts
font_path = ensure_cjk_fonts()
print(f'CJK font found: {font_path}')
"
```

**Expected**: Font path printed, no error.

### V2.3: SRT parsing

```bash
python3 -c "
from src.processor.subtitle import parse_srt
from pathlib import Path
segments = parse_srt(Path('data/srt/<video_id>.srt'))
print(f'Parsed {len(segments)} segments')
print(f'First: {segments[0]}')
print(f'Last: {segments[-1]}')
"
```

**Expected**: Correct segment count, each with `start`, `end`, `text`.

### V2.4: SRT → ASS conversion

```bash
python3 -c "
from src.processor.subtitle import srt_to_ass
from pathlib import Path
import yaml

with open('config/subtitle_styles.yaml') as f:
    styles = yaml.safe_load(f)

ass_path = srt_to_ass(
    Path('data/srt/<video_id>.srt'),
    styles['default'],
    Path('data/srt/<video_id>.ass')
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

**Expected**: Valid ASS file with all three required sections.

### V2.5: Subtitle burn-in produces viewable video

```bash
python3 -c "
from src.processor.ffmpeg import FFmpegProcessor
from pathlib import Path

proc = FFmpegProcessor()
output = proc.burn_subtitles(
    Path('data/raw/<video_id>.mp4'),
    Path('data/srt/<video_id>.srt'),
    Path('data/output/<video_id>_subtitled.mp4'),
    style={'font_name': 'Noto Sans CJK SC', 'font_size': 24,
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

**Expected**: Valid H.264 + AAC output. **Visual check**: subtitles visible, CJK renders correctly (not boxes).

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

### V2.7: Batch processing — one source → 4 outputs

```bash
python3 -c "
from src.processor import process_for_all_platforms
from pathlib import Path
from src.utils.config import load_config

cfg = load_config()
results = process_for_all_platforms(
    Path('data/raw/<video_id>.mp4'), Path('data/srt'),
    Path('data/output'), ['tiktok', 'youtube', 'facebook', 'x'], cfg
)
for platform, path in results.items():
    print(f'{platform}: {path} — {\"EXISTS\" if path.exists() else \"MISSING\"}')
"
```

**Expected**: Four files: `<id>_tiktok.mp4`, `<id>_youtube.mp4`, `<id>_facebook.mp4`, `<id>_x.mp4`.

### V2.8: Dual-line subtitle merge

```bash
python3 -c "
from src.processor.subtitle import merge_subtitles
from pathlib import Path

merged = merge_subtitles(
    Path('data/srt/<video_id>.srt'),
    Path('data/srt/<video_id>_en.srt'),
    Path('data/srt/<video_id>_dual.srt')
)
with open(merged) as f:
    print(f.read()[:500])
"
```

**Expected**: Each subtitle block has two lines (Chinese above, English below).

### V2.9: Unit tests pass

```bash
python3 -m pytest tests/test_processor.py -v
```

---

## Edge Cases

1. **No SRT exists** (music-only video): Produce video without subtitles, just reformat.
2. **Very long CJK lines**: Chinese text has no spaces. Auto-break at ~20 chars per line.
3. **ffmpeg not found**: Detect early, give clear install instructions per platform.
4. **CJK font missing**: Clear error with download/install instructions.
5. **Video already in target resolution**: Skip scaling, only re-encode if codec/bitrate change needed.
6. **X duration truncation**: Video is 5min but X allows 2:20. Truncate with logged warning (not silent).
7. **ASS special characters**: Escape special chars in font names and color codes.
8. **Corrupt video input**: Catch `subprocess.CalledProcessError`, parse ffmpeg stderr, raise informative error.
