from PIL import Image

from app.utils.ocr.easyocr_engine import (
    _format_ocr_results,
    _preprocess_for_ocr,
    _score_ocr_results,
    extract_ocr_result_from_pil_image,
    extract_text_and_boxes_from_pil_image,
)


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_ocr_results_keep_rows_and_column_gaps():
    results = [
        (_box(20, 10, 80, 25), "Action", 0.99),
        (_box(240, 10, 300, 25), "Time", 0.99),
        (_box(430, 10, 520, 25), "Personnel", 0.99),
        (_box(20, 45, 120, 60), "Orientation", 0.99),
        (_box(240, 45, 330, 60), "15 minutes", 0.99),
        (_box(430, 45, 540, 60), "Guidance Staff", 0.99),
    ]

    text = _format_ocr_results(results)

    assert "Action | Time | Personnel" in text
    assert "Orientation | 15 minutes | Guidance Staff" in text


def test_preprocess_for_ocr_upscales_small_scans(monkeypatch):
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_preprocess_enabled", True)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_min_dimension", 1200)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_max_dimension", 2600)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_threshold_enabled", False)

    image = Image.new("RGB", (500, 300), "white")
    processed = _preprocess_for_ocr(image)

    assert processed.mode == "RGB"
    assert min(processed.size) == 1200
    assert max(processed.size) <= 2600


def test_preprocess_for_ocr_can_threshold(monkeypatch):
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_preprocess_enabled", True)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_threshold_enabled", True)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_threshold_value", 128)

    image = Image.new("L", (20, 20), 100)
    processed = _preprocess_for_ocr(image)
    values = processed.convert("L").getdata()

    assert set(values) <= {0, 255}


def test_ocr_score_prefers_readable_text_over_symbol_noise():
    readable = [
        (_box(10, 10, 160, 30), "Guidance Office", 0.91),
        (_box(10, 45, 260, 65), "LSPU Entrance Test", 0.88),
    ]
    noisy = [
        (_box(10, 10, 160, 30), "GprVCotn] #tdlin", 0.32),
        (_box(10, 45, 260, 65), "CJint SttPt | AOr | lo u", 0.28),
    ]

    assert _score_ocr_results(readable) > _score_ocr_results(noisy)


def _poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


_ORIGINAL_POLY = _poly(10.0, 20.0, 40.0, 50.0)
_ENHANCED_POLY = _poly(80.0, 160.0, 320.0, 400.0)
_WEAK_TEXT = "xx"
_STRONG_TEXT = "Guidance Office LSPU Entrance Test"


def _prepare_resized_candidates(monkeypatch):
    """A 500x300 image is upscaled by the real preprocessor; original and
    enhanced therefore have different sizes. EasyOCR is not executed.
    """
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_preprocess_enabled", True)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_compare_original", True)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_min_dimension", 1200)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_max_dimension", 2600)
    monkeypatch.setattr("app.utils.ocr.easyocr_engine.settings.ocr_threshold_enabled", False)
    image = Image.new("RGB", (500, 300), "white")
    enhanced = _preprocess_for_ocr(image)
    assert enhanced.size != image.size
    return image, enhanced


def _patch_read_ocr(monkeypatch, original_size, enhanced_size, original_result, enhanced_result):
    original_wh = (int(original_size[0]), int(original_size[1]))
    enhanced_wh = (int(enhanced_size[0]), int(enhanced_size[1]))

    def fake_read(image_array):
        height, width = image_array.shape[:2]
        if (width, height) == original_wh:
            return original_result
        if (width, height) == enhanced_wh:
            return enhanced_result
        raise AssertionError(f"unexpected OCR candidate size {(width, height)}")

    monkeypatch.setattr("app.utils.ocr.easyocr_engine._read_ocr", fake_read)


def test_original_ocr_candidate_wins_reports_pixmap_coordinate_size(monkeypatch):
    """Contract test: original candidate wins. Not a scanned-PDF validation."""
    image, enhanced = _prepare_resized_candidates(monkeypatch)
    _patch_read_ocr(
        monkeypatch,
        image.size,
        enhanced.size,
        [(_ORIGINAL_POLY, _STRONG_TEXT, 0.99)],
        [(_ENHANCED_POLY, _WEAK_TEXT, 0.20)],
    )
    text, boxes, size = extract_ocr_result_from_pil_image(image)
    assert size == (float(image.size[0]), float(image.size[1]))
    assert size != (float(enhanced.size[0]), float(enhanced.size[1]))
    assert boxes[0]["x0"] == 10.0
    assert boxes[0]["y0"] == 20.0
    assert boxes[0]["x1"] == 40.0
    assert boxes[0]["y1"] == 50.0
    assert _STRONG_TEXT.split()[0] in text


def test_enhanced_resized_ocr_candidate_wins_reports_actual_output_size(monkeypatch):
    """Contract test: enhanced/resized candidate wins, including integer rounding."""
    image, enhanced = _prepare_resized_candidates(monkeypatch)
    _patch_read_ocr(
        monkeypatch,
        image.size,
        enhanced.size,
        [(_ORIGINAL_POLY, _WEAK_TEXT, 0.20)],
        [(_ENHANCED_POLY, _STRONG_TEXT, 0.99)],
    )
    _text, boxes, size = extract_ocr_result_from_pil_image(image)
    assert size == (float(enhanced.size[0]), float(enhanced.size[1]))
    assert size != (float(image.size[0]), float(image.size[1]))
    assert boxes[0]["x0"] == 80.0
    assert boxes[0]["y0"] == 160.0
    assert boxes[0]["x1"] == 320.0
    assert boxes[0]["y1"] == 400.0


def test_coordinate_size_belongs_to_winner_not_zoom_or_first_candidate(monkeypatch):
    image, enhanced = _prepare_resized_candidates(monkeypatch)
    assert image.size[0] != enhanced.size[0]
    _patch_read_ocr(
        monkeypatch,
        image.size,
        enhanced.size,
        [(_ORIGINAL_POLY, _WEAK_TEXT, 0.20)],
        [(_ENHANCED_POLY, _STRONG_TEXT, 0.99)],
    )
    _text, _boxes, size = extract_ocr_result_from_pil_image(image)
    assert size == (float(enhanced.size[0]), float(enhanced.size[1]))
    public_text, public_boxes = extract_text_and_boxes_from_pil_image(image)
    assert isinstance(public_text, str)
    assert public_boxes[0]["x0"] == 80.0


def test_winning_ocr_boxes_are_not_transformed(monkeypatch):
    image, enhanced = _prepare_resized_candidates(monkeypatch)
    _patch_read_ocr(
        monkeypatch,
        image.size,
        enhanced.size,
        [(_ORIGINAL_POLY, _WEAK_TEXT, 0.20)],
        [(_ENHANCED_POLY, _STRONG_TEXT, 0.99)],
    )
    _text, boxes, size = extract_ocr_result_from_pil_image(image)
    box = boxes[0]
    assert (box["x0"], box["y0"], box["x1"], box["y1"]) == (80.0, 160.0, 320.0, 400.0)
    zoom_like = 2.0
    assert (box["x0"] / zoom_like, box["y0"] / zoom_like) != (80.0, 160.0)
    assert size is not None
    assert box["x0"] != box["x0"] * (size[0] / image.size[0])
