"""Abstract base class for TTS providers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class BaseTTSProvider(ABC):
    """Abstract base class for text-to-speech providers."""

    @abstractmethod
    async def synthesize(self, text: str, voice: str, **kwargs) -> bytes:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize.
            voice: Voice identifier.
            **kwargs: Provider-specific parameters (rate, pitch, etc.).

        Returns:
            Audio bytes (MP3 or WAV depending on provider).
        """
        ...

    @abstractmethod
    async def list_voices(self, language: str | None = None) -> list[dict]:
        """List available voices.

        Args:
            language: Optional language filter (e.g., "vi", "en").

        Returns:
            List of dicts with keys: name, language, gender, provider.
        """
        ...

    async def synthesize_segments(
        self,
        segments: list[dict],
        voice: str,
        output_dir: Path,
        on_progress: callable | None = None,
        **kwargs,
    ) -> list[Path]:
        """Synthesize audio for each subtitle segment.

        Args:
            segments: List of dicts with 'start', 'end', 'text' keys.
            voice: Voice identifier.
            output_dir: Directory to save audio clips.
            on_progress: Optional callback(current, total, message).
            **kwargs: Provider-specific parameters.

        Returns:
            List of paths to generated audio clips.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        total = len(segments)

        for i, seg in enumerate(segments):
            text = _clean_text(seg.get("text", ""))
            if not text:
                paths.append(Path(""))  # placeholder for empty segments
                if on_progress:
                    on_progress(i + 1, total, f"Skipped empty segment {i + 1}/{total}")
                continue

            if on_progress:
                on_progress(i + 1, total, f"Generating segment {i + 1}/{total}")

            audio_bytes = await self.synthesize(text, voice, **kwargs)
            clip_path = output_dir / f"seg_{i:04d}.mp3"
            clip_path.write_bytes(audio_bytes)
            paths.append(clip_path)

        logger.info(f"Synthesized {total} segments to {output_dir}")
        return paths


def _clean_text(text: str) -> str:
    """Strip SRT formatting artifacts before TTS synthesis."""
    # Remove HTML-like tags (<i>, <b>, etc.)
    text = re.sub(r"<[^>]+>", "", text)
    # Remove ASS override tags ({\\an8}, etc.)
    text = re.sub(r"\{\\[^}]+\}", "", text)
    # Collapse whitespace
    text = " ".join(text.split())
    return text.strip()
