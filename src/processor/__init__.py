"""Video processing helpers — kept after the per-platform export pipeline
was removed.

Surviving exports:
    - ``ffmpeg.FFmpegProcessor`` (slimmed) for OCR + proxy-video generation
    - ``subtitle.parse_srt`` / ``subtitle.write_srt`` for SRT IO

Everything else (burn-in, per-platform reformat, ASS/PNG style rendering,
SubtitleStyleSpec, region detection, style matching) was deleted when the
app refocused away from in-app exports.
"""
