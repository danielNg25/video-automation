import sys

from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_transcriber(config: dict, method: str = "audio", **kwargs) -> BaseTranscriber:
    """Factory to create the appropriate transcriber.

    When method="audio", auto-selects mlx-whisper on macOS and faster-whisper elsewhere.
    When method="ocr", returns OCRTranscriber for subtitle extraction via PaddleOCR.

    Args:
        config: Config dict (whisper or ocr section depending on method).
        method: "audio" for Whisper transcription, "ocr" for OCR extraction.
        **kwargs: Extra args forwarded to OCRTranscriber (e.g. ocr_region, progress_callback).

    Returns:
        Configured transcriber instance.
    """
    if method == "ocr":
        from src.transcriber.ocr import OCRTranscriber

        fps = config.get("fps", 2.0)
        confidence = config.get("confidence_threshold", 0.7)
        similarity = config.get("similarity_threshold", 0.85)
        region_cfg = config.get("subtitle_region", {})

        logger.info(f"Using OCR backend (fps={fps})")
        return OCRTranscriber(
            fps=fps,
            confidence_threshold=confidence,
            similarity_threshold=similarity,
            subtitle_region_config=region_cfg,
            **kwargs,
        )

    # Audio (Whisper) backends
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
