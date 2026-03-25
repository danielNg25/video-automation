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

    logger.info(f"Using OCR backend (fps={fps}, crop={crop_bottom_pct:.0%})")
    return OCRTranscriber(
        fps=fps,
        confidence_threshold=confidence,
        similarity_threshold=similarity,
        subtitle_region_config=region_cfg,
        crop_bottom_pct=crop_bottom_pct,
        **kwargs,
    )
