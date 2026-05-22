"""Pipeline endpoints — single, batch, history, retry, stats."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import get_config, get_task_manager
from src.api.models import (
    BatchPipelineRequest,
    FullPipelineRequest,
    PipelineHistoryEntry,
    PipelineRequest,
    TaskResponse,
)
from src.utils.state import PipelineState, get_all_states, create_pipeline_run, update_pipeline_run, get_pipeline_runs

router = APIRouter()


# --- Existing: download → transcribe → translate pipeline ---


@router.post("/api/pipeline", response_model=TaskResponse)
async def start_pipeline(request: PipelineRequest):
    """Run download → transcribe → translate pipeline (existing behavior)."""
    tm = get_task_manager()
    config = get_config()

    task = tm.create_task("pipeline")
    asyncio.create_task(
        tm.run_pipeline(
            task.task_id,
            url=request.url,
            translate_profile=request.translate_profile,
            source_language=request.source_language,
            config=config,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


# --- Full pipeline: download → transcribe → translate → process → upload ---


@router.post("/api/pipeline/full", response_model=TaskResponse)
async def start_full_pipeline(request: FullPipelineRequest):
    """Run the full pipeline including process and upload stages."""
    tm = get_task_manager()
    config = get_config()

    task = tm.create_task("full_pipeline")

    # Persist pipeline run
    create_pipeline_run(
        run_id=task.task_id,
        mode="single",
        urls=[request.url],
        platforms=request.platforms,
    )

    asyncio.create_task(
        _run_full_pipeline(
            task_id=task.task_id,
            url=request.url,
            platforms=request.platforms,
            auto_upload=request.auto_upload,
            translate_profile=request.translate_profile,
            translation_override=request.translation_override,
            source_language=request.source_language,
            force=request.force,
            config=config,
            tts_profile=request.tts_profile,
            blur_enabled=request.blur_enabled,
            tts_provider=request.tts_provider,
            tts_voice=request.tts_voice,
            tts_api_key=request.tts_api_key,
            llm_api_key=request.llm_api_key,
            llm_backend=request.llm_backend,
            playback_speed=request.playback_speed,
            underlay_db=request.underlay_db,
            subtitle_style=request.subtitle_style,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


async def _run_full_pipeline(
    task_id: str,
    url: str,
    platforms: list[str],
    auto_upload: bool,
    translate_profile: str | None,
    source_language: str,
    force: bool,
    config: dict,
    translation_override: dict | None = None,
    tts_profile: str | None = None,
    blur_enabled: bool = True,
    tts_provider: str | None = None,
    tts_voice: str | None = None,
    tts_api_key: str | None = None,
    llm_api_key: str | None = None,
    llm_backend: str | None = None,
    playback_speed: float | None = None,
    underlay_db: float | None = None,
    subtitle_style: dict | None = None,
):
    """Execute the full pipeline as a background task with SSE events."""
    from src.pipeline import Pipeline

    tm = get_task_manager()
    task = tm.tasks[task_id]
    task.status = "running"

    def emit(stage: str, progress: float, message: str):
        task.progress = progress
        task.message = message
        task.current_stage = stage
        tm._emit(task_id, "progress", {
            "stage": stage,
            "progress": progress,
            "message": message,
        })

    try:
        # Apply LLM override from UI if provided
        if translation_override:
            cfg = {**config}
            cfg["translation"] = {**cfg.get("translation", {}), **translation_override}
        else:
            cfg = config
        pipeline = Pipeline(cfg)
        options = {
            "force": force,
            "subtitle_lang": source_language,
            "translate_profile": translate_profile,
            "tts_profile": tts_profile,
            "blur_enabled": blur_enabled,
            "tts_provider": tts_provider,
            "tts_voice": tts_voice,
            "tts_api_key": tts_api_key,
            "llm_api_key": llm_api_key,
            "llm_backend": llm_backend,
            "playback_speed": playback_speed,
            "underlay_db": underlay_db,
            "subtitle_style": subtitle_style,
        }

        result = await pipeline.process_single(url, platforms, options, emit)

        if result.get("status") == "done":
            task.status = "completed"
            task.progress = 1.0
            task.video_id = result.get("video_id")
            task.result = result

            # Register video in task manager index so FE can see it immediately
            vid = result.get("video_id", "")
            if vid and vid not in tm.video_index:
                from src.api.models import VideoResponse
                from src.utils.metadata import extract_metadata_from_file
                raw_path = Path(f"data/raw/{vid}.mp4")
                srt_dir = Path("data/srt")
                meta_path = Path(f"data/raw/{vid}.json")
                saved_meta = {}
                if meta_path.exists():
                    import json as _json
                    saved_meta = _json.loads(meta_path.read_text())
                file_meta = extract_metadata_from_file(raw_path) if raw_path.exists() else {}
                srt_langs = sorted({
                    p.stem.split("_", 1)[-1]
                    for p in srt_dir.glob(f"{vid}_*.srt")
                })
                thumb_path = Path(f"data/raw/{vid}_thumb.jpg")
                size_bytes = raw_path.stat().st_size if raw_path.exists() else 0
                tm.video_index[vid] = VideoResponse(
                    video_id=vid,
                    title=saved_meta.get("title", vid),
                    author=saved_meta.get("author", ""),
                    duration=saved_meta.get("duration", file_meta.get("duration", 0.0)),
                    resolution=file_meta.get("resolution", ""),
                    size=f"{size_bytes / (1024*1024):.1f} MB",
                    codec=file_meta.get("codec", ""),
                    description=saved_meta.get("description", ""),
                    hashtags=saved_meta.get("hashtags", []),
                    source_url=saved_meta.get("source_url", ""),
                    file_path=str(raw_path),
                    thumbnail=f"/files/raw/{vid}_thumb.jpg" if thumb_path.exists() else "",
                    has_srt=bool(srt_langs),
                    srt_languages=srt_langs,
                    status="transcribed" if srt_langs else "downloaded",
                )

            tm._emit(task_id, "complete", result)
            update_pipeline_run(task_id, {
                "status": "done",
                "video_ids": [result.get("video_id", "")],
                "succeeded": 1,
            })
        elif result.get("status") == "skipped":
            task.status = "completed"
            task.message = result.get("message", "Skipped")
            task.result = result
            tm._emit(task_id, "complete", result)
            update_pipeline_run(task_id, {
                "status": "skipped",
                "video_ids": [result.get("video_id", "")],
            })
        else:
            task.status = "failed"
            task.error = result.get("error", "Unknown error")
            tm._emit(task_id, "error", {"message": task.error})
            update_pipeline_run(task_id, {
                "status": "failed",
                "errors": [{"url": url, "error": task.error}],
                "failed": 1,
            })

    except Exception as e:
        task.status = "failed"
        task.error = str(e)
        tm._emit(task_id, "error", {"message": str(e)})
        update_pipeline_run(task_id, {
            "status": "failed",
            "errors": [{"url": url, "error": str(e)}],
            "failed": 1,
        })


# --- Batch pipeline ---


@router.post("/api/pipeline/batch")
async def start_batch_pipeline(request: BatchPipelineRequest):
    """Start batch processing of multiple URLs."""
    tm = get_task_manager()
    config = get_config()

    # Create a parent task for the batch
    batch_task = tm.create_task("batch_pipeline")
    batch_id = batch_task.task_id

    # Create individual tasks per URL
    task_ids = []
    for url in request.urls:
        child_task = tm.create_task("full_pipeline")
        task_ids.append(child_task.task_id)

    # Store child task_ids on batch task for later polling
    batch_task.result = {"task_ids": task_ids, "urls": request.urls}

    # Persist batch run
    create_pipeline_run(
        run_id=batch_id,
        mode="batch",
        urls=request.urls,
        platforms=request.platforms,
    )

    asyncio.create_task(
        _run_batch_pipeline(
            batch_id=batch_id,
            task_ids=task_ids,
            urls=request.urls,
            platforms=request.platforms,
            concurrency=request.concurrency,
            translate_profile=request.translate_profile,
            translation_override=request.translation_override,
            source_language=request.source_language,
            force=request.force,
            config=config,
            tts_profile=request.tts_profile,
            blur_enabled=request.blur_enabled,
            tts_provider=request.tts_provider,
            tts_voice=request.tts_voice,
            tts_api_key=request.tts_api_key,
            llm_api_key=request.llm_api_key,
            llm_backend=request.llm_backend,
            playback_speed=request.playback_speed,
            underlay_db=request.underlay_db,
            subtitle_style=request.subtitle_style,
        )
    )

    return {
        "batch_id": batch_id,
        "task_ids": task_ids,
        "total": len(request.urls),
    }


async def _run_batch_pipeline(
    batch_id: str,
    task_ids: list[str],
    urls: list[str],
    platforms: list[str],
    concurrency: int,
    translate_profile: str | None,
    translation_override: dict | None,
    source_language: str,
    force: bool,
    config: dict,
    tts_profile: str | None = None,
    blur_enabled: bool = True,
    tts_provider: str | None = None,
    tts_voice: str | None = None,
    tts_api_key: str | None = None,
    llm_api_key: str | None = None,
    llm_backend: str | None = None,
    playback_speed: float | None = None,
    underlay_db: float | None = None,
    subtitle_style: dict | None = None,
):
    """Execute batch pipeline with concurrency control."""
    from src.pipeline import Pipeline

    tm = get_task_manager()
    batch_task = tm.tasks[batch_id]
    batch_task.status = "running"

    semaphore = asyncio.Semaphore(concurrency)
    completed = 0
    errors: list[dict] = []

    async def process_one(idx: int, url: str, child_task_id: str):
        nonlocal completed
        async with semaphore:
            await _run_full_pipeline(
                task_id=child_task_id,
                url=url,
                platforms=platforms,
                auto_upload=False,
                translate_profile=translate_profile,
                translation_override=translation_override,
                source_language=source_language,
                force=force,
                config=config,
                tts_profile=tts_profile,
                blur_enabled=blur_enabled,
                tts_provider=tts_provider,
                tts_voice=tts_voice,
                tts_api_key=tts_api_key,
                llm_api_key=llm_api_key,
                llm_backend=llm_backend,
                playback_speed=playback_speed,
                underlay_db=underlay_db,
                subtitle_style=subtitle_style,
            )
            child_task = tm.tasks.get(child_task_id)
            if child_task and child_task.status == "failed":
                errors.append({"url": url, "error": child_task.error or "Unknown error"})
            completed += 1
            batch_task.progress = completed / len(urls)
            tm._emit(batch_id, "progress", {
                "completed": completed,
                "total": len(urls),
                "progress": batch_task.progress,
                "errors": errors,
            })

    tasks = [
        process_one(i, url, tid)
        for i, (url, tid) in enumerate(zip(urls, task_ids))
    ]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Summarize
    succeeded = sum(1 for tid in task_ids if tm.tasks.get(tid, None) and tm.tasks[tid].status == "completed")
    failed = len(task_ids) - succeeded

    # Collect video_ids from completed child tasks
    video_ids = [
        tm.tasks[tid].video_id
        for tid in task_ids
        if tm.tasks.get(tid) and tm.tasks[tid].video_id
    ]

    result = {
        "total": len(urls),
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors,
        "task_ids": task_ids,
        "urls": urls,
    }

    run_status = "failed" if (failed > 0 and succeeded == 0) else "done"
    update_pipeline_run(batch_id, {
        "status": run_status,
        "video_ids": video_ids,
        "succeeded": succeeded,
        "failed": failed,
        "errors": errors,
    })

    if failed > 0 and succeeded == 0:
        batch_task.status = "failed"
        batch_task.error = f"All {failed} videos failed"
        batch_task.result = result
        tm._emit(batch_id, "error", {"message": batch_task.error, **result})
    else:
        batch_task.status = "completed"
        batch_task.progress = 1.0
        batch_task.result = result
        tm._emit(batch_id, "complete", result)


# --- Pipeline status + history ---
# NOTE: Fixed-path routes MUST come before {task_id} to avoid being swallowed.


@router.get("/api/pipeline/history", response_model=list[PipelineHistoryEntry])
async def get_pipeline_history(
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, ge=1, le=100),
):
    """List all pipeline runs from state files, optionally filtered by status."""
    states = get_all_states()

    if status:
        states = [s for s in states if s.get("status") == status]

    entries = []
    for s in states[:limit]:
        entries.append(PipelineHistoryEntry(
            video_id=s.get("video_id", ""),
            url=s.get("url", ""),
            status=s.get("status", "unknown"),
            current_stage=s.get("current_stage", ""),
            progress=s.get("progress", 0.0),
            message=s.get("message", ""),
            completed_stages=s.get("completed_stages", []),
            stage_results=s.get("stage_results", {}),
            timestamps=s.get("timestamps", {}),
            platforms=s.get("platforms", []),
            error=s.get("error"),
            created_at=s.get("created_at", ""),
            updated_at=s.get("updated_at", ""),
        ))

    return entries


@router.get("/api/pipeline/runs")
async def get_runs(
    limit: int = Query(50, ge=1, le=200),
):
    """Get pipeline run log (batch + single runs), persisted to disk."""
    tm = get_task_manager()
    runs = get_pipeline_runs(limit)

    # Detect stale "running" runs whose task is no longer in memory
    # (server restarted or Ctrl+C killed the process).
    # Currently running tasks ARE in tm.tasks, so they stay "running".
    for run in runs:
        if run.get("status") == "running":
            task = tm.tasks.get(run["run_id"])
            if not task or task.status not in ("running", "queued"):
                run["status"] = "interrupted"
                update_pipeline_run(run["run_id"], {"status": "interrupted"})

    # Enrich each run with child video states
    for run in runs:
        children = []
        for vid in run.get("video_ids", []):
            if vid:
                state = PipelineState.load(vid)
                children.append({
                    "video_id": vid,
                    "status": state.status,
                    "current_stage": state.current_stage,
                    "progress": state.progress,
                    "message": state.message,
                    "completed_stages": state.completed_stages,
                    "error": state.error,
                    "title": state.stage_results.get("download", {}).get("title", ""),
                })
        run["children"] = children
    return runs


@router.get("/api/pipeline/{task_id}")
async def get_pipeline_status(task_id: str):
    """Get detailed pipeline status for a task.

    Returns in-memory task state enriched with on-disk PipelineState
    (current_stage, progress, message from state file).
    """
    tm = get_task_manager()
    task = tm.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    result = {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "status": task.status,
        "video_id": task.video_id,
        "current_stage": getattr(task, "current_stage", ""),
        "progress": task.progress,
        "message": task.message,
        "result": task.result,
        "error": task.error,
    }

    # For single pipeline tasks, enrich with on-disk state (survives server restart)
    if task.video_id:
        from src.utils.state import PipelineState
        state = PipelineState.load(task.video_id)
        result["current_stage"] = state.current_stage or result["current_stage"]
        result["progress"] = state.progress or result["progress"]
        result["message"] = state.message or result["message"]
        result["completed_stages"] = state.completed_stages

    # For batch tasks, aggregate child task states
    if task.task_type == "batch_pipeline" and task.result:
        child_task_ids = task.result.get("task_ids", [])
        children = []
        for cid in child_task_ids:
            child = tm.tasks.get(cid)
            if child and child.video_id:
                from src.utils.state import PipelineState
                cs = PipelineState.load(child.video_id)
                children.append({
                    "task_id": cid,
                    "video_id": child.video_id,
                    "status": cs.status,
                    "current_stage": cs.current_stage or getattr(child, "current_stage", ""),
                    "progress": cs.progress or child.progress,
                    "message": cs.message or child.message,
                    "error": cs.error,
                })
            elif child:
                children.append({
                    "task_id": cid,
                    "video_id": child.video_id,
                    "status": child.status,
                    "current_stage": getattr(child, "current_stage", ""),
                    "progress": child.progress,
                    "message": child.message,
                    "error": child.error,
                })
        result["children"] = children

    return result


# --- Retry ---


@router.post("/api/pipeline/{task_id}/retry", response_model=TaskResponse)
async def retry_pipeline(task_id: str):
    """Retry a failed pipeline from the failed stage."""
    tm = get_task_manager()
    old_task = tm.tasks.get(task_id)
    if not old_task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    if old_task.status != "failed":
        raise HTTPException(status_code=400, detail="Can only retry failed tasks")

    video_id = old_task.video_id
    if not video_id:
        raise HTTPException(status_code=400, detail="No video_id on task — cannot retry")

    # Load the saved state to find the URL and resume point
    state = PipelineState.load(video_id)

    config = get_config()
    new_task = tm.create_task("full_pipeline")

    asyncio.create_task(
        _run_full_pipeline(
            task_id=new_task.task_id,
            url=state.url,
            platforms=state.platforms or ["youtube", "tiktok"],
            auto_upload=False,
            translate_profile=None,
            source_language="zh",
            force=False,
            config=config,
        )
    )

    return TaskResponse(task_id=new_task.task_id, status=new_task.status)


# --- Dashboard stats ---


@router.get("/api/dashboard/stats")
async def get_dashboard_stats():
    """Summary stats: total videos, today's count, success rate, active tasks."""
    tm = get_task_manager()

    # Get stats from task manager (existing videos + tasks)
    base_stats = tm.get_stats()

    # Also count from state files for historical accuracy
    states = get_all_states()
    today_str = date.today().isoformat()

    total_from_states = len(states)
    today_from_states = sum(
        1 for s in states
        if s.get("created_at", "").startswith(today_str)
    )
    done_count = sum(1 for s in states if s.get("status") == "done")
    failed_count = sum(1 for s in states if s.get("status") == "failed")
    total_finished = done_count + failed_count
    success_rate = (done_count / total_finished * 100) if total_finished > 0 else 100.0

    return {
        "total_videos": max(base_stats["totalVideos"], total_from_states),
        "today": max(base_stats["processedToday"], today_from_states),
        "success_rate": round(success_rate / 100, 2),  # 0.0 – 1.0
        "active_tasks": base_stats["activeTasks"],
    }
