# Cancel a Running Pipeline + Cleanup

**Status:** Design
**Date:** 2026-05-28
**Owner:** Daniel

## Problem

The CLI pipeline (`src/pipeline.py`) handles SIGINT and writes an `"interrupted"` state file so the next run can resume. The API path (`src/api/task_manager.py` → `asyncio.create_task(...)` from `src/api/routers/pipeline.py`) is fire-and-forget — once a pipeline starts via the UI, there's no way to stop it short of killing the API server. If the user changes their mind mid-pipeline they have to wait for it to finish, then `delete_video` to throw away the result.

This costs minutes per "oops". It also leaves intermediate files (`.tmp.mp4` outputs, `bg_tmp/` PNG dirs, half-finished TTS WAVs) that nothing eventually claims.

## Goals

1. A **Stop button** on every running async task in the UI (full pipeline, batch pipeline, batch children, per-stage download/transcribe/translate/TTS/export).
2. Stopping is **instant** — running ffmpeg / OCR / yt-dlp subprocesses are killed, not waited out.
3. Stopping **deletes everything** for that video — reuses the existing `delete_video` path. As if the run never happened.
4. **Idempotent** on terminal states. Calling cancel on a completed task is a no-op with a clear response.
5. **Batch-aware**: cancelling a batch parent cancels all in-flight children with cleanup; per-child cancel works without affecting siblings.

## Non-goals

- A "pause / resume" mode. Stop means wipe. The CLI's resume-from-interrupted flow stays as-is for CLI users, but the API doesn't expose it.
- Cancelling short-lived tasks (dub generation, single export, preview frame/clip). These finish in seconds-to-minutes; no UI cancel button. The endpoint will accept their task IDs and work, but there's no FE surface for now.
- Reversing a partial cancel ("undo cancel"). Once delete_video runs, the files are gone.

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────┐
│ FE — pipeline row in dashboard or batch view                     │
│   [⊗ Stop] button → confirm modal → cancelTask(task_id)          │
└─────────────────────────────────────────────────────────────────┘
                                │ POST /api/tasks/{task_id}/cancel
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│ TaskManager.cancel_task(task_id)                                 │
│   1. Lookup task. Refuse if status in {completed, failed,        │
│      cancelled}.                                                  │
│   2. status = "cancelling" (transient guard against double calls)│
│   3. If task is a batch parent: recurse into child task IDs.     │
│   4. Kill any tracked subprocess: task._running_subprocess.kill()│
│   5. task._asyncio_task.cancel()                                 │
│   6. Wait up to 5s for the coroutine to exit.                    │
│   7. If task.video_id is set: delete_video(video_id).            │
│   8. status = "cancelled", emit SSE "cancelled" event.           │
│   9. Return {task_id, status, cleaned, video_id}.                │
└─────────────────────────────────────────────────────────────────┘
                                │ delete_video(video_id) handles:
                                ▼
       data/raw/{vid}.* + data/srt/{vid}_* + data/srt/{vid}.*
     + data/proxy/{vid}* + data/output/{vid}_* + data/output/{vid}.*
     + data/tts/{vid}_*  + data/tts/{vid}/  + data/logs/{vid}_*
     + data/preview/{vid}_*
```

## 1. Cancellation mechanism

### Task model extensions

In `src/api/task_manager.py`:

```python
@dataclass
class Task:
    task_id: str
    task_type: str
    status: str = "queued"
    # NEW: add "cancelling" (transient) and "cancelled" (terminal)
    # Full set: queued | running | cancelling | cancelled | completed | failed
    video_id: str | None = None
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    events: list[dict] = field(default_factory=list)

    # NEW — not serialized over SSE / API. Used internally for cancellation.
    _asyncio_task: asyncio.Task | None = None
    _running_subprocess: subprocess.Popen | None = None
    _child_task_ids: list[str] = field(default_factory=list)  # batch parents only
```

`_asyncio_task` is set immediately after `asyncio.create_task(...)` at every dispatch site. `_running_subprocess` is set inside helpers that spawn long-running processes. `_child_task_ids` is populated when a batch task creates its children.

### Subprocess tracking helper

Most cancel pain in this codebase is from `subprocess.run(...)` / `subprocess.Popen(...)` wrapped in `asyncio.to_thread`. `asyncio.Task.cancel()` raises `CancelledError` at the next `await`, but `to_thread` *blocks* on the thread until the subprocess returns. So we need to kill the subprocess explicitly.

Pattern (new helper in `src/api/task_manager.py`):

```python
async def run_subprocess_tracked(
    self, task_id: str, cmd: list[str], **kwargs,
) -> subprocess.CompletedProcess:
    """Run subprocess.run on a background thread, tracking its Popen so
    cancel_task can kill it. Use this wherever an ffmpeg / yt-dlp / OCR
    subprocess might run for more than a couple seconds."""
    proc = subprocess.Popen(cmd, **kwargs, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    task = self.tasks.get(task_id)
    if task is not None:
        task._running_subprocess = proc
    try:
        stdout, stderr = await asyncio.to_thread(proc.communicate)
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    finally:
        if task is not None and task._running_subprocess is proc:
            task._running_subprocess = None
```

Call sites that need this wrap (≈3 places):
- `_run_export_ffmpeg` in `src/api/routers/process.py` — the two `subprocess.run([ffmpeg, ...])` calls.
- `preview_clip` in `src/api/routers/editor.py` — the ffmpeg encode.
- `download_with_fallback` paths in `src/downloader/*` that spawn `yt-dlp` — already async via `asyncio.create_subprocess_exec`, but the Popen object should be tracked for kill.

The OCR transcribe path runs a long synchronous loop inside `asyncio.to_thread` — no subprocess to kill, but the loop already checks `_interrupted` flag at every iteration. We'll add a similar check on `task.status == "cancelling"` so it exits cleanly.

### cancel_task()

New method on `TaskManager`:

```python
async def cancel_task(self, task_id: str) -> dict:
    """Cancel a running task, kill its subprocess, and delete_video its
    output. Idempotent on terminal states."""
    task = self.tasks.get(task_id)
    if task is None:
        raise KeyError(task_id)

    if task.status in {"completed", "failed", "cancelled"}:
        return {
            "task_id": task_id, "status": task.status,
            "cleaned": False, "video_id": task.video_id,
            "message": f"Task already in terminal state: {task.status}",
        }

    if task.status == "cancelling":
        return {
            "task_id": task_id, "status": "cancelling",
            "cleaned": False, "video_id": task.video_id,
            "message": "Already cancelling",
        }

    task.status = "cancelling"
    self._emit(task_id, "cancelling", {"message": "Stopping..."})

    # Recurse into batch children first so we don't race the parent's cleanup.
    for child_id in list(task._child_task_ids):
        try:
            await self.cancel_task(child_id)
        except Exception as e:
            logger.warning(f"Failed to cancel child {child_id}: {e}")

    # Kill the tracked subprocess (instant).
    if task._running_subprocess is not None:
        try:
            task._running_subprocess.kill()
        except ProcessLookupError:
            pass  # already exited

    # Cancel the coroutine.
    if task._asyncio_task is not None and not task._asyncio_task.done():
        task._asyncio_task.cancel()
        try:
            await asyncio.wait_for(task._asyncio_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Cleanup. Best-effort — failure here doesn't unmark cancellation.
    cleaned = False
    if task.video_id:
        try:
            self.delete_video(task.video_id)
            cleaned = True
        except Exception as e:
            logger.error(f"delete_video({task.video_id}) failed during cancel: {e}")

    task.status = "cancelled"
    task.message = "Cancelled by user"
    self._emit(task_id, "cancelled", {
        "video_id": task.video_id, "cleaned": cleaned,
    })

    return {
        "task_id": task_id, "status": "cancelled",
        "cleaned": cleaned, "video_id": task.video_id,
    }
```

### Dispatch-site change

Every `asyncio.create_task(...)` in `src/api/routers/pipeline.py` (and similar dispatches in other routers) becomes a two-liner:

```python
task = tm.create_task("full_pipeline")
task._asyncio_task = asyncio.create_task(tm._run_full_pipeline(task.task_id, ...))
```

For batch:

```python
batch_task = tm.create_task("batch_pipeline")
for url in urls:
    child = tm.create_task("full_pipeline")
    batch_task._child_task_ids.append(child.task_id)
    child._asyncio_task = asyncio.create_task(tm._run_full_pipeline(child.task_id, ...))
batch_task._asyncio_task = asyncio.create_task(tm._batch_supervisor(batch_task.task_id))
```

## 2. API endpoint

```
POST /api/tasks/{task_id}/cancel

Response 200 (cancellation accepted, terminal or already cancelling):
{
  "task_id": str,
  "status": "cancelled" | "cancelling" | "completed" | "failed",
  "cleaned": bool,
  "video_id": str | null,
  "message": str (only when status indicates a no-op)
}

Response 404 if task_id is unknown.
```

Lives in a new router `src/api/routers/tasks.py` (small file — just this one endpoint plus a `GET /api/tasks/{id}` status fetch that already exists scattered across routers; consolidating is optional follow-up).

The endpoint is async (await `tm.cancel_task(...)` directly). It returns when cancellation has either succeeded or timed out at the 5s `wait_for`. That keeps the FE's flow simple — the response carries the final state.

## 3. FE surface

### API client

`ui-app/src/api/client.ts`:

```ts
export interface CancelTaskResponse {
  task_id: string;
  status: 'cancelled' | 'cancelling' | 'completed' | 'failed';
  cleaned: boolean;
  video_id: string | null;
  message?: string;
}

export function cancelTask(taskId: string): Promise<CancelTaskResponse> {
  return request(`/tasks/${taskId}/cancel`, { method: 'POST' });
}
```

### Components

**`ui-app/src/components/pipeline/StopButton.tsx`** (new): a small icon button that opens a confirmation modal, calls `cancelTask`, and reports the result via a parent callback. Reusable across pipeline row, batch row, batch-child row.

```
[⊗ Stop]   →   click   →   modal:
                           ┌─────────────────────────────────────┐
                           │ Stop this pipeline?                 │
                           │                                     │
                           │ All progress will be discarded and  │
                           │ any downloaded / transcribed /      │
                           │ generated files will be deleted.    │
                           │ This can't be undone.               │
                           │                                     │
                           │       [ Keep going ]  [ Stop ]      │
                           └─────────────────────────────────────┘
```

Modal text varies slightly for batch parent: "Stop this batch? N videos in progress will be discarded, their files deleted." (Pass `count` prop to `StopButton`.)

### Integration

- **Pipeline dashboard row** (`ui-app/src/pages/...` — locate the row component that renders per-task progress): add `<StopButton taskId={task.task_id} onCancelled={refresh}/>` next to the progress bar when `task.status === 'running'`.
- **Batch view**: parent row gets `<StopButton taskId={batchTaskId} count={childCount} />`; each child row gets its own button.

### SSE handling

The per-task SSE stream already supports event-type dispatch. Add two new cases in the FE's event handler:

- `'cancelling'`: update row status to "Stopping..." with a spinner; disable the StopButton.
- `'cancelled'`: remove the row (or mark it greyed-out + "Cancelled" depending on whether the page filters by status). Refresh the video list — the video should be gone after `delete_video`.

## 4. Testing strategy

### Unit (fast)

`tests/test_task_cancel.py`:

- `cancel_task` on a queued task → marks cancelled, no subprocess kill, no delete_video call (no video_id yet).
- `cancel_task` on a running task with a fake `_running_subprocess` → `.kill()` is called.
- `cancel_task` on a running task with a `video_id` → `delete_video` is called.
- `cancel_task` on a completed task → returns 200 with `status: completed`, no cleanup.
- `cancel_task` twice in rapid succession → second call sees `cancelling` and returns without re-running cleanup.
- `cancel_task` on a batch parent with two children → both children's `cancel_task` runs first; parent then marks cancelled.
- `cancel_task` where `delete_video` raises → task still marked cancelled, response has `cleaned: false`.

Tests use a mock `_running_subprocess` (a `MagicMock(spec=subprocess.Popen)`) and a fake `_asyncio_task` (a real `asyncio.create_task(asyncio.sleep(10))`). No real ffmpeg subprocess needed for unit coverage.

### Integration (one slow test, `@pytest.mark.integration`)

`tests/test_pipeline_cancel.py::test_cancel_mid_export`:

1. Fire a real ffmpeg-heavy export via the export endpoint.
2. Wait 1s for the subprocess to start.
3. `POST /api/tasks/{task_id}/cancel`.
4. Assert response within 6s (cancel + cleanup + 5s timeout fallback).
5. Assert `data/output/{vid}_export.mp4` does NOT exist.
6. Assert no ffmpeg process still running with our PID as parent.

### Manual (3-min smoke)

1. Start a full pipeline with a real Douyin URL → wait until it reaches translate → click Stop → confirm modal → confirm. Video row disappears. `ls data/srt/{vid}*` returns nothing.
2. Start a batch of 3 URLs → wait until at least 2 are running → click parent Stop → all three children disappear, batch row goes "Cancelled".
3. Stop one child of a 3-URL batch → that one disappears, the other two finish normally.
4. Click Stop on a task that just completed (race) → "Already completed" toast, no destructive action.

## Migration impact

| Surface | Change | User-visible |
|---|---|---|
| Existing CLI `src/pipeline.py` SIGINT path | Unchanged. CLI users keep their resume-from-interrupted flow. | None. |
| Existing API task statuses | Adds `cancelling`, `cancelled` to the union. FE filters that check `=== 'running'` keep working; FE filters that check `!== 'completed'` may now match `cancelled` — audit and adjust. | None directly. |
| `delete_video` | Called from one more place. Already idempotent (every internal file delete is guarded). | None. |
| SSE event types | Adds `cancelling`, `cancelled`. FE handler must add cases. Unknown types are already ignored defensively. | None. |
| Subprocess wrap | Three callsites refactored to use `run_subprocess_tracked`. Same return shape. | None. |

## Out of scope

- "Pause" / "resume" semantics (the CLI's interrupted-state flow stays CLI-only).
- Cancel buttons for dub / single-export / preview-clip / preview-frame tasks. The endpoint handles them; only the FE button is omitted.
- Persistent cancel history. `cancelled` tasks stay in `tm.tasks` for the session; we don't write a "cancelled at X" file to disk.
- Cleanup of stale `bg_tmp/`, `bg_preview_tmp/` directories from PRE-cancel pipelines that crashed without cancel firing — separate housekeeping concern.

## Critical files

- `src/api/task_manager.py` — `Task` dataclass + `cancel_task` + `run_subprocess_tracked` helper.
- `src/api/routers/tasks.py` *(new)* — `POST /api/tasks/{task_id}/cancel` endpoint.
- `src/api/routers/pipeline.py` — every `asyncio.create_task(...)` dispatch grows the `task._asyncio_task = ...` assignment. Batch dispatch populates `_child_task_ids`.
- `src/api/routers/process.py`, `src/api/routers/editor.py` — the two ffmpeg subprocess call sites wrap via `run_subprocess_tracked`.
- `src/transcriber/ocr.py` — long OCR loop adds a `tm.tasks[task_id].status == "cancelling"` early-exit check.
- `ui-app/src/api/client.ts` — `cancelTask` function + `CancelTaskResponse` type.
- `ui-app/src/components/pipeline/StopButton.tsx` *(new)*.
- Pipeline row component(s) in `ui-app/src/pages/` — locate at implementation time; add `<StopButton />` next to progress bar.
- `tests/test_task_cancel.py` *(new)*, `tests/test_pipeline_cancel.py` *(new)*.
