"""Unit tests for the external AWS EasyOCR worker HTTP client.

No live network calls -- mocks ``httpx.post`` (the same established
convention test_embeddings.py already uses for the HF remote client).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.admin.ocr_worker_client import OcrWorkerError, call_ocr_worker

FAKE_TOKEN = "fake-ocr-worker-secret-token-xyz"
FAKE_URL = "https://aska-piyu-ocr.example.com"


def _fake_response(status_code: int, json_body=None, json_error: Exception | None = None):
    response = MagicMock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = json_body
    return response


def _completed_payload(pages: list[tuple[int, str]], page_count: int | None = None):
    return {
        "status": "completed",
        "pages": [{"page": p, "text": t} for p, t in pages],
        "page_count": page_count if page_count is not None else len(pages),
        "processing_seconds": 10.22,
        "peak_rss_mb": 1462.2,
    }


# --- Happy path / page-aware mapping ----------------------------------------


def test_successful_single_page_response():
    payload = _completed_payload([(1, "Hello world.")])
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        page_texts = call_ocr_worker(b"%PDF-1.4 fake", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)
    assert page_texts == ["Hello world."]


def test_page_aware_mapping_preserves_order_and_indexes_from_one():
    payload = _completed_payload([(3, "page three"), (1, "page one"), (2, "page two")])
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        page_texts = call_ocr_worker(b"%PDF-1.4 fake", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)
    # Reordered regardless of response order -- position 0 is page 1, etc.
    assert page_texts == ["page one", "page two", "page three"]


def test_request_shape_endpoint_header_and_multipart_field_name():
    payload = _completed_payload([(1, "x")])
    with patch("httpx.post", return_value=_fake_response(200, payload)) as mock_post:
        call_ocr_worker(b"%PDF-1.4 fake", url="https://worker.example.com/", token=FAKE_TOKEN, timeout_seconds=30)

    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    args = mock_post.call_args.args
    endpoint = args[0] if args else kwargs.get("url")
    assert endpoint == "https://worker.example.com/ocr"  # trailing slash normalized
    assert kwargs["headers"]["Authorization"] == f"Bearer {FAKE_TOKEN}"
    assert "file" in kwargs["files"]
    assert kwargs["timeout"] == 30


# --- Error paths (C, D, E, F, G) ---------------------------------------------


def test_unauthorized_401_raises_ocr_worker_error():
    with patch("httpx.post", return_value=_fake_response(401)):
        with pytest.raises(OcrWorkerError, match="unauthorized"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token="wrong-token", timeout_seconds=30)


def test_forbidden_403_raises_ocr_worker_error():
    with patch("httpx.post", return_value=_fake_response(403)):
        with pytest.raises(OcrWorkerError, match="unauthorized"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_timeout_raises_ocr_worker_error():
    with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
        with pytest.raises(OcrWorkerError, match="timed out"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_connection_error_raises_ocr_worker_error():
    with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
        with pytest.raises(OcrWorkerError):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_5xx_raises_ocr_worker_error():
    with patch("httpx.post", return_value=_fake_response(503)):
        with pytest.raises(OcrWorkerError, match="503"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_malformed_json_raises_ocr_worker_error():
    with patch("httpx.post", return_value=_fake_response(200, json_error=ValueError("bad json"))):
        with pytest.raises(OcrWorkerError, match="JSON"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_response_not_a_json_object_rejected():
    with patch("httpx.post", return_value=_fake_response(200, [1, 2, 3])):
        with pytest.raises(OcrWorkerError, match="JSON object"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_status_not_completed_rejected():
    payload = _completed_payload([(1, "x")])
    payload["status"] = "failed"
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="completed"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_empty_pages_array_rejected():
    payload = _completed_payload([])
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="no pages"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_empty_text_on_every_page_rejected():
    payload = _completed_payload([(1, ""), (2, "   ")])
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="no usable text"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_page_count_mismatch_rejected():
    payload = _completed_payload([(1, "x"), (2, "y")], page_count=5)
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="page_count"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_non_contiguous_page_numbers_rejected():
    payload = _completed_payload([(1, "x"), (3, "y")])  # missing page 2
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="contiguous"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_duplicate_page_numbers_rejected():
    payload = _completed_payload([(1, "x"), (1, "y")])
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="duplicate"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_non_integer_page_number_rejected():
    payload = _completed_payload([(1, "x")])
    payload["pages"][0]["page"] = "one"
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="invalid page number"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


def test_non_string_text_rejected():
    payload = _completed_payload([(1, "x")])
    payload["pages"][0]["text"] = 12345
    with patch("httpx.post", return_value=_fake_response(200, payload)):
        with pytest.raises(OcrWorkerError, match="non-text"):
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)


# --- Security: token never leaked (K) ---------------------------------------


def test_token_never_appears_in_exception_message_or_logs(caplog):
    """Mirrors test_embeddings.py's HF-token test exactly, for the OCR
    worker's bearer token."""
    caught: list[Exception] = []
    with caplog.at_level(logging.DEBUG):
        with patch(
            "httpx.post",
            side_effect=httpx.TimeoutException(f"timed out, request=<...Authorization: Bearer {FAKE_TOKEN}...>"),
        ):
            try:
                call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)
            except OcrWorkerError as exc:
                caught.append(exc)
                logging.getLogger("app.services.admin.ocr_worker_client").exception("ocr worker call failed")

    assert len(caught) == 1
    assert FAKE_TOKEN not in str(caught[0])
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
        if record.exc_text:
            assert FAKE_TOKEN not in record.exc_text


def test_token_never_appears_on_401_rejection():
    with patch("httpx.post", return_value=_fake_response(401)):
        with pytest.raises(OcrWorkerError) as excinfo:
            call_ocr_worker(b"%PDF-1.4", url=FAKE_URL, token=FAKE_TOKEN, timeout_seconds=30)
    assert FAKE_TOKEN not in str(excinfo.value)
