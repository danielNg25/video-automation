from abc import ABC, abstractmethod
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BaseTranscriber(ABC):
    """Abstract base class for subtitle extraction backends."""

    @abstractmethod
    def transcribe(
        self, video_path: str, language: str = "zh", task: str = "transcribe"
    ) -> list[dict]:
        """Transcribe audio from a video file.

        Args:
            video_path: Path to video file.
            language: Source language code (e.g., 'zh').
            task: 'transcribe' for same-language or 'translate' for zh→en.

        Returns:
            List of segment dicts with 'start', 'end', 'text' keys.
        """
        ...

    def generate_srt(self, segments: list[dict], output_path: Path) -> Path:
        """Generate an SRT file from transcription segments.

        Args:
            segments: List of segment dicts with 'start', 'end', 'text'.
            output_path: Path to write the SRT file.

        Returns:
            Path to the written SRT file.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for i, seg in enumerate(segments, start=1):
                start_ts = self._format_timestamp(seg["start"])
                end_ts = self._format_timestamp(seg["end"])
                text = seg["text"].strip()
                if not text:
                    continue
                f.write(f"{i}\n")
                f.write(f"{start_ts} --> {end_ts}\n")
                f.write(f"{text}\n\n")

        logger.info(f"SRT written: {output_path} ({len(segments)} segments)")
        return output_path

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format seconds to SRT timestamp: HH:MM:SS,mmm

        Args:
            seconds: Time in seconds.

        Returns:
            Formatted timestamp string.
        """
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int(round((seconds - int(seconds)) * 1000))
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
