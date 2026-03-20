import sys

from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_transcriber(config: dict) -> BaseTranscriber:
    """Factory to create the appropriate transcriber for the current platform.

    Auto-selects mlx-whisper on macOS (Apple Silicon) and faster-whisper elsewhere.
    Config can override with 'backend' key.

    Args:
        config: Whisper config dict (expects 'model_size', optionally 'backend').

    Returns:
        Configured transcriber instance.
    """
    model_size = config.get("model_size", "large-v3")
    backend = config.get("backend")

    if backend is None:
        backend = "mlx" if sys.platform == "darwin" else "faster"

    if backend == "mlx":
        from src.transcriber.mlx import MLXWhisperTranscriber

        logger.info(f"Using MLX Whisper backend (model={model_size})")
        return MLXWhisperTranscriber(model_size=model_size)
    else:
        from src.transcriber.faster import FasterWhisperTranscriber

        device = config.get("device", "auto")
        compute_type = config.get("compute_type", "float16")
        vad_filter = config.get("vad_filter", True)
        vad_min_silence_ms = config.get("vad_min_silence_ms", 500)

        logger.info(f"Using faster-whisper backend (model={model_size}, device={device})")
        return FasterWhisperTranscriber(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            vad_filter=vad_filter,
            vad_min_silence_ms=vad_min_silence_ms,
        )
