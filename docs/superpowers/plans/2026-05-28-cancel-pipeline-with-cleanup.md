# Cancel a Running Pipeline + Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Stop button to every running async task in the UI. Stopping kills any tracked subprocess, cancels the asyncio task, and runs `delete_video` for full cleanup.

**Architecture:** Extend the existing `Task` dataclass with handles for the asyncio task, the running subprocess, and child task IDs. New `TaskManager.cancel_task(task_id)` orchestrates the kill + delete_video flow. New `POST /api/tasks/{task_id}/cancel` endpoint exposes it. Dispatch sites in routers store the asyncio handle on the task. ffmpeg / OCR / yt-dlp subprocess sites route through a `run_subprocess_tracked` helper so cancellation is instant.

**Tech Stack:** Python 3.11 + FastAPI, asyncio, subprocess, pytest + pytest-asyncio. FE: React 19 + TypeScript + Vitest.

**Reference spec:** [docs/superpowers/specs/2026-05-28-cancel-pipeline-with-cleanup-design.md](../specs/2026-05-28-cancel-pipeline-with-cleanup-design.md)

---

## File layout

**New:**
- `src/api/routers/tasks.py` — `POST /api/tasks/{task_id}/cancel` endpoint.
- `tests/test_task_cancel.py` — unit tests for `Task` model + `cancel_task` + `run_subprocess_tracked`.
- `tests/test_cancel_endpoint.py` — integration test for `POST /api/tasks/{id}/cancel`.
- `ui-app/src/components/pipeline/StopButton.tsx` — confirm-modal + cancel button.
- `ui-app/src/components/pipeline/__tests__/StopButton.test.tsx` — Vitest test.

**Modified:**
- `src/api/task_manager.py` — `Task` dataclass extended, `cancel_task` method, `run_subprocess_tracked` helper.
- `src/api/__init__.py` — register the new `tasks` router.
- `src/api/routers/pipeline.py` — dispatch sites store `_asyncio_task`; batch supervisor wraps each child in its own `asyncio.create_task` and populates `_child_task_ids`.
- `src/api/routers/process.py` — `_run_export_ffmpeg`'s two ffmpeg `subprocess.run` calls route through `run_subprocess_tracked`. Dispatch sites in `export_video` etc. store `_asyncio_task`.
- `src/api/routers/editor.py` — `preview_clip`'s ffmpeg uses `run_subprocess_tracked`. Dispatch site stores `_asyncio_task`.
- `src/api/routers/tts.py` — dispatch sites store `_asyncio_task`.
- `src/transcriber/ocr.py` — frame loop checks `task.status == "cancelling"` and exits early.
- `ui-app/src/api/client.ts` — `cancelTask` function + `CancelTaskResponse` type.
- `ui-app/src/api/types.ts` — `CancelTaskResponse` interface (if separated from client.ts conventions).
- Pipeline row component(s) in `ui-app/src/pages/` — render `<StopButton />` when `status === 'running'`. Implementer locates the right file via grep.
- FE SSE handler (in EditorTab.tsx / dashboard) — add `cancelling` and `cancelled` event cases.

---

## Phase 1: Task model + cancel mechanism

### Task 1: Extend `Task` dataclass with cancellation handles

**Files:**
- Modify: `src/api/task_manager.py`
- Test: `tests/test_task_cancel.py` (new)

- [ ] **Step 1: Write failing tests**

Create `tests/test_task_cancel.py`:

```python
"""Tests for Task model + cancel_task + run_subprocess_tracked."""

from __future__ import annotations

import asyncio
import subprocess
import pytest
from unittest.mock import MagicMock


class TestTaskFields:
    def test_task_has_cancellation_fields(self):
        from src.api.task_manager import Task
        t = Task(task_id="t1", task_type="full_pipeline")
        assert t._asyncio_task is None
        assert t._running_subprocess is None
        assert t._child_task_ids == []

    def test_task_status_can_be_cancelling_or_cancelled(self):
        from src.api.task_manager import Task
        t = Task(task_id="t1", task_type="full_pipeline")
        # The dataclass doesn't constrain status, but document the union.
        t.status = "cancelling"
        assert t.status == "cancelling"
        t.status = "cancelled"
        assert t.status == "cancelled"
```

- [ ] **Step 2: Run, expect failures**

Run: `python -m pytest tests/test_task_cancel.py::TestTaskFields -v`
Expected: 2 FAIL with `AttributeError: 'Task' object has no attribute '_asyncio_task'`.

- [ ] **Step 3: Extend `Task` dataclass**

In `src/api/task_manager.py`, find the existing `@dataclass class Task:` block (around line 21). Add three new fields after `events`:

```python
import asyncio
import subprocess
# … (only add these imports if missing)

@dataclass
class Task:
    task_id: str
    task_type: str
    # status union: queued | running | cancelling | cancelled | completed | failed
    status: str = "queued"
    video_id: str | None = None
    progress: float = 0.0
    message: str = ""
    result: dict | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    events: list[dict] = field(default_factory=list)

    # Cancellation handles — not serialized over API/SSE. The leading
    # underscore signals "internal", matching the existing _emit pattern.
    _asyncio_task: asyncio.Task | None = None
    _running_subprocess: subprocess.Popen | None = None
    _child_task_ids: list[str] = field(default_factory=list)
```

Verify `asyncio` and `subprocess` imports exist at module top. Add if missing.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_task_cancel.py::TestTaskFields -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/task_manager.py tests/test_task_cancel.py
git commit -m "feat(task): add cancellation handles to Task dataclass"
```

---

### Task 2: `run_subprocess_tracked` helper

**Files:**
- Modify: `src/api/task_manager.py`
- Test: `tests/test_task_cancel.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_task_cancel.py`:

```python
class TestRunSubprocessTracked:
    async def test_returns_completed_process(self, tmp_path):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")
        result = await tm.run_subprocess_tracked(
            task.task_id, ["echo", "hello"],
        )
        assert result.returncode == 0
        assert b"hello" in result.stdout

    async def test_clears_running_subprocess_on_completion(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")
        await tm.run_subprocess_tracked(task.task_id, ["true"])
        assert task._running_subprocess is None

    async def test_stores_subprocess_during_execution(self):
        """During the await, _running_subprocess should be the live Popen."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("test")

        async def kill_after_delay():
            await asyncio.sleep(0.05)
            assert task._running_subprocess is not None
            assert isinstance(task._running_subprocess, subprocess.Popen)
            task._running_subprocess.kill()

        killer = asyncio.create_task(kill_after_delay())
        # `sleep 5` should be killed by the killer task in ~50ms
        result = await tm.run_subprocess_tracked(task.task_id, ["sleep", "5"])
        await killer
        assert result.returncode != 0  # killed
```

- [ ] **Step 2: Run, expect failures**

Run: `python -m pytest tests/test_task_cancel.py::TestRunSubprocessTracked -v`
Expected: 3 FAIL with `AttributeError: 'TaskManager' object has no attribute 'run_subprocess_tracked'`.

- [ ] **Step 3: Implement the helper**

In `src/api/task_manager.py`, add a method to the `TaskManager` class (place after `_emit`):

```python
async def run_subprocess_tracked(
    self,
    task_id: str,
    cmd: list[str],
    **kwargs,
) -> subprocess.CompletedProcess:
    """Run a subprocess on a background thread, storing its Popen on the
    Task so cancel_task can kill it. Use this wherever a subprocess might
    run for more than ~1s (ffmpeg, yt-dlp, OCR).

    Captures stdout/stderr by default (callers can override via kwargs).
    Returns a `subprocess.CompletedProcess`. Does NOT raise on non-zero
    exit — callers handle that themselves (so a killed subprocess still
    flows through normally).
    """
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("stderr", subprocess.PIPE)
    proc = subprocess.Popen(cmd, **kwargs)
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

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_task_cancel.py::TestRunSubprocessTracked -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/task_manager.py tests/test_task_cancel.py
git commit -m "feat(task): add run_subprocess_tracked helper for cancellable subprocesses"
```

---

### Task 3: `cancel_task` method

**Files:**
- Modify: `src/api/task_manager.py`
- Test: `tests/test_task_cancel.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_task_cancel.py`:

```python
class TestCancelTask:
    async def test_cancel_queued_task_no_subprocess_no_video(self):
        """Queued tasks cancel cleanly, no video_id, no subprocess to kill."""
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("download")
        # Simulate a real asyncio task so cancel() has something to act on
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "cancelled"
        assert result["cleaned"] is False  # no video_id
        assert result["video_id"] is None
        assert task.status == "cancelled"

    async def test_cancel_kills_running_subprocess(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("export")
        mock_proc = MagicMock(spec=subprocess.Popen)
        task._running_subprocess = mock_proc
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        await tm.cancel_task(task.task_id)
        mock_proc.kill.assert_called_once()

    async def test_cancel_calls_delete_video_when_video_id_set(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid123"
        deleted = []
        monkeypatch.setattr(tm, "delete_video", lambda vid: deleted.append(vid) or True)
        async def sleeper():
            await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert deleted == ["vid123"]
        assert result["cleaned"] is True
        assert result["video_id"] == "vid123"

    async def test_cancel_completed_task_is_noop(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("export")
        task.status = "completed"
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "completed"
        assert result["cleaned"] is False

    async def test_cancel_already_cancelling_returns_noop(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.status = "cancelling"
        result = await tm.cancel_task(task.task_id)
        assert result["status"] == "cancelling"

    async def test_cancel_unknown_task_raises_keyerror(self):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        with pytest.raises(KeyError):
            await tm.cancel_task("no-such-id")

    async def test_cancel_batch_parent_cancels_children(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        parent = tm.create_task("batch_pipeline")
        child_a = tm.create_task("full_pipeline")
        child_b = tm.create_task("full_pipeline")
        parent._child_task_ids = [child_a.task_id, child_b.task_id]
        async def sleeper():
            await asyncio.sleep(10)
        parent._asyncio_task = asyncio.create_task(sleeper())
        child_a._asyncio_task = asyncio.create_task(sleeper())
        child_b._asyncio_task = asyncio.create_task(sleeper())
        await tm.cancel_task(parent.task_id)
        assert child_a.status == "cancelled"
        assert child_b.status == "cancelled"
        assert parent.status == "cancelled"

    async def test_cancel_continues_when_delete_video_raises(self, monkeypatch):
        from src.api.task_manager import TaskManager
        tm = TaskManager()
        task = tm.create_task("full_pipeline")
        task.video_id = "vid"
        def boom(vid): raise RuntimeError("disk full")
        monkeypatch.setattr(tm, "delete_video", boom)
        async def sleeper(): await asyncio.sleep(10)
        task._asyncio_task = asyncio.create_task(sleeper())
        result = await tm.cancel_task(task.task_id)
        assert task.status == "cancelled"
        assert result["cleaned"] is False
```

- [ ] **Step 2: Run, expect failures**

Run: `python -m pytest tests/test_task_cancel.py::TestCancelTask -v`
Expected: 8 FAIL with `AttributeError: 'TaskManager' object has no attribute 'cancel_task'`.

- [ ] **Step 3: Implement `cancel_task`**

In `src/api/task_manager.py`, add to the `TaskManager` class (after `run_subprocess_tracked`):

```python
async def cancel_task(self, task_id: str) -> dict:
    """Cancel a running task, kill its subprocess, and delete_video its
    output. Idempotent on terminal states. Raises KeyError if task_id is
    unknown.

    Returns: {task_id, status, cleaned, video_id, [message]}.
    """
    task = self.tasks.get(task_id)
    if task is None:
        raise KeyError(task_id)

    if task.status in {"completed", "failed", "cancelled"}:
        return {
            "task_id": task_id,
            "status": task.status,
            "cleaned": False,
            "video_id": task.video_id,
            "message": f"Task already in terminal state: {task.status}",
        }

    if task.status == "cancelling":
        return {
            "task_id": task_id,
            "status": "cancelling",
            "cleaned": False,
            "video_id": task.video_id,
            "message": "Already cancelling",
        }

    task.status = "cancelling"
    self._emit(task_id, "cancelling", {"message": "Stopping..."})

    # Recurse into batch children FIRST so we don't race the parent's
    # cleanup. Errors in child cancels are logged but don't block.
    for child_id in list(task._child_task_ids):
        try:
            await self.cancel_task(child_id)
        except Exception as e:
            logger.warning(f"Failed to cancel child {child_id}: {e}")

    # Kill the tracked subprocess (instant teardown of long ffmpeg / yt-dlp).
    if task._running_subprocess is not None:
        try:
            task._running_subprocess.kill()
        except (ProcessLookupError, OSError):
            pass  # already exited

    # Cancel the coroutine. Wait up to 5s for it to exit cleanly.
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
        "video_id": task.video_id,
        "cleaned": cleaned,
    })

    return {
        "task_id": task_id,
        "status": "cancelled",
        "cleaned": cleaned,
        "video_id": task.video_id,
    }
```

Verify `logger` is imported at module top. Add `from src.utils.logger import setup_logger; logger = setup_logger(__name__)` if missing.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_task_cancel.py::TestCancelTask -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add src/api/task_manager.py tests/test_task_cancel.py
git commit -m "feat(task): add cancel_task with subprocess kill + delete_video cleanup"
```

---

### Task 4: `POST /api/tasks/{task_id}/cancel` endpoint

**Files:**
- Create: `src/api/routers/tasks.py`
- Modify: `src/api/__init__.py`
- Test: `tests/test_cancel_endpoint.py` (new)

- [ ] **Step 1: Write failing integration test**

Create `tests/test_cancel_endpoint.py`:

```python
"""Integration tests for POST /api/tasks/{task_id}/cancel."""

from __future__ import annotations

import asyncio
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from src.api import create_app
    return TestClient(create_app())


class TestCancelEndpoint:
    def test_cancel_unknown_task_returns_404(self, client):
        r = client.post("/api/tasks/no-such-id/cancel")
        assert r.status_code == 404

    def test_cancel_running_task_returns_cancelled(self, client):
        from src.api.deps import get_task_manager
        tm = get_task_manager()
        task = tm.create_task("download")

        # Simulate a running task with a no-op coroutine
        async def sleeper():
            await asyncio.sleep(10)
        loop = asyncio.new_event_loop()
        try:
            task._asyncio_task = loop.create_task(sleeper())
            task.status = "running"
            # Drive the cancel through the endpoint
            r = client.post(f"/api/tasks/{task.task_id}/cancel")
            assert r.status_code == 200
            body = r.json()
            assert body["task_id"] == task.task_id
            assert body["status"] == "cancelled"
        finally:
            loop.close()

    def test_cancel_completed_task_returns_terminal_status(self, client):
        from src.api.deps import get_task_manager
        tm = get_task_manager()
        task = tm.create_task("export")
        task.status = "completed"
        r = client.post(f"/api/tasks/{task.task_id}/cancel")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "completed"
        assert body["cleaned"] is False
```

- [ ] **Step 2: Run, expect failures**

Run: `python -m pytest tests/test_cancel_endpoint.py -v`
Expected: 3 FAIL with 404s (router not registered).

- [ ] **Step 3: Create the router**

Create `src/api/routers/tasks.py`:

```python
"""Task lifecycle endpoints — currently just cancel.

Future home for `GET /api/tasks/{id}` consolidation if multiple routers
ever drift on the status shape.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.api.deps import get_task_manager

router = APIRouter()


@router.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running task, kill its subprocess, delete_video its output."""
    tm = get_task_manager()
    try:
        return await tm.cancel_task(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
```

- [ ] **Step 4: Register the router**

In `src/api/__init__.py`, find the imports block (around line 11) and the `include_router` block (around line 42-51).

Add `tasks` to the import:

```python
from src.api.routers import (
    download, transcribe, translate, process, editor,
    settings, pipeline, tts, replacement, events, tasks,
)
```

Add the registration after the other `include_router` calls:

```python
app.include_router(tasks.router)
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_cancel_endpoint.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add src/api/routers/tasks.py src/api/__init__.py tests/test_cancel_endpoint.py
git commit -m "feat(api): POST /api/tasks/{id}/cancel endpoint"
```

---

## Phase 2: Wire dispatch sites

### Task 5: Store `_asyncio_task` at all single-task dispatch sites

**Files:**
- Modify: `src/api/routers/pipeline.py`
- Modify: `src/api/routers/process.py`
- Modify: `src/api/routers/editor.py`
- Modify: `src/api/routers/tts.py`

This is a mechanical refactor across ~7 dispatch sites. Each `asyncio.create_task(...)` becomes a 2-line assignment to `task._asyncio_task`.

- [ ] **Step 1: Locate every dispatch site**

```bash
grep -n "asyncio.create_task" src/api/routers/*.py
```

Expected: ~9 hits across `pipeline.py`, `process.py`, `editor.py`, `tts.py`. Each is preceded by a `tm.create_task(...)` line within ~5 lines.

- [ ] **Step 2: Update each site**

For each `asyncio.create_task(coro_call(...))` that follows a `task = tm.create_task(...)`, change:

```python
# BEFORE
task = tm.create_task("foo")
asyncio.create_task(_run_foo(task.task_id, ...))
```

To:

```python
# AFTER
task = tm.create_task("foo")
task._asyncio_task = asyncio.create_task(_run_foo(task.task_id, ...))
```

The dispatch sites (verify the exact line via grep before editing):
- `src/api/routers/pipeline.py` around lines 54-55 (`pipeline` task)
- `src/api/routers/pipeline.py` around lines 76-86 (`full_pipeline` task — note `asyncio.create_task` may be on a separate line)
- `src/api/routers/pipeline.py` around lines 615-617 (`full_pipeline` task for retry)
- `src/api/routers/process.py` around lines 56-57 (`process` task)
- `src/api/routers/process.py` around line 402 (`export` task inside `run_export`)
- `src/api/routers/editor.py` around line 508 (`preview_clip` task inside `run_preview`)
- `src/api/routers/tts.py` around lines 33-34 (`tts` task)
- `src/api/routers/tts.py` around line 149 (`dub_sync` task)

For the `run_export` / `run_preview` patterns where `asyncio.create_task` calls a *local* coroutine `async def run_export()`, the assignment goes to the same variable:

```python
# BEFORE
task = tm.create_task("export")
# ... build run_export() locally ...
asyncio.create_task(run_export())

# AFTER
task = tm.create_task("export")
# ... build run_export() locally ...
task._asyncio_task = asyncio.create_task(run_export())
```

- [ ] **Step 3: Smoke-check imports**

Each modified file should already import `asyncio`. Verify with:

```bash
grep -n "^import asyncio" src/api/routers/pipeline.py src/api/routers/process.py src/api/routers/editor.py src/api/routers/tts.py
```

If any file is missing `import asyncio` at the top, add it.

- [ ] **Step 4: Run the full unit suite**

Run: `python -m pytest tests/ -q --ignore=tests/integration`
Expected: same green count as before this task (no regressions). The new tests from Tasks 1-4 still pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/routers/pipeline.py src/api/routers/process.py src/api/routers/editor.py src/api/routers/tts.py
git commit -m "feat(task): dispatch sites store asyncio.Task handle for cancellation"
```

---

### Task 6: Batch supervisor wraps children in individual asyncio tasks

**Files:**
- Modify: `src/api/routers/pipeline.py`

The current batch supervisor (`_run_batch_pipeline`, around line 340) creates per-URL coroutines and runs them via `asyncio.gather`. Children DON'T have individual asyncio.Task handles. To support per-child cancel, wrap each `process_one(...)` call in its own `asyncio.create_task`.

- [ ] **Step 1: Locate the batch supervisor**

```bash
grep -n "_run_batch_pipeline\|async def process_one\|asyncio.gather" src/api/routers/pipeline.py | head -10
```

Find the section where `tasks = [process_one(i, url, tid) for ...]` is constructed (around line 388).

- [ ] **Step 2: Wrap each child + record on parent**

Locate this block (around lines 388-392):

```python
tasks = [
    process_one(i, url, tid)
    for i, (url, tid) in enumerate(zip(urls, task_ids))
]
await asyncio.gather(*tasks, return_exceptions=True)
```

Replace it with:

```python
child_asyncio_tasks = []
for i, (url, tid) in enumerate(zip(urls, task_ids)):
    child = tm.tasks[tid]
    # Each child gets its own asyncio.Task so it can be cancelled
    # independently. Parent's _child_task_ids records the link.
    child._asyncio_task = asyncio.create_task(process_one(i, url, tid))
    batch_task._child_task_ids.append(tid)
    child_asyncio_tasks.append(child._asyncio_task)

await asyncio.gather(*child_asyncio_tasks, return_exceptions=True)
```

- [ ] **Step 3: Run unit suite**

Run: `python -m pytest tests/ -q --ignore=tests/integration`
Expected: still green.

- [ ] **Step 4: Commit**

```bash
git add src/api/routers/pipeline.py
git commit -m "feat(batch): wrap children in individual asyncio.Tasks + populate _child_task_ids"
```

---

## Phase 3: Subprocess kill integration

### Task 7: Wrap ffmpeg in `_run_export_ffmpeg` with `run_subprocess_tracked`

**Files:**
- Modify: `src/api/routers/process.py`

`_run_export_ffmpeg` calls `subprocess.run([ffmpeg, ...])` twice (step 1 = burn-in, step 2 = TTS mux). Both can take 30s-2min. We route them through the tracked helper so cancel can kill them instantly.

- [ ] **Step 1: Locate the two ffmpeg calls**

```bash
grep -n "subprocess.run\|FFmpegProcessor\._run_ffmpeg\|cmd1\|cmd2" src/api/routers/process.py | head -10
```

Find the two ffmpeg execution sites in `_run_export_ffmpeg` (likely uses `proc.run` or a local subprocess.run call).

- [ ] **Step 2: Pass task_id into `_run_export_ffmpeg`**

The function currently takes `video_id: str | None = None`. Add `task_id: str | None = None` to the signature (after `video_id`):

```python
def _run_export_ffmpeg(
    video_path: Path,
    subtitle_path: Path | None,
    tts_path: Path | None,
    output_path: Path,
    resolution: str | None,
    video_volume: float,
    tts_volume: float,
    seek_seconds: float | None = None,
    duration_seconds: float | None = None,
    video_id: str | None = None,
    task_id: str | None = None,
) -> None:
```

**Note:** `_run_export_ffmpeg` is currently synchronous. To call `run_subprocess_tracked` (which is async), we have two options:
- A: Convert `_run_export_ffmpeg` to `async def` and `await` the tracked subprocess.
- B: Keep it sync; have the caller run it via `asyncio.to_thread` and pass a callback or use a different sync-side subprocess tracking primitive.

Pick **Option A** — `async def`. Concretely:

```python
async def _run_export_ffmpeg(...) -> None:
    ...
```

Inside the function, replace both `subprocess.run([...])` (or equivalent) calls with:

```python
tm = get_task_manager() if task_id else None
result = await tm.run_subprocess_tracked(task_id, cmd) if tm else \
    subprocess.run(cmd, capture_output=True)
if result.returncode != 0:
    raise RuntimeError(f"ffmpeg failed: {result.stderr.decode()[-500:]}")
```

(`get_task_manager` is already imported in `process.py` for the endpoint handlers — verify with `grep -n "get_task_manager" src/api/routers/process.py`.)

- [ ] **Step 3: Update callers**

`_run_export_ffmpeg` is called from `export_video` and `preview_export` and possibly the integration test. Each call site currently does `await asyncio.to_thread(_run_export_ffmpeg, ...)`. After the async conversion, change to `await _run_export_ffmpeg(..., task_id=task.task_id)`.

Locate via:

```bash
grep -n "_run_export_ffmpeg" src/api/routers/process.py tests/
```

Update each call site to pass `task_id` and drop the `asyncio.to_thread` wrapper.

- [ ] **Step 4: Run the suite**

```bash
python -m pytest tests/ -q --ignore=tests/integration
```

Expected: still green. The integration test `tests/test_export_style.py` calls `_run_export_ffmpeg` directly — verify it still works (it has no task_id, so the helper falls back to `subprocess.run`).

- [ ] **Step 5: Commit**

```bash
git add src/api/routers/process.py
git commit -m "feat(export): track ffmpeg subprocess so cancel can kill it instantly"
```

---

### Task 8: Wrap preview_clip ffmpeg with `run_subprocess_tracked`

**Files:**
- Modify: `src/api/routers/editor.py`

- [ ] **Step 1: Locate the ffmpeg call in preview_clip**

```bash
grep -n "subprocess.run\|subprocess.Popen" src/api/routers/editor.py | head -10
```

Inside `run_preview` (the inner async function around line 410+), find the `subprocess.run([ffmpeg, ...])` or `await asyncio.to_thread(subprocess.run, ...)` call.

- [ ] **Step 2: Replace with tracked helper**

```python
# BEFORE (illustrative — match the actual existing code)
await asyncio.to_thread(
    subprocess.run, cmd, capture_output=True, check=True, timeout=120,
)

# AFTER
result = await tm.run_subprocess_tracked(task.task_id, cmd)
if result.returncode != 0:
    raise subprocess.CalledProcessError(
        result.returncode, cmd, output=result.stdout, stderr=result.stderr,
    )
```

(`tm` is already in scope via `tm = get_task_manager()` at the top of the endpoint. Verify.)

- [ ] **Step 3: Run unit suite**

```bash
python -m pytest tests/ -q --ignore=tests/integration
```

Expected: still green.

- [ ] **Step 4: Commit**

```bash
git add src/api/routers/editor.py
git commit -m "feat(preview): track preview_clip ffmpeg subprocess for cancellation"
```

---

### Task 9: OCR loop checks `cancelling` status

**Files:**
- Modify: `src/transcriber/ocr.py`

The OCR transcribe loop iterates over frames, each iteration costing 200-500ms. Adding a cancel check is cheap.

- [ ] **Step 1: Locate the frame loop**

```bash
grep -n "for i, frame_path in enumerate(frames)" src/transcriber/ocr.py
```

Two hits around lines 210 and 280. We add the check to BOTH.

- [ ] **Step 2: Pass `task_id` into the transcribe function**

Find the `transcribe(...)` method signature (around line 131). It's called from `task_manager.py::run_transcribe`. Add an optional `task_id: str | None = None` parameter.

```python
def transcribe(
    self,
    video_path: str,
    lang: str,
    mode: str = "transcribe",
    task_id: str | None = None,  # NEW
) -> list[dict]:
```

Inside each frame loop, after the loop body's first line, add:

```python
for i, frame_path in enumerate(frames):
    # Cancel check: short-circuit if the task is being cancelled.
    if task_id is not None:
        from src.api.task_manager import get_task_manager_instance
        tm = get_task_manager_instance()
        if tm is not None:
            task = tm.tasks.get(task_id)
            if task is not None and task.status == "cancelling":
                logger.info(f"OCR loop cancelled at frame {i}/{len(frames)}")
                return segments  # exit early; partial data
    # … existing frame processing …
```

**Wait — `get_task_manager_instance` doesn't exist.** Add a module-level accessor in `src/api/task_manager.py`:

```python
# At module top, after class definitions
_INSTANCE: TaskManager | None = None

def get_task_manager_instance() -> TaskManager | None:
    """Return the global TaskManager singleton if initialised, else None.

    Modules that need to introspect task state (e.g. OCR loop checking
    for cancellation) call this rather than importing TaskManager directly
    to avoid circular imports.
    """
    global _INSTANCE
    return _INSTANCE

def _set_task_manager_instance(tm: TaskManager) -> None:
    global _INSTANCE
    _INSTANCE = tm
```

And in `src/api/deps.py` (or wherever the singleton is created), call `_set_task_manager_instance(tm)` after constructing it. Look at `get_task_manager` to see the existing pattern:

```bash
grep -n "def get_task_manager\b\|TaskManager()" src/api/deps.py
```

Adjust accordingly.

- [ ] **Step 3: Pass `task_id` through `run_transcribe`**

In `src/api/task_manager.py::run_transcribe`, find where it calls the transcriber's `transcribe(...)`. Add `task_id=task_id` to the kwargs.

```bash
grep -n "transcriber.transcribe\|\.transcribe(" src/api/task_manager.py
```

- [ ] **Step 4: Run suite**

```bash
python -m pytest tests/ -q --ignore=tests/integration
```

Expected: still green.

- [ ] **Step 5: Commit**

```bash
git add src/transcriber/ocr.py src/api/task_manager.py src/api/deps.py
git commit -m "feat(ocr): exit transcribe loop early when task status is cancelling"
```

---

## Phase 4: Frontend

### Task 10: Add `cancelTask` API client function

**Files:**
- Modify: `ui-app/src/api/client.ts`

- [ ] **Step 1: Append to client.ts**

Find the end of the file and append:

```ts
// ── Task cancellation ────────────────────────────────────────────────

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

- [ ] **Step 2: Typecheck**

```bash
cd ui-app && npx tsc -b --noEmit
```

Expected: no NEW errors beyond pre-existing.

- [ ] **Step 3: Commit**

```bash
git add ui-app/src/api/client.ts
git commit -m "feat(fe): cancelTask client function + CancelTaskResponse type"
```

---

### Task 11: `StopButton` component

**Files:**
- Create: `ui-app/src/components/pipeline/StopButton.tsx`
- Create: `ui-app/src/components/pipeline/__tests__/StopButton.test.tsx`

- [ ] **Step 1: Write failing test**

Create the test directory + file:

```bash
mkdir -p ui-app/src/components/pipeline/__tests__
```

Create `ui-app/src/components/pipeline/__tests__/StopButton.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { StopButton } from '../StopButton';

// Mock the API call
vi.mock('../../../api/client', () => ({
  cancelTask: vi.fn(() => Promise.resolve({
    task_id: 't1',
    status: 'cancelled',
    cleaned: true,
    video_id: 'vid1',
  })),
}));

describe('StopButton', () => {
  it('renders the Stop label', () => {
    render(<StopButton taskId="t1" />);
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument();
  });

  it('opens confirm modal on click, does not cancel immediately', async () => {
    const onCancelled = vi.fn();
    render(<StopButton taskId="t1" onCancelled={onCancelled} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    // Modal opens
    expect(screen.getByText(/can't be undone/i)).toBeInTheDocument();
    // Callback NOT yet called
    expect(onCancelled).not.toHaveBeenCalled();
  });

  it('confirms and calls cancelTask + onCancelled', async () => {
    const { cancelTask } = await import('../../../api/client');
    const onCancelled = vi.fn();
    render(<StopButton taskId="t1" onCancelled={onCancelled} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    // Click the confirm button in modal
    fireEvent.click(screen.getByRole('button', { name: /^stop and delete/i }));
    await waitFor(() => expect(cancelTask).toHaveBeenCalledWith('t1'));
    await waitFor(() => expect(onCancelled).toHaveBeenCalled());
  });

  it('shows custom batch text when count > 1', () => {
    render(<StopButton taskId="b1" count={3} />);
    fireEvent.click(screen.getByRole('button', { name: /stop/i }));
    expect(screen.getByText(/3 videos in progress/i)).toBeInTheDocument();
  });
});
```

If `@testing-library/react` isn't installed, install it:

```bash
cd ui-app && npm install -D @testing-library/react @testing-library/jest-dom jsdom
```

You'll also need a vitest config that uses jsdom. Check `vitest.config.ts` or `vite.config.ts` and add `environment: 'jsdom'` to the test config:

```ts
// vitest.config.ts (create if missing)
import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: { environment: 'jsdom' },
});
```

- [ ] **Step 2: Run, expect failure**

```bash
cd ui-app && npx vitest run src/components/pipeline/__tests__/StopButton.test.tsx
```

Expected: FAIL (module not found).

- [ ] **Step 3: Implement StopButton**

Create `ui-app/src/components/pipeline/StopButton.tsx`:

```tsx
import { useState } from 'react';
import { cancelTask } from '../../api/client';
import type { CancelTaskResponse } from '../../api/client';

interface Props {
  taskId: string;
  /** When set and > 1, modal text reads "Stop this batch?" with the count. */
  count?: number;
  /** Called after the cancel API call returns. */
  onCancelled?: (response: CancelTaskResponse) => void;
}

export function StopButton({ taskId, count, onCancelled }: Props) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isBatch = (count ?? 1) > 1;

  const handleConfirm = async () => {
    setCancelling(true);
    setError(null);
    try {
      const result = await cancelTask(taskId);
      setConfirmOpen(false);
      onCancelled?.(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Cancel failed');
    } finally {
      setCancelling(false);
    }
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setConfirmOpen(true)}
        disabled={cancelling}
        className="px-2 py-1 text-[10px] font-mono uppercase tracking-tighter font-bold text-amber-400 hover:text-amber-300 border border-amber-500/30 hover:border-amber-500/60 rounded transition-colors"
      >
        {cancelling ? 'Stopping…' : '⊗ Stop'}
      </button>
      {confirmOpen && (
        <div
          className="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
          onClick={() => !cancelling && setConfirmOpen(false)}
        >
          <div
            className="bg-surface-container-low rounded-xl p-6 max-w-md mx-4 border border-outline-variant/20"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold uppercase tracking-widest mb-3 text-on-surface">
              {isBatch ? 'Stop this batch?' : 'Stop this pipeline?'}
            </h3>
            <p className="text-xs text-on-surface-variant mb-5 leading-relaxed">
              {isBatch
                ? `${count} videos in progress will be discarded, and any downloaded / transcribed / generated files will be deleted.`
                : "All progress will be discarded and any downloaded / transcribed / generated files will be deleted."}
              {' '}
              <span className="text-amber-400 font-bold">This can't be undone.</span>
            </p>
            {error && (
              <p className="text-xs text-red-400 font-mono mb-3">{error}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setConfirmOpen(false)}
                disabled={cancelling}
                className="px-4 py-2 text-xs font-bold uppercase tracking-widest text-on-surface-variant hover:text-on-surface transition-colors"
              >
                Keep going
              </button>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={cancelling}
                className="px-4 py-2 text-xs font-bold uppercase tracking-widest bg-amber-500/80 hover:bg-amber-500 text-on-primary-fixed rounded transition-colors disabled:opacity-50"
              >
                {cancelling ? 'Stopping…' : 'Stop and delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 4: Run tests**

```bash
cd ui-app && npx vitest run src/components/pipeline/__tests__/StopButton.test.tsx
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add ui-app/src/components/pipeline/StopButton.tsx \
        ui-app/src/components/pipeline/__tests__/StopButton.test.tsx \
        ui-app/package.json ui-app/package-lock.json \
        ui-app/vitest.config.ts  # if newly created
git commit -m "feat(fe): StopButton component with confirm modal"
```

---

### Task 12: Wire StopButton into pipeline row(s)

**Files:**
- Modify: Pipeline dashboard / row component(s) in `ui-app/src/pages/` (locate via grep)

- [ ] **Step 1: Locate where pipeline rows are rendered**

```bash
grep -rn "task.status\|task_type.*full_pipeline\|task_type.*batch_pipeline\|progress.*%" ui-app/src/pages/ | head -20
```

The most likely candidates are `ui-app/src/pages/DownloadTranscribe.tsx` or a dashboard page that shows active tasks. Open the file(s) and find the JSX that renders one task row.

- [ ] **Step 2: Add StopButton next to the progress bar**

For each per-task row (where status can be 'running'), add:

```tsx
import { StopButton } from '../components/pipeline/StopButton';

// Inside the row JSX, after the progress bar:
{task.status === 'running' && (
  <StopButton
    taskId={task.task_id}
    onCancelled={() => {
      // Refresh task list / video list. Use whatever pattern the
      // page uses for refresh (refetch, state mutation, etc.).
      refreshTasks();  // adjust to actual function name
    }}
  />
)}
```

For batch parent rows, pass `count` as the number of in-progress children:

```tsx
{task.task_type === 'batch_pipeline' && task.status === 'running' && (
  <StopButton
    taskId={task.task_id}
    count={task.result?.task_ids?.length ?? 0}
    onCancelled={() => refreshTasks()}
  />
)}
```

- [ ] **Step 3: TypeScript check + vite build**

```bash
cd ui-app && npx tsc -b --noEmit && npx vite build
```

Expected: no NEW errors. Bundle builds.

- [ ] **Step 4: Commit**

```bash
git add ui-app/src/pages/  # whichever file(s) you touched
git commit -m "feat(fe): pipeline rows expose StopButton when running"
```

---

### Task 13: SSE event handlers for cancelling / cancelled

**Files:**
- Modify: wherever per-task SSE events are consumed (likely the same page file as Task 12, plus any other listeners)

- [ ] **Step 1: Locate the SSE subscriber for task events**

```bash
grep -rn "subscribeSSE\|EventSource\|onmessage\|case 'progress'" ui-app/src/ | head -15
```

Find the switch / if-chain over event types.

- [ ] **Step 2: Add `cancelling` and `cancelled` cases**

Inside the event handler, after the existing `progress` / `complete` / `error` cases:

```tsx
case 'cancelling':
  // Mark the row as stopping; disable any per-row controls.
  setTaskState(taskId, { status: 'cancelling', message: 'Stopping…' });
  break;
case 'cancelled':
  // Refresh the task + video list. The video itself was deleted by the
  // backend's delete_video call, so the row should disappear.
  setTaskState(taskId, { status: 'cancelled', message: 'Cancelled' });
  refreshTasks();
  refreshVideos();
  break;
```

Adjust function names to whatever the page actually uses for state updates.

- [ ] **Step 3: Vite build**

```bash
cd ui-app && npx vite build
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add ui-app/src/  # whichever files
git commit -m "feat(fe): SSE handlers for cancelling + cancelled events"
```

---

## Phase 5: Integration test + ship

### Task 14: Integration test — cancel mid-export

**Files:**
- Create: `tests/test_pipeline_cancel_integration.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_pipeline_cancel_integration.py`:

```python
"""Integration: cancelling a running task kills the subprocess + cleans up."""

from __future__ import annotations

import asyncio
import subprocess
import time
from pathlib import Path

import pytest


@pytest.mark.integration
async def test_cancel_kills_running_subprocess():
    """run_subprocess_tracked + cancel_task end-to-end with a real sleep."""
    from src.api.task_manager import TaskManager
    tm = TaskManager()
    task = tm.create_task("test")

    async def long_subprocess():
        # `sleep 30` simulates a long ffmpeg encode.
        await tm.run_subprocess_tracked(task.task_id, ["sleep", "30"])
        return "completed"

    task._asyncio_task = asyncio.create_task(long_subprocess())
    await asyncio.sleep(0.2)  # let the subprocess actually start
    assert task._running_subprocess is not None
    assert task._running_subprocess.poll() is None  # still running

    # Cancel — should take well under 5s.
    start = time.monotonic()
    result = await tm.cancel_task(task.task_id)
    elapsed = time.monotonic() - start

    assert elapsed < 5.0, f"cancel took {elapsed:.2f}s — too slow"
    assert result["status"] == "cancelled"
    assert task.status == "cancelled"


@pytest.mark.integration
async def test_cancel_with_video_id_runs_delete_video(tmp_path, monkeypatch):
    """End-to-end: cancel a task with a video_id → delete_video fires →
    per-video files are removed."""
    from src.api.task_manager import TaskManager
    tm = TaskManager()

    # Lay out a fake video to verify it gets cleaned up.
    raw_dir = tmp_path / "data" / "raw"; raw_dir.mkdir(parents=True)
    srt_dir = tmp_path / "data" / "srt"; srt_dir.mkdir(parents=True)
    video_id = "test_cancel_vid"
    (raw_dir / f"{video_id}.mp4").write_bytes(b"fake mp4")
    (srt_dir / f"{video_id}_vi.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nx\n")

    monkeypatch.chdir(tmp_path)

    task = tm.create_task("full_pipeline")
    task.video_id = video_id

    async def sleeper():
        await asyncio.sleep(5)
    task._asyncio_task = asyncio.create_task(sleeper())

    result = await tm.cancel_task(task.task_id)

    assert result["cleaned"] is True
    assert not (raw_dir / f"{video_id}.mp4").exists()
    assert not (srt_dir / f"{video_id}_vi.srt").exists()
```

- [ ] **Step 2: Run the test**

```bash
python -m pytest tests/test_pipeline_cancel_integration.py -v -m integration
```

Expected: 2 passed in ~1-2s.

- [ ] **Step 3: Commit**

```bash
git add tests/test_pipeline_cancel_integration.py
git commit -m "test(cancel): integration test for kill + cleanup end-to-end"
```

---

### Task 15: Manual smoke + CHANGELOG + ship

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: Manual smoke test**

Rebuild:

```bash
make docker-rebuild
```

In the UI:

1. Start a full pipeline with a real Douyin URL. Wait until it's in download or transcribe stage.
2. Find the row in the dashboard. Click `⊗ Stop`. Confirm in modal.
3. Within ~5s the row should turn `Cancelled` (or disappear if the page filters by status). The video shouldn't appear in the video list.
4. `ls data/raw/` and `ls data/srt/` — confirm no files for the cancelled video_id.
5. Repeat with a batch of 2-3 URLs:
   a. Cancel one child mid-batch → that child disappears, others continue.
   b. Cancel the batch parent → all children disappear, batch row goes Cancelled.
6. Try cancelling a task that just completed (race) → should report "already completed" / no destructive action.

If any step fails, add a follow-up task; do not check this box until clean.

- [ ] **Step 2: Update CHANGELOG**

Append to `CHANGELOG.md` under `## [Unreleased]`:

```markdown
### Added
- **Cancel a running pipeline + automatic cleanup.** New `POST /api/tasks/{task_id}/cancel` endpoint kills any tracked ffmpeg / OCR / yt-dlp subprocess, cancels the asyncio task, and runs `delete_video` for full per-video cleanup. Batch-aware: cancelling a batch parent cancels all in-flight children with cleanup; per-child cancel works independently without affecting siblings. FE: `⊗ Stop` button next to every running task row, with a confirmation modal ("All progress will be discarded… This can't be undone"). Idempotent on terminal states (cancelling a completed task is a clear no-op). The `Task` model gains `_asyncio_task`, `_running_subprocess`, `_child_task_ids` internal handles. Long-running subprocesses now route through `TaskManager.run_subprocess_tracked` so the cancel kill is instant rather than waiting for the subprocess to return.
```

- [ ] **Step 3: README checklist**

In `README.md`, add a new section under "Implementation Progress":

```markdown
### Cancel Pipeline With Cleanup (2026-05-28)

> Design: [`docs/superpowers/specs/2026-05-28-cancel-pipeline-with-cleanup-design.md`](docs/superpowers/specs/2026-05-28-cancel-pipeline-with-cleanup-design.md)
> Plan: [`docs/superpowers/plans/2026-05-28-cancel-pipeline-with-cleanup.md`](docs/superpowers/plans/2026-05-28-cancel-pipeline-with-cleanup.md)

- [x] Task 1 — Task dataclass cancellation handles
- [x] Task 2 — run_subprocess_tracked helper
- [x] Task 3 — TaskManager.cancel_task method
- [x] Task 4 — POST /api/tasks/{id}/cancel endpoint
- [x] Task 5 — Dispatch sites store _asyncio_task
- [x] Task 6 — Batch supervisor wraps children individually
- [x] Task 7 — _run_export_ffmpeg tracks subprocess
- [x] Task 8 — preview_clip tracks subprocess
- [x] Task 9 — OCR loop cancels mid-frame
- [x] Task 10 — cancelTask FE client + types
- [x] Task 11 — StopButton component
- [x] Task 12 — StopButton wired into pipeline rows
- [x] Task 13 — SSE cancelling / cancelled event handlers
- [x] Task 14 — Integration test
```

- [ ] **Step 4: Open PR**

```bash
git add CHANGELOG.md README.md
git commit -m "docs(cancel): CHANGELOG + README rollup"
git push -u origin feature/cancel-pipeline-with-cleanup
gh pr create --title "Cancel a running pipeline with cleanup" --body "$(cat <<'EOF'
## Summary

Implements [docs/superpowers/specs/2026-05-28-cancel-pipeline-with-cleanup-design.md](docs/superpowers/specs/2026-05-28-cancel-pipeline-with-cleanup-design.md).

Adds a `⊗ Stop` button to every running async task in the UI. Cancelling:
- kills any tracked ffmpeg / OCR / yt-dlp subprocess immediately
- cancels the asyncio task
- runs `delete_video` to wipe all per-video files

Batch-aware: parent cancel kills all children; per-child cancel works without affecting siblings.

## Test plan

- [x] Unit tests for Task model, run_subprocess_tracked, cancel_task (8+ tests)
- [x] Endpoint integration tests for /api/tasks/{id}/cancel (3 tests)
- [x] Vitest tests for StopButton (4 tests)
- [x] Integration test: real subprocess kill + delete_video cleanup
- [ ] Manual smoke: cancel full pipeline, cancel batch parent, cancel batch child, cancel completed task
EOF
)"
```

---

## Spec coverage check

| Spec section | Implemented in |
|---|---|
| §1 Cancellation mechanism — Task model | Task 1 |
| §1 — run_subprocess_tracked helper | Task 2 |
| §1 — cancel_task method | Task 3 |
| §1 — Dispatch-site wiring | Task 5 |
| §1 — Batch children wrapped individually | Task 6 |
| §1 — Subprocess kill for ffmpeg / OCR | Tasks 7, 8, 9 |
| §2 — POST /api/tasks/{id}/cancel endpoint | Task 4 |
| §3 — FE client `cancelTask` | Task 10 |
| §3 — StopButton component | Task 11 |
| §3 — Pipeline row integration | Task 12 |
| §3 — SSE cancelling/cancelled handlers | Task 13 |
| §4 — Unit tests | Tasks 1, 2, 3 |
| §4 — Endpoint integration tests | Task 4 |
| §4 — End-to-end integration test | Task 14 |
| §4 — Manual smoke | Task 15 |
| Migration impact (CHANGELOG) | Task 15 |
