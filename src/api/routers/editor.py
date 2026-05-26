"""Editor router: save edited subtitles, preview frame/clip with burn-in."""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from src.api.deps import get_data_dir, get_task_manager
from src.api.models import (
    PreviewClipRequest,
    PreviewFrameRequest,
    SaveSrtRequest,
    SrtResponse,
    SubtitleSegment,
    TaskResponse,
)
from src.api.routers.transcribe import _resolve_srt_path
from src.processor.region_detector import load_subtitle_region
from src.processor.style import SubtitleStyleSpec, load_style, save_style_delta
from src.processor.subtitle import (
    _timestamp_to_seconds,
    parse_srt,
    write_srt,
)
from src.tts.base import _clean_text
from src.tts.dub_meta import load_dub_meta

router = APIRouter()


@router.get("/api/videos/{video_id}/raw")
async def serve_raw_video(video_id: str):
    """Serve the full-resolution raw video file."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    return FileResponse(
        path=str(video_path),
        media_type="video/mp4",
        filename=f"{video_id}.mp4",
        headers={"Content-Disposition": f'attachment; filename="{video_id}.mp4"'},
    )


def _mix_dub_preview(raw: Path, dub: Path, underlay_db: float, out: Path) -> None:
    """ffmpeg pipeline: raw video + raw audio (at underlay_db) + dub (at 0 dB) → MP4."""
    # underlay_db is negative (e.g., -18). Convert to volume factor.
    orig_vol = 10 ** (underlay_db / 20.0) if underlay_db is not None else 0.125

    cmd = [
        "ffmpeg", "-y",
        "-i", str(raw),
        "-i", str(dub),
        "-filter_complex",
        f"[0:a]volume={orig_vol:.4f}[orig];"
        f"[1:a]volume=1.0[dub];"
        f"[orig][dub]amix=inputs=2:duration=longest[mix]",
        "-map", "0:v",
        "-map", "[mix]",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        str(out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg dub-preview mix failed (exit {proc.returncode}): "
            f"{proc.stderr[-500:]}"
        )


@router.get("/api/videos/{video_id}/preview-mix")
async def serve_preview_mix(video_id: str, language: str):
    """Serve an MP4 mixing raw video with the dub audio for a language.

    Mix recipe:
    - Video stream from raw MP4 (stream-copied, fast).
    - Audio: raw original at ``underlay_db`` (from ``dub_meta`` or default
      -18 dB), mixed with dub WAV at 0 dB. Re-encoded as AAC.
    - Cached at ``data/preview/{video_id}_{language}_dub_mix.mp4``.
    - Cache freshness: cached file's mtime must be newer than the dub WAV's
      mtime AND the raw MP4's mtime. Otherwise regenerate.
    """
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    raw_path = Path(video.file_path)
    if not raw_path.exists():
        raise HTTPException(status_code=404, detail="Raw video missing on disk")

    # Find the dub WAV — glob `data/tts/{id}_{lang}_*.wav`, pick newest
    tts_dir = Path("data/tts")
    candidates = sorted(
        tts_dir.glob(f"{video_id}_{language}_*.wav"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    candidates = [p for p in candidates if p.is_file()]
    if not candidates:
        raise HTTPException(
            status_code=404,
            detail=f"No dub WAV for {video_id}/{language} — generate the dub first",
        )
    dub_wav = candidates[0]

    # Determine underlay_db: prefer dub_meta, else default
    meta = load_dub_meta(tts_dir, video_id, language)
    underlay_db = meta.underlay_db if meta is not None else -18.0

    # Output path + cache check
    preview_dir = Path("data/preview")
    preview_dir.mkdir(parents=True, exist_ok=True)
    out_path = preview_dir / f"{video_id}_{language}_dub_mix.mp4"

    needs_regen = (
        not out_path.exists()
        or out_path.stat().st_mtime < dub_wav.stat().st_mtime
        or out_path.stat().st_mtime < raw_path.stat().st_mtime
    )

    if needs_regen:
        await asyncio.to_thread(
            _mix_dub_preview, raw_path, dub_wav, underlay_db, out_path,
        )

    return FileResponse(
        path=str(out_path),
        media_type="video/mp4",
        filename=f"{video_id}_{language}_dub_mix.mp4",
    )


@router.get("/api/videos/{video_id}/proxy")
async def serve_proxy_video(video_id: str):
    """Serve a cached 480p proxy video, generating on first request."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    video_path = Path(video.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found on disk")

    data_dir = get_data_dir()
    proxy_path = data_dir / "proxy" / f"{video_id}_360p.mp4"

    if not proxy_path.exists():
        from src.processor.ffmpeg import FFmpegProcessor

        proc = FFmpegProcessor()
        try:
            await asyncio.to_thread(proc.generate_proxy, video_path, proxy_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Proxy generation failed: {e}")

    return FileResponse(
        path=str(proxy_path),
        media_type="video/mp4",
        filename=f"{video_id}_360p.mp4",
    )


def _check_dub_sync_against_meta(
    data_dir: Path, video_id: str, language: str, new_texts: list[str]
) -> bool:
    """Return True if the dub is out of sync with the new SRT texts.

    Compares cleaned per-segment text against the recorded ``segment_texts``
    in ``dub_meta_{language}.json``. If no metadata exists, the dub has not
    been generated for this language yet — no sync needed, return False.
    """
    meta = load_dub_meta(data_dir, video_id, language)
    if meta is None:
        return False
    if len(meta.segment_texts) != len(new_texts):
        return True
    for old, new in zip(meta.segment_texts, new_texts):
        if _clean_text(old) != _clean_text(new):
            return True
    return False


@router.get("/api/videos/{video_id}/style")
async def get_video_style(video_id: str):
    """Merged spec (global + per-video delta) plus a flag for whether the
    user has any per-video customizations."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    video = tm.video_index[video_id]
    region_obj = load_subtitle_region(Path("data/srt"), video_id)
    ocr_region = None
    if region_obj is not None:
        ocr_region = {
            "x": region_obj.x, "y": region_obj.y,
            "width": region_obj.width, "height": region_obj.height,
        }
    source_dims = (video.width, video.height) if getattr(video, "width", None) else None
    spec = load_style(
        video_id=video_id,
        source_dims=source_dims,
        ocr_region=ocr_region,
    )
    delta_path = Path("data/srt") / f"{video_id}_style.json"
    return {
        "video_id": video_id,
        "style": spec.model_dump(),
        "is_custom": delta_path.exists(),
    }


@router.put("/api/videos/{video_id}/style")
async def put_video_style(video_id: str, delta: dict):
    """Replace the per-video delta. Body is a partial SubtitleStyleSpec
    (FE-computed diff vs the global default)."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    save_style_delta(video_id, delta)
    return await get_video_style(video_id)


@router.delete("/api/videos/{video_id}/style")
async def delete_video_style(video_id: str):
    """Remove the per-video delta entirely. Subsequent GETs return global."""
    tm = get_task_manager()
    if video_id not in tm.video_index:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")
    delta_path = Path("data/srt") / f"{video_id}_style.json"
    if delta_path.exists():
        delta_path.unlink()
    return await get_video_style(video_id)


@router.put("/api/videos/{video_id}/srt", response_model=SrtResponse)
async def save_srt(video_id: str, request: SaveSrtRequest):
    """Save edited subtitle segments back to SRT file."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    # Resolve where to write: dubsync.srt when present, legacy otherwise.
    srt_path, is_dubsync = _resolve_srt_path(video_id, request.language)

    # Convert SubtitleSegment timestamps (HH:MM:SS,mmm) to seconds
    segments = []
    for seg in request.segments:
        segments.append(
            {
                "start": _timestamp_to_seconds(seg.startTime),
                "end": _timestamp_to_seconds(seg.endTime),
                "text": seg.text,
            }
        )

    write_srt(segments, srt_path)

    # Update video index srt_languages
    if request.language not in video.srt_languages:
        video.srt_languages.append(request.language)
        video.srt_languages.sort()
        video.has_srt = True

    # Check if this edit puts the dub out of sync with the saved dub_meta.
    from src.utils.state import PipelineState

    tts_data_dir = Path("data/tts")
    new_texts = [seg["text"] for seg in segments]
    is_dub_out_of_sync = _check_dub_sync_against_meta(
        tts_data_dir, video_id, request.language, new_texts
    )

    state = PipelineState.load(video_id)
    state_changed = False
    if is_dub_out_of_sync:
        if request.language not in state.dub_out_of_sync_languages:
            state.dub_out_of_sync_languages.append(request.language)
            state_changed = True
    else:
        if request.language in state.dub_out_of_sync_languages:
            state.dub_out_of_sync_languages.remove(request.language)
            state_changed = True
    if state_changed:
        state.save()

    # Re-parse to return fresh data
    parsed = parse_srt(srt_path)
    response_segments = []
    for i, seg in enumerate(parsed, start=1):
        from src.processor.subtitle import _seconds_to_srt_timestamp

        response_segments.append(
            SubtitleSegment(
                id=i,
                startTime=_seconds_to_srt_timestamp(seg["start"]),
                endTime=_seconds_to_srt_timestamp(seg["end"]),
                text=seg["text"],
            )
        )

    return SrtResponse(
        video_id=video_id,
        segments=response_segments,
        language=request.language,
        is_dubsync=is_dubsync,
    )


@router.post("/api/videos/{video_id}/preview-frame")
async def preview_frame(video_id: str, request: PreviewFrameRequest):
    """Render a single frame with burned-in subtitle, returns JPEG."""
    tm = get_task_manager()
    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"SRT file not found: {video_id}_{request.language}.srt",
        )

    from src.processor.ffmpeg import FFmpegProcessor
    from src.processor.style import SubtitleStyleSpec, load_style
    from src.processor.style_render import render_for_ffmpeg

    video_path = Path(video.file_path)
    proc = FFmpegProcessor()
    info = proc.get_video_info(video_path)
    src_w, src_h = info["width"], info["height"]

    # request.subtitle_style holds the live editor draft. Validate it as a
    # full SubtitleStyleSpec. Falls back to the merged global+per-video
    # default when the FE didn't send one.
    if request.subtitle_style:
        spec = SubtitleStyleSpec.model_validate(request.subtitle_style)
    else:
        spec = load_style(video_id=video_id, source_dims=(src_w, src_h))

    with tempfile.TemporaryDirectory() as tmp:
        artifacts = render_for_ffmpeg(spec, srt_path, src_w, src_h, Path(tmp))
        escaped = proc._escape_filter_path(artifacts.ass_path)
        vf = f"ass='{escaped}'"

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as jpg:
            out_path = jpg.name

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(request.timestamp),
                    "-i", str(video_path),
                    "-vf", vf,
                    "-frames:v", "1",
                    "-q:v", "2",
                    out_path,
                ],
                capture_output=True, check=True, timeout=30,
            )
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or b"").decode()[-200:]
            raise HTTPException(status_code=500, detail=f"ffmpeg failed: {stderr}")

    return FileResponse(
        path=out_path,
        media_type="image/jpeg",
        filename=f"{video_id}_frame_{request.timestamp:.1f}s.jpg",
    )


@router.post("/api/videos/{video_id}/preview-clip", response_model=TaskResponse)
async def preview_clip(video_id: str, request: PreviewClipRequest):
    """Render a short clip with burned-in subtitles (background task + SSE)."""
    tm = get_task_manager()

    video = tm.video_index.get(video_id)
    if not video:
        raise HTTPException(status_code=404, detail=f"Video {video_id} not found")

    data_dir = get_data_dir()
    srt_path = data_dir / "srt" / f"{video_id}_{request.language}.srt"
    if not srt_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"SRT file not found: {video_id}_{request.language}.srt",
        )

    task = tm.create_task("preview_clip")

    async def run_preview():
        task_obj = tm.tasks[task.task_id]
        task_obj.status = "running"
        task_obj.message = "Rendering preview clip..."
        tm._emit(
            task.task_id,
            "progress",
            {"progress": 0.3, "message": "Rendering preview clip..."},
        )

        try:
            from src.processor.ffmpeg import FFmpegProcessor
            from src.processor.style import SubtitleStyleSpec, load_style
            from src.processor.style_render import render_for_ffmpeg
            from src.processor.subtitle import build_background_overlay_filter

            video_path = Path(video.file_path)
            proc = FFmpegProcessor()
            info = proc.get_video_info(video_path)
            src_w, src_h = info["width"], info["height"]

            # Live editor draft, or merged default.
            if request.subtitle_style:
                spec = SubtitleStyleSpec.model_validate(request.subtitle_style)
            else:
                spec = load_style(video_id=video_id, source_dims=(src_w, src_h))

            output_dir = data_dir / "output"
            output_dir.mkdir(parents=True, exist_ok=True)
            clip_path = output_dir / f"{video_id}_preview.mp4"
            bg_dir = output_dir / "bg_preview_tmp"

            artifacts = render_for_ffmpeg(spec, srt_path, src_w, src_h, bg_dir)
            ass_path = artifacts.ass_path
            bg_images = artifacts.bg_pngs
            if bg_images:
                bg_images = [
                    img for img in bg_images
                    if img.get("path") and Path(img["path"]).exists()
                ] or None

            # Build the ffmpeg command. Source==output here (preview keeps
            # source dims), so scale_pad is a no-op for even dims.
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(request.start),
                "-i", str(video_path),
                "-t", str(request.duration),
            ]

            ass_suffix = f",ass='{proc._escape_filter_path(ass_path)}'" if ass_path else ""

            if bg_images:
                # Add PNG inputs and build overlay chain.
                for img in bg_images:
                    cmd += ["-i", img["path"]]
                overlay_fc = build_background_overlay_filter(bg_images)
                if ass_suffix:
                    fc = f"[0:v]null[bg_base];{overlay_fc};[bg_out]{ass_suffix.lstrip(',')}[out]"
                else:
                    fc = f"[0:v]null[bg_base];{overlay_fc}".replace("[bg_out]", "[out]")
                cmd += [
                    "-filter_complex", fc,
                    "-map", "[out]",
                ]
            else:
                vf = f"null{ass_suffix}"
                cmd += ["-vf", vf]

            cmd += [
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-crf", "23",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(clip_path),
            ]

            await asyncio.to_thread(
                subprocess.run,
                cmd, capture_output=True, check=True, timeout=120,
            )

            task_obj.status = "completed"
            task_obj.progress = 1.0
            task_obj.result = {
                "video_id": video_id,
                "clip_url": f"/api/videos/{video_id}/output/preview",
            }
            tm._emit(task.task_id, "complete", task_obj.result)

        except Exception as e:
            task_obj.status = "failed"
            task_obj.error = str(e)
            tm._emit(task.task_id, "error", {"message": str(e)})

    asyncio.create_task(run_preview())
    return TaskResponse(task_id=task.task_id, status=task.status)
