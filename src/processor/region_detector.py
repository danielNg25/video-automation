"""Subtitle region detector — analyzes OCR bounding boxes to find where original subtitles are."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SubtitleRegion:
    """Bounding rectangle for the original subtitle area in pixel coordinates."""

    x: int
    y: int
    width: int
    height: int

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2

    @property
    def bottom(self) -> int:
        return self.y + self.height

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> SubtitleRegion:
        return cls(x=d["x"], y=d["y"], width=d["width"], height=d["height"])


class SubtitleRegionDetector:
    """Detects the original subtitle region from OCR metadata."""

    def __init__(self, padding: int = 0):
        self.padding = padding

    def detect_from_ocr_meta(
        self,
        ocr_meta_path: Path,
    ) -> SubtitleRegion | None:
        """Load OCR metadata and return the pre-computed subtitle region.

        Args:
            ocr_meta_path: Path to {video_id}_ocr_meta.json.

        Returns:
            SubtitleRegion if region data exists, None otherwise.
        """
        if not ocr_meta_path.exists():
            logger.info(f"No OCR metadata at {ocr_meta_path} — blur will be skipped")
            return None

        with open(ocr_meta_path) as f:
            meta = json.load(f)

        region_data = meta.get("subtitle_region")
        if not region_data:
            logger.info("OCR metadata exists but has no subtitle_region — blur skipped")
            return None

        region = SubtitleRegion.from_dict(region_data)
        # No padding — blur exactly the OCR-detected subtitle bounding box.

        logger.info(
            f"Loaded subtitle region: x={region.x}, y={region.y}, "
            f"w={region.width}, h={region.height}"
        )
        return region

    def detect_from_boxes(
        self,
        ocr_boxes: list[dict],
        video_width: int,
        video_height: int,
    ) -> SubtitleRegion | None:
        """Compute subtitle region from raw OCR bounding boxes.

        Filters boxes to keep subtitle-classified text (bottom 35%, not watermarks),
        then computes the bounding rectangle that encompasses all subtitle text.

        Args:
            ocr_boxes: List of dicts with 'bbox' (4-point polygon), 'text', 'confidence',
                       and optional 'is_subtitle' flag.
            video_width: Frame width in pixels.
            video_height: Frame height in pixels.

        Returns:
            SubtitleRegion or None if no subtitle boxes found.
        """
        subtitle_boxes = []
        for box in ocr_boxes:
            # Use pre-classified flag if available, otherwise filter by position
            if "is_subtitle" in box:
                if not box["is_subtitle"]:
                    continue
            else:
                bbox = box.get("bbox", [])
                if len(bbox) < 4:
                    continue
                center_y = (bbox[0][1] + bbox[2][1]) / 2
                if center_y < video_height * 0.65:
                    continue

            subtitle_boxes.append(box)

        if not subtitle_boxes:
            logger.info("No subtitle bounding boxes found")
            return None

        # Compute the union bounding rectangle
        min_x = video_width
        min_y = video_height
        max_x = 0
        max_y = 0

        for box in subtitle_boxes:
            bbox = box.get("bbox", [])
            if len(bbox) < 4:
                continue
            for point in bbox:
                px, py = point[0], point[1]
                min_x = min(min_x, px)
                min_y = min(min_y, py)
                max_x = max(max_x, px)
                max_y = max(max_y, py)

        # Apply padding
        min_x = max(0, int(min_x) - self.padding)
        min_y = max(0, int(min_y) - self.padding)
        max_x = min(video_width, int(max_x) + self.padding)
        max_y = min(video_height, int(max_y) + self.padding)

        width = max_x - min_x
        height = max_y - min_y

        # Clamp to reasonable bounds
        if height < 50:
            height = 50
        if height > int(video_height * 0.4):
            height = int(video_height * 0.4)

        region = SubtitleRegion(x=min_x, y=min_y, width=width, height=height)
        logger.info(
            f"Detected subtitle region from {len(subtitle_boxes)} boxes: "
            f"x={region.x}, y={region.y}, w={region.width}, h={region.height}"
        )
        return region


def load_subtitle_region(srt_dir: Path, video_id: str) -> SubtitleRegion | None:
    """Convenience: load subtitle region from OCR metadata file.

    Returns None if no OCR metadata exists (e.g. video was Whisper-transcribed).
    """
    meta_path = srt_dir / f"{video_id}_ocr_meta.json"
    detector = SubtitleRegionDetector()
    return detector.detect_from_ocr_meta(meta_path)
