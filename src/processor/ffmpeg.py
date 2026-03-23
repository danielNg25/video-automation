"""FFmpeg wrapper for subtitle burn-in and platform-specific video reformatting."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml

from src.utils.logger import setup_logger

logger = setup_logger(__name__)

# Default platform specs (fallback if config not loaded)
DEFAULT_PLATFORM_SPECS = {
    "tiktok": {
        "resolution": "1080x1920",
        "crf": 23,
        "max_bitrate": "8M",
        "max_duration": 600,
        "max_file_size_mb": 4096,
    },
    "youtube": {
        "resolution": "1080x1920",
        "crf": 20,
        "max_bitrate": "12M",
        "max_duration": None,
        "max_file_size_mb": 262144,
    },
    "facebook": {
        "resolution": "1080x1920",
        "crf": 23,
        "max_bitrate": "8M",
        "max_duration": 900,
        "max_file_size_mb": 4096,
    },
    "x": {
        "resolution": "1080x1920",
        "crf": 26,
        "max_bitrate": "4M",
        "max_duration": 140,
        "max_file_size_mb": 512,
    },
}


class FFmpegProcessor:
    """Wraps ffmpeg subprocess calls for subtitle burn-in and video reformatting."""

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

    def _build_style_string(self, style: dict) -> str:
        """Convert style dict to ffmpeg ASS force_style string.

        Example output: "FontName=Arial,FontSize=24,PrimaryColour=&H00FFFFFF,..."
        """
        mapping = {
            "font_name": "FontName",
            "font_size": "FontSize",
            "primary_color": "PrimaryColour",
            "outline_color": "OutlineColour",
            "outline_width": "Outline",
            "shadow_depth": "Shadow",
            "alignment": "Alignment",
            "margin_v": "MarginV",
        }

        parts = []
        for key, ass_key in mapping.items():
            if key in style:
                parts.append(f"{ass_key}={style[key]}")

        if style.get("bold", False):
            parts.append("Bold=1")

        # Background color support
        bg_color = style.get("background_color", "")
        bg_opacity = style.get("background_opacity", 0)
        if bg_color:
            parts.append(f"BackColour={bg_color}")
            parts.append("BorderStyle=3")
        elif bg_opacity > 0:
            alpha_hex = f"{bg_opacity:02X}"
            parts.append(f"BackColour=&H{alpha_hex}000000")
            parts.append("BorderStyle=3")

        # Horizontal margin
        margin_h = style.get("margin_h", 0)
        if margin_h:
            parts.append(f"MarginL={max(0, margin_h)}")
            parts.append(f"MarginR={max(0, -margin_h)}")

        return ",".join(parts)

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

    def burn_subtitles(
        self,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        style: dict | None = None,
    ) -> Path:
        """Burn subtitles into video using ffmpeg subtitles filter.

        Args:
            video_path: Source video file.
            subtitle_path: SRT or ASS subtitle file.
            output_path: Output video path.
            style: Optional style dict for force_style override.

        Returns:
            Path to output video.
        """
        escaped_sub = self._escape_filter_path(subtitle_path)

        if style:
            style_str = self._build_style_string(style)
            vf = f"subtitles='{escaped_sub}':force_style='{style_str}'"
        else:
            vf = f"subtitles='{escaped_sub}'"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(self.config.get("crf", 23)),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

        logger.info(f"Burning subtitles: {subtitle_path.name} → {output_path.name}")
        self._run_ffmpeg(cmd)
        return output_path

    def reformat_for_platform(
        self,
        video_path: Path,
        platform: str,
        output_path: Path,
        platform_specs: dict | None = None,
    ) -> Path:
        """Reformat video to match platform specifications.

        Args:
            video_path: Source video file.
            platform: Platform name (tiktok, youtube, facebook, x).
            output_path: Output video path.
            platform_specs: Optional specs dict override.

        Returns:
            Path to output video.
        """
        specs = platform_specs or self._load_platform_specs(platform)
        resolution = specs.get("resolution", "1080x1920")
        w, h = resolution.split("x")
        crf = specs.get("crf", 23)
        max_bitrate = specs.get("max_bitrate", "8M")
        max_duration = specs.get("max_duration")

        # Check if duration truncation needed
        if max_duration:
            info = self.get_video_info(video_path)
            if info["duration"] > max_duration:
                logger.warning(
                    f"Platform {platform}: video is {info['duration']:.1f}s, "
                    f"truncating to {max_duration}s"
                )

        vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-maxrate",
            max_bitrate,
            "-bufsize",
            f"{int(max_bitrate.rstrip('M')) * 2}M",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
        ]

        if max_duration:
            cmd.extend(["-t", str(max_duration)])

        cmd.append(str(output_path))

        logger.info(f"Reformatting for {platform}: {resolution}, CRF {crf}")
        self._run_ffmpeg(cmd)
        return output_path

    def burn_and_reformat(
        self,
        video_path: Path,
        subtitle_path: Path,
        platform: str,
        output_path: Path,
        style: dict | None = None,
        platform_specs: dict | None = None,
    ) -> Path:
        """Single-pass: burn subtitles and reformat for platform.

        More efficient than separate burn + reformat as it avoids double encoding.

        Args:
            video_path: Source video file.
            subtitle_path: SRT or ASS subtitle file.
            platform: Platform name.
            output_path: Output video path.
            style: Optional style dict.
            platform_specs: Optional specs dict override.

        Returns:
            Path to output video.
        """
        specs = platform_specs or self._load_platform_specs(platform)
        resolution = specs.get("resolution", "1080x1920")
        w, h = resolution.split("x")
        crf = specs.get("crf", 23)
        max_bitrate = specs.get("max_bitrate", "8M")
        max_duration = specs.get("max_duration")

        # Check duration truncation
        if max_duration:
            info = self.get_video_info(video_path)
            if info["duration"] > max_duration:
                logger.warning(
                    f"Platform {platform}: video is {info['duration']:.1f}s, "
                    f"truncating to {max_duration}s"
                )

        escaped_sub = self._escape_filter_path(subtitle_path)

        # Build combined filter: scale + pad + subtitles
        scale_pad = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

        if style:
            style_str = self._build_style_string(style)
            sub_filter = f"subtitles='{escaped_sub}':force_style='{style_str}'"
        else:
            sub_filter = f"subtitles='{escaped_sub}'"

        vf = f"{scale_pad},{sub_filter}"

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            str(crf),
            "-maxrate",
            max_bitrate,
            "-bufsize",
            f"{int(max_bitrate.rstrip('M')) * 2}M",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
        ]

        if max_duration:
            cmd.extend(["-t", str(max_duration)])

        cmd.append(str(output_path))

        logger.info(f"Burn+reformat for {platform}: {subtitle_path.name}, {resolution}, CRF {crf}")
        self._run_ffmpeg(cmd)
        return output_path

    def mix_audio(
        self,
        video_path: Path,
        tts_audio_path: Path,
        output_path: Path,
        original_volume: float = 0.3,
        tts_volume: float = 1.0,
    ) -> Path:
        """Mix TTS audio with original video audio.

        Args:
            video_path: Source video file.
            tts_audio_path: TTS audio track (WAV).
            output_path: Output video path.
            original_volume: Volume level for original audio (0.0-1.0).
            tts_volume: Volume level for TTS audio (0.0-1.0).

        Returns:
            Path to output video with mixed audio.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        filter_complex = (
            f"[0:a]volume={original_volume}[orig];"
            f"[1:a]volume={tts_volume}[tts];"
            "[orig][tts]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(tts_audio_path),
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.info(
            f"Mixing audio: original={original_volume}, TTS={tts_volume} → {output_path.name}"
        )
        self._run_ffmpeg(cmd)
        return output_path

    def burn_reformat_and_dub(
        self,
        video_path: Path,
        subtitle_path: Path,
        tts_audio_path: Path,
        platform: str,
        output_path: Path,
        style: dict | None = None,
        platform_specs: dict | None = None,
        original_volume: float = 0.3,
        tts_volume: float = 1.0,
    ) -> Path:
        """Single-pass: burn subtitles, reformat for platform, and mix TTS audio.

        Args:
            video_path: Source video file.
            subtitle_path: SRT or ASS subtitle file.
            tts_audio_path: TTS audio track (WAV).
            platform: Platform name.
            output_path: Output video path.
            style: Optional style dict.
            platform_specs: Optional specs dict override.
            original_volume: Volume for original audio (0.0-1.0).
            tts_volume: Volume for TTS audio (0.0-1.0).

        Returns:
            Path to output video.
        """
        specs = platform_specs or self._load_platform_specs(platform)
        resolution = specs.get("resolution", "1080x1920")
        w, h = resolution.split("x")
        crf = specs.get("crf", 23)
        max_bitrate = specs.get("max_bitrate", "8M")
        max_duration = specs.get("max_duration")

        if max_duration:
            info = self.get_video_info(video_path)
            if info["duration"] > max_duration:
                logger.warning(
                    f"Platform {platform}: video is {info['duration']:.1f}s, "
                    f"truncating to {max_duration}s"
                )

        escaped_sub = self._escape_filter_path(subtitle_path)

        scale_pad = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
        )

        if style:
            style_str = self._build_style_string(style)
            sub_filter = f"subtitles='{escaped_sub}':force_style='{style_str}'"
        else:
            sub_filter = f"subtitles='{escaped_sub}'"

        vf = f"{scale_pad},{sub_filter}"

        # Audio mixing filter
        af = (
            f"[0:a]volume={original_volume}[orig];"
            f"[1:a]volume={tts_volume}[tts];"
            "[orig][tts]amix=inputs=2:duration=first:dropout_transition=0[aout]"
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(tts_audio_path),
            "-filter_complex", f"{af}",
            "-vf", vf,
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(crf),
            "-maxrate", max_bitrate,
            "-bufsize", f"{int(max_bitrate.rstrip('M')) * 2}M",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
        ]

        if max_duration:
            cmd.extend(["-t", str(max_duration)])

        cmd.append(str(output_path))

        logger.info(
            f"Burn+reformat+dub for {platform}: {subtitle_path.name}, "
            f"{resolution}, orig_vol={original_volume}, tts_vol={tts_volume}"
        )
        self._run_ffmpeg(cmd)
        return output_path

    def _load_platform_specs(self, platform: str) -> dict:
        """Load platform specs from config or fall back to defaults."""
        # Try loading from YAML config file
        config_path = Path("config/platforms.yaml")
        if config_path.exists():
            with open(config_path) as f:
                all_specs = yaml.safe_load(f)
            if platform in all_specs:
                return all_specs[platform]

        if platform in DEFAULT_PLATFORM_SPECS:
            return DEFAULT_PLATFORM_SPECS[platform]

        logger.warning(f"No specs found for platform '{platform}', using defaults")
        return {"resolution": "1080x1920", "crf": 23, "max_bitrate": "8M"}

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
