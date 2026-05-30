"""FFmpeg wrapper for video probing, frame extraction, and proxy generation."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class FFmpegProcessor:
    """Wraps ffmpeg subprocess calls for video probing and proxy generation."""

    def __init__(self, config: dict | None = None):
        self.config = config or {}
        self._verify_ffmpeg()

    def _verify_ffmpeg(self) -> None:
        """Check that ffmpeg and ffprobe are available on the system."""
        for cmd in ("ffmpeg", "ffprobe"):
            try:
                subprocess.run(
                    [cmd, "-version"],
                    capture_output=True,
                    check=True,
                    timeout=10,
                )
            except FileNotFoundError:
                raise RuntimeError(
                    f"{cmd} not found. Install ffmpeg:\n"
                    "  macOS: brew install ffmpeg\n"
                    "  Linux: sudo apt install -y ffmpeg"
                )
            except subprocess.SubprocessError as e:
                raise RuntimeError(f"{cmd} check failed: {e}")

    def get_video_info(self, video_path: Path) -> dict:
        """Probe video metadata via ffprobe.

        Returns:
            Dict with keys: duration, width, height, resolution, codec, size_bytes.
        """
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        video_stream = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            {},
        )

        width = int(video_stream.get("width", 0))
        height = int(video_stream.get("height", 0))
        return {
            "duration": float(fmt.get("duration", 0)),
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}" if width and height else "",
            "codec": video_stream.get("codec_name", ""),
            "size_bytes": int(fmt.get("size", 0)),
        }

    def generate_proxy(
        self,
        video_path: Path,
        output_path: Path,
        max_height: int = 360,
    ) -> Path:
        """Generate a low-resolution proxy video for editing.

        Transcodes to 480p with ultrafast preset for quick generation.
        Timestamps remain accurate for subtitle sync.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", f"scale=-2:{max_height}",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "28",
            "-c:a", "aac",
            "-b:a", "64k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            raise RuntimeError(f"Proxy generation failed: {result.stderr[-500:]}")

        logger.info(f"Generated proxy: {output_path}")
        return output_path

    def extract_frames(
        self,
        video_path: Path,
        output_dir: Path,
        fps: float = 2.0,
        crop_bottom_pct: float = 0.0,
    ) -> list[Path]:
        """Extract video frames as JPEG images at the given FPS.

        Args:
            video_path: Source video file.
            output_dir: Directory to write frame images.
            fps: Frames per second to extract (default 2.0).
            crop_bottom_pct: If >0, crop to only the bottom N% of the frame.
                E.g., 0.25 extracts only the bottom 25%. Speeds up OCR by
                reducing the area PaddleOCR needs to scan.

        Returns:
            Sorted list of extracted frame file paths.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        pattern = str(output_dir / "frame_%06d.jpg")

        if crop_bottom_pct > 0:
            # crop=w:h:x:y — keep bottom N% of the frame
            # in_w, in_h are ffmpeg expressions for input width/height
            crop_h = f"ih*{crop_bottom_pct}"
            vf = f"fps={fps},crop=iw:{crop_h}:0:ih-{crop_h}"
        else:
            vf = f"fps={fps}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vf", vf,
            "-q:v", "2",
            pattern,
        ]

        crop_info = f", crop bottom {crop_bottom_pct:.0%}" if crop_bottom_pct > 0 else ""
        logger.info(f"Extracting frames at {fps} FPS{crop_info}: {video_path.name}")
        self._run_ffmpeg(cmd)

        frames = sorted(output_dir.glob("frame_*.jpg"))
        logger.info(f"Extracted {len(frames)} frames to {output_dir}")
        return frames

    @staticmethod
    def _escape_filter_path(path: Path) -> str:
        """Escape file path for use in ffmpeg filter expressions.

        ffmpeg filter syntax requires escaping: \\ : ' [ ]
        """
        s = str(path)
        # Escape backslashes first, then colons and single quotes
        s = s.replace("\\", "\\\\\\\\")
        s = s.replace(":", "\\:")
        s = s.replace("'", "'\\\\\\''")
        return s

    @staticmethod
    def _run_ffmpeg(cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute an ffmpeg command with error handling."""
        logger.debug(f"ffmpeg command: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=600,  # 10 min timeout
            )
            return result
        except subprocess.CalledProcessError as e:
            # Parse ffmpeg stderr for meaningful error
            stderr = e.stderr or ""
            last_lines = "\n".join(stderr.strip().split("\n")[-5:])
            raise RuntimeError(f"ffmpeg failed:\n{last_lines}") from e
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg timed out after 10 minutes")
