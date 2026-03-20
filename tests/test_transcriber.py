from unittest.mock import patch

from src.transcriber import get_transcriber
from src.transcriber.base import BaseTranscriber


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
