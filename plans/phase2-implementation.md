# Phase 2 — Subtitle Burn-in + Reformat: Implementation Plan

## Context

Phase 1 is complete (tasks 1.1–1.25). Videos are downloaded to `data/raw/`, transcribed to Chinese SRT in `data/srt/`, and translated to English/Vietnamese via LLM translation profiles. Phase 2 burns **translated subtitles** (English, Vietnamese — not Chinese) into video and reformats per platform.

**Subtitle language mapping:**
- TikTok / Facebook → Vietnamese (`vi`)
- YouTube / X → English (`en`)

**Key constraint:** All subtitles are Latin-script. No CJK font handling needed. Default font: Arial.

---

## Implementation Order

```
2.4 Config updates (subtitle_styles.yaml + platforms.yaml)  ← no code deps
2.1 SRT parser + ASS converter (subtitle.py)                ← needs 2.4 for style format
2.2 FFmpeg processor (ffmpeg.py)                             ← needs 2.1
2.3 Platform specs integration (already in platforms.yaml)   ← merged into 2.2
2.5 Batch processor (__init__.py)                            ← needs 2.1, 2.2, 2.4
2.6 Tests (test_processor.py)                                ← needs 2.1, 2.2, 2.5
2.7 Process API router + service                             ← needs 2.5
2.8 Process page UI                                          ← needs 2.7
```

---

## Task Details

### 2.4 — Update Config Files

**Files to modify:**

1. **`config/subtitle_styles.yaml`** — Update font and sizes per Phase 2 plan:
   - `default.font_name`: `"Noto Sans CJK SC"` → `"Arial"`
   - `default.font_size`: `18` → `24`
   - `tiktok.font_size`: `20` → `28`, `margin_v`: `50` → `80`
   - `youtube.font_size`: `18` → `22`
   - `facebook.font_size`: `18` → `26`
   - `x.font_size`: `16` → `22`
   - Wrap platform overrides under a `platforms:` key for clarity

2. **`config/platforms.yaml`** — Fix subtitle languages:
   - `tiktok.subtitle_language`: `zh` → `vi`
   - `facebook.subtitle_language`: `en` → `vi`
   - Add `max_bitrate` field per platform (8M, 12M, 8M, 4M)

3. **`src/processor/CLAUDE.md`** — Update to reflect English/Vietnamese (not Chinese/CJK)

---

### 2.1 — SRT Parser + ASS Converter

**File:** `src/processor/subtitle.py`

**Existing code to keep:**
- `parse_srt()` — already implemented, works for all languages
- `_timestamp_to_seconds()` — helper, keep as-is
- `translate_srt()` — Phase 1 function, keep as-is

**New functions to add:**

```python
def _seconds_to_ass_timestamp(seconds: float) -> str:
    """Convert seconds to ASS timestamp format (H:MM:SS.cc)."""

def srt_to_ass(srt_path: Path, style_config: dict, output_path: Path) -> Path:
    """Convert SRT to styled ASS with [Script Info], [V4+ Styles], [Events]."""
    # Parse SRT using existing parse_srt()
    # Build ASS header with style from config
    # Convert each segment to ASS Dialogue line
    # Write to output_path

def merge_subtitles(primary_srt: Path, secondary_srt: Path, output_path: Path) -> Path:
    """Create dual-line SRT (primary on top, secondary on bottom)."""
    # Parse both SRTs
    # Align by timestamp (match segments with overlapping times)
    # Combine text: primary\nsecondary
    # Write merged SRT

def select_subtitle_for_platform(
    video_id: str, platform: str, srt_dir: Path, platform_config: dict
) -> Path | None:
    """Return correct SRT path for platform's subtitle_language config.
    Fallback chain: configured lang → en → vi → zh → None
    """

def break_long_lines(text: str, max_chars: int = 40) -> str:
    """Break text at word boundaries if exceeding max_chars."""
```

---

### 2.2 — FFmpeg Processor

**File:** `src/processor/ffmpeg.py` (NEW)

```python
class FFmpegProcessor:
    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._verify_ffmpeg()

    def _verify_ffmpeg(self) -> None:
        """Check ffmpeg and ffprobe are available. Raise RuntimeError if not."""

    def get_video_info(self, video_path: Path) -> dict:
        """Probe video via ffprobe. Returns dict with duration, resolution, codec, size."""

    def _build_style_string(self, style: dict) -> str:
        """Convert style dict to ffmpeg ASS force_style string."""

    def burn_subtitles(
        self, video_path: Path, subtitle_path: Path, output_path: Path,
        style: dict | None = None
    ) -> Path:
        """Burn SRT/ASS into video using -vf subtitles= filter."""

    def reformat_for_platform(
        self, video_path: Path, platform: str, output_path: Path,
        platform_specs: dict | None = None
    ) -> Path:
        """Resize, re-encode per platform specs."""

    def burn_and_reformat(
        self, video_path: Path, subtitle_path: Path, platform: str,
        output_path: Path, style: dict | None = None,
        platform_specs: dict | None = None
    ) -> Path:
        """Single-pass: burn subtitles + reformat for platform."""
```

**Implementation notes:**
- Use `subprocess.run` with `check=True`, capture stderr
- Common ffmpeg args: `-c:v libx264 -preset medium -crf {crf} -c:a aac -b:a 128k -movflags +faststart`
- Subtitle burn: `-vf "subtitles='{srt_path}':force_style='{style_str}'"`
- Duration limit: `-t {max_duration}` with logged warning if truncating
- Scale filter: `-vf "scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"`
- Escape special chars in file paths for ffmpeg filter

---

### 2.3 — Platform Specs (merged into 2.2 + 2.4)

Already defined in `config/platforms.yaml`. `FFmpegProcessor.reformat_for_platform()` reads specs from config. Add `max_bitrate` field. No separate code file needed.

---

### 2.5 — Batch Processor

**File:** `src/processor/__init__.py` (currently empty)

```python
def process_for_all_platforms(
    video_id: str, video_path: Path, srt_dir: Path, output_dir: Path,
    platforms: list[str], config: dict,
    style_overrides: dict | None = None,
    on_progress: Callable | None = None,
) -> dict[str, Path]:
    """Process video for all requested platforms.
    For each platform: select SRT → merge style → burn_and_reformat.
    Returns: {platform: output_path}
    """
```

---

### 2.6 — Tests

**File:** `tests/test_processor.py` (NEW)

Test classes: `TestParseSrt`, `TestSrtToAss`, `TestMergeSubtitles`, `TestBreakLongLines`, `TestSelectSubtitleForPlatform`, `TestBuildStyleString`, `TestFFmpegProcessor`, `TestProcessForAllPlatforms`, plus `@pytest.mark.integration` class for real ffmpeg tests.

---

### 2.7 — Process API Router + Service

**Files:**
1. `src/api/models.py` — Add: `ProcessRequest`, `ProcessResult`, `SubtitleStyleResponse`, `PlatformSpecResponse`
2. `src/api/routers/process.py` (NEW) — 6 endpoints
3. `src/api/task_manager.py` — Add `run_process()` method
4. `src/api/__init__.py` — Register router + mount `/files/output`

---

### 2.8 — Process Page UI

**Files:**
1. `ui-app/src/api/types.ts` — Add process-related types
2. `ui-app/src/api/client.ts` — Add `postProcess`, `getSubtitleStyles`, `getPlatforms`
3. `ui-app/src/pages/SubtitleProcess.tsx` — Rewrite with real backend integration

---

## Files Modified/Created Summary

| File | Action | Task |
|------|--------|------|
| `config/subtitle_styles.yaml` | Modify | 2.4 |
| `config/platforms.yaml` | Modify | 2.4 |
| `src/processor/CLAUDE.md` | Modify | 2.4 |
| `src/processor/subtitle.py` | Modify (add 5 functions) | 2.1 |
| `src/processor/ffmpeg.py` | Create | 2.2 |
| `src/processor/__init__.py` | Create | 2.5 |
| `tests/test_processor.py` | Create | 2.6 |
| `src/api/models.py` | Modify (add 4 models) | 2.7 |
| `src/api/routers/process.py` | Create | 2.7 |
| `src/api/task_manager.py` | Modify (add run_process) | 2.7 |
| `src/api/__init__.py` | Modify (register router) | 2.7 |
| `ui-app/src/api/types.ts` | Modify (add types) | 2.8 |
| `ui-app/src/api/client.ts` | Modify (add functions) | 2.8 |
| `ui-app/src/pages/SubtitleProcess.tsx` | Rewrite | 2.8 |
| `README.md` | Modify (check off tasks) | all |
| `CHANGELOG.md` | Modify (add entries) | all |

---

## Verification Plan

1. `python -m pytest tests/test_processor.py -v` — all unit tests pass
2. SRT parsing + ASS conversion produce valid output
3. English subtitle burn-in produces viewable video
4. Vietnamese diacritics render correctly
5. X/Twitter reformat meets constraints (≤140s, ≤512MB, H.264)
6. Batch: TikTok/Facebook get Vietnamese, YouTube/X get English
7. API: `POST /api/process` + SSE progress works
8. UI: select video → process → preview output per platform
