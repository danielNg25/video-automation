from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


class MLXWhisperTranscriber(BaseTranscriber):
    """Transcriber using mlx-whisper for macOS Apple Silicon."""

    def __init__(self, model_size: str = "large-v3"):
        self.model_size = model_size
        # Map model_size to HuggingFace model path
        self._model_map = {
            "tiny": "mlx-community/whisper-tiny-mlx",
            "base": "mlx-community/whisper-base-mlx",
            "small": "mlx-community/whisper-small-mlx",
            "medium": "mlx-community/whisper-medium-mlx",
            "large-v3": "mlx-community/whisper-large-v3-mlx",
        }

    def _get_model_path(self) -> str:
        """Get the HuggingFace model path for the configured model size."""
        return self._model_map.get(self.model_size, f"mlx-community/whisper-{self.model_size}-mlx")

    def transcribe(
        self, video_path: str, language: str = "zh", task: str = "transcribe"
    ) -> list[dict]:
        """Transcribe using mlx-whisper.

        Args:
            video_path: Path to video file.
            language: Source language code.
            task: 'transcribe' or 'translate'.

        Returns:
            List of segment dicts with 'start', 'end', 'text'.
        """
        import mlx_whisper

        model_path = self._get_model_path()
        logger.info(
            f"Transcribing {video_path} with MLX Whisper "
            f"(model={model_path}, language={language}, task={task})"
        )

        result = mlx_whisper.transcribe(
            video_path,
            path_or_hf_repo=model_path,
            language=language,
            task=task,
        )

        segments = []
        for seg in result.get("segments", []):
            segments.append(
                {
                    "start": seg["start"],
                    "end": seg["end"],
                    "text": seg["text"],
                }
            )

        logger.info(f"Transcription complete: {len(segments)} segments")
        return segments
