# Pipeline Progress Tracker + Global Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single 0-100% bar on the running-pipeline UI with a per-stage tracker (one row per pipeline stage), and lift pipeline status to an app-level React Context so it survives page navigation and renders instantly on return.

**Architecture:** Backend exposes one derived `stage_progress` field on the `GET /api/pipeline/{task_id}` response, computed from the existing overall `progress` + `current_stage` via a `STAGE_RANGES` constant (declared canonically in `src/pipeline.py`). Frontend introduces a `PipelineStatusProvider` React Context that owns the polling loop and lives at the app root; `DownloadTranscribe.tsx` consumes the context instead of owning local pipeline state. A new `PipelineStageTracker` component renders five status rows from the context's status.

**Tech Stack:** Python 3.11, pytest with pytest-asyncio (auto mode), ruff, FastAPI, React 19, TypeScript, Tailwind CSS 4.

**Source spec:** [docs/superpowers/specs/2026-05-22-pipeline-progress-tracker-and-global-store.md](../specs/2026-05-22-pipeline-progress-tracker-and-global-store.md). All design decisions are locked in there.

**Branch:** `feature/phase4-dubbing-redesign-spec` (HEAD = 01889ad — spec already committed).

---

## File Structure

**Files to create:**

- `ui-app/src/lib/pipelineStatus.tsx` — `PipelineStatus` type, `PipelineStatusProvider`, `usePipelineStatus()` hook. Owns the polling loop and sessionStorage persistence.
- `ui-app/src/components/PipelineStageTracker.tsx` — pure presentational component that renders 5 stage rows from a `PipelineStatus` prop.

**Files to modify:**

- `src/pipeline.py` — add `STAGE_RANGES` constant near the top of the file. Keep `emit()` unchanged (the numeric literals already in use match `STAGE_RANGES`).
- `src/api/routers/pipeline.py` — add `_stage_progress(current_stage, overall_progress)` helper. Include `stage_progress` in the GET response (both single and batch-child paths).
- `tests/test_pipeline_endpoints.py` (new test file, or extend `tests/test_pipeline.py` if it exists) — unit test for `_stage_progress` + TestClient test for the GET endpoint.
- `ui-app/src/App.tsx` — wrap the router tree in `<PipelineStatusProvider>`.
- `ui-app/src/pages/DownloadTranscribe.tsx` — delete local pipeline state, local polling, local mount-effect reconnect. Use `usePipelineStatus()` hook. Replace the progress strip JSX with `<PipelineStageTracker status={status} />`.
- `CHANGELOG.md` — `### Added` / `### Changed` entries per task.

---

## Task 1: Backend — STAGE_RANGES + stage_progress derivation

**Files:**
- Modify: `src/pipeline.py` (add constant)
- Modify: `src/api/routers/pipeline.py` (helper + GET field)
- Modify: `tests/test_pipeline.py` (or create `tests/test_pipeline_endpoints.py`)

- [ ] **Step 1: Confirm current emit ranges in `src/pipeline.py`**

```bash
grep -n "emit(\"\|^    def emit" src/pipeline.py | head -20
```

You should see emit() calls at boundaries:
- `emit("download", 0.20, ...)` — end of download
- `emit("transcribe", 0.20, ...)` and `emit("transcribe", 0.45, ...)` — bounds
- `emit("translate", 0.45, ...)` and `emit("translate", 0.60, ...)` — bounds
- `emit("tts", 0.60, ...)` and `emit("tts", 0.70, ...)` — bounds
- `emit("process", 1.0, ...)` — end (process spans 0.70 → 1.00)

These confirm the canonical ranges:
```
download:   0.00 → 0.20
transcribe: 0.20 → 0.45
translate:  0.45 → 0.60
tts:        0.60 → 0.70
process:    0.70 → 1.00
```

- [ ] **Step 2: Add `STAGE_RANGES` constant to `src/pipeline.py`**

Add this near the top of `src/pipeline.py`, just after the imports and before any class definitions:

```python
# Per-stage progress ranges in the overall 0..1 pipeline.progress space.
# These are the canonical values that emit() callsites use as boundaries.
# Consumers that need to recover per-stage 0..1 progress from overall
# progress can use these:
#   stage_progress = (overall - lo) / (hi - lo)
STAGE_RANGES: dict[str, tuple[float, float]] = {
    "download":   (0.00, 0.20),
    "transcribe": (0.20, 0.45),
    "translate":  (0.45, 0.60),
    "tts":        (0.60, 0.70),
    "process":    (0.70, 1.00),
}
```

Do NOT change emit() or its callsites — STAGE_RANGES is purely declarative documentation that consumers can import.

- [ ] **Step 3: Write the failing tests**

Create `tests/test_pipeline_endpoints.py` (NEW file):

```python
"""Tests for /api/pipeline/{task_id} stage_progress derivation."""
from __future__ import annotations

from fastapi.testclient import TestClient


def _make_client(monkeypatch, tmp_path):
    """Build a TestClient and inject a stub task into the task manager."""
    monkeypatch.chdir(tmp_path)
    from src.api import create_app
    from src.api.deps import get_task_manager

    app = create_app()
    tm = get_task_manager()
    # Inject a stub task — minimum fields needed for the GET handler.
    from src.api.task_manager import Task
    task = Task(task_id="t1", task_type="full_pipeline")
    task.status = "running"
    task.current_stage = "transcribe"
    task.progress = 0.325        # halfway through transcribe (0.20-0.45 range)
    task.message = "Running OCR on frame 100/200"
    task.video_id = None         # so the on-disk PipelineState enrich path is skipped
    tm.tasks["t1"] = task
    return TestClient(app)


class TestStageProgressDerivation:
    def test_transcribe_midpoint_maps_to_half(self):
        """transcribe range is (0.20, 0.45); overall 0.325 → stage 0.5."""
        from src.api.routers.pipeline import _stage_progress

        result = _stage_progress("transcribe", 0.325)
        assert abs(result - 0.5) < 1e-6

    def test_tts_midpoint_maps_to_half(self):
        """tts range is (0.60, 0.70); overall 0.65 → stage 0.5."""
        from src.api.routers.pipeline import _stage_progress

        result = _stage_progress("tts", 0.65)
        assert abs(result - 0.5) < 1e-6

    def test_overall_at_stage_lo_maps_to_zero(self):
        from src.api.routers.pipeline import _stage_progress

        assert _stage_progress("transcribe", 0.20) == 0.0

    def test_overall_at_stage_hi_maps_to_one(self):
        from src.api.routers.pipeline import _stage_progress

        assert _stage_progress("transcribe", 0.45) == 1.0

    def test_clamps_overshoot_to_one(self):
        """If overall exceeds the stage's hi (unexpected but defensive),
        the returned per-stage value clamps at 1.0."""
        from src.api.routers.pipeline import _stage_progress

        assert _stage_progress("download", 0.50) == 1.0

    def test_clamps_undershoot_to_zero(self):
        """If overall is below the stage's lo (also unexpected), clamp at 0."""
        from src.api.routers.pipeline import _stage_progress

        assert _stage_progress("process", 0.50) == 0.0

    def test_unknown_stage_returns_zero(self):
        """For stage names not in STAGE_RANGES (e.g. 'skip', empty), return 0.0."""
        from src.api.routers.pipeline import _stage_progress

        assert _stage_progress("skip", 0.5) == 0.0
        assert _stage_progress("", 0.5) == 0.0


class TestGetPipelineStatusIncludesStageProgress:
    def test_stage_progress_field_present(self, tmp_path, monkeypatch):
        client = _make_client(monkeypatch, tmp_path)
        resp = client.get("/api/pipeline/t1")
        assert resp.status_code == 200
        body = resp.json()
        assert "stage_progress" in body, f"response body missing stage_progress: {body!r}"
        # Stub task has current_stage='transcribe', progress=0.325 → stage_progress ≈ 0.5
        assert abs(body["stage_progress"] - 0.5) < 1e-6
```

If `Task` doesn't have keyword constructor args matching `(task_id=..., task_type=...)`, use whatever the actual signature is. Grep:
```bash
grep -n "class Task\|@dataclass" src/api/task_manager.py | head
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
python -m pytest tests/test_pipeline_endpoints.py -v
```

Expected: all 8 tests fail because `_stage_progress` doesn't exist and the GET response doesn't include `stage_progress`.

- [ ] **Step 5: Implement `_stage_progress` in the router**

In `src/api/routers/pipeline.py`, at the top of the file (after imports), add:

```python
from src.pipeline import STAGE_RANGES


def _stage_progress(current_stage: str, overall_progress: float) -> float:
    """Recover per-stage 0..1 progress from overall pipeline progress.

    Uses `STAGE_RANGES` (defined in src/pipeline.py) to invert emit()'s
    forward mapping (overall = lo + stage_progress * (hi - lo)).

    Returns 0.0 if the stage name isn't in STAGE_RANGES (e.g. 'skip',
    empty string, or any new stage that hasn't been registered yet).
    Clamps the result to [0.0, 1.0] in case of mild over/undershoot.
    """
    if current_stage not in STAGE_RANGES:
        return 0.0
    lo, hi = STAGE_RANGES[current_stage]
    if hi == lo:
        return 0.0
    raw = (overall_progress - lo) / (hi - lo)
    return max(0.0, min(1.0, raw))
```

- [ ] **Step 6: Add `stage_progress` to the GET response**

In `src/api/routers/pipeline.py`, find the existing `get_pipeline_status` handler (around line 487-535). After the existing `result = { ... }` dict is built and AFTER any on-disk PipelineState enrichment (around line 518), but BEFORE the batch-children aggregation block, add:

```python
    # Derived per-stage progress (0..1 within the current stage's range).
    result["stage_progress"] = _stage_progress(
        result.get("current_stage", "") or "",
        float(result.get("progress") or 0.0),
    )
```

For batch tasks, the existing code populates `result["children"]` with per-video state. After each child dict is built, also set `child["stage_progress"]`. Find the existing children-aggregation block (search for `result["children"]` or `for child in ...`):

```bash
grep -n "result\[\"children\"\]\|child_status\|for state in\|batch_pipeline" src/api/routers/pipeline.py | head
```

For each child dict where `current_stage` and `progress` are populated, add:

```python
        child["stage_progress"] = _stage_progress(
            child.get("current_stage", "") or "",
            float(child.get("progress") or 0.0),
        )
```

- [ ] **Step 7: Run tests to verify they pass**

```bash
python -m pytest tests/test_pipeline_endpoints.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 8: Run the full test suite**

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all pre-existing tests still pass.

- [ ] **Step 9: Lint**

```bash
ruff check src/pipeline.py src/api/routers/pipeline.py tests/test_pipeline_endpoints.py
```

Expected: no NEW errors. Pre-existing warnings persist.

- [ ] **Step 10: Update CHANGELOG**

In `CHANGELOG.md`, append to the existing `### Added` block under `[Unreleased]`:

```
- `stage_progress: float` field on `GET /api/pipeline/{task_id}` (and per child in batch responses). Derived from the existing overall `progress` and `current_stage` via the new canonical `STAGE_RANGES` constant in `src/pipeline.py`. Lets the UI render per-stage progress without backend changes to `emit()`.
```

- [ ] **Step 11: Commit**

```bash
git add src/pipeline.py src/api/routers/pipeline.py tests/test_pipeline_endpoints.py CHANGELOG.md
git commit -m "Expose stage_progress on pipeline status endpoint

Adds STAGE_RANGES canonical constant to src/pipeline.py
documenting the per-stage 0..1 boundaries that emit() already
uses inline. The router's GET handler derives a new
stage_progress field from (progress - lo) / (hi - lo) so
consumers can render per-stage progress without threading a
new arg through every emit() callsite.

Batch task children also get stage_progress on each per-child
dict.

8 new tests cover the helper (boundary, mid, clamp,
unknown-stage) plus a TestClient assertion that the GET
response includes the field."
```

No AI mentions, no Co-Authored-By.

---

## Task 2: Frontend — `pipelineStatus.tsx` context

**Files:**
- Create: `ui-app/src/lib/pipelineStatus.tsx`

This task creates the standalone React Context. No UI changes yet — verify it TypeScript-compiles and the file exports are correctly typed. Integration into the page lands in Task 4.

- [ ] **Step 1: Create the directory + file**

Create `ui-app/src/lib/pipelineStatus.tsx` with the full content below.

```tsx
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/** Canonical pipeline stage names — must match `STAGE_RANGES` keys in src/pipeline.py. */
export type PipelineStageName =
  | 'download'
  | 'transcribe'
  | 'translate'
  | 'tts'
  | 'process';

export const PIPELINE_STAGE_ORDER: PipelineStageName[] = [
  'download',
  'transcribe',
  'translate',
  'tts',
  'process',
];

export type PipelineRunStatus = 'idle' | 'running' | 'completed' | 'failed';

export type PipelineMode = 'single' | 'batch';

export type PipelineChild = {
  videoId: string;
  status: string;
  currentStage: string;
  stageProgress: number;
  progress: number;
  message: string;
  error: string | null;
};

export type PipelineStatus = {
  taskId: string | null;
  mode: PipelineMode | null;
  status: PipelineRunStatus;
  currentStage: PipelineStageName | '';
  stageProgress: number;       // 0..1, per-current-stage
  completedStages: PipelineStageName[];
  progress: number;            // 0..1 overall
  message: string;
  videoId: string | null;
  // Batch-only fields
  children: PipelineChild[];
  batchTotal: number;
  batchCompleted: number;
  error: string | null;
};

const IDLE_STATUS: PipelineStatus = {
  taskId: null,
  mode: null,
  status: 'idle',
  currentStage: '',
  stageProgress: 0,
  completedStages: [],
  progress: 0,
  message: '',
  videoId: null,
  children: [],
  batchTotal: 0,
  batchCompleted: 0,
  error: null,
};

const STORAGE_KEY = 'pipeline_active_task';
const POLL_INTERVAL_MS = 2000;

/** Subset of PipelineStatus persisted to sessionStorage for optimistic restore. */
type LastKnown = Pick<
  PipelineStatus,
  'currentStage' | 'stageProgress' | 'completedStages' | 'progress' | 'message'
>;

type StoredPayload = {
  taskId: string;
  mode: PipelineMode;
  lastKnown?: LastKnown;
};

/** Strict guards used in JSON.parse fallback. */
const VALID_STAGES = new Set<string>(PIPELINE_STAGE_ORDER);

function isPipelineStageName(s: unknown): s is PipelineStageName {
  return typeof s === 'string' && VALID_STAGES.has(s);
}

function parseStoredPayload(raw: string | null): StoredPayload | null {
  if (!raw) return null;
  try {
    const obj = JSON.parse(raw);
    if (
      obj &&
      typeof obj.taskId === 'string' &&
      (obj.mode === 'single' || obj.mode === 'batch')
    ) {
      return obj as StoredPayload;
    }
  } catch {
    // fall through
  }
  return null;
}

function primedFromStored(stored: StoredPayload | null): PipelineStatus {
  if (!stored) return IDLE_STATUS;
  const lk = stored.lastKnown;
  return {
    ...IDLE_STATUS,
    taskId: stored.taskId,
    mode: stored.mode,
    status: 'running',
    currentStage: lk && isPipelineStageName(lk.currentStage) ? lk.currentStage : '',
    stageProgress: lk?.stageProgress ?? 0,
    completedStages:
      lk?.completedStages?.filter(isPipelineStageName) ?? [],
    progress: lk?.progress ?? 0,
    message: lk?.message ?? 'Resuming…',
  };
}

type ContextValue = {
  status: PipelineStatus;
  /** Start tracking a newly-launched task. Resets in-memory state. */
  startPolling: (taskId: string, mode: PipelineMode) => void;
  /** Stop polling and reset status to idle. */
  stopPolling: () => void;
};

const PipelineStatusContext = createContext<ContextValue>({
  status: IDLE_STATUS,
  startPolling: () => {},
  stopPolling: () => {},
});

export function usePipelineStatus(): ContextValue {
  return useContext(PipelineStatusContext);
}

export function PipelineStatusProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<PipelineStatus>(() =>
    primedFromStored(parseStoredPayload(sessionStorage.getItem(STORAGE_KEY)))
  );
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const taskIdRef = useRef<string | null>(status.taskId);
  const modeRef = useRef<PipelineMode | null>(status.mode);

  const clearStored = useCallback(() => {
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const persistStored = useCallback((s: PipelineStatus) => {
    if (!s.taskId || !s.mode || s.status !== 'running') return;
    const payload: StoredPayload = {
      taskId: s.taskId,
      mode: s.mode,
      lastKnown: {
        currentStage: s.currentStage,
        stageProgress: s.stageProgress,
        completedStages: s.completedStages,
        progress: s.progress,
        message: s.message,
      },
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, []);

  const stopPollingInternal = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    taskIdRef.current = null;
    modeRef.current = null;
  }, []);

  const pollOnce = useCallback(async () => {
    const tid = taskIdRef.current;
    const mode = modeRef.current;
    if (!tid || !mode) return;
    try {
      const r = await fetch(`/api/pipeline/${tid}`);
      if (!r.ok) {
        stopPollingInternal();
        clearStored();
        setStatus(IDLE_STATUS);
        return;
      }
      const d = await r.json();
      if (mode === 'batch' && Array.isArray(d.children)) {
        const childrenRaw = d.children as Array<Record<string, unknown>>;
        const children: PipelineChild[] = childrenRaw.map((c) => ({
          videoId: String(c.video_id ?? ''),
          status: String(c.status ?? ''),
          currentStage: String(c.current_stage ?? ''),
          stageProgress: typeof c.stage_progress === 'number' ? c.stage_progress : 0,
          progress: typeof c.progress === 'number' ? c.progress : 0,
          message: String(c.message ?? ''),
          error: c.error == null ? null : String(c.error),
        }));
        const done = children.filter((c) => c.status === 'done' || c.status === 'failed').length;
        const total = children.length;
        const next: PipelineStatus = {
          ...IDLE_STATUS,
          taskId: tid,
          mode: 'batch',
          status:
            d.status === 'completed'
              ? 'completed'
              : d.status === 'failed'
                ? 'failed'
                : 'running',
          progress: total > 0 ? children.reduce((a, c) => a + c.progress, 0) / total : 0,
          message: typeof d.message === 'string' ? d.message : '',
          children,
          batchTotal: total,
          batchCompleted: done,
          error: d.error == null ? null : String(d.error),
        };
        setStatus(next);
        persistStored(next);
        if (next.status !== 'running') {
          stopPollingInternal();
          clearStored();
        }
        return;
      }
      // single-pipeline path
      const rawStage = String(d.current_stage ?? '');
      const currentStage: PipelineStageName | '' = isPipelineStageName(rawStage) ? rawStage : '';
      const completedStages = Array.isArray(d.completed_stages)
        ? (d.completed_stages as unknown[]).filter(isPipelineStageName)
        : [];
      const next: PipelineStatus = {
        ...IDLE_STATUS,
        taskId: tid,
        mode: 'single',
        status:
          d.status === 'completed'
            ? 'completed'
            : d.status === 'failed'
              ? 'failed'
              : 'running',
        currentStage,
        stageProgress: typeof d.stage_progress === 'number' ? d.stage_progress : 0,
        completedStages,
        progress: typeof d.progress === 'number' ? d.progress : 0,
        message: typeof d.message === 'string' ? d.message : '',
        videoId: typeof d.video_id === 'string' ? d.video_id : null,
        children: [],
        error: d.error == null ? null : String(d.error),
      };
      setStatus(next);
      persistStored(next);
      if (next.status !== 'running') {
        stopPollingInternal();
        clearStored();
      }
    } catch {
      // Network blip — keep polling on the next tick.
    }
  }, [clearStored, persistStored, stopPollingInternal]);

  const startPolling = useCallback(
    (taskId: string, mode: PipelineMode) => {
      stopPollingInternal();
      taskIdRef.current = taskId;
      modeRef.current = mode;
      const seed: PipelineStatus = {
        ...IDLE_STATUS,
        taskId,
        mode,
        status: 'running',
        message: 'Starting…',
      };
      setStatus(seed);
      persistStored(seed);
      pollRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
      // Fire immediately so the UI doesn't wait a full POLL_INTERVAL for the first update.
      void pollOnce();
    },
    [persistStored, pollOnce, stopPollingInternal]
  );

  const stopPolling = useCallback(() => {
    stopPollingInternal();
    clearStored();
    setStatus(IDLE_STATUS);
  }, [clearStored, stopPollingInternal]);

  // On mount: if sessionStorage has an active task, resume polling.
  useEffect(() => {
    const stored = parseStoredPayload(sessionStorage.getItem(STORAGE_KEY));
    if (stored) {
      taskIdRef.current = stored.taskId;
      modeRef.current = stored.mode;
      pollRef.current = setInterval(pollOnce, POLL_INTERVAL_MS);
      void pollOnce();
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <PipelineStatusContext.Provider value={{ status, startPolling, stopPolling }}>
      {children}
    </PipelineStatusContext.Provider>
  );
}
```

- [ ] **Step 2: Verify the file TypeScript-compiles**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -15
```

Expected: zero new errors.

- [ ] **Step 3: Lint**

```bash
cd ui-app && npm run lint 2>&1 | tail -15
```

Expected: no NEW errors. (Pre-existing warnings persist.)

- [ ] **Step 4: Update CHANGELOG**

Append to existing `### Added` block:

```
- `ui-app/src/lib/pipelineStatus.tsx`: new `PipelineStatusProvider` React Context + `usePipelineStatus()` hook. Owns the pipeline-polling loop at the app root so it survives page navigation. On mount, optimistically primes state from `sessionStorage['pipeline_active_task'].lastKnown` so the running-pipeline UI renders instantly on hard refresh while the reconnect fetch runs in the background. Standalone file — not wired into any page yet (Task 4 does that).
```

- [ ] **Step 5: Commit**

```bash
git add ui-app/src/lib/pipelineStatus.tsx CHANGELOG.md
git commit -m "Add PipelineStatusProvider context (unwired)

Standalone React Context that owns the pipeline-polling loop and
persists last-known stage/progress/message to sessionStorage on
every status update.

On mount, optimistic restore reads sessionStorage and primes state
from the lastKnown payload immediately, then resumes the polling
loop. On a poll response showing completed/failed, the context
stops polling and clears sessionStorage.

Not wired into any page yet — DownloadTranscribe migrates in
Task 4."
```

No AI mentions, no Co-Authored-By.

---

## Task 3: Frontend — `PipelineStageTracker.tsx` component

**Files:**
- Create: `ui-app/src/components/PipelineStageTracker.tsx`

A pure presentational component. No state, no side effects — just renders 5 rows from a `PipelineStatus` prop.

- [ ] **Step 1: Create the file**

Create `ui-app/src/components/PipelineStageTracker.tsx`:

```tsx
import {
  PIPELINE_STAGE_ORDER,
  type PipelineStageName,
  type PipelineStatus,
} from '../lib/pipelineStatus';

const STAGE_LABELS: Record<PipelineStageName, string> = {
  download: 'Download',
  transcribe: 'Transcribe (OCR)',
  translate: 'Translate',
  tts: 'TTS Dubbing',
  process: 'Process & Burn',
};

type StageRowState = 'done' | 'running' | 'pending' | 'skipped';

function rowState(
  stage: PipelineStageName,
  status: PipelineStatus
): StageRowState {
  if (status.completedStages.includes(stage)) return 'done';
  if (status.currentStage === stage) return 'running';
  // Translate-skipped detection: currentStage has moved past translate
  // without translate appearing in completedStages.
  if (stage === 'translate') {
    const currentIdx = PIPELINE_STAGE_ORDER.indexOf(
      (status.currentStage || 'download') as PipelineStageName
    );
    const translateIdx = PIPELINE_STAGE_ORDER.indexOf('translate');
    if (
      currentIdx > translateIdx ||
      status.completedStages.some((s) => {
        const i = PIPELINE_STAGE_ORDER.indexOf(s);
        return i > translateIdx;
      })
    ) {
      return 'skipped';
    }
  }
  return 'pending';
}

function StageIcon({ state }: { state: StageRowState }) {
  if (state === 'done') {
    return (
      <div className="w-6 h-6 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-sm">check</span>
      </div>
    );
  }
  if (state === 'running') {
    return (
      <div className="w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center shrink-0">
        <div className="w-3 h-3 rounded-full border-2 border-primary border-t-transparent animate-spin" />
      </div>
    );
  }
  if (state === 'skipped') {
    return (
      <div className="w-6 h-6 rounded-full bg-surface-container-highest text-zinc-600 flex items-center justify-center shrink-0">
        <span className="material-symbols-outlined text-sm">remove</span>
      </div>
    );
  }
  return (
    <div className="w-6 h-6 rounded-full border border-outline-variant/30 shrink-0" />
  );
}

function StageBar({
  state,
  stagePercent,
}: {
  state: StageRowState;
  stagePercent: number;
}) {
  const width =
    state === 'done' ? 100 : state === 'running' ? Math.round(stagePercent) : 0;
  const colorClass =
    state === 'done'
      ? 'bg-emerald-500/30'
      : state === 'running'
        ? 'bg-primary'
        : 'bg-surface-container-highest';
  return (
    <div className="w-full h-1.5 bg-surface-container-highest rounded-full overflow-hidden">
      <div
        className={`h-full ${colorClass} transition-all duration-300`}
        style={{ width: `${width}%` }}
      />
    </div>
  );
}

export function PipelineStageTracker({ status }: { status: PipelineStatus }) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <span className="material-symbols-outlined text-primary text-lg">
          account_tree
        </span>
        <span className="text-xs font-bold uppercase tracking-widest text-zinc-500">
          Pipeline running
        </span>
        <span className="ml-auto text-[10px] font-mono text-zinc-500">
          {Math.round((status.progress ?? 0) * 100)}% overall
        </span>
      </div>
      <div className="space-y-3">
        {PIPELINE_STAGE_ORDER.map((stage) => {
          const state = rowState(stage, status);
          const isRunning = state === 'running';
          const stagePercent = (status.stageProgress ?? 0) * 100;
          const labelClass =
            state === 'done'
              ? 'text-emerald-400'
              : state === 'running'
                ? 'text-on-surface'
                : state === 'skipped'
                  ? 'text-zinc-600 line-through'
                  : 'text-zinc-600';
          return (
            <div key={stage} className="flex items-start gap-3">
              <StageIcon state={state} />
              <div className="flex-1 min-w-0 space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <span className={`text-sm font-semibold ${labelClass}`}>
                    {STAGE_LABELS[stage]}
                  </span>
                  {state === 'running' && (
                    <span className="text-[10px] font-mono text-on-surface-variant">
                      {Math.round(stagePercent)}%
                    </span>
                  )}
                </div>
                <StageBar state={state} stagePercent={stagePercent} />
                {isRunning && status.message && (
                  <p className="text-[10px] font-mono text-on-surface-variant whitespace-pre-line">
                    {status.message}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify the file TypeScript-compiles**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -10
```

Expected: zero new errors.

- [ ] **Step 3: Lint**

```bash
cd ui-app && npm run lint 2>&1 | tail -10
```

Expected: no NEW errors.

- [ ] **Step 4: Update CHANGELOG**

Append to existing `### Added` block:

```
- `ui-app/src/components/PipelineStageTracker.tsx`: pure presentational component that renders 5 rows (Download / Transcribe / Translate / TTS / Process) from a `PipelineStatus` prop. Each row shows status icon (done ✓ / running ● / pending ○ / skipped ⊖), label, per-stage progress bar, and the current message when running. Translate-skipped state is auto-detected when `currentStage` advances past translate without translate appearing in `completedStages`.
```

- [ ] **Step 5: Commit**

```bash
git add ui-app/src/components/PipelineStageTracker.tsx CHANGELOG.md
git commit -m "Add PipelineStageTracker component (unwired)

Pure presentational component, props = { status: PipelineStatus }.
Renders 5 stage rows: status icon + label + per-stage progress bar
+ current-stage message. Translate-skipped state is auto-detected
when currentStage advances past translate without translate
appearing in completedStages.

Not yet rendered anywhere — DownloadTranscribe wires it in
Task 4."
```

No AI mentions, no Co-Authored-By.

---

## Task 4: Wire everything into the app

**Files:**
- Modify: `ui-app/src/App.tsx` (wrap with provider)
- Modify: `ui-app/src/pages/DownloadTranscribe.tsx` (delete local state, use context, render tracker)
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Wrap the app root in `<PipelineStatusProvider>`**

Open `ui-app/src/App.tsx`. Currently:

```tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { lazy, Suspense } from 'react';

// ... lazy imports ...

function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<LoadingFallback />}>
        <Routes>
          <Route element={<Layout />}>
            ...
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
```

Add the provider import and wrap the routes:

```tsx
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { Layout } from './components/Layout';
import { lazy, Suspense } from 'react';
import { PipelineStatusProvider } from './lib/pipelineStatus';

// ... lazy imports unchanged ...

function App() {
  return (
    <BrowserRouter>
      <PipelineStatusProvider>
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route element={<Layout />}>
              ...
            </Route>
          </Routes>
        </Suspense>
      </PipelineStatusProvider>
    </BrowserRouter>
  );
}
```

The provider sits inside `BrowserRouter` (so its descendants can use `useNavigate` if needed) but outside `Suspense` (so it's not torn down on lazy-route swaps).

- [ ] **Step 2: Open DownloadTranscribe.tsx and identify deletions**

```bash
grep -n "pipelineStage\|pipelineProgress\|pipelineMessage\|isPipeline\|pollRef\|startPolling\|stopPolling\|saveActiveTask\|clearActiveTask\|PIPELINE_TASK_KEY" ui-app/src/pages/DownloadTranscribe.tsx | head -30
```

You'll see references to:
- Local state: `pipelineStage`, `pipelineProgress`, `pipelineMessage`, `isPipeline`
- `pollRef`, `startPolling`, `stopPolling`, `saveActiveTask`, `clearActiveTask`
- `PIPELINE_TASK_KEY` constant at file top
- Mount-effect block that handles sessionStorage reconnect

All of these are now owned by the context.

- [ ] **Step 3: Replace the imports**

At the top of `ui-app/src/pages/DownloadTranscribe.tsx`, add:

```tsx
import { usePipelineStatus } from '../lib/pipelineStatus';
import { PipelineStageTracker } from '../components/PipelineStageTracker';
```

- [ ] **Step 4: Delete the `PIPELINE_TASK_KEY` constant and local state**

Find and delete (use grep to locate exact lines):

```tsx
const PIPELINE_TASK_KEY = 'pipeline_active_task';
```

```tsx
const [pipelineStage, setPipelineStage] = useState('');
const [pipelineProgress, setPipelineProgress] = useState(0);
const [pipelineMessage, setPipelineMessage] = useState('');
const [isPipeline, setIsPipeline] = useState(false);
```

(Keep `setBatchResults` / `batchResults` state — those drive the URL card's batch progress display, which the spec says stays unchanged.)

- [ ] **Step 5: Delete the local polling helpers**

Find and delete:

```tsx
const pollRef = useRef<...>(null);

const clearActiveTask = () => sessionStorage.removeItem(PIPELINE_TASK_KEY);
const saveActiveTask = (taskId: string, mode: 'single' | 'batch') => { ... };
const stopPolling = useCallback(() => { ... }, []);
const startPolling = useCallback((taskId: string, mode: 'single' | 'batch') => { ... }, [...]);
```

If you're not sure of the boundaries, search for the `startPolling` function body and delete from its opening `const startPolling` through the matching closing `}, [...]);`. Same for `stopPolling`.

- [ ] **Step 6: Delete the sessionStorage-reconnect block in the mount effect**

Find the existing `useEffect` that contains the `sessionStorage.getItem(PIPELINE_TASK_KEY)` block (around line 233). DELETE that entire block — the provider now owns reconnect. The mount effect should keep loading videos, profiles, and TTS providers; just remove the reconnect block.

After this step, the mount effect looks like:

```tsx
useEffect(() => {
  loadVideos();
  getProfiles().then((p) => {
    setProfiles(p);
    setSelectedProfile((prev) => prev || (p.length > 0 ? p[0].name : ''));
  }).catch(() => {});
  getTTSProviders().then(setTtsProviders).catch(() => {});
  // (no return cleanup needed — polling is now owned by PipelineStatusProvider)
}, [loadVideos]);
```

- [ ] **Step 7: Add the context hook**

Near the top of the component body (after the existing `const navigate = useNavigate();` line), add:

```tsx
const { status: pipelineStatus, startPolling } = usePipelineStatus();
const isPipeline = pipelineStatus.status === 'running';
```

The local `isPipeline` consumers throughout the component continue to work because we re-declared it as a derived value.

- [ ] **Step 8: Replace `startPolling`/`saveActiveTask` callsites in handlers**

Find every callsite where the old local `startPolling(task_id, 'single')` or `saveActiveTask(taskId, 'single')` was used. Replace with the context's `startPolling`.

In `handlePipeline`, after the single-URL POST:

```tsx
// was:
saveActiveTask(task_id, 'single');
startPolling(task_id, 'single');
// becomes:
startPolling(task_id, 'single');
```

And for the batch POST:

```tsx
// was:
saveActiveTask(data.batch_id, 'batch');
startPolling(data.batch_id, 'batch');
// becomes:
startPolling(data.batch_id, 'batch');
```

The context's `startPolling` handles sessionStorage internally — no separate `saveActiveTask` call is needed.

Also: the old code had a callback inside the poll function that called `navigate('/videos/{video_id}')` when the pipeline completed. The new context doesn't do navigation. To preserve that behavior, add a `useEffect` reacting to the context status:

```tsx
useEffect(() => {
  if (
    pipelineStatus.status === 'completed' &&
    pipelineStatus.mode === 'single' &&
    pipelineStatus.videoId
  ) {
    loadVideos();
    navigate(`/videos/${pipelineStatus.videoId}`);
  } else if (
    pipelineStatus.status === 'completed' &&
    pipelineStatus.mode === 'batch'
  ) {
    loadVideos();
    setBatchResults(null);
    setUrlInput('');
  } else if (pipelineStatus.status === 'failed') {
    setError(pipelineStatus.error || 'Pipeline failed');
  }
}, [
  pipelineStatus.status,
  pipelineStatus.mode,
  pipelineStatus.videoId,
  pipelineStatus.error,
  loadVideos,
  navigate,
]);
```

For batch progress: the context updates `pipelineStatus.batchTotal` and `pipelineStatus.batchCompleted` on every poll. Wire those into the existing `batchResults` state via another effect:

```tsx
useEffect(() => {
  if (pipelineStatus.mode === 'batch' && pipelineStatus.status === 'running') {
    setBatchResults({
      completed: pipelineStatus.batchCompleted,
      total: pipelineStatus.batchTotal,
    });
  }
}, [
  pipelineStatus.mode,
  pipelineStatus.status,
  pipelineStatus.batchCompleted,
  pipelineStatus.batchTotal,
]);
```

This is a small migration cost — the old local poll handler set `batchResults` directly inside the poll loop; now we derive it from the context.

- [ ] **Step 9: Replace the slim progress strip with `<PipelineStageTracker>`**

Find the existing JSX (added in Task 4 of the page-cleanup work):

```tsx
{/* Running progress strip — visible only during a single-URL pipeline run */}
{isPipeline && !isBatchMode && (
  <div className="bg-surface-container-low rounded-xl p-4 flex items-center gap-4">
    ... slim bar JSX ...
  </div>
)}
```

Replace with:

```tsx
{/* Per-stage pipeline tracker — visible only during a single-URL pipeline run */}
{isPipeline && pipelineStatus.mode === 'single' && (
  <div className="bg-surface-container-low rounded-xl p-5">
    <PipelineStageTracker status={pipelineStatus} />
  </div>
)}
```

The batch UI in the URL card is unchanged (it consumes `batchResults`, which the effect in Step 8 keeps updated).

- [ ] **Step 10: TypeScript + lint**

```bash
cd ui-app && npx tsc --noEmit 2>&1 | tail -10
cd ui-app && npm run lint 2>&1 | tail -10
```

Expected: zero TS errors. Lint count: same or lower (no NEW errors).

Common issues:
- Unused imports for `useRef`, `useCallback` if those were only used by the deleted polling code. Remove them.
- Unused `PIPELINE_TASK_KEY` constant — should be deleted in Step 4.
- TS complaints about `status.videoId` being `string | null` when navigating — guard with `if (pipelineStatus.videoId)` in the navigate effect.

- [ ] **Step 11: Update CHANGELOG**

Append to existing `### Changed` block:

```
- Pipeline launcher (DownloadTranscribe): replaced the slim single-bar progress strip with the per-stage `<PipelineStageTracker>` (5 rows showing each pipeline stage's status and individual progress). Lifted pipeline polling state to the new `PipelineStatusProvider` context at the app root — the polling loop survives navigation between pages, so the tracker renders instantly when returning to the Pipeline page mid-run instead of waiting for a reconnect fetch. `App.tsx` wraps the router tree in the provider. Local `pipelineStage`/`pipelineProgress`/`pipelineMessage`/`isPipeline` state + `startPolling`/`stopPolling`/`saveActiveTask`/`clearActiveTask` helpers + the mount-effect reconnect block were all deleted (~80 lines).
```

- [ ] **Step 12: Commit**

```bash
git add ui-app/src/App.tsx ui-app/src/pages/DownloadTranscribe.tsx CHANGELOG.md
git commit -m "Wire pipeline status context into DownloadTranscribe

Pipeline polling state lives at the app root now (PipelineStatusProvider
in App.tsx). DownloadTranscribe.tsx no longer owns local state or the
polling loop — it reads from usePipelineStatus() and renders the new
PipelineStageTracker component when a single-URL pipeline is running.

Removed (~80 lines):
- pipelineStage, pipelineProgress, pipelineMessage, isPipeline state
- pollRef, startPolling, stopPolling, saveActiveTask, clearActiveTask
- The sessionStorage reconnect block in the mount effect
- PIPELINE_TASK_KEY constant

Added side-effect useEffects to handle pipeline completion / failure
(navigate to video, clear batch results, surface errors) and to mirror
batch progress into the existing batchResults state.

The tracker survives navigation across pages because the provider lives
above the routes and doesn't unmount on route changes."
```

No AI mentions, no Co-Authored-By.

---

## Task 5: Manual QA + finalize

**Files:**
- No code changes — manual verification only.

This task verifies the full set of changes against a real pipeline run and any short-pipeline scenarios (e.g. translation skipped), then pushes the branch.

- [ ] **Step 1: Run full automated test suite**

```bash
python -m pytest tests/ -v -x --ignore=tests/test_integration.py
```

Expected: all pass. The Task 1 tests (`test_pipeline_endpoints.py`) should be at 8 passing.

- [ ] **Step 2: Rebuild Docker and start the app**

```bash
make docker-up
```

Wait for the build to finish, then tail logs:

```bash
make docker-logs
```

Expected: app starts cleanly; no import errors.

- [ ] **Step 3: UI smoke — first-load with no active pipeline**

In a browser at `http://localhost:8000`:

- Open the Pipeline launcher (DownloadTranscribe).
- Confirm: no running-state UI is visible. Configuration card is shown as expected.

- [ ] **Step 4: UI smoke — start a pipeline, watch the tracker**

- Paste a Douyin URL in `testurl.txt`.
- Click Run Pipeline.
- Confirm: the Configuration card disappears. A new "Pipeline running" panel appears with 5 rows.
- Watch the rows: download row first shows the spinner + animated bar; once download completes, the row gets a green ✓ and its bar fills.
- Repeat for transcribe (OCR is the slow stage — watch its bar inch from 0 to 100% over 30s-2min).
- The "stage_progress" % indicator in the right of the current row matches the OCR's actual progress.

- [ ] **Step 5: UI smoke — navigate away and back during a run**

- While the pipeline is running (e.g. mid-OCR), click on "Settings" or "Video Library".
- Wait 2-3 seconds.
- Click back to "Pipeline".
- The tracker should appear INSTANTLY (no 10s wait, no Configuration card flash).
- The current stage's progress should be approximately where it was when you left, refining within a poll cycle (~2s).

- [ ] **Step 6: UI smoke — hard browser refresh during a run**

- Continue the same run (or start a new one).
- Press F5 to hard-refresh the browser.
- Within ~1s of page reload, the tracker should be visible (primed from sessionStorage's lastKnown).
- Within ~2s of that, the values refresh from the reconnect fetch.

- [ ] **Step 7: UI smoke — translation skipped**

- Start a new pipeline with "Skip translation" selected in the Translation Profile dropdown.
- Watch the tracker: when transcribe completes and the next stage starts (TTS or Process), the Translate row should switch to the "skipped" state — dim icon (⊖) and strikethrough label.

- [ ] **Step 8: UI smoke — batch mode**

- Paste 2-3 URLs in the input (newline-separated) to enter batch mode.
- Click Run Pipeline.
- The URL card's batch progress bar should still work (e.g. "1/3 done", "2/3 done").
- The single-URL per-stage tracker should NOT appear in batch mode (it's gated on `pipelineStatus.mode === 'single'`).

- [ ] **Step 9: Push the branch**

```bash
git push origin feature/phase4-dubbing-redesign-spec
```

- [ ] **Step 10: Report state**

Return:
- Total commits on the feature branch since main: `git rev-list --count main..HEAD`
- Files changed: `git diff --stat main..HEAD | tail -1`
- Test counts from Step 1
- Brief summary of what worked / didn't in Steps 4-8

---

## Self-Review Checklist

**Spec coverage:**

- ✅ §Goal 1 (per-stage visibility) — Tasks 1 (`stage_progress` field) + 3 (`PipelineStageTracker`) + 4 (rendered in DownloadTranscribe)
- ✅ §Goal 2 (instant restore on navigate-back) — Task 2 (context lives above routes) + Task 4 (provider wrapper)
- ✅ §Goal 3 (backward compat for existing `progress` field) — Task 1 adds field; doesn't remove or change existing fields
- ✅ §Backend `STAGE_RANGES` defined in `src/pipeline.py` — Task 1 Step 2
- ✅ §Backend `_stage_progress` helper in router — Task 1 Step 5
- ✅ §Backend batch-children `stage_progress` per child — Task 1 Step 6
- ✅ §Frontend `PipelineStatus` type with all fields (taskId, mode, status, currentStage, stageProgress, completedStages, progress, message, videoId, batch fields, error) — Task 2 Step 1
- ✅ §Frontend `PipelineStatusProvider` + `usePipelineStatus()` hook — Task 2 Step 1
- ✅ §Frontend internal pollRef + 2s polling — Task 2 Step 1
- ✅ §Frontend on-mount sessionStorage prime + reconnect — Task 2 Step 1
- ✅ §Frontend persist `lastKnown` on every status update + clear on completion — Task 2 Step 1
- ✅ §Frontend `PipelineStageTracker` component, 5 rows — Task 3 Step 1
- ✅ §Frontend translate-skipped detection (Option A) — Task 3 Step 1 (`rowState` logic)
- ✅ §App.tsx wraps router in provider — Task 4 Step 1
- ✅ §DownloadTranscribe lifts state to context — Task 4 Steps 4-9
- ✅ §Tests (backend `_stage_progress` + TestClient GET assertion) — Task 1 Step 3

**Placeholder scan:**

- No "TBD" / "TODO" / "fill in details" — checked.
- No "Add appropriate error handling" — concrete try/catch shown.
- No "Similar to Task N" — JSX/Python code blocks are explicit in each task.
- No references to undefined types or functions — `PipelineStatus`, `usePipelineStatus`, `PIPELINE_STAGE_ORDER`, `PipelineStageName`, `PipelineMode`, `PipelineChild`, `STAGE_LABELS` are all defined in Task 2/3 and used consistently in Task 4.

**Type consistency:**

- `PipelineStatus.currentStage: PipelineStageName | ''` — used as the union type in Task 3 (`rowState`'s argument typing) and Task 4 (effect dep `pipelineStatus.currentStage`). Consistent.
- `PipelineStatus.completedStages: PipelineStageName[]` — used consistently.
- `STAGE_LABELS: Record<PipelineStageName, string>` in Task 3 keys match `PIPELINE_STAGE_ORDER` items in Task 2.
- `StoredPayload` shape: `{ taskId: string, mode: PipelineMode, lastKnown?: LastKnown }` — consistent across persist + parse paths.
- Backend `STAGE_RANGES` keys (`"download"`, `"transcribe"`, `"translate"`, `"tts"`, `"process"`) match frontend `PIPELINE_STAGE_ORDER` strings exactly. Drift risk: if either side adds a new stage, both must update. The spec calls this out and accepts the trade-off.

**Known risks (call out but no plan change):**

- Task 1 Step 3's `_make_client` mirrors the pattern from `tests/test_srt_endpoints.py`. If `Task`'s constructor doesn't accept `task_id=...` and `task_type=...` as kwargs (it's probably a dataclass — verify with the grep at Step 3), adjust to use whatever fields the dataclass has. The behavior of the tests must not change.
- Task 4 Step 9's existing JSX has a comment that says "Running progress strip" from a prior commit (Task 4 of the previous plan). Make sure to find/replace the right block; the comment string changes from "Running progress strip" to "Per-stage pipeline tracker".
- Task 4 Step 8's effects use the context's `pipelineStatus.status === 'completed'` as the trigger to navigate. The context fires this exactly once when the pipeline finishes (then stops polling and resets). If the effect runs after the user has already left DownloadTranscribe, the navigate is harmless (we're already on a different page, navigate target is a video page that's reachable from anywhere). Acceptable.
