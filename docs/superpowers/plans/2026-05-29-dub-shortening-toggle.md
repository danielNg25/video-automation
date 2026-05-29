# Dub-Shortening Toggle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users disable the LLM-based dub-text shortening (`_apply_shortening`) from the per-video DubTab while keeping it on by default for the CLI/pipeline. Stage 0 (LLM sentence merging) still runs in both modes; only Stage 3 (per-sentence shortening) is gated.

**Architecture:** A single boolean `enable_shortening: bool = True` threads from a new DubTab checkbox through `POST /api/tts` → `task_manager.run_tts` → `runner.run_tts_track` → `assembler.generate_full_track`. When `False`, the assembler skips the call to `_apply_shortening` and flags planner-recommended sentences with `reason="shorten_disabled"` so the per-sentence `merged.json` documents the decision.

**Tech Stack:** FastAPI + Pydantic v2 (BE), React 19 + TypeScript + Tailwind 4 + Vite + vitest (FE).

---

## Context the implementer needs

**Spec:** [docs/superpowers/specs/2026-05-29-dub-shortening-toggle-design.md](docs/superpowers/specs/2026-05-29-dub-shortening-toggle-design.md) — full design rationale.

**Files at HEAD (read before starting):**
- [src/api/models.py:232](src/api/models.py#L232) — `TTSRequest` class
- [src/api/task_manager.py:669-681](src/api/task_manager.py#L669-L681) — `run_tts` signature; `version: str = "draft"` is the field we slot next to
- [src/api/routers/tts.py](src/api/routers/tts.py) — `POST /api/tts` handler that forwards into `run_tts`
- [src/tts/runner.py:120-133](src/tts/runner.py#L120-L133) — `run_tts_track` signature
- [src/tts/assembler.py:418-434](src/tts/assembler.py#L418-L434) — `generate_full_track` signature; `version: str = "draft"` at line 434
- [src/tts/assembler.py:327-417](src/tts/assembler.py#L327-L417) — `_apply_shortening` method (the gate target)
- [ui-app/src/api/client.ts:296](ui-app/src/api/client.ts#L296) — `postTTS` signature; `version` param at line 296
- [ui-app/src/pages/VideoDetail.tsx](ui-app/src/pages/VideoDetail.tsx) — owns the TTS state passed into DubTab (search for `tts_playback_speed` and `tts_underlay_db` localStorage usage)
- [ui-app/src/pages/videoDetail/DubTab.tsx](ui-app/src/pages/videoDetail/DubTab.tsx) — slider controls between which the checkbox lands (Playback Speed around line 208, Underlay around line 228)
- [ui-app/src/components/dub/__tests__/VersionPicker.test.tsx](ui-app/src/components/dub/__tests__/VersionPicker.test.tsx) — vitest precedent for component tests

**Commands you'll use:**
- BE test (single file): `python -m pytest tests/test_tts.py::TestShorteningToggle -v`
- BE full suite: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py`
- FE test (single file): `cd ui-app && npx vitest run src/pages/videoDetail/__tests__/DubTab.test.tsx`
- FE full suite: `cd ui-app && npx vitest run`
- FE build: `cd ui-app && npm run build`
- BE lint: `ruff check src/ tests/`

**Repo rules to follow (from CLAUDE.md):**
- Branch: `feature/subtitle-versioning` already exists with the spec commit `9459b81`. Stay on it. This work bundles with PR #19.
- Every commit updates `CHANGELOG.md` (`Added` for new behavior) and the progress section in `README.md`. Bundle CHANGELOG + README into the final Task 4 commit.
- **No AI mentions** in commit messages or code comments.

---

## File structure

| Path | Action | Responsibility |
|------|--------|---------------|
| `src/api/models.py` | Modify | Add `enable_shortening: bool = True` field to `TTSRequest` |
| `src/api/routers/tts.py` | Modify | Forward `request.enable_shortening` into `tm.run_tts(...)` |
| `src/api/task_manager.py` | Modify | Add `enable_shortening: bool = True` to `run_tts`, forward to `run_tts_track` |
| `src/tts/runner.py` | Modify | Add `enable_shortening: bool = True` to `run_tts_track`, forward to `assembler.generate_full_track` |
| `src/tts/assembler.py` | Modify | Add `enable_shortening: bool = True` to `generate_full_track`; gate the `_apply_shortening` call; flag planner-recommended sentences when disabled |
| `tests/test_tts.py` | Modify | Add `TestShorteningToggle` class with one test |
| `ui-app/src/api/client.ts` | Modify | `postTTS` gains `shortenToFit: boolean = true` parameter (6th positional) |
| `ui-app/src/pages/VideoDetail.tsx` | Modify | New `enableShortening` state with localStorage persistence; pass into DubTab; forward to `postTTS` |
| `ui-app/src/pages/videoDetail/DubTab.tsx` | Modify | New props `enableShortening` / `onChangeEnableShortening`; checkbox between Playback Speed and Underlay |
| `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx` | Create | One vitest covering the checkbox behavior |
| `CHANGELOG.md` | Modify | One `Added` entry under `[Unreleased]` |
| `README.md` | Modify | Progress section for this feature |

---

### Task 1: BE — thread `enable_shortening` and gate `_apply_shortening`

Plumb the flag end-to-end on the BE in one cohesive change. The test asserts the load-bearing behavior: when the flag is `False`, `_apply_shortening` is not awaited and planner-recommended sentences are marked `reason="shorten_disabled"`.

**Files:**
- Modify: `src/api/models.py`
- Modify: `src/api/routers/tts.py`
- Modify: `src/api/task_manager.py`
- Modify: `src/tts/runner.py`
- Modify: `src/tts/assembler.py`
- Modify: `tests/test_tts.py`

- [ ] **Step 1.1: Write the failing test**

Append a new test class to `tests/test_tts.py` (place it after `TestShortenTextsBatchFloor`):

```python
class TestShorteningToggle:
    @pytest.mark.asyncio
    async def test_apply_shortening_skipped_when_disabled(self, tmp_path):
        """generate_full_track must not call `_apply_shortening` when
        enable_shortening=False. Planner-flagged sentences get
        reason='shorten_disabled' so the audit trail makes the decision
        visible."""
        from unittest.mock import AsyncMock, patch

        from src.tts.assembler import TTSAssembler

        translator = AsyncMock()
        translator.shorten_texts_batch = AsyncMock()
        provider = AsyncMock()
        provider.synthesize = AsyncMock(return_value=b"audio")

        assembler = TTSAssembler(max_concurrent=2, translator=translator)

        # Patch the assembler's _apply_shortening so we can assert it
        # wasn't awaited. Patch the heavy ffmpeg/audio helpers so the
        # function actually runs end-to-end on a mocked segment.
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

        apply_mock.assert_not_awaited()
        translator.shorten_texts_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_apply_shortening_called_when_enabled(self, tmp_path):
        """The default path still calls `_apply_shortening` — the toggle is
        opt-out, not opt-in."""
        from unittest.mock import AsyncMock, patch

        from src.tts.assembler import TTSAssembler

        translator = AsyncMock()
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
                enable_shortening=True,
            )

        apply_mock.assert_awaited_once()
```

- [ ] **Step 1.2: Run — confirm fail**

Run: `python -m pytest tests/test_tts.py::TestShorteningToggle -v 2>&1 | tail -10`

Expected: 2 FAIL with `TypeError: generate_full_track() got an unexpected keyword argument 'enable_shortening'`. The signature doesn't accept the kwarg yet.

- [ ] **Step 1.3: Add `enable_shortening` to `generate_full_track` + gate the call**

Open `src/tts/assembler.py`. The `generate_full_track` signature is currently:

```python
async def generate_full_track(
    self,
    provider: BaseTTSProvider,
    segments: list[dict],
    voice_profile: dict,
    video_duration: float,
    output_path: Path,
    on_progress: callable | None = None,
    merge_sentences: bool = True,
    llm_caller: Callable | None = None,
    srt_path: Path | None = None,  # kept for back-compat; ignored
    playback_speed: float | None = None,
    video_id: str | None = None,
    language: str | None = None,
    provider_name: str | None = None,
    underlay_db: float | None = None,  # kept for back-compat; no longer used
    version: str = "draft",
) -> tuple[Path, list[dict]]:
```

Add `enable_shortening: bool = True` after `version`:

```python
    version: str = "draft",
    enable_shortening: bool = True,
) -> tuple[Path, list[dict]]:
```

Find the log line near the top of the function body that mentions `version` (search for `Generating dub for version`). Extend it to include the shortening state:

```python
logger.info(
    f"Generating dub for version={version} "
    f"shortening={'on' if enable_shortening else 'off'}"
)
```

If the existing log line is structured differently, append `shortening=...` to whatever message exists — the assertion in the manual smoke test reads this line.

Find the Stage 3 call to `_apply_shortening` (search for `await self._apply_shortening(`). Wrap it in the `enable_shortening` check:

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
    # effective_speed is still the only timing nudge they get.
    for sp in dub_plan.sentences:
        if sp.shorten_pct < 1.0:
            sp.needs_review = True
            sp.reason = "shorten_disabled"
```

The exact kwargs in the `_apply_shortening(...)` call match what's currently there — don't change them, just wrap.

- [ ] **Step 1.4: Run — confirm the two new tests pass**

Run: `python -m pytest tests/test_tts.py::TestShorteningToggle -v 2>&1 | tail -10`

Expected: 2 passed.

- [ ] **Step 1.5: Add `enable_shortening` to `run_tts_track` in `src/tts/runner.py`**

`run_tts_track` signature has `version: str = "draft"` around line 133. Add the new flag right after it:

```python
    version: str = "draft",
    enable_shortening: bool = True,
```

Find where `run_tts_track` invokes `assembler.generate_full_track(...)`. Add `enable_shortening=enable_shortening` to the kwargs passed in (alongside the existing `version=version`).

- [ ] **Step 1.6: Add `enable_shortening` to `run_tts` in `src/api/task_manager.py`**

`run_tts` signature has `version: str = "draft"` around line 681. Add right after:

```python
    version: str = "draft",
    enable_shortening: bool = True,
```

Find where `run_tts` invokes `run_tts_track(...)` (search for `run_tts_track(` in the file). Forward the new flag:

```python
    enable_shortening=enable_shortening,
```

- [ ] **Step 1.7: Add `enable_shortening` field to `TTSRequest` in `src/api/models.py`**

Locate the `TTSRequest` class around line 232. Add a new field (place it near `version: str = "draft"` if that field already exists in the class; otherwise put it next to `playback_speed`):

```python
class TTSRequest(BaseModel):
    # ...existing fields...
    enable_shortening: bool = True
```

- [ ] **Step 1.8: Forward the field in `src/api/routers/tts.py`**

Open `src/api/routers/tts.py` and find the `start_tts` (or similarly-named) handler that calls `tm.run_tts(...)`. Add `enable_shortening=request.enable_shortening` to the kwargs passed in:

```python
task._asyncio_task = asyncio.create_task(
    tm.run_tts(
        task.task_id,
        request.video_id,
        # ...existing args including version...
        version=request.version,
        enable_shortening=request.enable_shortening,
    )
)
```

The exact argument list depends on whether `run_tts` uses positional or keyword args at the call site — match the existing style.

- [ ] **Step 1.9: Run the full BE suite**

Run: `python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10`

Expected: green (the new 2 tests + all prior).

Then lint:

`ruff check src/api/models.py src/api/routers/tts.py src/api/task_manager.py src/tts/runner.py src/tts/assembler.py tests/test_tts.py 2>&1 | tail -5`

Expected: no new errors.

- [ ] **Step 1.10: Commit**

```bash
git add src/api/models.py src/api/routers/tts.py src/api/task_manager.py src/tts/runner.py src/tts/assembler.py tests/test_tts.py
git commit -m "feat(tts): enable_shortening flag gates _apply_shortening

POST /api/tts accepts enable_shortening: bool = True. The flag threads
through run_tts → run_tts_track → generate_full_track and gates the
call to _apply_shortening. When False, planner-flagged sentences get
needs_review=True with reason='shorten_disabled' so the per-sentence
merged.json documents why a clip might overrun.

Stage 0 (LLM sentence merging) runs in both modes — the toggle only
controls Stage 3 (per-sentence text compression). The pipeline path
keeps the default True so CLI behavior is unchanged.

Two new tests in TestShorteningToggle verify the gate: one for the
disabled path (assert _apply_shortening not awaited, translator
untouched) and one for the enabled path (assert awaited once)."
```

---

### Task 2: FE — `postTTS` signature + VideoDetail state and persistence

Thread the flag through the FE client and the page-level state. DubTab integration (the actual checkbox UI) lands in Task 3 so this commit is mechanical and reviewable.

**Files:**
- Modify: `ui-app/src/api/client.ts`
- Modify: `ui-app/src/pages/VideoDetail.tsx`

- [ ] **Step 2.1: Add `shortenToFit` parameter to `postTTS`**

In `ui-app/src/api/client.ts`, locate `postTTS` (around line 286-311). The current signature ends with `version: string = 'draft'` around line 296. Add the new parameter right after `version`:

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
      video_id: videoId,
      language,
      provider,
      voice,
      version,
      enable_shortening: shortenToFit,
      api_key: apiKey ?? null,
      llm_api_key: llmApiKey ?? null,
      llm_backend: llmBackend ?? null,
      playback_speed: playbackSpeed ?? null,
      underlay_db: underlayDb ?? null,
    }),
  });
}
```

The body field is `enable_shortening` (snake_case BE field name); the FE-side argument is `shortenToFit` (semantic name). The default `true` keeps existing call sites working without change.

- [ ] **Step 2.2: Add `enableShortening` state + persistence in VideoDetail**

In `ui-app/src/pages/VideoDetail.tsx`, find the existing TTS state declarations (search for `ttsPlaybackSpeed` or `tts_playback_speed`). Add the new state next to them, mirroring the same persistence pattern:

```tsx
const [enableShortening, setEnableShortening] = useState<boolean>(() => {
  const stored = storageGet('tts_enable_shortening');
  return stored === null ? true : stored === 'true';
});

useEffect(() => {
  storageSet('tts_enable_shortening', String(enableShortening));
}, [enableShortening]);
```

`storageGet` and `storageSet` are already imported in this file (they're used for `tts_playback_speed`, etc.). If they aren't in scope yet, add them to the existing import line.

- [ ] **Step 2.3: Update the `postTTS` call site**

Find where `postTTS(...)` is called in `VideoDetail.tsx` (search for `postTTS(`). Add `enableShortening` as the 6th positional argument (right after `selectedVersion`):

```tsx
postTTS(
  videoId,
  ttsLanguage,
  selectedTtsProvider,
  voiceForRequest,
  selectedVersion,
  enableShortening,
  ttsApiKey || undefined,
  llmApiKey || undefined,
  llmBackend || undefined,
  ttsPlaybackSpeed,
  ttsUnderlayDb,
);
```

The exact arg list depends on what the current call site uses — preserve whatever args were there but slot `enableShortening` at position 6.

- [ ] **Step 2.4: Pass `enableShortening` and its setter into `<DubTab>`**

Find where `<DubTab>` is rendered in `VideoDetail.tsx`. Add two props (DubTab won't consume them yet — that's Task 3 — but adding them now keeps Task 3's diff focused on the checkbox UI):

```tsx
<DubTab
  /* ...existing props... */
  enableShortening={enableShortening}
  onChangeEnableShortening={setEnableShortening}
/>
```

If TypeScript complains because DubTab's Props don't yet declare those fields, add them as optional in the DubTab Props interface for this commit:

```ts
// in DubTab.tsx temporarily:
enableShortening?: boolean;
onChangeEnableShortening?: (next: boolean) => void;
```

Task 3 will make them required when the checkbox starts consuming them.

- [ ] **Step 2.5: Run FE tests + build**

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: all tests still pass (no new tests yet); build succeeds (the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may persist — not introduced by this work).

- [ ] **Step 2.6: Commit**

```bash
git add ui-app/src/api/client.ts ui-app/src/pages/VideoDetail.tsx ui-app/src/pages/videoDetail/DubTab.tsx
git commit -m "feat(fe): thread enableShortening through postTTS and VideoDetail

postTTS gains shortenToFit: boolean = true at position 6 (right after
version). The JSON body carries it as the BE-style enable_shortening
field. Existing callers default to shortening on.

VideoDetail owns the enableShortening state, mirroring the same
localStorage persistence pattern as tts_playback_speed (storage key:
tts_enable_shortening). The state + setter are passed into DubTab as
optional props for now — the checkbox UI lands in the next commit."
```

---

### Task 3: FE — DubTab checkbox + vitest

Render the checkbox between the Playback Speed and Underlay sections. Add one vitest covering the controlled-prop behavior.

**Files:**
- Modify: `ui-app/src/pages/videoDetail/DubTab.tsx`
- Create: `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx`

- [ ] **Step 3.1: Write the failing test**

Create `ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DubTab from '../DubTab';

function renderDubTab(overrides: Partial<React.ComponentProps<typeof DubTab>> = {}) {
  const props = {
    // Required props — fill with minimal values so the component mounts.
    // Mirror the shape used at the VideoDetail call site.
    selectedProvider: 'google',
    selectedVoiceId: '',
    selectedLanguage: 'vi',
    ttsVoices: [],
    ttsProviders: [],
    onChangeProvider: vi.fn(),
    onChangeVoice: vi.fn(),
    onChangeLanguage: vi.fn(),
    playbackSpeed: 1.5,
    onChangePlaybackSpeed: vi.fn(),
    underlayDb: -12,
    onChangeUnderlayDb: vi.fn(),
    isGeneratingTts: false,
    ttsProgress: 0,
    ttsGenerated: false,
    ttsError: '',
    ttsList: [],
    onReloadTtsList: vi.fn(),
    onGenerate: vi.fn(),
    versions: [],
    selectedVersion: 'draft',
    onVersionChange: vi.fn(),
    enableShortening: true,
    onChangeEnableShortening: vi.fn(),
    ...overrides,
  };
  return { ...render(<DubTab {...(props as React.ComponentProps<typeof DubTab>)} />), props };
}

describe('DubTab — shorten-to-fit checkbox', () => {
  it('reflects the enableShortening prop on render', () => {
    renderDubTab({ enableShortening: false });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i }) as HTMLInputElement;
    expect(box.checked).toBe(false);
  });

  it('renders checked when enableShortening is true', () => {
    renderDubTab({ enableShortening: true });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i }) as HTMLInputElement;
    expect(box.checked).toBe(true);
  });

  it('calls onChangeEnableShortening with the new boolean on click', () => {
    const { props } = renderDubTab({ enableShortening: true });
    const box = screen.getByRole('checkbox', { name: /shorten dub to fit/i });
    fireEvent.click(box);
    expect(props.onChangeEnableShortening).toHaveBeenCalledWith(false);
  });
});
```

The `renderDubTab` helper's prop block is approximate — the actual DubTab Props interface is the source of truth. If TypeScript complains during step 3.2 about missing or surplus mock props, adjust the helper to match the real interface (don't change real props to fit the test).

- [ ] **Step 3.2: Run — confirm fail**

```bash
cd ui-app && npx vitest run src/pages/videoDetail/__tests__/DubTab.test.tsx 2>&1 | tail -10
```

Expected: 3 FAIL with `Unable to find an accessible element with the role "checkbox" and name /shorten dub to fit/i`. The checkbox doesn't exist yet.

- [ ] **Step 3.3: Make the new props required**

In `ui-app/src/pages/videoDetail/DubTab.tsx`, find the Props interface where Task 2 added the optional fields. Drop the `?`:

```ts
enableShortening: boolean;
onChangeEnableShortening: (next: boolean) => void;
```

- [ ] **Step 3.4: Destructure the new props in the component body**

Find the existing destructuring block (around line 63-66, where `playbackSpeed` and `underlayDb` are pulled). Add the two new props alongside:

```ts
const {
  /* ...existing destructured props... */
  playbackSpeed, onChangePlaybackSpeed,
  enableShortening, onChangeEnableShortening,
  underlayDb, onChangeUnderlayDb,
  /* ...rest... */
} = props;
```

- [ ] **Step 3.5: Render the checkbox between Playback Speed and Underlay**

Locate the Playback Speed section (search for `value={playbackSpeed}`; around line 208) and the Underlay section (search for `Original underlay`; around line 225). Add this JSX block between them:

```tsx
{/* Shorten-to-fit toggle */}
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

The label wraps the input so clicking the text also toggles the box. `accent-primary` ties the checkbox tint to the existing theme color used by sliders.

- [ ] **Step 3.6: Run the new tests + the FE suite**

```bash
cd ui-app && npx vitest run src/pages/videoDetail/__tests__/DubTab.test.tsx 2>&1 | tail -10
```

Expected: 3 passed.

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
```

Expected: every prior FE test still passes, plus the 3 new ones.

```bash
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: build succeeds (modulo the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx).

- [ ] **Step 3.7: Commit**

```bash
git add ui-app/src/pages/videoDetail/DubTab.tsx ui-app/src/pages/videoDetail/__tests__/DubTab.test.tsx
git commit -m "feat(dub): 'Shorten dub to fit timeline' checkbox in DubTab

A checkbox between Playback Speed and Underlay controls. The label
wraps the input so the text toggles too; accent-primary matches the
theme. Sublabel explains the tradeoff: 'Uncheck to keep the original
translation — clips may overrun.'

Three vitest tests: prop-reflects-on-render (checked + unchecked), and
onChange-fires-with-the-new-boolean."
```

---

### Task 4: CHANGELOG + README rollup

Per CLAUDE.md, every commit updates `CHANGELOG.md` and the `README.md` progress section. Bundle both into one final commit on the branch.

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`

- [ ] **Step 4.1: Add CHANGELOG entry**

In `CHANGELOG.md`, find the `## [Unreleased]` section. Add a new `### Added` subsection above any existing `### Fixed` / `### Changed` blocks (or extend the existing `### Added` if it's at the top). Use this text:

```markdown
### Added
- **DubTab "Shorten dub to fit timeline" checkbox.** Lets the user disable the LLM-based per-sentence text shortening (`_apply_shortening`) when generating dubs from the per-video page. Defaults on (matches today's behavior and the pipeline default). Stage 0 (LLM sentence merging) still runs when the box is unchecked — only Stage 3 (per-sentence compression) is skipped. Sentences the planner deemed in need of shortening get flagged `needs_review=True, reason="shorten_disabled"` so the per-sentence `merged.json` documents why a clip might overrun. The state is persisted as `tts_enable_shortening` in localStorage (mirrors `tts_playback_speed`). `POST /api/tts` accepts a new `enable_shortening: bool = True` field; `postTTS` FE client gains a 6th positional `shortenToFit: boolean = true` parameter. CLI/pipeline behavior unchanged — `run_tts` defaults to `enable_shortening=True`. 2 new BE tests + 3 new FE vitest tests.
```

- [ ] **Step 4.2: Add README progress section**

In `README.md`, find the "Subtitle Versioning + Dub-Version Picker (2026-05-29)" subsection (added by the in-flight versioning work on this branch). Insert this new subsection immediately after it (before the next `---` or section break):

```markdown
### Dub-Shortening Toggle (2026-05-29)

> Bundled into PR #19 (subtitle versioning) per scope decision during brainstorming. See [`docs/superpowers/specs/2026-05-29-dub-shortening-toggle-design.md`](docs/superpowers/specs/2026-05-29-dub-shortening-toggle-design.md) and [`docs/superpowers/plans/2026-05-29-dub-shortening-toggle.md`](docs/superpowers/plans/2026-05-29-dub-shortening-toggle.md).

- [x] **Task 1** — BE plumbing + gate: `enable_shortening: bool = True` threads from `TTSRequest` → `run_tts` → `run_tts_track` → `generate_full_track`; `_apply_shortening` is skipped when disabled and planner-flagged sentences get `reason="shorten_disabled"`. 2 new tests in `TestShorteningToggle`.
- [x] **Task 2** — FE plumbing: `postTTS` gains `shortenToFit` as the 6th positional arg; VideoDetail owns the `enableShortening` state with localStorage persistence.
- [x] **Task 3** — DubTab "Shorten dub to fit timeline" checkbox between Playback Speed and Underlay (3 vitest).
- [x] **Task 4** — CHANGELOG + README updates.

**Not in this PR:** standalone text→voice tool (sub-project 3 of the dub-sync rebuild) — separate spec + PR.
```

- [ ] **Step 4.3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(dub): CHANGELOG + README rollup for shorten-to-fit toggle"
```

---

## Final verification (run before reporting DONE)

- [ ] **Step F.1: All BE tests pass**

```bash
python -m pytest tests/ -x --ignore=tests/test_pipeline_cancel_integration.py 2>&1 | tail -10
```

Expected: green, 2 more tests than the prior baseline.

- [ ] **Step F.2: All FE tests pass**

```bash
cd ui-app && npx vitest run 2>&1 | tail -10
```

Expected: green, 3 more tests than the prior baseline.

- [ ] **Step F.3: FE build is clean**

```bash
cd ui-app && npm run build 2>&1 | tail -10
```

Expected: succeeds (the two pre-existing errors in Timeline.tsx and DownloadTranscribe.tsx may persist — not in scope).

- [ ] **Step F.4: BE lint is clean**

```bash
ruff check src/api/models.py src/api/routers/tts.py src/api/task_manager.py src/tts/runner.py src/tts/assembler.py tests/test_tts.py 2>&1 | tail -5
```

Expected: no new errors on the touched files.

- [ ] **Step F.5: Manual smoke (after PR merge)**

1. Open a video → Dub tab → "Shorten dub to fit timeline" checkbox is **checked** by default on first visit; reflects the last value on subsequent visits.
2. Uncheck → reload the page → checkbox stays unchecked (localStorage round-trip).
3. With checkbox **checked**, generate a dub → confirm the existing iterative shortening behavior (clips that would overrun get LLM-shortened text). Inspect `data/tts/{id}_*_*.merged.json` — overflowing groups should have `was_shortened=true`.
4. With checkbox **unchecked**, regenerate the dub → inspect the same `merged.json` — planner-flagged sentences should have `was_shortened=false`, `needs_review=true`, `reason="shorten_disabled"`. The corresponding clips retain the original text. If a clip overruns its source span at the chosen playback speed, expect a real timing overrun in the WAV.
5. Pipeline (CLI `python -m src process …`) → check the dub log line; should read `shortening=on` (default `enable_shortening=True`).

---

## Self-review checklist (for the implementer)

- [ ] Spec coverage: each spec requirement maps to a task — `TTSRequest` field (Task 1), task_manager (Task 1), runner (Task 1), assembler gate (Task 1), BE test (Task 1), `postTTS` (Task 2), VideoDetail state + persistence (Task 2), DubTab checkbox + FE test (Task 3), CHANGELOG/README (Task 4).
- [ ] No "TBD" / "implement later" / "similar to Task N" in any step.
- [ ] Name consistency: `enable_shortening` (BE field, Python param), `enableShortening` (FE state + prop), `shortenToFit` (FE API param). These three names refer to the same boolean.
- [ ] localStorage key is `tts_enable_shortening` everywhere it's read or written.
- [ ] No AI-attribution strings in any commit message.
- [ ] Branch stays `feature/subtitle-versioning`; no new branches created.
