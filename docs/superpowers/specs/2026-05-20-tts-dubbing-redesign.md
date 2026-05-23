# TTS Dubbing Redesign — Plan-then-Emit with Chinese Underlay

**Status:** Draft — ready for implementation planning
**Date:** 2026-05-20
**Scope:** `src/tts/assembler.py` (rewrite), small additions to `src/processor/`, `src/api/`, `ui-app/`

## Problem

The current dubbing pipeline (`src/tts/assembler.py`) has three concrete user-visible failures:

1. **Some dubbed sentences are silently dropped from the output.** When TTS synthesis fails or returns zero-duration audio, the sentence is logged at `WARNING` and excluded from the final WAV. The docstring claims "no silent skips" but the code (lines 637–641) does drop them.
2. **Aggressive LLM shortening destroys meaning.** The current shortening loop runs up to 3 passes with each pass 5pp tighter, reaching a floor of 30% of the original character count. Sentences shortened to that floor are barely intelligible.
3. **The burned-in subtitle does not reflect what was actually spoken.** When a sentence is shortened, `{stem}.merged.srt` is written but the burn-in step still uses the original per-segment SRT, so the visible text diverges from the dub.

Underlying these is a structural issue: the assembler tries to fit Vietnamese (typically 10–20% longer than Chinese) into the source video's exact timing by mutilating either content (over-shortening) or completeness (silent drops). Neither lever is acceptable in the current settings.

## Goals

In priority order:

1. **Uniform, predictable pacing.** Every Vietnamese sentence plays at the same configurable `playback_speed` (default 1.5×; user-tunable 1.0–2.0×). No mixed paces within a single track.
2. **No silent skips.** Every merged sentence is acknowledged in the output WAV. Synthesis failures fall back to the original Chinese audio at that slot, not silence.
3. **Natural-sounding speech.** Sentences only get shortened as much as the timing actually requires, and never below 60% of the original character count.
4. **Audible original.** The Chinese voice track sits underneath the Vietnamese dub at a configurable level (default -12 dB), as both a stylistic choice and a redundancy signal.
5. **Subtitle parity.** The burned-in per-segment subtitle reflects the spoken (possibly shortened) text and the actual dub timing.
6. **Auditable.** Every shortening decision, push, reclaim, and failure is recorded in a structured plan file per run.
7. **Pipeline ≡ Per-Video.** Same code path, same configuration, byte-identical output whether triggered from the Pipeline launcher or the Video Studio "Generate TTS" button.

## Non-goals

- Changing the translation step. Translation continues to produce per-segment Vietnamese; the dubbing pipeline consumes that output.
- Changing the merge-into-sentences step (Stage 0). The LLM/heuristic grouping in `src/tts/assembler.py` stays.
- Changing TTS providers or voices. The provider abstraction (`BaseTTSProvider`) is unchanged.
- Replacing the per-segment SRT format. Burned-in subtitles remain 1-line-per-segment, just with redistributed text and shifted timings.
- Automating quality grading of LLM-shortened text. Quality remains a manual-QA concern.

## Architecture

The current linear pipeline is restructured into a planner-then-emitter shape. Decisions are computed by a pure function over input data; emission is a separate stage that takes a finalised `DubPlan`.

```
Stage 0   Merge segments → sentence groups          (unchanged)
Stage 1   Synthesise all sentences at natural speed (one batched provider call)
Stage 2   Build DubPlan (pure function)             (NEW — testable without ffmpeg/LLM)
Stage 3   Batch re-synth shortened sentences        (one batched LLM call + TTS calls)
Stage 4   Apply atempo at playback_speed            (unchanged)
Stage 5   Concatenate: silence + underlay + clips   (revised: adds Chinese underlay)
Stage 6   Emit per-segment dubsync.srt              (NEW)
```

Key structural changes from today:

- `DubPlan` and `SentencePlan` are new dataclasses. The planner is a pure function: same inputs → same outputs, no I/O.
- The iterative shortening loop (current Stage 1.5) becomes a single batched LLM call after Phase B of the planner decides exact target percentages.
- Stage 5's filter graph now takes the source MP4 as an additional input and mixes its audio stream underneath the Vietnamese clips. No pre-extraction step.
- A new `{video_id}_{lang}.dubsync.srt` is written; the burn-in step prefers it over the original SRT if present.

## Data Structures

Defined in `src/tts/assembler.py`:

```python
@dataclass
class SentencePlan:
    index: int
    segment_indices: list[int]       # source SRT segment indices
    original_text: str                # post-merge, pre-shortening
    target_text: str                  # final spoken text; == original_text if not shortened
    natural_synth_duration: float    # measured from Stage 1
    original_start: float             # source-aligned start (from merge)
    original_end: float               # source-aligned end
    final_start: float                # actual start in output WAV (after push)
    final_duration: float             # natural_synth_duration / playback_speed (target)
    drift_in: float                   # accumulated offset entering this sentence
    drift_out: float                  # accumulated offset leaving this sentence
    shorten_pct: float                # 1.0 = no shortening; 0.85 = trimmed to 85%
    push_amount: float                # seconds this sentence pushed the next one later
    reclaimed_silence: float          # seconds borrowed from gap after this sentence
    needs_review: bool
    reason: str | None                # one of the strings in §"Failure Modes"


@dataclass
class DubPlan:
    sentences: list[SentencePlan]
    playback_speed: float
    underlay_db: float                # 0.0 disables underlay
    total_drift_end: float
    drift_cap_hits: int
    reset_points: list[int]           # sentence indices where drift was reset to 0
```

## Constants

Defined at module top in `src/tts/assembler.py`:

```python
PLAYBACK_SPEED_DEFAULT  = 1.5
UNDERLAY_DB_DEFAULT     = -12.0
SHORTEN_TARGETS         = [0.85, 0.75, 0.65]   # tried in order, loosest first
SHORTEN_FLOOR           = 0.60                  # never accept text below this fraction
RECLAIM_MIN_GAP         = 1.0                   # only reclaim from silent gaps ≥ 1.0s
RECLAIM_RESERVE         = 0.2                   # always leave 0.2s silence after reclaim
RESET_GAP_THRESHOLD     = 3.0                   # gaps ≥ 3.0s reset accumulated drift to 0
DRIFT_CAP               = 3.0                   # max accumulated drift before Phase C rebalance
```

All durations are in **played-seconds** (post-atempo at `playback_speed`), not natural-synth seconds. The conversion `played = natural / playback_speed` is applied once at the top of the planner.

## Algorithm (Stage 2 — the Planner)

The planner takes `(sentence_groups, natural_synth_durations, playback_speed, video_duration, drift_cap, underlay_db)` and returns a `DubPlan`. Three phases.

### Phase A — Walk sentences, compute desired positions, accumulate drift

```
drift = 0
for i in range(len(sentences)):
    desired_dur = natural_synth_duration[i] / playback_speed
    slot_size   = original_end[i] - original_start[i]
    next_start  = original_start[i+1] if i+1 < N else video_duration
    raw_gap_after = next_start - original_end[i]

    final_start[i] = original_start[i] + drift

    if desired_dur <= slot_size:
        # fits within its own slot
        final_duration[i] = desired_dur
        # If drift > 0, try to recover via reclaim from the gap after
        if drift > 0 and raw_gap_after >= RECLAIM_MIN_GAP:
            reclaim = min(drift, raw_gap_after - RECLAIM_RESERVE)
            drift -= reclaim
            reclaimed_silence[i] = reclaim
    else:
        # Overruns slot. Absorb via reclaim first, then accept push.
        overrun = desired_dur - slot_size
        if raw_gap_after >= RECLAIM_MIN_GAP:
            absorb = min(overrun, raw_gap_after - RECLAIM_RESERVE)
            overrun -= absorb
            reclaimed_silence[i] = absorb
        final_duration[i] = desired_dur
        drift += overrun
        push_amount[i] = overrun
        if overrun > 0:
            overflow_candidates.append(i)

    drift_out[i] = drift

    if raw_gap_after >= RESET_GAP_THRESHOLD:
        reset_points.append(i)
        drift = 0
```

After Phase A, every sentence has a tentative position, accumulated drift is known, and `overflow_candidates` lists sentences that still push downstream.

### Phase B — Decide shortening targets

For each `i` in `overflow_candidates`:

```
slot_size = original_end[i] - original_start[i]
available = slot_size + reclaimed_silence[i]
required_shorten_pct = available / desired_dur[i]
# pick loosest target that fits
chosen = next((t for t in SHORTEN_TARGETS if t <= required_shorten_pct), SHORTEN_FLOOR)
shorten_pct[i] = chosen
```

This guarantees a sentence overrunning by 12% picks `0.85`, not `0.65`. A sentence overrunning by 50% picks `0.60` (the floor) — and is still allowed to push if 60% doesn't fully fit.

### Phase C — Drift-cap rebalance

After Phase B, recompute drift assuming each `overflow_candidates[i]` succeeds at its `shorten_pct[i]`. If projected drift ever exceeds `DRIFT_CAP` at any sentence:

```
while max_projected_drift > DRIFT_CAP:
    # pick the sentence upstream of the cap hit with the largest overrun
    # that still has shortening budget left
    target = max(
        (s for s in upstream_sentences if shorten_pct[s] > SHORTEN_FLOOR),
        key=lambda s: desired_dur[s] - (slot_size[s] + reclaimed_silence[s]),
        default=None,
    )
    if target is None:
        # No upstream sentence can shorten more. Flag the cap-hit sentences.
        for s in cap_hit_window:
            needs_review[s] = True
            reason[s] = "drift_cap_hit"
        break
    shorten_pct[target] = next_tighter(shorten_pct[target])  # e.g. 0.85 → 0.75
    recompute_drift()
    drift_cap_hits += 1
```

The result is a `DubPlan` with all decisions encoded. **No LLM calls yet.** No ffmpeg yet.

## Stage 3 — Batch re-synthesis

Collect all sentences with `shorten_pct[i] < 1.0`. Make one batched LLM call:

```python
batch = [
    {"index": s.index, "original": s.original_text,
     "target_pct": s.shorten_pct, "target_chars": int(len(s.original_text) * s.shorten_pct)}
    for s in plan.sentences if s.shorten_pct < 1.0
]
shortened = await translator.shorten_texts_batch(batch)
```

Re-synthesise each shortened text concurrently (existing semaphore). After re-synth, re-measure:

- If actual duration ≤ planned `final_duration`: accept, store as `target_text`.
- If actual duration > planned by ≤ 10%: accept, flag `needs_review=True, reason="shorten_undershot"`. Subsequent emission absorbs the small extra via reclaim if available; otherwise it adds to drift (which is already capped).
- If actual duration > planned by > 10%: discard re-synth, keep Stage 1 clip, flag `reshorten_undershot_hard`. Final position adjusted at emission.
- If re-synth raises or returns zero-duration: discard, keep Stage 1 clip, flag `reshorten_failed`.

## Stage 5 — Filter graph (with Chinese underlay)

ffmpeg call shape:

```
ffmpeg -i {silence_anchor.wav}   # [0]: anullsrc, length = video_duration
       -i {video_id}.mp4         # [1]: source video, audio stream at [1:a]
       -i {clip_0.mp3} -i {clip_1.mp3} ... -i {clip_K.mp3}  # [2..K+1]

-filter_complex "
  [1:a]aformat=channel_layouts=mono:sample_rates=24000,volume={underlay_db}dB[underlay];
  [2]adelay={ms_0}|{ms_0}[d0];
  [3]adelay={ms_1}|{ms_1}[d1];
  ...
  [0][underlay][d0][d1]...[dK]amix=inputs={K+2}:duration=first:dropout_transition=0,volume={K+2}[mixed];
  [mixed]loudnorm=I=-16:TP=-1.5:LRA=11[out]
"
-map "[out]" -c:a pcm_s16le -ar 24000 {output.wav}
```

For synth-failure slots (`reason ∈ {synth_failed, synth_empty}`), the underlay branch gets one extra `volume` filter per failure window:

```
[1:a]aformat=...,
     volume=enable='between(t,{f0_start},{f0_end})':volume={-underlay_db}dB,
     volume=enable='between(t,{f1_start},{f1_end})':volume={-underlay_db}dB,
     ...
     volume={underlay_db}dB
[underlay]
```

The chained `volume` filters with `enable=` raise the underlay back to 0 dB during failure windows (cancelling the configured `underlay_db` cut), then the final `volume={underlay_db}dB` applies the base cut everywhere else. For zero failures the graph stays at the happy-path shape (one `volume`, no `enable`).

If `underlay_db == 0`, the entire `[1:a]…[underlay]` branch and its slot in `amix` are omitted.

## Stage 6 — dubsync.srt emission

Output path: `data/srt/{video_id}_{lang}.dubsync.srt`

For each `SentencePlan` p, for each `seg_idx` in `p.segment_indices`:

```
# Text redistribution (proportional by original char count, snapped to word boundaries)
orig_chars = [len(_clean_text(segments[k].text)) for k in p.segment_indices]
total_orig = sum(orig_chars)
target_chars = [round(len(p.target_text) * c / total_orig) for c in orig_chars]
# Walk p.target_text, slicing at nearest word boundary ≥ cumulative target_chars[i]

# Timing redistribution (proportional by original duration, anchored at p.final_start)
total_orig_dur = segments[p.segment_indices[-1]].end - segments[p.segment_indices[0]].start
anchor = p.final_start
for k, orig_idx in enumerate(p.segment_indices):
    orig_dur = segments[orig_idx].end - segments[orig_idx].start
    share = (orig_dur / total_orig_dur) * p.final_duration
    out_seg = (anchor, anchor + share, text_chunks[k])
    anchor += share
```

The processor's burn-in step (`src/processor/`) is changed to prefer `{video_id}_{lang}.dubsync.srt` if it exists, falling back to `{video_id}_{lang}.srt`. One log line indicates which file was used.

## Configuration Surface

### Backend (`config/config.yaml`)

```yaml
tts:
  playback_speed: 1.5    # already exists; documented here for completeness
  underlay_db: -12.0     # 0 disables the underlay; range typically -24..0
```

Both values support `${VAR:-default}` interpolation per project convention.

### Per-request (FastAPI models in `src/api/routers/`)

Additive fields (all existing requests stay valid):

```python
class TTSRequest(BaseModel):
    # existing fields...
    playback_speed: float | None = None
    underlay_db: float | None = None
```

Same fields added to `TTSPreviewRequest`, `FullPipelineRequest`, `BatchPipelineRequest`. Field precedence at the assembler: request value → Settings localStorage value (sent as request value by the UI) → `config.yaml` → constant default.

### UI (`ui-app/src/pages/`)

- **Settings page**: new "Original-language underlay" select with options `Off / -24 dB / -18 dB / -12 dB / -6 dB`. Default `-12 dB`. Persisted to `localStorage['tts_underlay_db']`.
- **VideoDetail (Video Studio)**: TTS panel adds a small "Underlay" select inline beside the existing "Playback Speed" input. Default reads from Settings; per-run override sent on the request.
- **DownloadTranscribe (Pipeline launcher)**: same select alongside the playback-speed input. Same default and override behaviour.
- **TTSPreview component**: reads `tts_underlay_db` and includes the underlay in the preview snippet so what you hear before generating matches what you get.

## Failure Modes

Every failure path has a distinct `reason` string. The `tts.complete` SSE event carries a `review_reasons` histogram so the UI can show "2 sentences hit the drift cap, 1 synth failure" at a glance.

| Trigger | Handling | `reason` |
|---|---|---|
| Stage 1 synth raises | One retry with re-cleaned text. If retry fails, slot gets Chinese-at-0-dB; underlay ducks to 0 in that span. | `synth_failed` |
| Stage 1 synth returns 0-byte / 0-duration | One retry, then Chinese-at-0-dB fallback as above. | `synth_empty` |
| Stage 3 re-synth raises | Keep Stage 1 clip. Sentence not shortened; downstream push/reclaim absorbs. | `reshorten_failed` |
| Stage 3 re-synth clip ≥ original duration | Discard re-synth, keep Stage 1 clip. | `reshorten_not_shorter` |
| Stage 3 clip > planned by ≤ 10% | Accept, flag. | `shorten_undershot` |
| Stage 3 clip > planned by > 10% | Discard re-synth, keep Stage 1 clip. | `reshorten_undershot_hard` |
| Atempo (`_speed_up_audio`) raises | Use natural-speed clip for that slot. | `atempo_failed` |
| Atempo off target by > 10% | Use natural-speed clip for that slot. | `atempo_off_target` |
| Drift cap hit, no upstream sentence can shorten more | Slot kept; small overlap with next sentence at amix. Underlay stays constant in overlap region. | `drift_cap_hit` |
| `final_start + final_duration > video_duration` after Phase C | Force tighter shortening in Phase C rebalance. If unrecoverable, flag. | `overruns_video_end` |

### Contract

For every sentence that survived Stage 0's merge:

1. Exactly one entry in `DubPlan.sentences`.
2. Exactly one entry per source segment in `{video_id}_{lang}.dubsync.srt`.
3. The output WAV at `[final_start, final_start + final_duration)` contains either the Vietnamese dub over the Chinese underlay, OR the Chinese audio at 0 dB (with underlay locally muted). Never silence.
4. If condition 3's fallback path was used, `needs_review = True` with a specific `reason`.

## Output Artifacts

All written next to the dub WAV (`data/tts/{video_id}_{lang}_{provider}_{profile}.wav`):

- `{stem}.plan.json` — full `DubPlan` serialised. Header + per-sentence rows with the fields from the data structure section. Existing artifact; gains new fields (`drift_in/out`, `push_amount`, `reclaimed_silence`, `reason`, `underlay_db` in header).
- `{stem}.plan.tsv` — same data, tab-separated. Existing artifact; gains new columns.
- `{stem}.sentences.srt` — one entry per merged sentence with `final_start`/`final_start + final_duration` and `target_text`. Existing artifact; timings now reflect actual positions.
- `{video_id}_{lang}.dubsync.srt` — **NEW**. Per-segment SRT with redistributed text and retimed positions. Lives in `data/srt/`, not `data/tts/`, so the processor can find it next to the legacy `{video_id}_{lang}.srt`.

The legacy `{stem}.merged.srt` and `{stem}.merged.json` artifacts are removed (their content is now covered by `.sentences.srt` and `.plan.json` respectively).

## SSE Event Schema

The `tts.complete` event becomes:

```json
{
  "review_count": 2,
  "review_reasons": {"synth_failed": 1, "drift_cap_hit": 1},
  "underlay_db": -12.0,
  "playback_speed": 1.5,
  "total_drift_end": 0.4,
  "drift_cap_hits": 1,
  "sentence_plan": [/* SentencePlan rows */]
}
```

Existing consumers (Dashboard, VideoDetail) continue to read `review_count` and `sentence_plan` as before. The UI adds a small histogram next to `review_count` showing `review_reasons`.

## Testing

### Planner unit tests (no ffmpeg, no LLM, no network)

`tests/test_tts_planner.py` (new file):

| Test | Setup | Asserts |
|---|---|---|
| `test_plan_no_overflow_passthrough` | All sentences fit at 1.5× | `shorten_pct = 1.0`, `drift_out = 0` for all |
| `test_plan_picks_loosest_shorten_target` | One sentence needs 12% trim | Picks `0.85`, not `0.65` |
| `test_plan_reclaims_silent_gap` | Sentence overruns 0.6s, next gap is 1.5s | `reclaimed_silence ≈ 0.6`, `drift_out = 0` |
| `test_plan_pushes_when_no_gap` | Overrun 0.8s, next gap 0.3s | `push_amount = 0.8`, downstream `drift_in = 0.8` |
| `test_plan_resets_drift_at_long_pause` | Drift 1.2s entering a 3.5s gap | After gap, `drift_in = 0` for next sentence |
| `test_plan_drift_cap_forces_rebalance` | Projected drift hits 3.5s | Phase C tightens upstream sentence; final drift ≤ 3.0s |
| `test_plan_drift_cap_unrecoverable` | Drift would exceed 3s, all upstream at SHORTEN_FLOOR | Cap-hit sentence flagged `needs_review = True`, `reason = "drift_cap_hit"` |
| `test_plan_at_1x_playback_speed` | Same inputs, `playback_speed = 1.0` | Algorithm scales — every duration ~1.5× the 1.5× run |
| `test_plan_at_2x_playback_speed` | Same inputs, `playback_speed = 2.0` | Most sentences fit without shortening |

### Assembler integration tests (ffmpeg, mocked TTS provider)

`tests/test_tts_assembler.py` (extends existing file):

| Test | Setup | Asserts |
|---|---|---|
| `test_regression_zero_duration_synth_no_longer_silent` | **Regression**: mock provider returns 0-byte audio for sentence 3 | (a) `len(plan.sentences) == N` (no drops); (b) RMS at sentence 3's slot > underlay floor (audible Chinese); (c) plan entry `needs_review=True, reason="synth_empty"` |
| `test_synth_failure_falls_back_to_chinese_full_volume` | Mock provider raises on sentence 3 | Output WAV has higher RMS at sentence 3's slot than at non-failure slots; plan entry `reason = "synth_failed"` |
| `test_atempo_failure_falls_back_to_natural` | Patch `_speed_up_audio` to raise once | That sentence plays at 1.0×; flagged `atempo_failed`; rest of track unaffected |
| `test_underlay_volume_applied` | `underlay_db = -18` vs `underlay_db = -12` | Chinese band ~6 dB quieter in the -18 run |
| `test_underlay_zero_disables` | `underlay_db = 0` | Output WAV at silent gaps shows noise floor only |
| `test_dubsync_srt_written` | Normal run with one shortened sentence | `{video_id}_{lang}.dubsync.srt` exists; affected segment's text is a substring of the shortened sentence; timing matches `final_start`/`final_duration` proportional split |
| `test_no_silent_drops_invariant` | 10 sentences, 2 with synth failures | `len(plan.sentences) == 10`; `dubsync.srt` covers all source segments |

### Manual QA (against URLs in `testurl.txt`)

Before merging:

- Generate dub at `playback_speed=1.5, underlay_db=-12` (defaults). Listen end-to-end. Confirm: Vietnamese dominant, Chinese audible underneath, no muted sentences, no chipmunk artifacts.
- Same video at `playback_speed=1.2`: confirm more sentences need shortening/push, no quality regression.
- Same video at `playback_speed=2.0`: confirm almost no shortening triggers and drift recovers via reclaim.
- Open `{stem}.plan.tsv` in a spreadsheet: confirm every `was_shortened=True` row's `target_text` reads sensibly.
- Play `dubsync.srt` against the source video in VLC: visible subtitles match the dub.

## Migration

- `data/tts/{stem}.merged.srt` and `{stem}.merged.json` from past runs are obsolete and can be deleted. The new emission does not write them.
- Existing `data/srt/{video_id}_{lang}.srt` files remain untouched; they serve as the legacy fallback when `dubsync.srt` is absent (e.g., for videos processed before this change).
- No database schema changes. No state file changes. No breaking API changes.

## Open Questions

None at draft time. All design decisions were locked in during brainstorming:

- Strategy: shorten first (gently), then push downstream if needed.
- Shorten floor: 60% (three pass targets: 85% / 75% / 65%).
- Drift recovery: reclaim silent gaps ≥ 1s; reset at gaps ≥ 3s.
- Drift cap: 3s; if exceeded, Phase C forces tighter shortening on biggest-overrun upstream sentence.
- Subtitle update: per-segment chunks with proportional text redistribution at word boundaries.
- Fitting algorithm: plan-then-emit, two passes.
- Underlay default: -12 dB, uniform (no sidechain ducking).
- Underlay configurable at: Settings page + per-run override on TTS panel.
- Source MP4 audio read directly by ffmpeg in the mix filter graph; no pre-extraction step.
- Cap-hit overlap regions: underlay stays constant at the configured level.
