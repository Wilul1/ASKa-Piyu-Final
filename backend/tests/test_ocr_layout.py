from PIL import Image

from app.utils.ocr.easyocr_engine import (
    _format_ocr_results,
    _preprocess_for_ocr,
    _score_ocr_results,
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
