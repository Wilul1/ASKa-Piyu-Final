"""HTTP client for the optional, external AWS EasyOCR worker.

This module ONLY talks to the worker and validates its response shape --
it never touches Chroma, embeddings, Postgres, or chunking/cleaning/
metadata. See app/services/admin/digital_ingestion.py for how its output
(page_texts, the exact per-page shape extract_digital_text_only returns)
feeds into the EXISTING cleaning/chunking/metadata/publishing pipeline
completely unchanged -- the worker's only job is turning PDF bytes into
page-aware text.

Security: the worker's bearer token is never logged, never interpolated
into an exception message, and never reachable via `from exc` chaining --
an httpx exception's repr can carry the original request, including the
Authorization header, depending on the transport. This mirrors the
existing, already-reviewed convention in app/services/embeddings.py's HF
remote client.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class OcrWorkerError(RuntimeError):
    """Raised for any OCR worker problem: unreachable, timed out, non-200,
    malformed JSON, or a response that fails schema validation.

    Always safe to surface as a plain digital-ingestion job failure (maps
    to status="failed" in process_ingestion_job) -- the worker is called
    strictly BEFORE anything is written to Chroma, so a failure here can
    never leave a partial publish behind, and the original PDF bytes
    remain in the job row for the admin to retry.
    """


def call_ocr_worker(
    pdf_bytes: bytes,
    *,
    url: str,
    token: str,
    timeout_seconds: float,
) -> list[str]:
    """POST ``pdf_bytes`` to the worker's ``/ocr`` endpoint and return
    ``page_texts`` -- one string per page, in page order, 1-indexed
    position 0 == page 1 -- the same shape extract_digital_text_only
    returns, so the caller can feed it through the existing
    build_chunks_with_pages unchanged.

    Raises OcrWorkerError for any failure; never returns a partial or
    ambiguous result silently.
    """
    import httpx

    endpoint = url.rstrip("/") + "/ocr"
    headers = {"Authorization": f"Bearer {token}"}
    files = {"file": ("document.pdf", pdf_bytes, "application/pdf")}

    try:
        response = httpx.post(endpoint, headers=headers, files=files, timeout=timeout_seconds)
    except httpx.TimeoutException:
        # Deliberately not `from exc` / not interpolating str(exc): a
        # timeout exception's repr can include the request (and its
        # Authorization header) depending on the underlying transport.
        raise OcrWorkerError(
            f"OCR worker request timed out after {timeout_seconds:.0f}s."
        ) from None
    except httpx.HTTPError:
        raise OcrWorkerError(
            "OCR worker request failed (network/transport error)."
        ) from None

    if response.status_code in (401, 403):
        # Status code only -- never the response body or response.request
        # (the latter carries the Authorization header).
        raise OcrWorkerError(
            f"OCR worker rejected the request as unauthorized (HTTP {response.status_code})."
        )
    if response.status_code != 200:
        raise OcrWorkerError(
            f"OCR worker request failed with HTTP {response.status_code}."
        )

    try:
        payload = response.json()
    except ValueError:
        raise OcrWorkerError("OCR worker response was not valid JSON.") from None

    return _validate_and_convert(payload)


def _validate_and_convert(payload: Any) -> list[str]:
    """Strict schema validation -- reject anything that doesn't exactly
    match the documented worker response shape rather than guessing."""
    if not isinstance(payload, dict):
        raise OcrWorkerError("OCR worker response was not a JSON object.")

    if payload.get("status") != "completed":
        raise OcrWorkerError(
            f"OCR worker did not report a completed result (status={payload.get('status')!r})."
        )

    pages = payload.get("pages")
    if not isinstance(pages, list) or not pages:
        raise OcrWorkerError("OCR worker response contained no pages.")

    page_count = payload.get("page_count")
    if not isinstance(page_count, int) or page_count != len(pages):
        raise OcrWorkerError(
            "OCR worker response's page_count did not match the number of pages returned."
        )

    by_number: dict[int, str] = {}
    for entry in pages:
        if not isinstance(entry, dict):
            raise OcrWorkerError("OCR worker response contained a malformed page entry.")
        page_no = entry.get("page")
        text = entry.get("text")
        if not isinstance(page_no, int) or isinstance(page_no, bool) or page_no < 1:
            raise OcrWorkerError("OCR worker response contained an invalid page number.")
        if not isinstance(text, str):
            raise OcrWorkerError("OCR worker response contained a non-text page body.")
        if page_no in by_number:
            raise OcrWorkerError(f"OCR worker response contained duplicate page number {page_no}.")
        by_number[page_no] = text

    max_page = max(by_number)
    if max_page != len(pages) or sorted(by_number) != list(range(1, max_page + 1)):
        raise OcrWorkerError("OCR worker response page numbers were not contiguous from 1.")

    page_texts = [by_number[i] for i in range(1, max_page + 1)]
    if not any(t.strip() for t in page_texts):
        raise OcrWorkerError("OCR worker returned no usable text on any page.")

    return page_texts
