# src/tts — TTS module

This module handles text-to-speech dubbing for the pipeline.

## Files

- `__init__.py` — factory: `get_tts_provider()` selects Edge TTS by default, falling back to other providers based on config.
- `base.py` — `BaseTTSProvider` ABC with `synthesise(text, voice, output_path)`.
- `assembler.py` — end-to-end dubbing orchestrator: synthesises per-segment clips, runs the planner, applies atempo, mixes underlay, writes the final WAV and `dubsync.srt`.
- `planner.py` — pure-function timing/shortening core (see below).
- `runner.py` — pipeline stage wrapper that calls the assembler and persists state.
- `dubsync_srt.py` — writes `{video_id}_{lang}.dubsync.srt` from planner output for use by the processor's burn-in step.
- `edge.py`, `openai_tts.py`, `google_tts.py`, `elevenlabs.py`, `piper_tts.py`, `gtts_provider.py` — provider implementations.

## Planner architecture (2026-05-20)

- `planner.py` is the pure-function core: `Planner.build_plan(...)` returns a `DubPlan` with per-sentence shortening targets, push amounts, gap reclaims, and review flags. No I/O — fully unit-tested in `tests/test_tts_planner.py`.
- The assembler synthesises at natural speed, calls the planner, runs one batched LLM shortening pass for sentences with `shorten_pct < 1.0`, applies atempo, and mixes via `_concatenate_with_silence` with the source MP4's audio as an underlay (read directly via ffmpeg's `[1:a]`).
- Synth-failure slots un-duck the underlay so the source Chinese voice carries that span at 0 dB.
- `data/srt/{video_id}_{lang}.dubsync.srt` is the per-segment SRT the processor's burn-in prefers; it carries the actually-spoken text at the actually-played timings.
- Known limitation: Phase C's drift-cap rebalance loop is structurally present but rarely fires under the current Phase B selection heuristics. Drift cap enforcement currently relies on `needs_review` flagging at end of run rather than active mid-run rebalancing.
