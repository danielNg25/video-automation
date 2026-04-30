"""Process router: subtitle burn-in + platform reformatting endpoints."""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_config, get_data_dir, get_task_manager
from src.api.models import ExportRequest, ProcessRequest, ProcessResult, TaskResponse
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
    asyncio.create_task(
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


@router.get("/api/subtitle-styles")
async def get_subtitle_styles():
    """Return subtitle style configuration."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")
    with open(config_path) as f:
        return yaml.safe_load(f)


@router.put("/api/subtitle-styles")
async def update_default_subtitle_style(style: dict):
    """Update the default subtitle style."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")

    with open(config_path) as f:
        styles = yaml.safe_load(f)

    styles["default"] = {**styles.get("default", {}), **style}

    with open(config_path, "w") as f:
        yaml.safe_dump(styles, f, default_flow_style=False)

    return styles


@router.put("/api/subtitle-styles/{platform}")
async def update_subtitle_style(platform: str, style: dict):
    """Update platform-specific subtitle style."""
    config_path = Path("config/subtitle_styles.yaml")
    if not config_path.exists():
        raise HTTPException(status_code=404, detail="Subtitle styles config not found")

    with open(config_path) as f:
        styles = yaml.safe_load(f)

    if "platforms" not in styles:
        styles["platforms"] = {}
    styles["platforms"][platform] = style

    with open(config_path, "w") as f:
        yaml.safe_dump(styles, f, default_flow_style=False)

    return styles


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


def _load_subtitle_style(video_id: str) -> dict:
    """Load subtitle style: per-video override → global default."""
    # Per-video style
    style_path = Path("data/srt") / f"{video_id}_style.json"
    if style_path.exists():
        with open(style_path) as f:
            return json.load(f)
    # Global default
    config_path = Path("config/subtitle_styles.yaml")
    if config_path.exists():
        with open(config_path) as f:
            styles = yaml.safe_load(f) or {}
        return styles.get("default", {})
    return {}


def _run_export_ffmpeg(
    video_path: Path,
    subtitle_path: Path | None,
    tts_path: Path | None,
    output_path: Path,
    style: dict,
    resolution: str | None,
    video_volume: float,
    tts_volume: float,
    seek_seconds: float | None = None,
    duration_seconds: float | None = None,
    video_id: str | None = None,
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

    # Auto-detect blur region from OCR metadata (respects saved blur_enabled flag)
    blur_filter = None
    blur_enabled = style.get("blur_enabled", True)  # default on if not saved
    if video_id and blur_enabled:
        from src.processor.region_detector import load_subtitle_region
        region = load_subtitle_region(Path("data/srt"), video_id)
        if region:
            blur_mode = style.get("blur_mode", "blur")
            blur_strength = style.get("blur_strength", 15)
            blur_filter = FFmpegProcessor._build_blur_filter(region, blur_strength=blur_strength, blur_mode=blur_mode)

            # Apply style matching. Pass output dims so the matcher applies
            # the same scale + letterbox-pad math the video goes through. When
            # output == source (the new default), scale=1 and pad=0, so the
            # region passes through unchanged in source coords.
            from src.processor.style_matcher import SubtitleStyleMatcher
            matcher = SubtitleStyleMatcher()
            matched = matcher.match_style(
                region, src_w, src_h, style,
                output_width=int(w), output_height=int(h),
            )
            style = {**style, **matched}

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
        from src.processor.subtitle import srt_to_ass, generate_subtitle_background_images
        ass_path = subtitle_path.with_suffix(".export.ass")
        # Use the EXPORT resolution as the ASS canvas so ass=… maps 1:1 to
        # output pixels. Combined with style_matcher's letterbox-aware coords
        # this puts the burned subtitle directly over the blurred area.
        srt_to_ass(subtitle_path, style, ass_path, play_res_x=int(w), play_res_y=int(h))
        # Generate rounded-rect background PNGs
        bg_dir = output_path.parent / "bg_tmp"
        bg_images = generate_subtitle_background_images(
            subtitle_path, style, bg_dir, int(w), int(h),
        )
        # Treat an empty list the same as None — building an overlay chain
        # with zero PNG inputs produces a malformed filter graph.
        if not bg_images:
            bg_images = None
        else:
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
            style = _load_subtitle_style(video_id)

            tm._emit(task.task_id, "progress", {"progress": 0.2, "message": "Rendering video..."})

            await asyncio.to_thread(
                _run_export_ffmpeg,
                video_path, srt_path, tts_path, output_path,
                style, request.resolution,
                request.video_volume, request.tts_volume,
                video_id=video_id,
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

    asyncio.create_task(run_export())
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
    style = _load_subtitle_style(video_id)

    # Seek to 1/3 of video for a representative preview
    midpoint = max(0, (video.duration or 30) / 3)

    await asyncio.to_thread(
        _run_export_ffmpeg,
        video_path, srt_path, tts_path, output_path,
        style, request.resolution,
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
