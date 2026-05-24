"""Tests for OCRTranscriber._parse_ocr_result — the shape adapter.

Locks the contract that downstream filtering / watermark logic expects:
each detection is `(bbox_4pts, text_str, confidence_float)`.
Covers RapidOCR (current engine), PaddleOCR v2, and PaddleOCR v3 shapes.
"""


class TestParseRapidOCR:
    def test_empty(self):
        from src.transcriber.ocr import OCRTranscriber
        assert OCRTranscriber._parse_ocr_result(None) == []
        assert OCRTranscriber._parse_ocr_result([]) == []

    def test_single_detection(self):
        """RapidOCR emits [[bbox_pts, text, conf], ...]."""
        from src.transcriber.ocr import OCRTranscriber
        raw = [
            [[[0, 0], [100, 0], [100, 20], [0, 20]], "hello", 0.95],
        ]
        out = OCRTranscriber._parse_ocr_result(raw)
        assert len(out) == 1
        bbox, text, conf = out[0]
        assert bbox == [[0, 0], [100, 0], [100, 20], [0, 20]]
        assert text == "hello"
        assert conf == 0.95

    def test_confidence_stringified_is_cast(self):
        """Some ORT pipelines emit conf as np.float32 / np.str_. Cast safely."""
        from src.transcriber.ocr import OCRTranscriber
        raw = [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], "x", "0.5"],
        ]
        out = OCRTranscriber._parse_ocr_result(raw)
        assert out[0][2] == 0.5

    def test_multiple_detections_preserved_in_order(self):
        from src.transcriber.ocr import OCRTranscriber
        raw = [
            [[[0, 0], [10, 0], [10, 10], [0, 10]], "first", 0.9],
            [[[20, 0], [30, 0], [30, 10], [20, 10]], "second", 0.85],
        ]
        out = OCRTranscriber._parse_ocr_result(raw)
        assert [d[1] for d in out] == ["first", "second"]


class TestParsePaddleV3:
    def test_dict_with_rec_texts(self):
        """Paddle v3 returns one dict with parallel rec_texts/rec_scores/dt_polys."""
        from src.transcriber.ocr import OCRTranscriber
        raw = [{
            "rec_texts": ["one", "two"],
            "rec_scores": [0.95, 0.80],
            "dt_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[20, 0], [30, 0], [30, 10], [20, 10]],
            ],
        }]
        out = OCRTranscriber._parse_ocr_result(raw)
        assert len(out) == 2
        assert out[0] == ([[0, 0], [10, 0], [10, 10], [0, 10]], "one", 0.95)


class TestParsePaddleV2:
    def test_nested_list_with_bbox_and_text_tuple(self):
        """Paddle v2: [[(bbox, (text, conf)), ...]]."""
        from src.transcriber.ocr import OCRTranscriber
        raw = [
            [
                (
                    [[0, 0], [10, 0], [10, 10], [0, 10]],
                    ("hello", 0.99),
                ),
            ],
        ]
        out = OCRTranscriber._parse_ocr_result(raw)
        assert len(out) == 1
        assert out[0] == ([[0, 0], [10, 0], [10, 10], [0, 10]], "hello", 0.99)
