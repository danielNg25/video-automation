# Transcriber Module

Extracts subtitles from video frames via PaddleOCR — the audio-Whisper backends (faster-whisper, mlx-whisper) were removed when the project narrowed to burned-in Chinese subtitle extraction.

## Key Components

- `base.py` — `BaseTranscriber` ABC: defines `transcribe()` (abstract) and `generate_srt()` / `_format_timestamp()` (concrete, shared).
- `ocr.py` — `OCRTranscriber`: PaddleOCR-based extractor with subtitle-region auto-detection, watermark/UI filtering, and dedup.
- `__init__.py` — `get_transcriber()` factory; returns `OCRTranscriber` unconditionally (no platform branching).

## Constraints

- **Paddle 3.x oneDNN bug workaround**: `_get_ocr()` calls `paddle.set_flags({"FLAGS_use_mkldnn": False})` and passes `enable_mkldnn=False` to the `PaddleOCR(...)` constructor. Without these, `ocr.ocr()` / `ocr.predict()` crashes on x86_64 with `ConvertPirAttribute2RuntimeAttribute not support [pir::ArrayAttribute<pir::DoubleAttribute>]` from the PIR new-executor's OneDNN instruction lowering. Setting `FLAGS_*` via env doesn't help — paddle reads them too late.
- Subtitle-region heuristics: text below `min_y` (default 0.65 of frame height), appearing in <`max_watermark_frequency` of frames (default 0.80), with `min_text_height` >= 2% — filters out watermarks and UI chrome.
- SRT format: sequence number, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, text, blank line.

## Connects To

- **Input**: MP4 from `data/raw/` (provided by downloader)
- **Output**: SRT files in `data/srt/` and `{video_id}_ocr_meta.json` (subtitle region bbox) — consumed by `processor` for subtitle burn-in and Phase 6 blur
