# Dub-Shortening Toggle

> **Branch:** `feature/subtitle-versioning` (bundled into PR #19). The toggle lands as additional commits on the versioning branch — the user picked "Stack on top of PR #19" during brainstorming so both ship together.

## Goal

Let the user disable the LLM-based dub-text shortening (`_apply_shortening`, Stage 3) from the per-video DubTab while keeping it enabled by default for the CLI/pipeline path. Stage 0 (LLM sentence merging) still runs when shortening is disabled — only the per-sentence text compression is skipped.

## Why

The pipeline always wants the dub to fit each sentence's source span (so it can stitch back into the original video without overruns). For the per-video DubTab, the user is iterating manually and sometimes prefers the LLM's natural translation, accepting the risk of an overrun rather than a shortened sentence that loses nuance. The user asked for this control explicitly.

## Non-goals

- No per-sentence override (no "shorten this one but not that one").
- No exposing the toggle in the CLI/pipeline UI — it stays on by default there.
- No change to the planner's `shorten_pct` computation. The planner still flags sentences that would benefit from shortening; the toggle gates whether the LLM is asked to actually shorten them.
- No retroactive change to already-generated dub WAVs.
- No save/recall per-version of the toggle state — it's a global "how should I generate dubs" preference (localStorage-persisted), not part of the snapshot.

## Architecture

A single boolean threads from the FE checkbox through `POST /api/tts` to `generate_full_track`. The assembler conditionally calls `_apply_shortening`. When disabled, the planner-flagged sentences get a clear `reason="shorten_disabled"` so the per-sentence plan rows (visible in `data/tts/{id}_*.merged.json` and via the BE response) document why a clip might overrun.

```
┌─────────────────┐       enable_shortening: bool        ┌──────────────────────┐
│ DubTab checkbox │ ──────────────────────────────────►  │ POST /api/tts        │
└─────────────────┘       (default true)                 └──────────────────────┘
                                                                    │
                                                                    ▼
                                                          ┌──────────────────────┐
                                                          │ task_manager.run_tts │
                                                          └──────────────────────┘
                                                                    │
                                                                    ▼
                                                          ┌──────────────────────┐
                                                          │ runner.run_tts_track │
                                                          └──────────────────────┘
                                                                    │
                                                                    ▼
                                                          ┌──────────────────────────────┐
                                                          │ assembler.generate_full_track│
                                                          │                              │
                                                          │   Stage 0: LLM merge ✓       │
                                                          │   Stage 1: synth ✓           │
                                                          │   Stage 2: planner ✓         │
                                                          │   Stage 3: _apply_shortening │
                                                          │           ← gated by flag    │
                                                          │   Stage 4: atempo ✓          │
                                                          │   Stage 5: concat ✓          │
                                                          └──────────────────────────────┘
```

The pipeline path (`src.cli` / `src.pipeline`) doesn't expose the flag to users; it calls `run_tts` with the default `enable_shortening=True`, preserving today's behavior.

## Backend changes

### `src/api/models.py`

Add to `TTSRequest`:

```python
enable_shortening: bool = True
```

Default `True` so the existing pipeline and any unaware FE callers continue to shorten.

### `src/api/task_manager.py`

`run_tts` gains:

```python
enable_shortening: bool = True
```

(placed after `version: str = "draft"` from the versioning work, before any other defaulted kwargs).

Forwarded to `run_tts_track`.

### `src/api/routers/tts.py`

The `POST /api/tts` handler passes `request.enable_shortening` into `tm.run_tts(...)`.

### `src/tts/runner.py`

`run_tts_track` gains the same `enable_shortening: bool = True` parameter and forwards it to `assembler.generate_full_track`.

### `src/tts/assembler.py`

`generate_full_track` gains `enable_shortening: bool = True` (placed near `version`, before the log-line block that already prints `version`). The log line is extended to include shortening state:

```python
logger.info(
    f"Generating dub for version={version} "
    f"shortening={'on' if enable_shortening else 'off'}"
)
```

The Stage 3 call becomes:

```python
if enable_shortening:
    await self._apply_shortening(
        plan=dub_plan, sentence_groups=sentence_groups, slots=slots,
        provider=provider, voice=voice, kwargs=kwargs, tmp=tmp,
        effective_speed=effective_speed,
    )
else:
    # Shortening disabled — flag the planner's recommendations for
    # visibility but don't ask the LLM to compress text. Clips that
    # would have shortened may overrun; the atempo pass at
    # `effective_speed` is still the only timing nudge they get.
    for sp in dub_plan.sentences:
        if sp.shorten_pct < 1.0:
            sp.needs_review = True
            sp.reason = "shorten_disabled"
```

Nothing else changes in the function. Stages 0 (LLM sentence merge), 1 (synth), 2 (planner), 4 (atempo), 5 (concat) all run identically.

## Frontend changes

### `ui-app/src/api/client.ts`

`postTTS` gains a `shortenToFit: boolean = true` parameter (placed after `version`):

```ts
export function postTTS(
  videoId: string,
  language: string,
  provider: string,
  voice: string,
  version: string = 'draft',
  shortenToFit: boolean = true,
  apiKey?: string,
  llmApiKey?: string,
  llmBackend?: string,
  playbackSpeed?: number,
  underlayDb?: number,
): Promise<TaskResponse> {
  return request('/tts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      // ...existing fields...
      enable_shortening: shortenToFit,
    }),
  });
}
```

The argument order matters for existing call sites — adding `shortenToFit` after `version` puts it next to its semantic neighbor (also-defaulted-true) and keeps existing positional calls passing `apiKey` / `llmApiKey` / etc. in the right slot.

### `ui-app/src/pages/VideoDetail.tsx`

New state, persisted via the existing localStorage pattern (mirrors `ttsPlaybackSpeed` / `ttsUnderlayDb`):

```tsx
const [enableShortening, setEnableShortening] = useState<boolean>(() => {
  const stored = storageGet('tts_enable_shortening');
  return stored === null ? true : stored === 'true';
});
```

Persisted on change:

```tsx
useEffect(() => {
  storageSet('tts_enable_shortening', String(enableShortening));
}, [enableShortening]);
```

Passed into `<DubTab>` as `enableShortening` / `onChangeEnableShortening`.

The `postTTS` call site updates to pass `enableShortening` as the 6th positional argument:

```ts
postTTS(
  videoId,
  ttsLanguage,
  selectedTtsProvider,
  voiceForRequest,
  selectedVersion,
  enableShortening,           // ← new
  ttsApiKey || undefined,
  llmApiKey || undefined,
  llmBackend || undefined,
  ttsPlaybackSpeed,
  ttsUnderlayDb,
);
```

### `ui-app/src/pages/videoDetail/DubTab.tsx`

New props on the interface:

```ts
enableShortening: boolean;
onChangeEnableShortening: (next: boolean) => void;
```

New checkbox rendered between the Playback Speed slider section and the Underlay slider section:

```tsx
<div className="px-3 py-3 rounded-lg border border-outline-variant/15">
  <label className="flex items-start gap-2 cursor-pointer">
    <input
      type="checkbox"
      checked={enableShortening}
      onChange={(e) => onChangeEnableShortening(e.target.checked)}
      className="mt-0.5 accent-primary"
    />
    <div className="flex-1">
      <div className="text-xs font-medium text-on-surface">
        Shorten dub to fit timeline
      </div>
      <div className="text-[10px] text-on-surface-variant mt-0.5 leading-snug">
        Uses the LLM to compress text when a sentence would overrun its
        time slot. Uncheck to keep the original translation — clips may
        overrun.
      </div>
    </div>
  </label>
</div>
```

No styling overhaul, no separate section header — slots in next to the other timing controls.

## Tests

### BE — `tests/test_tts.py`

Add a new test class `TestShorteningToggle` next to `TestIterativeShortening`. The new class operates on `_apply_shortening` directly (same level as the existing iterative tests) and adds one integration assertion at `generate_full_track` level via mocking.

```python
class TestShorteningToggle:
    @pytest.mark.asyncio
    async def test_apply_shortening_skipped_when_disabled(self, tmp_path):
        """generate_full_track must not call `_apply_shortening` when
        enable_shortening=False, even when the planner flags sentences for
        shortening. Flagged sentences get reason='shorten_disabled' instead."""
        from unittest.mock import AsyncMock, patch
        from src.tts.assembler import TTSAssembler

        translator = AsyncMock()
        translator.shorten_texts_batch = AsyncMock()
        provider = AsyncMock()
        provider.synthesize = AsyncMock(return_value=b"audio")

        assembler = TTSAssembler(max_concurrent=2, translator=translator)

        with patch.object(
            assembler, "_apply_shortening", AsyncMock()
        ) as apply_mock, patch(
            "src.tts.assembler._get_audio_duration", return_value=2.0
        ), patch(
            "src.tts.assembler._concatenate_with_silence"
        ):
            await assembler.generate_full_track(
                provider=provider,
                segments=[{
                    "start": 0.0, "end": 1.0,
                    "text": "hi", "index": 0,
                }],
                voice_profile={"voice": "v"},
                video_duration=1.0,
                output_path=tmp_path / "out.wav",
                playback_speed=1.5,
                enable_shortening=False,
            )

        # _apply_shortening must NOT be awaited when the flag is off.
        apply_mock.assert_not_awaited()
        # The translator's shorten_texts_batch must NOT be touched either.
        translator.shorten_texts_batch.assert_not_called()

```

For the "needs_review marked as shorten_disabled" assertion, the implementer can either inline an extra assertion in the test above (after building a sentence with `shorten_pct = 0.85`), or extract the post-skip flagging into a tiny helper that's directly unit-testable. Either approach is fine — what matters is that the `reason="shorten_disabled"` contract is asserted.

The existing `TestIterativeShortening` (in `tests/test_tts.py`) shows how to mock translator + provider + plan and inspect post-run state; this test reuses that pattern.

### FE — `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` (new file)

Two assertions:

1. Clicking the "Shorten dub to fit timeline" checkbox calls `onChangeEnableShortening` with the new boolean.
2. The checkbox reflects the incoming `enableShortening` prop on render.

vitest + RTL, matches the pattern in `ui-app/src/components/dub/__tests__/VersionPicker.test.tsx`.

## Verification

1. `python -m pytest tests/test_tts.py::test_apply_shortening_skipped_when_flag_disabled -v` — passes.
2. `python -m pytest tests/ -x` — full BE suite green.
3. `cd ui-app && npx vitest run` — full FE suite green (including the new DubTab test).
4. `cd ui-app && npm run build` — succeeds (modulo the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).
5. **Manual smoke:**
   - Open a video → Dub tab → "Shorten dub to fit timeline" checkbox is **checked** by default (or whatever the user last set).
   - Generate a dub with checkbox checked → expect the existing behavior (clips that would overrun get LLM-shortened text).
   - Uncheck → reload the page → checkbox stays unchecked (localStorage round-trip).
   - Generate a dub with checkbox unchecked → inspect `data/tts/{id}_*.merged.json`: planner-flagged sentences should have `was_shortened=False`, `needs_review=True`, `reason="shorten_disabled"`. The corresponding clips should retain the original sentence text. If a clip overruns, expect a real timing overrun (no atempo magic beyond `playback_speed`).
   - Pipeline (CLI `python -m src process …`) → confirm the log line still says `shortening=on` for pipeline runs (default `enable_shortening=True`).

## Out of scope

- Per-version persistence of the toggle. The toggle is a per-user preference, not a property of a version. If the user wants two dubs of the same version with different shortening behavior, they can flip the toggle between two `Generate Dub` clicks.
- Auto-detecting when shortening would help and showing a recommendation in the UI. The current `merged.json` already records `was_shortened` and `reason` — a UI surfacing those is a follow-up.
- A per-sentence "shorten / don't shorten" override.

## Critical files

- [src/api/models.py](src/api/models.py) — `TTSRequest.enable_shortening` field
- [src/api/task_manager.py](src/api/task_manager.py) — `run_tts` signature
- [src/api/routers/tts.py](src/api/routers/tts.py) — forwarding
- [src/tts/runner.py](src/tts/runner.py) — `run_tts_track` signature
- [src/tts/assembler.py](src/tts/assembler.py) — gate on `_apply_shortening`
- [tests/test_tts.py](tests/test_tts.py) — one BE test
- [ui-app/src/api/client.ts](ui-app/src/api/client.ts) — `postTTS` signature
- [ui-app/src/pages/VideoDetail.tsx](ui-app/src/pages/VideoDetail.tsx) — state + persistence + call site
- [ui-app/src/pages/videoDetail/DubTab.tsx](ui-app/src/pages/videoDetail/DubTab.tsx) — checkbox UI
- `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` — new FE test
- [CHANGELOG.md](CHANGELOG.md) — entry under `[Unreleased] → Added`
- [README.md](README.md) — progress section entry
