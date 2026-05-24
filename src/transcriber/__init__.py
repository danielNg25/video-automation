from src.transcriber.base import BaseTranscriber
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def get_transcriber(config: dict, **kwargs) -> BaseTranscriber:
    """Factory to create an OCR transcriber for subtitle extraction.

    Args:
        config: OCR config dict.
        **kwargs: Extra args forwarded to OCRTranscriber (e.g. ocr_region, progress_callback).

    Returns:
        Configured OCRTranscriber instance.
    """
    from src.transcriber.ocr import OCRTranscriber

    fps = config.get("fps", 2.0)
    confidence = config.get("confidence_threshold", 0.7)
    similarity = config.get("similarity_threshold", 0.85)
    region_cfg = config.get("subtitle_region", {})
    crop_bottom_pct = config.get("crop_bottom_pct", 0.0)
    enable_frame_diff = config.get("enable_frame_diff", True)
    frame_diff_threshold = config.get("frame_diff_threshold", 3.0)
    execution_provider = config.get("execution_provider", "auto")

    logger.info(
        f"Using OCR backend (fps={fps}, crop={crop_bottom_pct:.0%}, "
        f"frame_diff={'on' if enable_frame_diff else 'off'}, "
        f"provider={execution_provider})"
    )
    return OCRTranscriber(
        fps=fps,
        confidence_threshold=confidence,
        similarity_threshold=similarity,
        subtitle_region_config=region_cfg,
        crop_bottom_pct=crop_bottom_pct,
        enable_frame_diff=enable_frame_diff,
        frame_diff_threshold=frame_diff_threshold,
        execution_provider=execution_provider,
        **kwargs,
    )
