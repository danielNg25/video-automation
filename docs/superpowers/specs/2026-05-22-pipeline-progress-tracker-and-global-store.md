# Pipeline Progress: Per-Stage Tracker + Global Status Store

**Status:** Draft — ready for implementation planning
**Date:** 2026-05-22
**Scope:** `src/api/routers/pipeline.py` (GET endpoint), `ui-app/src/lib/pipelineStatus.tsx` (new context), `ui-app/src/components/PipelineStageTracker.tsx` (new component), `ui-app/src/pages/DownloadTranscribe.tsx` (replace local state with the context), `ui-app/src/App.tsx` or root (wrap with provider).

## Problem

Two user-reported issues with the pipeline-running UX after the recent compact-form redesign.

**1. Progress bar is inaccurate / not informative.** The current single bar shows a 0–100% percent derived from the overall pipeline `progress` (`src/pipeline.py::emit()` maps each stage into a hardcoded sub-range of 0..1). The mapping is uneven (e.g. TTS is mapped to 0.60..0.70, only 10% of the bar) — and the bar is silent about what's actually happening within each stage. The user has no idea OCR is the slow stage because the bar appears stuck. There's no way to tell which step is current versus which are done, except by reading a single line of text below the bar.

**2. Navigating away from the pipeline page and back takes >10 seconds to show the running pipeline.** The current `DownloadTranscribe.tsx` owns the pipeline state locally (`isPipeline`, `pipelineProgress`, `pipelineMessage`, `pipelineStage`). When the user navigates away, the component unmounts and the state is lost. On return, the mount effect reads `sessionStorage`, fetches `/api/pipeline/{task_id}`, and only after that fetch resolves does it set `isPipeline = true` (which is what makes the progress strip render). The progress strip is therefore invisible during the entire fetch round-trip. Even when fetches are fast (~100ms), the perception is bad. When fetches are slow (~10s, observed), the experience is broken.

## Goals

In priority order:

1. **Per-stage visibility.** Show ALL pipeline stages in a stacked tracker, with each stage's status (done / running / pending) and its own progress bar. The user can see at a glance "OCR is running, 65% through" rather than "the overall bar is at 35%."
2. **Instant restore on navigate-back.** When returning to the pipeline page during a run, the per-stage tracker renders immediately from in-memory state — no fetch wait.
3. **Backward compatible.** The existing single `progress` field on the GET endpoint keeps working for any other UI surface or external consumer that reads it (Dashboard / VideoCard / etc.).
4. **Minimal backend change.** The existing `emit(stage, progress, message)` and `PipelineState` mechanics stay; we add ONE derived field on the GET response.

## Non-goals

- Changing the stage ranges in `pipeline.py::emit()`. Once the UI shows per-stage progress, the overall mapping no longer matters for the running-UX (the bar-per-stage replaces the one combined bar).
- Adding stage-elapsed-time display. The backend tracks `timestamps` per stage but surfacing them is YAGNI for v1.
- SSE / WebSocket-based progress streaming. Current 2s polling is acceptable now that the strip renders instantly on mount.
- Batch-mode tracker. Batch already shows a different "N/M done" summary in the URL card. We keep batch mode as-is; the new per-stage tracker is for single-URL pipeline runs only.

## Architecture

```
                         ┌────────────────────────────────────────┐
                         │  PipelineStatusProvider (app-level)    │
                         │   - owns polling loop                  │
                         │   - holds PipelineStatus state         │
                         │   - persists lastKnown to sessionStg   │
                         └─────┬─────────────────────────┬────────┘
                               │                         │
                  startPolling()/stopPolling()      status (read-only)
                               │                         │
                               ▼                         ▼
                  ┌────────────────────────┐   ┌────────────────────────┐
                  │ DownloadTranscribe.tsx │   │ PipelineStageTracker   │
                  │  - calls start on Run  │   │  - 5 rows (one per     │
                  │  - renders tracker     │   │    stage)              │
                  └────────────────────────┘   │  - reads status.current│
                                                │    Stage, completed   │
                                                │    Stages, stageProgress│
                                                └────────────────────────┘
```

Top-level provider wraps the app router. The provider keeps the polling loop alive across page navigations (it doesn't unmount when the user leaves DownloadTranscribe). The provider also persists `lastKnown` (currentStage, stageProgress, completedStages, message) to sessionStorage on every status update — so on a hard refresh the strip can render from sessionStorage instantly while the reconnect fetch runs in the background.

## Backend changes

### `src/api/routers/pipeline.py::get_pipeline_status`

The response already includes:

```json
{
  "task_id": ...,
  "status": ...,
  "current_stage": "tts",
  "progress": 0.65,
  "message": "...",
  "completed_stages": ["download", "transcribe", "translate"],
  ...
}
```

Add a derived `stage_progress` field. Mapping:

```python
STAGE_RANGES = {
    "download":   (0.00, 0.20),
    "transcribe": (0.20, 0.45),
    "translate":  (0.45, 0.60),
    "tts":        (0.60, 0.70),
    "process":    (0.70, 1.00),
}

def _stage_progress(current_stage: str, overall_progress: float) -> float:
    """Recover per-stage 0..1 progress from overall progress + current stage.
    Returns 0.0 if the current stage isn't in STAGE_RANGES (e.g. 'skip')."""
    if current_stage not in STAGE_RANGES:
        return 0.0
    lo, hi = STAGE_RANGES[current_stage]
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (overall_progress - lo) / (hi - lo)))
```

In the GET handler, set:

```python
result["stage_progress"] = _stage_progress(
    result["current_stage"], result["progress"]
)
```

This adds one float to the response and zero impact on the polling cost. The existing `progress` and `current_stage` fields stay unchanged.

**Why derive instead of plumb-through?** The emit() callsites in `src/pipeline.py` compute overall progress from per-stage progress (e.g. `pct = 0.60 + (current/total) * 0.10`). The reverse mapping `(progress - lo) / (hi - lo)` is exact up to float precision — no information lost. We avoid threading a new arg through every emit() call site. If the stage ranges ever change in `pipeline.py`, the same constants need to change in `STAGE_RANGES` in `pipeline.py` (router). Acceptable single-source pain.

To avoid drift, define `STAGE_RANGES` in ONE place — `src/pipeline.py` — and import into the router.

### `src/api/routers/pipeline.py` for batch tasks

Batch task children are already aggregated into `result["children"]`. Each child gets the same `stage_progress` derivation. Same helper, applied per child.

## Frontend changes

### New: `ui-app/src/lib/pipelineStatus.tsx`

A React Context that owns:
- `task` state shape (taskId, mode, status, currentStage, stageProgress, completedStages, message, batch fields).
- The polling interval (continues across navigations).
- `startPolling(taskId, mode)` and `stopPolling()` methods exposed via hook.
- sessionStorage write on every status change (so a hard refresh restores instantly).

```ts
type PipelineStageName = 'download' | 'transcribe' | 'translate' | 'tts' | 'process';

type PipelineStatus = {
  taskId: string | null;
  mode: 'single' | 'batch' | null;
  status: 'idle' | 'running' | 'completed' | 'failed';
  currentStage: PipelineStageName | '';
  stageProgress: number;        // 0..1, per-current-stage
  completedStages: PipelineStageName[];
  progress: number;             // 0..1 overall (kept for back-compat consumers)
  message: string;
  videoId?: string | null;
  // Batch only
  children?: Array<{
    videoId: string;
    status: string;
    currentStage: string;
    progress: number;
    message: string;
    error: string | null;
  }>;
  batchTotal?: number;
  batchCompleted?: number;
  error?: string | null;
};
```

Storage key: `pipeline_active_task` (already used by DownloadTranscribe). New payload shape (additive):

```json
{
  "taskId": "...",
  "mode": "single",
  "lastKnown": {
    "currentStage": "tts",
    "stageProgress": 0.42,
    "completedStages": ["download", "transcribe", "translate"],
    "progress": 0.64,
    "message": "..."
  }
}
```

On `PipelineStatusProvider` mount:
1. Read sessionStorage. If a `pipeline_active_task` exists with `lastKnown`, immediately populate `status` with `lastKnown` values (optimistic restore — no fetch wait).
2. Fire a single reconnect fetch (`GET /api/pipeline/{taskId}`). If response is `running`, start the polling loop. If `completed`/`failed`, clear sessionStorage and mark status appropriately.

On status update (every poll response):
- Update React state.
- Persist `lastKnown` to sessionStorage.
- If `status` is `completed` or `failed`, stop polling and clear sessionStorage.

### New: `ui-app/src/components/PipelineStageTracker.tsx`

Pure presentational component, props = `{ status: PipelineStatus }`. Renders 5 stage rows (or 4 if translation is skipped — see below):

```tsx
const STAGES: { id: PipelineStageName; label: string }[] = [
  { id: 'download',   label: 'Download' },
  { id: 'transcribe', label: 'Transcribe (OCR)' },
  { id: 'translate',  label: 'Translate' },
  { id: 'tts',        label: 'TTS Dubbing' },
  { id: 'process',    label: 'Process & Burn' },
];
```

Per row:
- **Status icon (left, 20×20)**:
  - Done (in `completedStages`): green check ✓
  - Current (`currentStage === id`): primary-colored spinner
  - Pending (else): empty circle ○ with dim border
- **Stage name** (text-sm, primary text color for current, default for others, dim for pending)
- **Progress bar (right, fills available width)**:
  - Done: full (100%, dim color)
  - Current: animated bar at `stageProgress * 100`% (primary color, transitions duration-300)
  - Pending: empty (0%)
- **Message** (under the bar, only when current): truncated, mono small font

Layout:
```
[●] Translate         [████████░░░░] 42%
                      Translating segment 12/47 (DeepSeek)
```

Translation-skipped detection: if the user didn't select a translation profile (`translate_profile` was null on the original request), we can't know that from the GET response alone. **Two simple approaches:**

- **A. Show "Skipped" if currentStage advances past translate without translate appearing in completedStages.** I.e. when `completedStages.includes('transcribe') && currentStage !== 'translate' && !completedStages.includes('translate')` → render translate as `Skipped` (dim, slashed-out label).
- **B. Always show all 5 stages; pending stages that never run just stay "○ pending" until pipeline completes, then become "○ skipped" retroactively.**

Pick A — clearer signaling during the run.

### Modified: `ui-app/src/App.tsx` (or root component)

Wrap the existing router/layout in `<PipelineStatusProvider>` so the context is available app-wide.

```tsx
<PipelineStatusProvider>
  <Layout>
    <Routes>...</Routes>
  </Layout>
</PipelineStatusProvider>
```

### Modified: `ui-app/src/pages/DownloadTranscribe.tsx`

Substantial reduction of local state. Replace the locally-managed pipeline state + polling with the context:

```tsx
const { status, startPolling } = usePipelineStatus();
const isPipeline = status.status === 'running';
```

Delete:
- `const [pipelineStage, setPipelineStage] = useState('');`
- `const [pipelineProgress, setPipelineProgress] = useState(0);`
- `const [pipelineMessage, setPipelineMessage] = useState('');`
- `const [isPipeline, setIsPipeline] = useState(false);`
- `const pollRef = useRef(...)`, `stopPolling`, `startPolling` (the local versions).
- The mount-effect block that handles sessionStorage reconnect (the context owns this now).

Replace `handlePipeline`'s post-POST code:
```tsx
// was:
saveActiveTask(task_id, 'single');
startPolling(task_id, 'single');
// becomes:
startPolling(task_id, 'single');   // context handles sessionStorage internally
```

Replace the JSX progress strip:
```tsx
// was: the slim single-bar strip
{isPipeline && !isBatchMode && (
  <div ...>{stage + percent + message}</div>
)}
// becomes:
{isPipeline && status.mode === 'single' && (
  <div className="bg-surface-container-low rounded-xl p-5">
    <PipelineStageTracker status={status} />
  </div>
)}
```

Batch mode keeps its existing UI (URL card's batch progress bar). No change.

### Other consumers

The Dashboard page may also poll `/api/pipeline/{task_id}` for active tasks. If so, it can also use `usePipelineStatus()` to read the status without owning a polling loop. **Out of scope for this spec.** Only Dashboard/etc. that opt in get the benefit; existing local-polling consumers continue working unchanged since the GET response is additive.

## Data flow

```
User clicks Run Pipeline (DownloadTranscribe)
  → POST /api/pipeline/full
  → response { task_id }
  → context.startPolling(task_id, 'single')
       → context starts setInterval(poll, 2000)
       → context persists { taskId, mode, lastKnown: {} } to sessionStorage
       → first poll fires immediately
  → DownloadTranscribe re-renders with status.status === 'running'
  → PipelineStageTracker shows download spinner + 0% bar

[poll cycle, every 2s]
  → GET /api/pipeline/{task_id}
  → response { current_stage, progress, stage_progress, completed_stages, message }
  → context updates status
  → context persists lastKnown to sessionStorage
  → PipelineStageTracker re-renders

User navigates to Settings, then back to Pipeline
  → DownloadTranscribe unmounts; context stays mounted at app root
  → polling continues uninterrupted
  → DownloadTranscribe remounts, reads status from context, renders instantly

Hard browser refresh
  → context mounts, reads sessionStorage, primes status from lastKnown
  → PipelineStageTracker renders immediately from primed state
  → Reconnect fetch fires async; updates status when resolved
  → Polling resumes

Pipeline completes (poll response status === 'completed')
  → context stops polling
  → context clears sessionStorage
  → context sets status.status = 'completed'
  → DownloadTranscribe handles the completion (navigate to video, refresh library, etc.)
```

## Tests

### Backend

`tests/test_pipeline_endpoints.py` (new file or add to existing test_pipeline.py):

```python
def test_stage_progress_derivation():
    """Given a current stage and overall progress, _stage_progress recovers
    the per-stage 0..1 value."""
    from src.api.routers.pipeline import _stage_progress

    # Transcribe range is (0.20, 0.45); overall 0.325 → stage 0.5
    assert abs(_stage_progress("transcribe", 0.325) - 0.5) < 1e-6

    # TTS range is (0.60, 0.70); overall 0.65 → stage 0.5
    assert abs(_stage_progress("tts", 0.65) - 0.5) < 1e-6

    # Clamped to [0, 1]
    assert _stage_progress("download", 0.50) == 1.0
    assert _stage_progress("process", 0.50) == 0.0

    # Unknown stage → 0.0 (e.g. 'skip', empty string)
    assert _stage_progress("skip", 0.5) == 0.0
    assert _stage_progress("", 0.5) == 0.0


def test_get_pipeline_status_includes_stage_progress(tmp_path, monkeypatch):
    """The GET endpoint surfaces stage_progress alongside the existing progress."""
    # Wire up a TestClient with a pre-existing task in the manager.
    # (Mirror tests/test_srt_endpoints.py::_make_client pattern.)
    # Set task.progress = 0.325, task.current_stage = "transcribe".
    # GET /api/pipeline/{task_id} → response includes stage_progress ≈ 0.5
```

### Frontend

No automated UI tests in this repo. Manual QA in the implementation plan's final task.

## Backward compatibility

The GET response gains `stage_progress`. Existing consumers that read `progress` and `current_stage` keep working unchanged.

The sessionStorage payload shape changes: from `{ taskId, mode }` to `{ taskId, mode, lastKnown: {...} }`. Old payload (missing `lastKnown`) gracefully degrades — the provider treats missing `lastKnown` as "no optimistic restore" and falls through to the reconnect fetch (current behavior). One-line guard in the parse step:

```tsx
const lastKnown = saved.lastKnown ?? null;
if (lastKnown) {
  // Optimistic restore
} else {
  // Reconnect fetch only
}
```

## Migration

- No backend migration. New field is additive.
- Old sessionStorage entries from before this change keep working (just no optimistic restore).
- No data files touched.
- No new dependencies.

## Open Questions

None at draft time. Translation-skipped UI behavior was decided above (Option A — show "Skipped" when currentStage moves past translate without it being in completedStages). Per-stage elapsed time is explicitly out of scope.
