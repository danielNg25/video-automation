# Transcriber Module

Transcribes video audio to SRT subtitles using Whisper.

## Key Components

- `base.py` — `BaseTranscriber` ABC: defines `transcribe()` (abstract) and `generate_srt()` / `_format_timestamp()` (concrete, shared). Also contains `get_transcriber()` factory that auto-selects backend via `sys.platform`.
- `faster.py` — `FasterWhisperTranscriber`: CTranslate2 backend for Linux/CUDA production.
- `mlx.py` — `MLXWhisperTranscriber`: MLX backend for macOS Apple Silicon development.

## Constraints

- Auto-selection: `sys.platform == "darwin"` → MLX, otherwise → faster-whisper. Config can override.
- VAD filtering enabled by default (`vad_filter=True`, `min_silence_duration_ms=500`).
- Model `large-v3` (~3GB) downloads on first use — handle gracefully.
- `task="transcribe"` for Chinese, `task="translate"` for Whisper's built-in zh→en translation.
- SRT format: sequence number, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, text, blank line.

## Connects To

- **Input**: MP4 from `data/raw/` (provided by downloader)
- **Output**: SRT files in `data/srt/` → consumed by `processor` for subtitle burn-in
