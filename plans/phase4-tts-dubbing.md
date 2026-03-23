# Phase 4 — TTS Dubbing (Week 4)

## Context

The pipeline translates Chinese subtitles to English/Vietnamese, but the original Chinese audio remains. TTS dubbing generates voiceover from translated subtitles and mixes it into the video, making content accessible to non-Chinese speakers.

## Pipeline Position

```
Download → Transcribe → Translate → [TTS Dubbing] → Process (burn subs + mix audio) → Upload
```

TTS is a separate stage so users can preview audio before burning in. Generated once per language, reused across platforms (e.g., Vietnamese TTS for both TikTok and Facebook).

---

## Architecture

Follows existing patterns:
- **ABC + backends + factory** (like `src/transcriber/`)
- **Voice profiles in YAML** (like `config/subtitle_styles.yaml`)
- **Background task + SSE** (like `run_process` in task_manager)
- **Audio mixing via ffmpeg** (no Python audio libraries)

---

## Task List

### Backend

#### 4.1 TTS base class — `src/tts/base.py`

```python
class BaseTTSProvider(ABC):
    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes  # abstract
    async def list_voices(self, language: str | None = None) -> list[dict]  # abstract
    async def synthesize_segments(self, segments, voice, output_dir, on_progress) -> list[Path]  # concrete
```

`synthesize_segments` iterates segments, calls `synthesize` for each, saves audio clips, emits progress.

**Dependencies**: none.

#### 4.2 Edge TTS provider — `src/tts/edge.py`

Default provider. Free, no API key, async, good Vietnamese support.
- Voices: `vi-VN-HoaiMyNeural` (female), `vi-VN-NamMinhNeural` (male), `en-US-JennyNeural`, `en-US-GuyNeural`
- Supports `rate` and `pitch` parameters
- Output: MP3 (convert to WAV via ffmpeg for mixing)

**Dependencies**: 5.1.

#### 4.3 OpenAI TTS provider — `src/tts/openai_tts.py`

Uses `httpx.AsyncClient` to call `/v1/audio/speech`.
- Voices: alloy, echo, fable, onyx, nova, shimmer
- Models: `tts-1` (fast), `tts-1-hd` (quality)
- API key from config with `${OPENAI_API_KEY}` interpolation

**Dependencies**: 5.1.

#### 4.4 Google Cloud TTS provider — `src/tts/google_tts.py`

Excellent Vietnamese quality.
- Voices: `vi-VN-Standard-A/B/C/D`, `vi-VN-Wavenet-A/B/C/D`
- Via REST API (httpx) or `google-cloud-texttospeech` library

**Dependencies**: 5.1.

#### 4.5 TTS factory — `src/tts/__init__.py`

```python
def get_tts_provider(config: dict) -> BaseTTSProvider:
    # "edge" → EdgeTTSProvider, "openai" → OpenAITTSProvider, "google" → GoogleTTSProvider
```

**Dependencies**: 5.2, 5.3, 5.4.

#### 4.6 Voice profiles config — `config/tts_voices.yaml`

```yaml
default_provider: edge

profiles:
  female-vi-natural:
    provider: edge
    voice: "vi-VN-HoaiMyNeural"
    language: vi
    speed: "+0%"
    pitch: "+0Hz"
  male-vi-natural:
    provider: edge
    voice: "vi-VN-NamMinhNeural"
    language: vi
    speed: "+0%"
  female-en-edge:
    provider: edge
    voice: "en-US-JennyNeural"
    language: en
    speed: "+0%"
  male-en-onyx:
    provider: openai
    voice: "onyx"
    language: en
    speed: 1.0

platforms:
  tiktok:
    enabled: true
    profile: female-vi-natural
    original_volume: 0.3    # 30% original audio
    tts_volume: 1.0         # 100% TTS
  youtube:
    enabled: true
    profile: female-en-edge
    original_volume: 0.3
    tts_volume: 1.0
  facebook:
    enabled: true
    profile: female-vi-natural
    original_volume: 0.3
    tts_volume: 1.0
  x:
    enabled: false
```

**Dependencies**: none.

#### 4.7 TTS audio assembler — `src/tts/assembler.py`

Core logic to build a full-length audio track from segments:

```python
class TTSAssembler:
    async def generate_full_track(
        self, provider, segments, voice_profile, video_duration, output_path, on_progress
    ) -> Path:
```

**Algorithm:**
1. For each segment: `provider.synthesize(text, voice)` → save audio clip
2. Get clip duration via ffprobe
3. Compare clip duration vs segment window (`end - start`)
4. If longer: speed up with ffmpeg `atempo` filter (chain for >2x: `atempo=2.0,atempo=1.25` for 2.5x)
5. If shorter: leave as-is (silence fills gap naturally)
6. Concatenate all clips with silence padding to match video duration
7. Output: single WAV at `data/tts/{video_id}_{language}.wav`

Use `asyncio.gather` with `Semaphore(5)` for concurrent TTS API requests.

**Dependencies**: 5.1, 5.5.

#### 4.8 Audio mixing in ffmpeg — `src/processor/ffmpeg.py`

Add methods:

```python
def mix_audio(self, video_path, tts_audio_path, output_path, original_volume=0.3, tts_volume=1.0) -> Path
def burn_reformat_and_dub(self, video_path, subtitle_path, tts_audio_path, platform, output_path, ...) -> Path
```

ffmpeg command for mixing:
```bash
ffmpeg -i video.mp4 -i tts.wav \
  -filter_complex "[0:a]volume=0.3[orig];[1:a]volume=1.0[tts];[orig][tts]amix=inputs=2:duration=first[aout]" \
  -map 0:v -map "[aout]" -c:v libx264 -c:a aac -b:a 128k output.mp4
```

**Dependencies**: 5.7.

#### 4.9 Update batch processor — `src/processor/__init__.py`

Add `tts_audio_paths: dict[str, Path]` and `tts_mix_settings` params to `process_for_all_platforms`. If TTS audio exists for a platform, use `burn_reformat_and_dub` instead of `burn_and_reformat`.

**Dependencies**: 5.8.

#### 4.10 Config + infra updates

- `config/config.example.yaml`: add `tts:` section (enabled, default_provider, voices_config path)
- `pyproject.toml`: add `edge-tts>=6.1.0`
- `.gitignore`: add `data/tts/`
- `src/api/deps.py`: add `"tts"` to data subdirectories

**Dependencies**: none.

#### 4.11 TTS unit tests — `tests/test_tts.py`

Test ABC, factory, mocked Edge TTS synthesis, assembler duration fitting, ffmpeg audio mix command generation.

**Dependencies**: 5.1-5.8.

---

### API

#### 4.12 TTS Pydantic models — `src/api/models.py`

`TTSRequest`, `TTSPreviewRequest`, `TTSResult`, `VoiceInfo`, `VoiceProfileConfig`.

**Dependencies**: none.

#### 4.13 TTS router — `src/api/routers/tts.py`

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/tts` | Generate TTS → `{task_id}` with SSE progress |
| `GET` | `/api/tts/voices` | List voices (filter by `?language=vi&provider=edge`) |
| `GET` | `/api/tts/profiles` | Get voice profiles from YAML |
| `PUT` | `/api/tts/profiles/{name}` | Create/update profile |
| `DELETE` | `/api/tts/profiles/{name}` | Delete profile |
| `GET` | `/api/videos/{video_id}/tts/{language}` | Stream generated TTS audio |
| `POST` | `/api/tts/preview` | Quick preview: single text → audio blob |

**Dependencies**: 5.5, 5.6, 5.7, 5.12.

#### 4.14 Task manager + app registration

- `src/api/task_manager.py`: add `run_tts()` with SSE progress ("Generating segment 3/50...")
- `src/api/__init__.py`: register TTS router, mount `data/tts` static
- `src/api/routers/process.py`: add `enable_tts` + `tts_mix_settings` to `ProcessRequest`

**Dependencies**: 5.13.

---

### UI

#### 4.15 TTS TypeScript types — `ui-app/src/api/types.ts`

`TTSRequest`, `TTSPreviewRequest`, `TTSResult`, `VoiceInfo`, `VoiceProfileConfig`.

**Dependencies**: none.

#### 4.16 TTS API client — `ui-app/src/api/client.ts`

`postTTS`, `getTTSVoices`, `getTTSProfiles`, `getTTSAudioUrl`, `postTTSPreview`.

**Dependencies**: 5.15.

#### 4.17 TTS section on Process page — `ui-app/src/pages/SubtitleProcess.tsx`

Add collapsible "TTS Dubbing" section:
1. **Enable TTS toggle** — master switch
2. **Voice profile selector** — dropdown from `GET /api/tts/profiles`
3. **Per-platform voice assignment** — within each platform card
4. **Volume mix sliders** — "Original Audio" (0-100%) + "TTS Voice" (0-100%) per platform
5. **Preview button** — plays TTS of a sample segment via `<audio>` element
6. **Generate TTS button** — triggers `POST /api/tts`, shows SSE progress
7. **Audio player** — after generation, play back the full TTS track

**Dependencies**: 5.15, 5.16.

#### 4.18 TTS preview component — `ui-app/src/components/TTSPreview.tsx`

Play/stop button. POST to `/api/tts/preview` → get audio blob → play via `new Audio(URL.createObjectURL(blob))`.

**Dependencies**: 5.16.

---

## Dependency Graph

```
Level 0 (parallel):  5.1, 5.6, 5.10, 5.12, 5.15

Level 1:  5.2, 5.3, 5.4 (←5.1)

Level 2:  5.5 (←5.2,5.3,5.4)  |  5.16 (←5.15)

Level 3:  5.7 (←5.1,5.5)  |  5.13 (←5.5,5.6,5.7,5.12)

Level 4:  5.8 (←5.7)  |  5.14 (←5.13)

Level 5:  5.9 (←5.8)  |  5.17, 5.18 (←5.16)

Level 6:  5.11 (←5.1-5.8)
```

**Recommended sequence**: 5.1+5.6+5.10 → 5.2 (Edge only first) → 5.5 → 5.7 → 5.8+5.9 → 5.12+5.13+5.14 → 5.15+5.16+5.17+5.18 → 5.11 → 5.3+5.4 (additional providers later)

---

## Verification Checklist

### V4.1: Edge TTS installed

```bash
python3 -c "import edge_tts; print('ok')"
```

### V4.2: List available voices

```bash
curl http://localhost:8000/api/tts/voices?language=vi
```

**Expected**: JSON array with Vietnamese voices including `vi-VN-HoaiMyNeural`.

### V4.3: Voice preview

```bash
curl -X POST http://localhost:8000/api/tts/preview \
  -H "Content-Type: application/json" \
  -d '{"text": "Xin chào các bạn", "voice": "vi-VN-HoaiMyNeural", "provider": "edge"}'
```

**Expected**: Audio bytes returned, playable in browser.

### V4.4: Generate TTS for video

```bash
curl -X POST http://localhost:8000/api/tts \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "language": "vi", "voice_profile": "female-vi-natural"}'
# Subscribe SSE for progress
curl -N http://localhost:8000/api/events/{task_id}
```

**Expected**: SSE shows "Generating segment 1/N...", WAV created at `data/tts/{id}_vi.wav`.

### V4.5: TTS duration matches video

```bash
python3 -c "
import subprocess, json
video_info = json.loads(subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', 'data/raw/<id>.mp4']))
tts_info = json.loads(subprocess.check_output(['ffprobe', '-v', 'quiet', '-print_format', 'json', '-show_format', 'data/tts/<id>_vi.wav']))
print(f'Video: {float(video_info[\"format\"][\"duration\"]):.1f}s')
print(f'TTS: {float(tts_info[\"format\"][\"duration\"]):.1f}s')
"
```

**Expected**: Durations match within ±0.5s.

### V4.6: Audio mixing produces dubbed video

```bash
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"video_id": "<id>", "platforms": ["youtube"], "enable_tts": true}'
```

**Expected**: Output video has mixed audio (original quieter + TTS overlay).

### V4.7: Volume levels correct

Play output video — original Chinese audio should be faintly audible (30%), English/Vietnamese TTS should be dominant (100%).

### V4.8: UI flow

1. Open Process page → enable TTS toggle
2. Select voice profile → click Preview → hear sample audio
3. Click Generate TTS → see progress "Generating segment 5/50..."
4. After generation, play back full TTS track
5. Select platforms → click Process → output has dubbed audio

### V4.9: Unit tests pass

```bash
python3 -m pytest tests/test_tts.py -v
```

---

## Edge Cases

1. **No translated SRT**: TTS requires translated SRT. Warn user if translation not done yet.
2. **Empty segments**: Skip segments with empty text (music-only sections).
3. **Very long text in short window**: If TTS generates 10s audio for a 3s window, speeding up 3x+ makes speech unintelligible. Warn user if ratio exceeds 2.5x.
4. **Edge TTS rate limiting**: Microsoft may throttle. Add delays between requests, use retry with backoff.
5. **Vietnamese text cleanup**: Strip SRT formatting artifacts (`<i>`, `{\\an8}`) before TTS synthesis.
6. **Audio sample rate mismatch**: Edge TTS outputs 24kHz MP3, video may be 48kHz. ffmpeg handles resampling automatically.
7. **No internet**: Edge TTS requires internet. Detect and show clear error.
8. **TTS failure mid-batch**: If one segment fails, retry that segment. If retry fails, skip it (silence for that segment).
9. **Platform-specific voice**: TikTok gets Vietnamese voice, YouTube gets English voice — verify correct voice used per platform.
10. **Large video (50+ segments)**: Use concurrent TTS requests (Semaphore(5)) for performance. Show accurate progress.
