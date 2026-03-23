from unittest.mock import patch

from src.transcriber import get_transcriber
from src.transcriber.base import BaseTranscriber
from src.transcriber.ocr import OCRTranscriber


class TestTimestampFormatting:
    """Tests for BaseTranscriber._format_timestamp."""

    def test_zero(self):
        assert BaseTranscriber._format_timestamp(0.0) == "00:00:00,000"

    def test_simple_seconds(self):
        assert BaseTranscriber._format_timestamp(1.5) == "00:00:01,500"

    def test_minutes_and_seconds(self):
        assert BaseTranscriber._format_timestamp(61.5) == "00:01:01,500"

    def test_hours_minutes_seconds(self):
        assert BaseTranscriber._format_timestamp(3661.123) == "01:01:01,123"

    def test_large_value(self):
        assert BaseTranscriber._format_timestamp(7384.999) == "02:03:04,999"

    def test_sub_millisecond(self):
        # Should round to nearest millisecond
        result = BaseTranscriber._format_timestamp(1.0005)
        assert result == "00:00:01,001" or result == "00:00:01,000"

    def test_exact_minute(self):
        assert BaseTranscriber._format_timestamp(60.0) == "00:01:00,000"

    def test_exact_hour(self):
        assert BaseTranscriber._format_timestamp(3600.0) == "01:00:00,000"


class TestSRTGeneration:
    """Tests for BaseTranscriber.generate_srt."""

    def _make_transcriber(self):
        """Create a concrete subclass for testing."""

        class ConcreteTranscriber(BaseTranscriber):
            def transcribe(self, video_path, language="zh", task="transcribe"):
                return []

        return ConcreteTranscriber()

    def test_generate_srt_basic(self, tmp_path):
        t = self._make_transcriber()
        segments = [
            {"start": 0.0, "end": 2.5, "text": "你好世界"},
            {"start": 3.0, "end": 5.5, "text": "测试字幕"},
        ]
        out = t.generate_srt(segments, tmp_path / "test.srt")
        content = out.read_text(encoding="utf-8")

        assert "1\n" in content
        assert "00:00:00,000 --> 00:00:02,500" in content
        assert "你好世界" in content
        assert "2\n" in content
        assert "00:00:03,000 --> 00:00:05,500" in content
        assert "测试字幕" in content

    def test_generate_srt_skips_empty_text(self, tmp_path):
        t = self._make_transcriber()
        segments = [
            {"start": 0.0, "end": 1.0, "text": ""},
            {"start": 1.0, "end": 2.0, "text": "  "},
            {"start": 2.0, "end": 3.0, "text": "valid"},
        ]
        out = t.generate_srt(segments, tmp_path / "test.srt")
        content = out.read_text(encoding="utf-8")
        # Only the valid segment should appear
        assert "valid" in content
        assert content.count("-->") == 1

    def test_generate_srt_creates_parent_dirs(self, tmp_path):
        t = self._make_transcriber()
        segments = [{"start": 0.0, "end": 1.0, "text": "test"}]
        out = t.generate_srt(segments, tmp_path / "sub" / "dir" / "test.srt")
        assert out.exists()

    def test_generate_srt_empty_segments(self, tmp_path):
        t = self._make_transcriber()
        out = t.generate_srt([], tmp_path / "empty.srt")
        content = out.read_text(encoding="utf-8")
        assert content == ""


class TestTranscriberFactory:
    """Tests for get_transcriber factory."""

    def test_selects_mlx_on_darwin(self):
        with patch("src.transcriber.sys") as mock_sys:
            mock_sys.platform = "darwin"
            t = get_transcriber({"model_size": "tiny"})
        from src.transcriber.mlx import MLXWhisperTranscriber

        assert isinstance(t, MLXWhisperTranscriber)
        assert t.model_size == "tiny"

    def test_selects_faster_on_linux(self):
        with patch("src.transcriber.sys") as mock_sys:
            mock_sys.platform = "linux"
            t = get_transcriber({"model_size": "base"})
        from src.transcriber.faster import FasterWhisperTranscriber

        assert isinstance(t, FasterWhisperTranscriber)
        assert t.model_size == "base"

    def test_config_override_backend(self):
        t = get_transcriber({"model_size": "small", "backend": "mlx"})
        from src.transcriber.mlx import MLXWhisperTranscriber

        assert isinstance(t, MLXWhisperTranscriber)

    def test_faster_whisper_config_options(self):
        config = {
            "model_size": "medium",
            "backend": "faster",
            "device": "cuda",
            "compute_type": "int8",
            "vad_filter": False,
            "vad_min_silence_ms": 300,
        }
        t = get_transcriber(config)
        from src.transcriber.faster import FasterWhisperTranscriber

        assert isinstance(t, FasterWhisperTranscriber)
        assert t.device == "cuda"
        assert t.compute_type == "int8"
        assert t.vad_filter is False
        assert t.vad_min_silence_ms == 300

    def test_default_model_size(self):
        t = get_transcriber({"backend": "mlx"})
        assert t.model_size == "large-v3"


class TestMLXModelMapping:
    """Tests for MLXWhisperTranscriber model path mapping."""

    def test_known_model(self):
        from src.transcriber.mlx import MLXWhisperTranscriber

        t = MLXWhisperTranscriber(model_size="large-v3")
        assert t._get_model_path() == "mlx-community/whisper-large-v3-mlx"

    def test_tiny_model(self):
        from src.transcriber.mlx import MLXWhisperTranscriber

        t = MLXWhisperTranscriber(model_size="tiny")
        assert t._get_model_path() == "mlx-community/whisper-tiny-mlx"

    def test_unknown_model_fallback(self):
        from src.transcriber.mlx import MLXWhisperTranscriber

        t = MLXWhisperTranscriber(model_size="custom-v2")
        assert t._get_model_path() == "mlx-community/whisper-custom-v2-mlx"


class TestOCRTranscriberClassification:
    """Tests for OCRTranscriber auto-classification logic."""

    def _make_bbox(self, cx, cy, text_h, text_w=200):
        """Create a PaddleOCR-style bbox centered at (cx, cy)."""
        x1 = cx - text_w / 2
        x2 = cx + text_w / 2
        y1 = cy - text_h / 2
        y2 = cy + text_h / 2
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def test_subtitle_text_in_bottom_region(self):
        """Text in bottom 35% of frame should be classified as subtitle."""
        t = OCRTranscriber()
        # Frame is 1080x1920
        bbox = self._make_bbox(540, 1600, 50)  # center_y=1600, bottom region
        detections = [(bbox, "你好世界", 0.95)]

        text = t._filter_subtitle_text(detections, set(), 1920, 1080)
        assert "你好世界" in text

    def test_text_in_top_region_filtered(self):
        """Text in top of frame should be filtered out."""
        t = OCRTranscriber()
        bbox = self._make_bbox(540, 100, 30)  # top of frame
        detections = [(bbox, "watermark", 0.95)]

        text = t._filter_subtitle_text(detections, set(), 1920, 1080)
        assert text == ""

    def test_small_text_filtered(self):
        """Text too small (< 2% frame height) should be filtered."""
        t = OCRTranscriber()
        # frame height 1920, 2% = 38.4px. Make text 20px tall
        bbox = self._make_bbox(540, 1600, 20)
        detections = [(bbox, "tiny", 0.95)]

        text = t._filter_subtitle_text(detections, set(), 1920, 1080)
        assert text == ""

    def test_text_at_edge_filtered(self):
        """Text in outer 10% horizontal margin should be filtered."""
        t = OCRTranscriber()
        # frame width 1080, 10% margin = 108px. Place text at x=50
        bbox = self._make_bbox(50, 1600, 50)
        detections = [(bbox, "edge", 0.95)]

        text = t._filter_subtitle_text(detections, set(), 1920, 1080)
        assert text == ""

    def test_low_confidence_filtered(self):
        """Text below confidence threshold should be filtered."""
        t = OCRTranscriber(confidence_threshold=0.7)
        bbox = self._make_bbox(540, 1600, 50)
        detections = [(bbox, "unsure", 0.3)]

        text = t._filter_subtitle_text(detections, set(), 1920, 1080)
        assert text == ""


class TestOCRWatermarkFiltering:
    """Tests for watermark detection by frequency."""

    def _make_bbox(self, cx, cy, text_h, text_w=200):
        x1 = cx - text_w / 2
        x2 = cx + text_w / 2
        y1 = cy - text_h / 2
        y2 = cy + text_h / 2
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    def test_high_frequency_position_is_watermark(self):
        """Text appearing in >80% of sampled frames at same Y = watermark."""
        t = OCRTranscriber()
        # 10 samples, text at y=1700 appears in 9/10 = 90%
        bbox = self._make_bbox(540, 1700, 50)
        sample_detections = [
            (i, [(bbox, "@username", 0.95)]) for i in range(9)
        ] + [(9, [])]

        watermarks = t._build_watermark_positions(sample_detections, 10, 1920)
        bucket = int(1700) // max(1, int(1920 * 0.05))
        assert bucket in watermarks

    def test_low_frequency_not_watermark(self):
        """Text appearing in <80% of frames should not be classified as watermark."""
        t = OCRTranscriber()
        bbox = self._make_bbox(540, 1700, 50)
        # Only 3/10 frames = 30%
        sample_detections = [
            (i, [(bbox, "subtitle", 0.95)]) for i in range(3)
        ] + [(i, []) for i in range(3, 10)]

        watermarks = t._build_watermark_positions(sample_detections, 10, 1920)
        bucket = int(1700) // max(1, int(1920 * 0.05))
        assert bucket not in watermarks

    def test_varying_text_not_watermark(self):
        """High-frequency position with varying text = subtitles, not watermark."""
        t = OCRTranscriber()
        bbox = self._make_bbox(540, 1700, 50)
        # Text at same Y in 10/10 frames but different text each time
        texts = ["你好", "世界", "今天", "天气", "很好", "谢谢", "再见", "朋友", "开心", "快乐"]
        sample_detections = [
            (i, [(bbox, texts[i], 0.95)]) for i in range(10)
        ]

        watermarks = t._build_watermark_positions(sample_detections, 10, 1920)
        bucket = int(1700) // max(1, int(1920 * 0.05))
        assert bucket not in watermarks

    def test_watermark_position_skipped_in_filter(self):
        """Detections at watermark Y-positions should be skipped."""
        t = OCRTranscriber()
        frame_height = 1920
        bucket_size = max(1, int(frame_height * 0.05))
        bbox = self._make_bbox(540, 1700, 50)
        y_bucket = int(1700) // bucket_size

        detections = [(bbox, "watermark text", 0.95)]
        text = t._filter_subtitle_text(detections, {y_bucket}, frame_height, 1080)
        assert text == ""


class TestOCRDeduplication:
    """Tests for frame deduplication logic."""

    def test_identical_frames_merge(self):
        """Identical consecutive texts should merge into one segment."""
        t = OCRTranscriber(fps=2.0, similarity_threshold=0.85)
        frame_texts = ["你好世界", "你好世界", "你好世界", "", ""]
        segments = t._deduplicate_frames(frame_texts)
        assert len(segments) == 1
        assert segments[0]["text"] == "你好世界"
        assert segments[0]["start"] == 0.0
        assert segments[0]["end"] == 1.5  # 3 frames at 0.5s each

    def test_different_texts_create_separate_segments(self):
        """Different texts should create separate segments."""
        t = OCRTranscriber(fps=2.0, similarity_threshold=0.85)
        frame_texts = ["你好", "你好", "", "世界", "世界", ""]
        segments = t._deduplicate_frames(frame_texts)
        assert len(segments) == 2
        assert segments[0]["text"] == "你好"
        assert segments[1]["text"] == "世界"

    def test_empty_frames_close_segment(self):
        """Empty frame should close the current segment."""
        t = OCRTranscriber(fps=2.0, similarity_threshold=0.85)
        frame_texts = ["text", "text", "", "", "new", "new"]
        segments = t._deduplicate_frames(frame_texts)
        assert len(segments) == 2

    def test_min_duration_filter(self):
        """Segments shorter than 0.5s should be filtered out."""
        t = OCRTranscriber(fps=2.0, similarity_threshold=0.85)
        # Single frame = 0.5s at 2fps, then empty → segment is exactly at boundary
        frame_texts = ["short", ""]
        segments = t._deduplicate_frames(frame_texts)
        # 1 frame at 2fps → segment from 0.0 to 0.5s = 0.5s duration, passes filter
        assert len(segments) == 1

    def test_all_empty_returns_nothing(self):
        """All empty frames should return no segments."""
        t = OCRTranscriber(fps=2.0)
        segments = t._deduplicate_frames(["", "", ""])
        assert segments == []

    def test_similar_text_extends_segment(self):
        """Slightly different but similar text should extend segment."""
        t = OCRTranscriber(fps=2.0, similarity_threshold=0.85)
        # These are similar enough (>0.85 ratio)
        frame_texts = ["你好世界欢迎", "你好世界欢迎你", "", ""]
        segments = t._deduplicate_frames(frame_texts)
        assert len(segments) == 1
        # Should keep the longer text
        assert segments[0]["text"] == "你好世界欢迎你"


class TestOCRParseResult:
    """Tests for PaddleOCR result parsing."""

    def test_parse_v2_result(self):
        """PaddleOCR v2 format: [[(bbox, (text, conf)), ...]]"""
        result = [[
            [[[10, 20], [200, 20], [200, 50], [10, 50]], ("你好", 0.95)],
            [[[10, 100], [200, 100], [200, 130], [10, 130]], ("世界", 0.88)],
        ]]
        detections = OCRTranscriber._parse_ocr_result(result)
        assert len(detections) == 2
        assert detections[0][1] == "你好"
        assert detections[0][2] == 0.95

    def test_parse_v3_result(self):
        """PaddleOCR v3 format: [{"rec_texts": [...], ...}]"""
        import numpy as np

        result = [{
            "rec_texts": ["你好", "世界"],
            "rec_scores": [0.95, 0.88],
            "dt_polys": [
                np.array([[10, 20], [200, 20], [200, 50], [10, 50]]),
                np.array([[10, 100], [200, 100], [200, 130], [10, 130]]),
            ],
        }]
        detections = OCRTranscriber._parse_ocr_result(result)
        assert len(detections) == 2
        assert detections[0][1] == "你好"
        assert detections[0][2] == 0.95
        assert detections[1][1] == "世界"

    def test_parse_empty_result(self):
        assert OCRTranscriber._parse_ocr_result(None) == []
        assert OCRTranscriber._parse_ocr_result([]) == []
        assert OCRTranscriber._parse_ocr_result([None]) == []


class TestTranscriberFactoryOCR:
    """Tests for factory OCR backend selection."""

    def test_factory_returns_ocr_transcriber(self):
        t = get_transcriber({"fps": 1.0}, method="ocr")
        assert isinstance(t, OCRTranscriber)
        assert t.fps == 1.0

    def test_factory_default_is_audio(self):
        """No method arg should default to audio backend."""
        t = get_transcriber({"model_size": "tiny", "backend": "mlx"})
        from src.transcriber.mlx import MLXWhisperTranscriber
        assert isinstance(t, MLXWhisperTranscriber)

    def test_factory_ocr_with_region(self):
        region = {"x": 0.1, "y": 0.7, "w": 0.8, "h": 0.25}
        t = get_transcriber({}, method="ocr", ocr_region=region)
        assert isinstance(t, OCRTranscriber)
        assert t.ocr_region == region

    def test_factory_ocr_config_passthrough(self):
        config = {
            "fps": 3.0,
            "confidence_threshold": 0.8,
            "similarity_threshold": 0.9,
            "subtitle_region": {"min_y": 0.5, "max_watermark_frequency": 0.7},
        }
        t = get_transcriber(config, method="ocr")
        assert t.fps == 3.0
        assert t.confidence_threshold == 0.8
        assert t.similarity_threshold == 0.9
        assert t.min_y == 0.5
        assert t.max_watermark_freq == 0.7
