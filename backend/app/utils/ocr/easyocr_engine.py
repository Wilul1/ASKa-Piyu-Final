"""EasyOCR wrapper for scanned images and PDF page renders."""

from __future__ import annotations

import io
import re
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from app.config import settings
from app.utils.console_encoding import suppress_ml_progress_output

if TYPE_CHECKING:
    import easyocr


@lru_cache(maxsize=1)
def get_reader() -> easyocr.Reader:
    import easyocr

    with suppress_ml_progress_output():
        return easyocr.Reader(
            settings.easyocr_languages,
            gpu=settings.easyocr_gpu,
            verbose=False,
        )


def extract_text_from_image_bytes(image_bytes: bytes) -> str:
    """Run OCR on raw image bytes (PNG, JPEG, etc.)."""
    image = Image.open(io.BytesIO(image_bytes))
    text, _boxes = _run_ocr_image(image)
    return text


def extract_text_from_pil_image(image: Image.Image) -> str:
    text, _boxes = _run_ocr_image(image)
    return text


def extract_text_and_boxes_from_pil_image(image: Image.Image) -> tuple[str, list[dict]]:
    """Like extract_text_from_pil_image, but also returns word-level bounding boxes.

    Boxes are in the pixel space of the supplied image (e.g. a rendered PDF page
    pixmap), with keys: text, x0, y0, x1, y1, cy, height.
    """
    return _run_ocr_image(image)


def _preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """
    Normalize scanned forms before OCR.

    The pipeline stays conservative: it improves contrast and small text without
    trying to erase table lines or seals that may carry document context.
    """
    image = ImageOps.exif_transpose(image)
    if not settings.ocr_preprocess_enabled:
        return image.convert("RGB")

    image = image.convert("L")
    image = _resize_for_ocr(image)
    image = image.filter(ImageFilter.MedianFilter(size=3))
    image = ImageOps.autocontrast(image)

    contrast = max(1.0, float(settings.ocr_contrast_factor))
    image = ImageEnhance.Contrast(image).enhance(contrast)

    if settings.ocr_threshold_enabled:
        threshold = min(255, max(0, int(settings.ocr_threshold_value)))
        image = image.point(lambda pixel: 255 if pixel >= threshold else 0)

    return image.convert("RGB")


def _resize_for_ocr(image: Image.Image) -> Image.Image:
    width, height = image.size
    if width <= 0 or height <= 0:
        return image

    min_dimension = max(1, int(settings.ocr_min_dimension))
    max_dimension = max(min_dimension, int(settings.ocr_max_dimension))
    smallest = min(width, height)
    largest = max(width, height)

    if smallest >= min_dimension or largest >= max_dimension:
        return image

    scale = min(min_dimension / smallest, max_dimension / largest)
    if scale <= 1.0:
        return image

    new_size = (round(width * scale), round(height * scale))
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _run_ocr_image(image: Image.Image) -> tuple[str, list[dict]]:
    image = ImageOps.exif_transpose(image)
    original = image.convert("RGB")
    candidates = [original]

    if settings.ocr_preprocess_enabled:
        enhanced = _preprocess_for_ocr(image)
        if enhanced.tobytes() != original.tobytes() or enhanced.size != original.size:
            if settings.ocr_compare_original:
                candidates.append(enhanced)
            else:
                candidates = [enhanced]

    best_results: list | None = None
    best_score = -1.0
    for candidate in candidates:
        results = _read_ocr(np.array(candidate))
        score = _score_ocr_results(results)
        if score > best_score:
            best_results = results
            best_score = score

    if not best_results:
        return "", []
    return _format_ocr_results(best_results), _boxes_from_results(best_results)


def _read_ocr(image_array: np.ndarray) -> list:
    reader = get_reader()
    with suppress_ml_progress_output():
        return reader.readtext(image_array, detail=1, paragraph=False)


def _score_ocr_results(results: list) -> float:
    if not results:
        return 0.0

    texts: list[str] = []
    confidences: list[float] = []
    for result in results:
        parsed = _parse_easyocr_result(result)
        if parsed is None:
            continue
        text = parsed["text"]
        texts.append(text)
        confidences.append(_parse_confidence(result))

    joined = " ".join(texts)
    if not joined.strip():
        return 0.0

    alpha_count = sum(1 for char in joined if char.isalpha())
    symbol_count = sum(1 for char in joined if not char.isalnum() and not char.isspace())
    char_count = max(1, len(joined))
    alpha_ratio = alpha_count / char_count
    symbol_ratio = symbol_count / char_count
    mean_confidence = sum(confidences) / len(confidences) if confidences else 0.0
    readable_words = len(re.findall(r"[A-Za-z]{3,}", joined))

    return (
        mean_confidence * 3.0
        + alpha_ratio
        + min(readable_words / 40, 1.0)
        - symbol_ratio
    )


def _boxes_from_results(results: list) -> list[dict]:
    """Parse raw EasyOCR results into sorted word boxes (text + coordinates)."""
    boxes = []
    for result in results:
        parsed = _parse_easyocr_result(result)
        if parsed is not None:
            boxes.append(parsed)
    boxes.sort(key=lambda item: (item["cy"], item["x0"]))
    return boxes


def _format_ocr_results(results: list) -> str:
    """Rebuild OCR text from bounding boxes so tables keep row order."""
    boxes = _boxes_from_results(results)

    if not boxes:
        return "\n".join(str(line) for line in results)

    heights = sorted(item["height"] for item in boxes if item["height"] > 0)
    median_height = heights[len(heights) // 2] if heights else 12
    row_threshold = max(8, median_height * 0.75)

    rows: list[list[dict]] = []
    for box in boxes:
        if not rows:
            rows.append([box])
            continue

        current = rows[-1]
        current_y = sum(item["cy"] for item in current) / len(current)
        if abs(box["cy"] - current_y) <= row_threshold:
            current.append(box)
        else:
            rows.append([box])

    lines: list[str] = []
    for row in rows:
        row.sort(key=lambda item: item["x0"])
        column_gap = max(median_height * 1.8, 28)

        parts: list[str] = []
        previous_x1: float | None = None
        for item in row:
            if previous_x1 is not None and item["x0"] - previous_x1 > column_gap:
                parts.append("|")
            parts.append(item["text"])
            previous_x1 = item["x1"]

        line = " ".join(parts)
        line = line.replace(" | ", " | ")
        if line.strip():
            lines.append(line.strip())

    return "\n".join(lines)


def _parse_easyocr_result(result) -> dict | None:
    if isinstance(result, str):
        return {
            "text": result.strip(),
            "x0": 0.0,
            "x1": float(len(result)),
            "y0": 0.0,
            "y1": 12.0,
            "cy": 0.0,
            "height": 12.0,
        }

    if not isinstance(result, (tuple, list)) or len(result) < 2:
        return None

    bbox = result[0]
    text = str(result[1]).strip()
    if not text:
        return None

    try:
        xs = [float(point[0]) for point in bbox]
        ys = [float(point[1]) for point in bbox]
    except (TypeError, ValueError, IndexError):
        return None

    y0 = min(ys)
    y1 = max(ys)
    return {
        "text": text,
        "x0": min(xs),
        "x1": max(xs),
        "y0": y0,
        "y1": y1,
        "cy": (y0 + y1) / 2,
        "height": max(1.0, y1 - y0),
    }


def _parse_confidence(result) -> float:
    if not isinstance(result, (tuple, list)) or len(result) < 3:
        return 0.0
    try:
        return max(0.0, min(1.0, float(result[2])))
    except (TypeError, ValueError):
        return 0.0
