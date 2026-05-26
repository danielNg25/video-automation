"""Integration: export endpoint honors every spec field end-to-end.

Marked `integration` because it builds a tiny fixture video on disk and
runs the full export pipeline (fastapi route → asyncio.to_thread →
ffmpeg). Slow-ish (~10s) but it's the only test that catches "schema +
renderer math are correct but the wiring drops a field somewhere."
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


@pytest.mark.integration
def test_export_honors_full_spec(tmp_path, monkeypatch):
    # Lay out the fixture directories the loaders expect:
    #   config/subtitle_styles.yaml           ← global default
    #   data/raw/{vid}.mp4                    ← source video
    #   data/srt/{vid}_vi.srt                 ← subtitles
    #   data/srt/{vid}_style.json             ← per-video delta
    #   data/output/{vid}_export.mp4          ← export result
    # We chdir to tmp_path so the relative paths in src/processor/style.py
    # and src/processor/region_detector.py resolve under tmp_path.
    repo_root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "subtitle_styles.yaml").write_text(
        (repo_root / "config" / "subtitle_styles.yaml").read_text()
    )
    raw_dir = tmp_path / "data" / "raw"; raw_dir.mkdir(parents=True)
    srt_dir = tmp_path / "data" / "srt"; srt_dir.mkdir(parents=True)
    out_dir = tmp_path / "data" / "output"; out_dir.mkdir(parents=True)

    # 1. Create a 3-second fixture video with silent audio (720x1280). Export
    # pipeline maps `0:a`, so we need an audio track even though it's silent.
    video_id = "test_export_spec"
    video_path = raw_dir / f"{video_id}.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "color=black:s=720x1280:r=24:d=3",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "3",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-shortest",
            str(video_path),
        ],
        check=True, capture_output=True,
    )

    # 2. Write a tiny SRT.
    srt = srt_dir / f"{video_id}_vi.srt"
    srt.write_text(
        "1\n00:00:00,500 --> 00:00:02,500\nXin chào\n",
        encoding="utf-8",
    )

    # 3. Write a per-video style delta with every visible field set.
    delta = {
        "text": {"font_size": 4.0, "color": "#FF0000", "bold": True},
        "position": {"alignment": "bottom-center", "margin_v": 20.0},
        "outline": {"width": 0.2, "color": "#00FF00"},
        "background": {"shape": "rounded", "color": "#FFFF00",
                       "opacity": 80, "radius": 1.5,
                       "padding_x": 1.0, "padding_y": 0.5},
    }
    (srt_dir / f"{video_id}_style.json").write_text(json.dumps(delta))

    # 4. Run the export ffmpeg helper directly (avoids spinning up the API).
    from src.api.routers.process import _run_export_ffmpeg
    output = out_dir / f"{video_id}_export.mp4"
    _run_export_ffmpeg(
        video_path=video_path,
        subtitle_path=srt,
        tts_path=None,
        output_path=output,
        resolution=None,
        video_volume=1.0,
        tts_volume=1.0,
        video_id=video_id,
    )
    assert output.exists(), "export did not produce an output file"

    # 5. Extract a frame at t=1.5s (segment is active 0.5–2.5).
    frame = tmp_path / "frame.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "1.5", "-i", str(output),
         "-frames:v", "1", str(frame)],
        check=True, capture_output=True,
    )

    # 6. Inspect with PIL: assert there's a yellow band near the bottom
    #    (bg color #FFFF00) and red text pixels (color #FF0000) within it.
    from PIL import Image
    img = Image.open(frame).convert("RGB")
    w, h = img.size
    pixels = img.load()

    # The bg should sit at ~20% from bottom (margin_v=20% of 1280 = 256px).
    # Allow a generous y-band because of padding + text height.
    yellow_count = 0
    red_count = 0
    for y in range(int(h * 0.6), int(h * 0.95)):
        for x in range(0, w):
            r, g, b = pixels[x, y]
            if r > 200 and g > 200 and b < 80:
                yellow_count += 1
            elif r > 200 and g < 80 and b < 80:
                red_count += 1
    assert yellow_count > 1000, f"expected yellow bg pixels in lower band, got {yellow_count}"
    assert red_count > 50, f"expected red text pixels in lower band, got {red_count}"
