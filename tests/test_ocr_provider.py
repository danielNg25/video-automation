"""Tests for _pick_provider — the ORT execution-provider auto-selector.

Picks the best available ONNX Runtime execution provider for OCR. CPU is
the always-available fallback; CUDA/DirectML kick in when the user runs
on a GPU host with the matching onnxruntime wheel installed.
"""

from unittest.mock import patch


class TestPickProvider:
    def test_override_cpu_returns_cpu(self):
        from src.transcriber.ocr import _pick_provider
        assert _pick_provider("cpu") == "CPUExecutionProvider"

    def test_override_cuda_returns_cuda(self):
        from src.transcriber.ocr import _pick_provider
        assert _pick_provider("cuda") == "CUDAExecutionProvider"

    def test_override_directml_returns_dml(self):
        from src.transcriber.ocr import _pick_provider
        assert _pick_provider("directml") == "DmlExecutionProvider"

    def test_override_coreml_returns_coreml(self):
        from src.transcriber.ocr import _pick_provider
        assert _pick_provider("coreml") == "CoreMLExecutionProvider"

    def test_unknown_override_falls_back_to_cpu(self):
        """Defensive: an unrecognised override string shouldn't crash."""
        from src.transcriber.ocr import _pick_provider
        assert _pick_provider("nonsense") == "CPUExecutionProvider"

    def test_auto_picks_cuda_when_available(self):
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            return_value=["CUDAExecutionProvider", "CPUExecutionProvider"],
        ):
            assert _pick_provider("auto") == "CUDAExecutionProvider"

    def test_auto_picks_dml_over_cpu(self):
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            return_value=["DmlExecutionProvider", "CPUExecutionProvider"],
        ):
            assert _pick_provider("auto") == "DmlExecutionProvider"

    def test_auto_prefers_cuda_over_dml(self):
        """Priority: CUDA > DirectML > CoreML > CPU."""
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            return_value=[
                "DmlExecutionProvider",
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ],
        ):
            assert _pick_provider("auto") == "CUDAExecutionProvider"

    def test_auto_falls_back_to_cpu(self):
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            return_value=["CPUExecutionProvider"],
        ):
            assert _pick_provider("auto") == "CPUExecutionProvider"

    def test_no_known_providers_returns_cpu(self):
        """A weird ORT install with unknown providers shouldn't crash."""
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            return_value=["SomeFutureExecutionProvider"],
        ):
            assert _pick_provider("auto") == "CPUExecutionProvider"

    def test_ort_import_error_returns_cpu(self):
        """If onnxruntime can't be imported (rare during fresh installs)
        we still return a valid provider name."""
        from src.transcriber.ocr import _pick_provider
        with patch(
            "onnxruntime.get_available_providers",
            side_effect=RuntimeError("boom"),
        ):
            assert _pick_provider("auto") == "CPUExecutionProvider"
