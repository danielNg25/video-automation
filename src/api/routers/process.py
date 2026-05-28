"""Process router: subtitle burn-in + platform reformatting endpoints."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import ExportRequest, ProcessRequest, ProcessResult, TaskResponse
from src.processor.style import SubtitleStyleSpec, load_style, save_global_default
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()


@router.post("/api/process", response_model=TaskResponse)
async def start_process(request: ProcessRequest):
    """Start video processing for selected platforms."""
    tm = get_task_manager()
    config = get_config()

    video = tm.video_index.get(request.video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {request.video_id} not found")

    valid_platforms = {"tiktok", "youtube", "facebook", "x"}
    invalid = set(request.platforms) - valid_platforms
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid platforms: {invalid}")

    # Build blur settings dict if provided
    blur_dict = None
    manual_region_dict = None
    if request.blur_settings:
        blur_dict = {
            "enabled": request.blur_settings.enabled,
            "strength": request.blur_settings.strength,
            "mode": request.blur_settings.mode,
            "fill_color": request.blur_settings.fill_color,
        }
    if request.manual_region:
        manual_region_dict = {
            "x": request.manual_region.x,
            "y": request.manual_region.y,
            "width": request.manual_region.width,
            "height": request.manual_region.height,
        }

    task = tm.create_task("process")
    task._asyncio_task = asyncio.create_task(
        tm.run_process(
            task.task_id,
            request.video_id,
            request.platforms,
            request.subtitle_style,
            request.subtitle_language_overrides,
            config,
            enable_tts=request.enable_tts,
            tts_mix_settings=request.tts_mix_settings,
            blur_settings=blur_dict,
            manual_region=manual_region_dict,
        )
    )
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.get("/api/process/{task_id}", response_model=ProcessResult)
async def get_process_result(task_id: str):
    """Get processing result for a completed task."""
    tm = get_task_manager()
    task = tm.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if task.status == "failed":
        raise HTTPException(status_code=500, detail=task.error or "Processing failed")
    if task.status != "completed":
        raise HTTPException(status_code=202, detail="Processing still in progress")
    return ProcessResult(**(task.result or {}))


@router.get("/api/subtitle-styles", response_model=SubtitleStyleSpec)
async def get_subtitle_styles():
    """Return the global default subtitle style."""
    return load_style()


@router.put("/api/subtitle-styles", response_model=SubtitleStyleSpec)
async def put_subtitle_styles(spec: SubtitleStyleSpec):
    """Replace the global default. Body must be a full SubtitleStyleSpec."""
    save_global_default(spec)
    return spec


@router.get("/api/platforms")
async def get_platforms():
    """Return platform specifications."""
    config_path = Path("config/platforms.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Platform config not found")
    with open(config_path) as f:
        return yaml.safe_load(f)


@router.get("/api/videos/{video_id}/output/{platform}")
async def get_processed_video(video_id: str, platform: str):
    """Stream a processed video file."""
    data_dir = get_data_dir()
    output_path = data_dir / "output" / f"{video_id}_{platform}.mp4"
    if not output_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Processed video not found: {video_id}_{platform}.mp4",
        )
    return FileResponse(
        path=str(output_path),
        media_type="video/mp4",
        filename=f"{video_id}_{platform}.mp4",
    )


async def _run_export_ffmpeg(
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
    """Run ffmpeg export with optional subtitles, blur, and TTS mixing.

    When `resolution` is None or empty, the output uses the source video's
    native dimensions — no scale, no letterbox pad. Blur, burned subtitles,
    and rounded-rect background PNGs all share the source coordinate space,
    so positioning is exact. Pass an explicit "WxH" only when a caller needs
    a hard target (e.g. a TikTok-mandated 1080×1920).
    """
    from src.processor.ffmpeg import FFmpegProcessor

    proc = FFmpegProcessor()
    info = proc.get_video_info(video_path)
    src_w, src_h = info["width"], info["height"]

    if not resolution:
        w, h = src_w, src_h
    elif "x" in resolution:
        ws, hs = resolution.split("x", 1)
        if not (ws.isdigit() and hs.isdigit()):
            raise ValueError(
                f"Invalid resolution {resolution!r}; both W and H must be integers"
            )
        w, h = int(ws), int(hs)
    else:
        raise ValueError(
            f"Invalid resolution {resolution!r}; expected WxH e.g. 1080x1920"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Load canonical spec; it carries blur + position + everything else.
    from src.processor.style import load_style
    from src.processor.style_render import render_for_ffmpeg
    from src.processor.region_detector import load_subtitle_region

    ocr_region = None
    region_obj = None
    if video_id:
        region_obj = load_subtitle_region(Path("data/srt"), video_id)
        if region_obj:
            ocr_region = {
                "x": region_obj.x, "y": region_obj.y,
                "width": region_obj.width, "height": region_obj.height,
            }
    spec = load_style(
        video_id=video_id,
        source_dims=(src_w, src_h),
        ocr_region=ocr_region,
    )

    # Blur is independent of position now (no more "blur on ⇒ override position").
    blur_filter = None
    if spec.blur.enabled and region_obj is not None:
        blur_filter = FFmpegProcessor._build_blur_filter(
            region_obj,
            blur_strength=spec.blur.strength,
            blur_mode=spec.blur.mode,
        )

    # Build video filter. When output equals source we skip scale+pad entirely
    # so blur, burned subtitle, and rounded-rect bg PNGs all share one coord
    # space (the source). libx264/yuv420p needs even dims, so on the rare
    # odd-source case we crop down to the nearest even pair.
    if (w, h) == (src_w, src_h):
        if w % 2 == 0 and h % 2 == 0:
            scale_pad = "null"
        else:
            even_w, even_h = w - (w % 2), h - (h % 2)
            scale_pad = f"crop={even_w}:{even_h}:0:0"
            w, h = even_w, even_h
    else:
        scale_pad = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

    ass_path = None
    bg_images = None
    if subtitle_path and subtitle_path.exists():
        bg_dir = output_path.parent / "bg_tmp"
        artifacts = render_for_ffmpeg(spec, subtitle_path, int(w), int(h), bg_dir)
        ass_path = artifacts.ass_path
        bg_images = artifacts.bg_pngs
        if bg_images:
            # Drop any entry whose PNG didn't actually land on disk; an empty
            # `-i path` arg or a missing file will silently kill the whole
            # filter chain (libx264 sees EOF before getting any frames).
            bg_images = [
                img for img in bg_images
                if img.get("path") and Path(img["path"]).exists()
            ] or None
    use_subs_filter = ass_path is not None

    has_tts = tts_path and tts_path.exists()

    # Step 1: Build intermediate (blur + scale + pad + bg boxes + subtitles)
    intermediate = output_path.with_suffix(".tmp.mp4") if has_tts else output_path
    intermediate.parent.mkdir(parents=True, exist_ok=True)

    cmd1 = ["ffmpeg", "-y"]
    if seek_seconds is not None:
        cmd1 += ["-ss", str(seek_seconds)]
    cmd1 += ["-i", str(video_path)]
    if duration_seconds is not None:
        cmd1 += ["-t", str(duration_seconds)]

    ass_suffix = f",ass='{ass_path}'" if use_subs_filter else ""

    if bg_images:
        from src.processor.subtitle import build_background_overlay_filter
        # Add PNG inputs and build overlay chain
        for img in bg_images:
            cmd1 += ["-i", img["path"]]

        if blur_filter:
            # blur → scale+pad → [bg_base] → overlay PNGs → ass text → [out]
            fc_start = f"{blur_filter};[blurred]{scale_pad}[bg_base]"
        else:
            fc_start = f"[0:v]{scale_pad}[bg_base]"

        overlay_fc = build_background_overlay_filter(bg_images)
        fc = f"{fc_start};{overlay_fc};[bg_out]{ass_suffix.lstrip(',')}[out]" if ass_suffix else f"{fc_start};{overlay_fc}"
        if not ass_suffix:
            fc = fc.replace("[bg_out]", "[out]")

        cmd1 += [
            "-filter_complex", fc,
            "-map", "[out]",
            "-map", "0:a",
            "-af", f"volume={video_volume}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(intermediate),
        ]
    elif blur_filter:
        fc = f"{blur_filter};[blurred]{scale_pad}{ass_suffix}[out]"
        cmd1 += [
            "-filter_complex", fc,
            "-map", "[out]",
            "-map", "0:a",
            "-af", f"volume={video_volume}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(intermediate),
        ]
    else:
        vf = f"{scale_pad}{ass_suffix}"
        cmd1 += [
            "-vf", vf,
            "-af", f"volume={video_volume}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            str(intermediate),
        ]

    logger.info(
        "Export step 1 cmd: ffmpeg ... %d args, filter_complex/vf len=%d",
        len(cmd1),
        len(cmd1[cmd1.index("-filter_complex") + 1])
        if "-filter_complex" in cmd1
        else (
            len(cmd1[cmd1.index("-vf") + 1]) if "-vf" in cmd1 else 0
        ),
    )
    tm = get_task_manager() if task_id else None
    if tm is not None:
        # No explicit timeout — cancellation is now user-driven via cancel_task.
        # A hung ffmpeg will be killed by the user clicking Stop.
        result = await tm.run_subprocess_tracked(task_id, cmd1, text=True)
    else:
        result = subprocess.run(cmd1, capture_output=True, text=True, timeout=600)

    # Clean up background PNG temp dir
    if bg_images:
        import shutil
        bg_dir = output_path.parent / "bg_tmp"
        shutil.rmtree(bg_dir, ignore_errors=True)

    if result.returncode != 0:
        # Surface the full command + tail of stderr so the actual ffmpeg
        # complaint is debuggable. Without this you only see the last 500
        # chars of stderr with no context.
        logger.error("ffmpeg export step 1 failed.\nCommand: %s\nStderr (tail):\n%s",
                     " ".join(cmd1), result.stderr[-1500:])
        raise RuntimeError(
            f"Export failed (rc={result.returncode}): {result.stderr[-800:]}"
        )

    # Step 2: Mix TTS audio if needed
    if has_tts:
        cmd2 = ["ffmpeg", "-y",
            "-i", str(intermediate),
            "-i", str(tts_path),
        ]
        if seek_seconds is not None:
            # TTS was not seeked in step 1 input, need to offset
            cmd2 = ["ffmpeg", "-y",
                "-i", str(intermediate),
                "-ss", str(seek_seconds),
                "-i", str(tts_path),
            ]
        af = (
            f"[0:a]volume=1.0[orig];"
            f"[1:a]volume={tts_volume}[tts];"
            f"[orig][tts]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )
        cmd2 += [
            "-filter_complex", af,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]
        if tm is not None:
            result = await tm.run_subprocess_tracked(task_id, cmd2, text=True)
        else:
            result = subprocess.run(cmd2, capture_output=True, text=True, timeout=600)
        intermediate.unlink(missing_ok=True)
        if result.returncode != 0:
            logger.error("ffmpeg audio-mix step 2 failed.\nCommand: %s\nStderr (tail):\n%s",
                         " ".join(cmd2), result.stderr[-1500:])
            raise RuntimeError(
                f"Audio mix failed (rc={result.returncode}): {result.stderr[-800:]}"
            )


@router.post("/api/videos/{video_id}/export", response_model=TaskResponse)
async def export_video(video_id: str, request: ExportRequest):
    """Export video with burned subtitles and optional TTS dub."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    task = tm.create_task("export")

    async def run_export():
        task_obj = tm.tasks[task.task_id]
        task_obj.status = "running"
        task_obj.video_id = video_id
        try:
            tm._emit(task.task_id, "progress", {"progress": 0.1, "message": "Starting export..."})

            video_path = Path(video.file_path)
            srt_path = Path("data/srt") / f"{video_id}_{request.subtitle_language}.srt" if request.subtitle_language else None
            tts_path = Path("data/tts") / request.tts_file if request.tts_file else None
            output_path = Path("data/output") / f"{video_id}_export.mp4"

            tm._emit(task.task_id, "progress", {"progress": 0.2, "message": "Rendering video..."})

            await _run_export_ffmpeg(
                video_path, srt_path, tts_path, output_path,
                request.resolution,
                request.video_volume, request.tts_volume,
                video_id=video_id,
                task_id=task.task_id,
            )

            # Update video status to exported
            video_info = tm.video_index.get(video_id)
            if video_info:
                video_info.status = "exported"
                tm.video_index[video_id] = video_info

            task_obj.status = "completed"
            task_obj.progress = 1.0
            task_obj.result = {"output_path": str(output_path)}
            tm._emit(task.task_id, "complete", {"output_path": str(output_path)})
        except Exception as e:
            task_obj.status = "failed"
            task_obj.error = str(e)
            tm._emit(task.task_id, "error", {"message": str(e)})

    task._asyncio_task = asyncio.create_task(run_export())
    return TaskResponse(task_id=task.task_id, status=task.status)


@router.post("/api/videos/{video_id}/export/preview")
async def preview_export(video_id: str, request: ExportRequest):
    """Render a 5-second preview clip with the given export settings."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video.file_path)
    srt_path = Path("data/srt") / f"{video_id}_{request.subtitle_language}.srt" if request.subtitle_language else None
    tts_path = Path("data/tts") / request.tts_file if request.tts_file else None
    output_path = Path("data/output") / f"{video_id}_preview.mp4"

    # Seek to 1/3 of video for a representative preview
    midpoint = max(0, (video.duration or 30) / 3)

    await _run_export_ffmpeg(
        video_path, srt_path, tts_path, output_path,
        request.resolution,
        request.video_volume, request.tts_volume,
        seek_seconds=midpoint, duration_seconds=5,
        video_id=video_id,
    )

    return FileResponse(path=str(output_path), media_type="video/mp4", filename=f"{video_id}_preview.mp4")


@router.get("/api/videos/{video_id}/export")
async def get_exported_video(video_id: str):
    """Stream the exported video."""
    output_path = Path("data/output") / f"{video_id}_export.mp4"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(path=str(output_path), media_type="video/mp4", filename=f"{video_id}_export.mp4")


@router.get("/api/videos/{video_id}/export/status")
async def get_export_status(video_id: str):
    """Check if an exported video exists."""
    output_path = Path("data/output") / f"{video_id}_export.mp4"
    if output_path.exists():
        stat = output_path.stat()
        return {"exists": True, "size": stat.st_size, "modified": stat.st_mtime}
    return {"exists": False}


@router.delete("/api/videos/{video_id}/export")
async def delete_exported_video(video_id: str):
    """Delete the exported video."""
    output_path = Path("data/output") / f"{video_id}_export.mp4"
    if output_path.exists():
        output_path.unlink()
    # Also delete preview
    preview_path = Path("data/output") / f"{video_id}_preview.mp4"
    if preview_path.exists():
        preview_path.unlink()
    return {"status": "deleted"}
