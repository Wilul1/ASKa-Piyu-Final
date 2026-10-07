"""Zero-cost digital-PDF background ingestion for the Heroku web dyno.

Deliberately separate from app/services/admin/knowledge_base_pipeline.py
(the full local/Docker ingestion pipeline, which can use OCR/local
embeddings and remains unmodified). This module is a narrower, independent
path for the Heroku web dyno specifically:

- PyMuPDF digital text extraction ONLY. No app.utils.pdf.pymupdf_extractor
  and no app.utils.ocr.easyocr_engine import anywhere in this module's
  import graph -- avoided by construction, not by a runtime check, so
  EasyOCR/PyTorch can never be triggered from this code path regardless of
  document content. A document with insufficient digital text gets
  status="ocr_required" and stops; nothing is indexed.
- Embeddings happen implicitly via the existing HFRemoteEmbeddingFunction
  already configured on the production Chroma collection
  (ASKA_EMBEDDING_BACKEND=huggingface) -- this module never loads
  sentence-transformers/torch either.
- Runs as an in-process asyncio background task on the SAME web dyno (the
  same pattern already used by citation_verification_jobs.py) -- no new
  dyno, no new paid service. See IngestionJob's own docstring for the
  Postgres-only job/status/dedup/original-file storage design.
- Version-aware, safe replacement: a replacement ALWAYS gets a brand new
  Chroma document_id. The new version's chunks are added and verified
  BEFORE the old version's chunks (looked up by their own, different,
  document_id -- never by source_filename) are deleted. If verification
  fails, the old version is left untouched. If deleting the old version
  fails AFTER the new version is confirmed published, the job is marked
  needs_reconciliation rather than silently left inconsistent or retried
  blindly.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import fitz  # PyMuPDF

from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import IngestionJob
from app.models.schemas import StructuredDocumentSchema
from app.services.admin.knowledge_base_pipeline import (
    _HONORIFIC_PREFIX_RE,
    chunk_preview,
    is_trustworthy_title_heading,
    knowledge_base_statistics,
    knowledge_units_for_extraction,
    pipeline_stages,
    validation_report,
)
from app.services.admin.ocr_worker_client import OcrWorkerError, call_ocr_worker
from app.services.chroma_store import KnowledgeBaseStore, get_knowledge_base_store
from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata
from app.services.text_cleaner import (
    _ARTICLE_CHAPTER_HEADING_RE,
    _DECIMAL_HEADING_RE,
    _is_bare_section_marker,
    _is_major_section_heading,
    clean_extracted_text,
    is_heading_candidate,
)

logger = logging.getLogger(__name__)

# Matches the existing _any_digital_signal() heuristic in
# app/services/document_ingestion.py (reimplemented locally -- see module
# docstring for why this file never imports that one).
MIN_DIGITAL_CHARS_PER_PAGE = 20

MAX_PDF_BYTES = 25 * 1024 * 1024  # 25 MB -- generous for a policy/handbook PDF, bounds memory use

# Chroma Cloud enforces a per-request "Number of records" quota on the Add
# action (separate from total collection size -- see the 2026-10-03 incident:
# a single 371-record add() was rejected with "current usage of 371 exceeds
# limit of 300" while the collection already held 728 records overall). 250
# leaves headroom under that 300 ceiling for any per-tenant variance.
CHROMA_ADD_MAX_BATCH_SIZE = 250


class DigitalIngestionError(RuntimeError):
    """Raised for conditions that should stop the job with status='failed'.

    Always means: the new version never became visible in Chroma, and the
    old version (if any) was never touched. Safe for the admin to retry.
    """


class DigitalIngestionReconciliationError(RuntimeError):
    """Raised when automatic cleanup could not fully restore a known-good
    state and a human must inspect/reconcile Chroma manually.

    Maps to status='needs_reconciliation', never 'failed' (which would
    wrongly imply it's simply safe to retry) and never silently
    'published'. The message always carries whatever document_id a human
    needs to find the leftover chunks.
    """


class DigitalIngestionActiveJobError(RuntimeError):
    """Raised when a new job cannot be created because another job is
    already queued/processing/indexing on this single dyno.

    Deliberately NOT a sha256-based duplicate check (see module docstring
    for start_extraction_job) -- this is purely the single-worker
    concurrency guard already used by the existing /ingest-digital path,
    extended to also cover the new review/index split.
    """

    def __init__(self, active_job_id: str) -> None:
        super().__init__(f"Another job (id={active_job_id}) is already in progress on this dyno.")
        self.active_job_id = active_job_id


class DigitalIngestionJobStateError(RuntimeError):
    """Raised when an operation is requested against an IngestionJob whose
    current status doesn't allow it (e.g. indexing a job that isn't
    review_ready yet). Carries the job's actual status for the caller to
    report back."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Job is not in a valid state for this operation (status={status}).")
        self.status = status


def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def validate_pdf_bytes(file_bytes: bytes, *, content_type: str | None) -> None:
    if not file_bytes:
        raise DigitalIngestionError("Uploaded file is empty.")
    if len(file_bytes) > MAX_PDF_BYTES:
        raise DigitalIngestionError(
            f"File exceeds the {MAX_PDF_BYTES // (1024 * 1024)}MB limit for this ingestion path."
        )
    if not file_bytes.startswith(b"%PDF-"):
        raise DigitalIngestionError("File does not look like a PDF (missing %PDF- header).")
    if content_type and content_type not in ("application/pdf", "application/octet-stream"):
        raise DigitalIngestionError(f"Unsupported content type for this path: {content_type}")


def _page_offsets_from_texts(page_texts: list[str]) -> list[int]:
    """page_start_offsets[i] is the character offset, in the newline-joined
    full text, at which page i's text begins -- shared by both the digital
    (PyMuPDF) and OCR-worker text sources so page_number metadata is
    computed identically regardless of which one produced the text."""
    offsets: list[int] = []
    running = 0
    for text in page_texts:
        offsets.append(running)
        running += len(text) + 1  # +1 for the "\n" used to join pages below
    return offsets


def extract_digital_text_only(file_bytes: bytes) -> tuple[list[str], list[int]]:
    """PyMuPDF-only extraction. See module docstring for the OCR-avoidance guarantee.

    Returns (page_texts, page_start_offsets) -- see _page_offsets_from_texts.
    """
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        raise DigitalIngestionError(f"Could not open file as a PDF: {exc}") from exc

    page_texts: list[str] = []
    try:
        for page in doc:
            page_texts.append(page.get_text() or "")
    finally:
        doc.close()

    return page_texts, _page_offsets_from_texts(page_texts)


def has_usable_digital_text(page_texts: list[str]) -> bool:
    return any(len(t.strip()) > MIN_DIGITAL_CHARS_PER_PAGE for t in page_texts)


def ocr_worker_configured() -> bool:
    """Whether the external AWS EasyOCR worker is enabled AND safely
    configured. Returns False (never raises) for any missing/insecure
    configuration, so the caller falls back to the existing ocr_required
    behavior rather than attempting an unsafe or broken call.
    """
    if not settings.ocr_worker_enabled:
        return False
    if not settings.ocr_worker_url or not settings.ocr_worker_token:
        logger.error(
            "ASKA_OCR_WORKER_ENABLED is true but ASKA_OCR_WORKER_URL/ASKA_OCR_WORKER_TOKEN "
            "is not set -- falling back to ocr_required."
        )
        return False
    if not settings.ocr_worker_url.startswith("https://"):
        logger.error(
            "ASKA_OCR_WORKER_ENABLED is true but ASKA_OCR_WORKER_URL does not start with "
            "https:// -- refusing to call it insecurely. Falling back to ocr_required."
        )
        return False
    return True


def run_ocr_worker(file_bytes: bytes) -> tuple[list[str], list[int]]:
    """Call the external OCR worker and return (page_texts, page_offsets) --
    the exact same shape extract_digital_text_only returns, so the result
    feeds into build_chunks_with_pages completely unchanged.

    Raises DigitalIngestionError (never OcrWorkerError) on any failure --
    this call happens strictly BEFORE anything is written to Chroma, so a
    failure here is always a plain, safe-to-retry job failure, exactly
    like any other pre-publish error on this path (see module docstring).
    """
    try:
        page_texts = call_ocr_worker(
            file_bytes,
            url=settings.ocr_worker_url,
            token=settings.ocr_worker_token,
            timeout_seconds=settings.ocr_worker_timeout_seconds,
        )
    except OcrWorkerError as exc:
        raise DigitalIngestionError(f"OCR worker failed: {exc}") from exc
    return page_texts, _page_offsets_from_texts(page_texts)


def _page_for_offset(char_start: int, page_offsets: list[int]) -> int:
    """1-indexed page number containing a given character offset in the joined text."""
    page_index = 0
    for i, start in enumerate(page_offsets):
        if start <= char_start:
            page_index = i
        else:
            break
    return page_index + 1


_MIN_HEADING_BODY_GAP_CHARS = 40
_DENSE_HEADING_RUN_MIN_SIZE = 4
_BARE_YEAR_PREFIX_RE = re.compile(r"^(?:19|20)\d{2}\s")


def _is_strong_numbered_heading(line: str) -> bool:
    """True for a roman-numeral ("I. General Information"), decimal
    ("3.2 Change of Grades"), or Article/Chapter ("Article 6. Procedure
    for Major Disciplinary Actions") structural heading -- the
    document's own explicit, unambiguous section markers.

    These must never be swept away by either the dense-run or
    roster-context heuristics below (both designed to suppress AMBIGUOUS
    shape-only matches, like a roster's role/designation lines or a
    title page's letterhead fragments), even when one happens to sit
    immediately adjacent to a roster/letterhead block -- e.g. "I.
    General Information" immediately follows a long Board of
    Regents/Administrative Officials roster in the real Faculty Manual,
    with only a small character gap separating them.

    The decimal-heading path excludes a bare 19xx/20xx-prefixed line
    (e.g. "2020 Edition") -- it coincidentally matches the same
    "number + capitalized word" shape as a genuine subsection number
    ("3.2 Change of Grades"), but a 4-digit year is a publication-year
    label, not a section number.
    """
    if _is_major_section_heading(line) or _ARTICLE_CHAPTER_HEADING_RE.match(line):
        return True
    return bool(_DECIMAL_HEADING_RE.match(line) and not _BARE_YEAR_PREFIX_RE.match(line))


def _is_protected_heading(line: str) -> bool:
    """True for a heading-shaped line that must never be swept away by
    the dense-run or roster-context heuristics, regardless of its
    surrounding gap structure.

    Covers _is_strong_numbered_heading PLUS a multi-word ALL-CAPS
    heading that is NOT itself an honorific name line -- e.g. "BOARD OF
    REGENTS" or "ADMINISTRATIVE OFFICIALS", the enclosing anchor heading
    of a roster, versus "HON. FULL NAME" (a roster member, which IS
    honorific-prefixed and so is correctly excluded here). Relying only
    on incidental gap sizes to spare the roster's own anchor heading is
    fragile -- some real documents happen to have a large gap between
    the anchor and its first member (sparing it by luck), others do not
    -- so the anchor is protected explicitly instead.
    """
    if _is_strong_numbered_heading(line):
        return True
    if not (line.isupper() and len(line.split()) >= 2 and not _HONORIFIC_PREFIX_RE.match(line)):
        return False
    # Exclude a serial/identifier-shaped line (e.g. "ISSN 978-971-94281-9-0")
    # -- str.isupper() is true for it too (its only cased characters,
    # "ISSN", are uppercase), but a genuine ALL-CAPS anchor heading
    # ("BOARD OF REGENTS", "ADMINISTRATIVE OFFICIALS") is made entirely
    # of real words, never a token that's mostly digits/hyphens/dots.
    if any(re.fullmatch(r"[\d.\-/]+", word) for word in line.split()):
        return False
    return True


def _heading_offsets(text: str) -> tuple[list[int], list[str]]:
    """(sorted char offsets, heading text) for every TRUSTWORTHY heading
    line in ``text``, in document order -- used to find the governing
    heading for a given chunk (see _attach_section_headings).

    Two passes, deliberately in this order:

    1. Density is measured over EVERY is_heading_candidate-shaped line
       (the broad, shared shape test), not just the ones that will
       later survive is_trustworthy_title_heading's stricter checks.
       This matters for a person/role roster (e.g. a Board of Regents
       listing): each "HON. FULL NAME" line is itself heading-shaped but
       gets rejected later by the honorific-prefix check, and rejecting
       it FIRST would make the roster's OWN role/designation lines
       ("LSPU President", "Member", "Chairperson," / wrapped committee
       descriptions) look like several small, independent 1-3-line
       clusters instead of the one dense roster they actually are --
       each individually too small to reach _DENSE_HEADING_RUN_MIN_SIZE,
       so none of them would get suppressed. Measuring density on the
       full candidate set (honorific lines included) correctly reveals
       the roster as one long, dense run and suppresses the whole span.
    2. Only a candidate that is BOTH outside any such dense run AND
       passes is_trustworthy_title_heading (stricter than plain
       is_heading_candidate -- see its docstring) is kept.

    Requiring a RUN of several, not just two adjacent candidates, matters
    because a legitimate compound heading is often itself 2-3 lines
    packed just as tightly (e.g. "Chapter 3" / "UNDERGRADUATE ACADEMIC
    POLICIES" / "Article 1. Classifications of Students" -- three lines,
    one newline apart, all naming the SAME section boundary) -- treating
    any tight pair as untrustworthy would wrongly suppress that, too.
    """
    raw_lines = text.split("\n")
    all_offsets: list[int] = []
    all_lines: list[str] = []
    all_line_numbers: list[int] = []
    running = 0
    for line_no, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped and is_heading_candidate(stripped):
            all_offsets.append(running)
            all_lines.append(stripped)
            all_line_numbers.append(line_no)
        running += len(line) + 1  # +1 for the removed "\n"

    protected = [_is_protected_heading(line) for line in all_lines]

    dense_indices: set[int] = set()
    run: list[int] = [0] if all_offsets else []
    for i in range(1, len(all_offsets)):
        gap = all_offsets[i] - (all_offsets[i - 1] + len(all_lines[i - 1]))
        between_lines = raw_lines[all_line_numbers[i - 1] + 1 : all_line_numbers[i]]
        # A contact-block line (phone/address/domain) in the gap is a
        # hard break, never bridged -- crossing one means whatever
        # follows is a fresh region, not part of the SAME dense run as
        # whatever came before it. Without this, a short single-word
        # anchor heading (e.g. "FOREWORD") sitting just past a genuine
        # letterhead's own address/phone/website line could otherwise
        # be pulled into that same run purely by raw character
        # proximity, even though the contact-block line between them is
        # exactly the boundary marking where the letterhead ends.
        crosses_contact_block = any(_looks_like_contact_block_line(l) for l in between_lines)
        if gap < _MIN_HEADING_BODY_GAP_CHARS and not crosses_contact_block:
            run.append(i)
        else:
            if len(run) >= _DENSE_HEADING_RUN_MIN_SIZE:
                dense_indices.update(idx for idx in run if not protected[idx])
            run = [i]
    if len(run) >= _DENSE_HEADING_RUN_MIN_SIZE:
        dense_indices.update(idx for idx in run if not protected[idx])

    roster_spans = _roster_context_spans(text)

    repeat_counts: dict[str, int] = {}
    for line in all_lines:
        key = line.casefold()
        repeat_counts[key] = repeat_counts.get(key, 0) + 1

    offsets: list[int] = []
    headings: list[str] = []
    for i, (offset, line, line_no) in enumerate(zip(all_offsets, all_lines, all_line_numbers)):
        if i in dense_indices or not is_trustworthy_title_heading(line):
            continue
        if _is_wrapped_prose_continuation(raw_lines, line_no):
            continue
        if not protected[i] and any(start <= offset < end for start, end in roster_spans):
            continue
        if not protected[i] and _is_letterhead_heading(line_no, raw_lines):
            continue
        if _is_table_fragment_heading(i, all_lines, all_line_numbers, raw_lines, repeat_counts):
            continue
        offsets.append(offset)
        headings.append(line)
    return offsets, headings


_ROSTER_HONORIFIC_REACH_CHARS = 400


def _roster_context_spans(text: str) -> list[tuple[int, int]]:
    """Character spans (start, end) that are a dense person/role roster
    (e.g. a Board of Regents / Administrative Officials listing),
    detected via at least two honorific-prefixed name lines ("HON. ...",
    "Dr. ...", "Atty. ...") within _ROSTER_HONORIFIC_REACH_CHARS of each
    other.

    A role/designation line SANDWICHED between two such name lines
    (e.g. "CHED Commissioner" between "HON. LILIAN A. DE LAS LLAGAS" and
    the next honorific name) is still clearly part of the roster even
    when it escapes the generic dense-run check above -- an incidental
    hyphen in a NEIGHBORING role-description line (e.g. "Chairperson-
    Designate and Presiding Officer") breaks THAT line's own
    is_heading_candidate shape test and artificially widens the
    measured gap, fragmenting what is structurally one continuous
    roster into several small runs each below the density threshold.
    Anchoring directly on honorific name lines (immune to that
    fragmentation, since each name line is checked independently of its
    neighbors) is a more robust roster signal.
    """
    lines = text.split("\n")
    honorific_offsets: list[int] = []
    running = 0
    for line in lines:
        stripped = line.strip()
        if stripped and _HONORIFIC_PREFIX_RE.match(stripped):
            honorific_offsets.append(running)
        running += len(line) + 1

    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(honorific_offsets):
        j = i
        while (
            j + 1 < len(honorific_offsets)
            and honorific_offsets[j + 1] - honorific_offsets[j] <= _ROSTER_HONORIFIC_REACH_CHARS
        ):
            j += 1
        if j > i:
            spans.append((honorific_offsets[i], honorific_offsets[j] + _ROSTER_HONORIFIC_REACH_CHARS))
        i = j + 1
    return spans


# An institution-name + geographic/location line pair (e.g. "Laguna State
# Polytechnic University (LSPU)" / "Province of Laguna") is itself
# shape-indistinguishable from a real two-line heading -- the only
# reliable generic signal is what immediately FOLLOWS it: a genuine
# letterhead/contact block (campus addresses, phone numbers, postal
# codes), never found following a real structural heading like FOREWORD
# or BOARD OF REGENTS. Matching structural shape only, never a specific
# place name/institution/filename.
_PHONE_NUMBER_RE = re.compile(r"\(\d{2,4}\)\s*\d{3,4}[-\s]?\d{3,4}|\b\d{3,4}[-\s]\d{3,4}[-\s]\d{3,4}\b")
_EMAIL_OR_WEBSITE_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|(?i:www\.\S+|https?://\S+)")
# A domain-TLD-shaped token (".edu.ph", ".com", ...) combined with at
# least 2 dots overall -- broader than requiring a literal "www." (real
# PDF text extraction can render "www.lspu.edu.ph" as "w.lspu.edu.ph",
# dropping a character) while still specific enough to avoid matching
# ordinary prose, which essentially never contains these TLD segments.
_DOMAIN_TLD_RE = re.compile(r"(?i:\.(?:com|org|net|edu|gov|ph|co)\b)")
_ADDRESS_ABBREVIATION_RE = re.compile(
    r"(?i:\bbrgy\.?\b|\bbarangay\b|\bsitio\b|\bpurok\b|\bsto\.?\b|\bsta\.?\b|\bst\.?\s|\bave\.?\s|\bblvd\.?\b)"
)
_TRAILING_POSTAL_CODE_RE = re.compile(r",\s*\d{4}\s*$")
_LETTERHEAD_CONTACT_REACH_LINES = 30


def _looks_like_contact_block_line(line: str) -> bool:
    """True for a line shaped like part of a letterhead's address/contact
    block -- a phone number, an email/website/domain, a Philippine-style
    barangay/street address abbreviation, or an address line ending in a
    trailing 4-digit postal code (e.g. "Brgy. Bubukal, Sta. Cruz, Laguna,
    4009"). Deliberately specific, narrow shapes -- essentially never
    coincidentally present in ordinary policy-manual body prose -- rather
    than a broad heuristic that could misfire on legitimate headings.
    """
    return bool(
        _PHONE_NUMBER_RE.search(line)
        or _EMAIL_OR_WEBSITE_RE.search(line)
        or (_DOMAIN_TLD_RE.search(line) and line.count(".") >= 2)
        or _ADDRESS_ABBREVIATION_RE.search(line)
        or _TRAILING_POSTAL_CODE_RE.search(line)
    )


def _is_letterhead_heading(line_no: int, raw_lines: list[str]) -> bool:
    """True when a contact-block line (see _looks_like_contact_block_line)
    appears within _LETTERHEAD_CONTACT_REACH_LINES lines after this
    candidate -- strong, generic evidence that the candidate itself is
    part of an institutional letterhead (institution name + location),
    not a real structural heading. A real heading like FOREWORD or BOARD
    OF REGENTS is never followed by an address/phone number this closely.
    """
    end = min(line_no + 1 + _LETTERHEAD_CONTACT_REACH_LINES, len(raw_lines))
    return any(_looks_like_contact_block_line(raw_lines[k]) for k in range(line_no + 1, end))


_PROSE_CONNECTOR_WORDS = frozenset(
    {"a", "an", "the", "of", "in", "on", "for", "to", "and", "or", "by", "as", "with"}
)
_MIN_PROSE_CONTENT_WORDS = 2


def _looks_like_flowing_prose(line: str) -> bool:
    """True when ``line`` reads as a real grammatical sentence fragment
    (at least _MIN_PROSE_CONTENT_WORDS lowercase, non-connector words),
    as opposed to a short Title-Case/letterhead-style label that merely
    fails the heading-shape test for an incidental reason (e.g. a hyphen
    in "ESPU-West Pilot Extension Classes" breaks is_heading_candidate's
    Title-Case check, but that line is still not flowing prose -- it has
    zero lowercase content words).

    Never true for a contact-block-shaped line (see
    _looks_like_contact_block_line) -- a bare website/email/phone/address
    label like "website: w.lspu.edu.ph" can coincidentally have 2+
    lowercase tokens (defeating the word-count check above) without
    being a grammatical sentence at all.
    """
    if _looks_like_contact_block_line(line):
        return False
    content_words = 0
    for word in line.split():
        if not word[:1].islower():
            continue
        bare = word.strip(".,;:()[]\"'/").lower()
        if bare and bare not in _PROSE_CONNECTOR_WORDS:
            content_words += 1
    return content_words >= _MIN_PROSE_CONTENT_WORDS


def _is_wrapped_prose_continuation(lines: list[str], line_no: int) -> bool:
    """True when the heading-shaped line at ``lines[line_no]`` is
    actually a wrapped continuation of an ordinary prose sentence, not a
    new heading -- e.g. "Statutes, Omnibus Rules Implementing Book V of
    Executive" in "The information contained herein are based on the /
    Statutes, Omnibus Rules Implementing Book V of Executive / Order No.
    292 ..." happens to be short and Title Case (a formal legal citation
    naturally capitalizes every word) but is really the middle of one
    sentence split across three lines by the page layout.

    Evidence: the immediately preceding non-blank line (a) trails off
    without terminal sentence punctuation (a real sentence in progress,
    not a completed thought), (b) is not itself heading-shaped (a
    legitimate compound heading, e.g. "Chapter 3" immediately followed
    by its own title line, is exempted here), and (c) genuinely reads as
    flowing prose (see _looks_like_flowing_prose) rather than merely
    being some OTHER short label that happens to fail the heading-shape
    test for an unrelated, incidental reason.
    """
    for k in range(line_no - 1, -1, -1):
        prev = lines[k].strip()
        if not prev:
            continue
        if prev[-1:] in ".!?:;":
            return False
        if is_heading_candidate(prev) or _is_bare_section_marker(prev):
            return False
        return _looks_like_flowing_prose(prev)
    return False


_TABLE_FRAGMENT_REPEAT_MIN = 3


def _next_raw_line_is_flowing_prose(raw_lines: list[str], line_no: int) -> bool:
    """True when the next NON-BLANK raw line after ``line_no`` reads as a
    real grammatical sentence fragment (see _looks_like_flowing_prose).

    A genuine heading -- a real office/service name, a roman-numeral
    major section, a numbered subsection -- always introduces either
    explanatory prose or (for a roster/letterhead-style anchor, already
    handled separately above) a block this function is never consulted
    for. A table/form fragment -- a column value, a role name, a
    duration, a running total -- never does: whatever follows it is
    just more of the same short, structured row content.
    """
    for k in range(line_no + 1, len(raw_lines)):
        candidate = raw_lines[k].strip()
        if not candidate:
            continue
        return _looks_like_flowing_prose(candidate)
    return False


def _is_table_fragment_heading(
    i: int,
    all_lines: list[str],
    all_line_numbers: list[int],
    raw_lines: list[str],
    repeat_counts: dict[str, int],
) -> bool:
    """True for a heading-candidate that is really a fragment of a
    repeating administrative table/form (Office or Division / Fees to
    Be Paid / Processing Time / Person Responsible / Client Steps --
    the standard structure of a Citizen's Charter-style service
    catalog), not a genuine section/service title -- judged entirely by
    STRUCTURE (does it introduce real explanatory content? does the
    exact same fragment recur elsewhere?), never by matching specific
    column-header words.

    A roman-numeral/Article/Chapter major heading is never a table
    fragment -- these are the document's own explicit, unambiguous
    structural markers (same exemption _is_strong_numbered_heading
    already grants elsewhere) and are exempted unconditionally.

    Two shapes, judged differently because they fail in different ways:

    1. A NUMBERED candidate ("1. Enrollment", "3. Accept the signed")
       is structurally ambiguous: a genuine numbered service heading
       and a numbered CLIENT STEP table row share the exact same "N.
       Capitalized phrase" shape. The one reliable distinguishing
       signal is what follows: a real numbered service heading always
       introduces explanatory prose ("This process provides
       description and series of steps..."); a numbered client-step
       row never does (what follows is more table structure -- another
       short step, a role name, a duration). So a numbered candidate is
       a table fragment exactly when it is NOT followed by prose.
    2. A NON-numbered candidate (an ALL-CAPS phrase like "FEES TO BE
       PAID", or a short Title-Case fragment like "Transaction Type",
       "Administrative Aide VI", "Where to Secure") is a table fragment
       when the exact same text recurs _TABLE_FRAGMENT_REPEAT_MIN+ times
       elsewhere as a heading candidate -- a genuine one-off anchor
       heading like "BOARD OF REGENTS" is never, by construction, the
       SAME exact text repeated verbatim three or more times across a
       document; that repetition is the signature of a recurring
       table/form column-header or cell-value label being reused by
       every single service entry, regardless of whether it happens to
       be ALL-CAPS or Title-Case. This path deliberately does NOT also
       require "not followed by prose" the way the numbered path does:
       a table's own requirement/location VALUE text is frequently
       itself phrased as an ordinary lowercase multi-word description
       (e.g. a Checklist/Where-to-Secure cell reading "units/colleges
       and campuses of the university endorsed by..."), which would
       pass the same flowing-prose heuristic used to recognize genuine
       explanatory service prose -- repetition count alone is the more
       reliable signal here, since a real heading's repeated use is
       comparatively rare and a recurring table label's is not.
    """
    line = all_lines[i]
    if _is_major_section_heading(line) or _ARTICLE_CHAPTER_HEADING_RE.match(line):
        return False
    if _DECIMAL_HEADING_RE.match(line) and not _BARE_YEAR_PREFIX_RE.match(line):
        line_no = all_line_numbers[i]
        return not _next_raw_line_is_flowing_prose(raw_lines, line_no)
    return repeat_counts.get(line.casefold(), 0) >= _TABLE_FRAGMENT_REPEAT_MIN


def _attach_section_headings(chunks: list[DocumentChunk], cleaned_text: str) -> list[DocumentChunk]:
    """Attaches metadata["section_heading"] = the heading that governs
    MOST of a chunk's own content, so titles reflect a real
    section/subsection heading instead of an arbitrary first-line
    fragment (which can be a mid-sentence slice or a leftover TOC row --
    see _title_from_metadata in knowledge_base_pipeline.py, which already
    prefers "section_heading" over any first-line fallback).

    Prefers the LATEST heading that begins WITHIN the chunk's own span
    (char_start to char_start+len(text)) over the nearest heading
    preceding only its start offset: a short section's trailing content
    is sometimes packed into the same chunk as the START of the next
    section (e.g. a short "PRAYER" immediately followed, in the same
    chunk, by "Chapter 1" and its own opening paragraph) -- in that
    case the chunk's bulk of actual content belongs to the LATER
    heading, not the one technically preceding char_start. No change is
    made when a chunk has no trustworthy heading at all; the existing
    first-line fallback still applies for that case, as before.
    """
    offsets, headings = _heading_offsets(cleaned_text)
    if not offsets:
        return chunks
    updated: list[DocumentChunk] = []
    for chunk in chunks:
        chunk_end = chunk.char_start + len(chunk.text)
        idx_start = bisect.bisect_right(offsets, chunk.char_start) - 1
        idx_end = bisect.bisect_right(offsets, chunk_end) - 1
        idx = idx_end if idx_end > idx_start else idx_start
        metadata = dict(chunk.metadata or {})
        if idx >= 0:
            metadata["section_heading"] = headings[idx]
        else:
            # No trustworthy heading governs this chunk, by FULL
            # document-level analysis -- any heading-shaped line in this
            # chunk's own text that passes is_trustworthy_title_heading
            # was therefore already rejected by the letterhead/roster/
            # wrapped-prose checks above (every line that passes BOTH
            # is_heading_candidate and is_trustworthy_title_heading and
            # is NOT rejected by those checks is, by construction,
            # already present in ``offsets``/``headings``). Tell
            # _title_from_chunk's fallback not to re-discover it via its
            # own, document-context-blind scan of the chunk's text.
            metadata["title_fallback_suppressed"] = True
        updated.append(
            DocumentChunk(
                text=chunk.text, chunk_index=chunk.chunk_index, char_start=chunk.char_start, metadata=metadata
            )
        )
    return updated


def build_chunks_with_pages(
    page_texts: list[str],
    page_offsets: list[int],
    *,
    chunk_size: int,
    chunk_overlap: int,
    title: str,
    source_filename: str,
) -> list[DocumentChunk]:
    full_text = "\n".join(page_texts)
    cleaned = clean_extracted_text(full_text, page_texts=page_texts)
    if not cleaned.strip():
        raise DigitalIngestionError("No usable text remained after cleaning.")

    raw_chunks = chunk_document_text(cleaned, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    chunks = [
        DocumentChunk(
            text=c.text,
            chunk_index=c.chunk_index,
            char_start=c.char_start,
            metadata={
                **(c.metadata or {}),
                "document_type": "information",
                "title": title,
                "source_document": source_filename,
                "page_number": _page_for_offset(c.char_start, page_offsets),
            },
        )
        for c in raw_chunks
    ]
    chunks = _attach_section_headings(chunks, cleaned)
    # allow_llm=False: this path must stay fast and free of per-chunk LLM
    # calls (classify_chunk's Groq fallback can take minutes and cost real
    # API usage across a multi-page document) -- rule/similarity-only
    # classification is an accepted tradeoff for the zero-cost web-dyno path.
    return enrich_chunks_with_category_metadata(
        chunks, title=title, source_document=source_filename, allow_llm=False
    )


def _mirror_page_range_metadata(chunks: list[DocumentChunk]) -> list[DocumentChunk]:
    """Mirror page_number into page_start/page_end on each chunk's metadata.

    The admin preview/validation helpers reused below (knowledge_units_for_
    extraction / chunk_preview, built for the legacy pipeline's chunker)
    read page_start/page_end; this pipeline's chunks only carry page_number
    (consumed separately by citation grounding -- see chroma_store.py /
    question_answering.py). Purely additive: page_number is left untouched.
    """
    for chunk in chunks:
        metadata = chunk.metadata or {}
        if "page_number" in metadata and "page_start" not in metadata:
            metadata["page_start"] = metadata["page_number"]
            metadata["page_end"] = metadata["page_number"]
    return chunks


def _lightweight_structured_response(text: str) -> StructuredDocumentSchema:
    """Cheap, O(n)-trivial "structured" display field for the lightweight
    pipeline -- wraps the already-cleaned text directly, with no fields.

    Deliberately does NOT call
    app.services.structured_document_parser.build_structured_document() /
    parse_structured_document() (generic service-block regex scanning
    designed for the legacy local/Docker pipeline's Citizen's Charter /
    form documents). On the 2026-10-05 LSPU Student Handbook incident,
    that call alone took long enough on a 198-page/~343K-char document to
    blow past Heroku's 30s router timeout (H12) -- a local, isolated
    timing benchmark on comparably-sized synthetic text measured it at
    over 1000 seconds, versus low-single-digit-seconds for every other
    stage in this pipeline (cleaning, chunking, knowledge units, chunk
    preview, validation report) combined. The lightweight pipeline's
    "structured" field is a display convenience only -- the admin reviews
    and edits review_text/cleaned_text, and Index publishes from the
    persisted page texts, never from this field -- so there is nothing to
    lose by never running that scan here.
    """
    return StructuredDocumentSchema(fields=[], formatted_text=text)


def _lightweight_detected_document_type(*, reason: str) -> dict[str, Any]:
    return {
        "document_type": "information",
        "base_document_type": "information",
        "reason": reason,
        "scores": {},
        "manual_override": False,
        "admin_selected_document_type": None,
        "parser_kind": None,
    }


def _extract_or_ocr(file_bytes: bytes) -> tuple[list[str], list[int], str]:
    """Shared by build_lightweight_preview/build_lightweight_publish: PyMuPDF
    digital extraction, falling back to the remote OCR worker exactly as
    process_ingestion_job already does. Raises DigitalIngestionError if
    digital text is insufficient and the worker is unavailable/misconfigured
    -- never silently proceeds with empty/garbage text.
    """
    page_texts, page_offsets = extract_digital_text_only(file_bytes)
    extraction_method = "pymupdf_digital"
    if not has_usable_digital_text(page_texts):
        if not ocr_worker_configured():
            raise DigitalIngestionError(
                "This document does not contain enough selectable/digital text, "
                "and the remote OCR worker is not configured. Configure the OCR "
                "worker, or use the full local/Docker admin environment, to "
                "extract this document."
            )
        page_texts, page_offsets = run_ocr_worker(file_bytes)
        extraction_method = "remote_ocr_worker"
    return page_texts, page_offsets, extraction_method


def assemble_preview_payload(
    page_texts: list[str],
    *,
    title: str,
    source_filename: str,
    extraction_method: str,
) -> dict[str, Any]:
    """Pure (page_texts -> ExtractDocumentResponse-shaped dict) assembly --
    cleaning, chunking, and the cheap preview/validation/pipeline-stage
    helpers. No network/OCR call, no Chroma write. Shared by:
      - build_lightweight_preview (digital-fast synchronous path, where
        page_texts was just extracted/OCR'd in the same call), and
      - build_preview_from_job (rebuilds the SAME shape on demand from a
        review_ready/indexing/published job's persisted extracted_pages_json
        -- see that function's docstring for why this is cheap enough to
        never need to be persisted itself).
    """
    page_offsets = _page_offsets_from_texts(page_texts)
    full_text = "\n".join(page_texts)
    cleaned = clean_extracted_text(full_text, page_texts=page_texts)

    chunks = build_chunks_with_pages(
        page_texts,
        page_offsets,
        chunk_size=settings.chunk_max_chars,
        chunk_overlap=settings.chunk_overlap,
        title=title,
        source_filename=source_filename,
    )
    chunks = _mirror_page_range_metadata(chunks)

    units = knowledge_units_for_extraction(None, chunks, kb_document_type=None)
    previews = chunk_preview(chunks)
    validation = validation_report(document_type="information", units=units, chunks=chunks)
    stages = pipeline_stages(
        extraction_method=extraction_method,
        structuring_method="generic_chunking",
        indexed=False,
    )

    return {
        "document_type": "information",
        "document_profile": "information",
        "admin_selected_document_type": None,
        "parser_document_type": None,
        "source_type": None,
        "raw_text": full_text,
        "cleaned_text": cleaned,
        "review_text": cleaned,
        "extracted_text": cleaned,
        "page_count": len(page_texts),
        "extraction_method": extraction_method,
        "structuring_method": "generic_chunking",
        "pipeline_stages": stages,
        "structured": _lightweight_structured_response(cleaned),
        "diagnostic_report": None,
        "validation_report": validation,
        "detected_document_type": _lightweight_detected_document_type(
            reason="Lightweight cloud-safe pipeline: generic chunking, no document-type detection."
        ),
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": knowledge_base_statistics(),
    }


def build_lightweight_preview(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
) -> dict[str, Any]:
    """Cloud-safe equivalent of knowledge_base_pipeline.extract_document_preview
    for runtimes without local easyocr/sentence-transformers (see
    app.services.ingestion_runtime.ingestion_available). Never writes to
    Chroma. Returns a dict matching the ExtractDocumentResponse schema
    exactly, so the existing Flutter Extract & Structure UI needs no change.

    Used directly only when the whole extraction (including OCR, if
    needed) can safely run inside a single synchronous call -- i.e. never
    from the HTTP route when OCR is required (see start_extraction_job),
    only from contexts (tests, the legacy-shaped /ingest route) that accept
    a potentially slow synchronous call.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)
    title = (filename or "Untitled document").rsplit(".", 1)[0]
    source_document = filename or "Untitled document"

    page_texts, _page_offsets, extraction_method = _extract_or_ocr(file_bytes)
    return assemble_preview_payload(
        page_texts, title=title, source_filename=source_document, extraction_method=extraction_method
    )


def chunks_from_pages_or_reviewed_text(
    page_texts: list[str],
    reviewed_text: str | None,
    *,
    title: str,
    source_filename: str,
) -> list[DocumentChunk]:
    """Build chunks either from the original (possibly OCR'd) page texts, or
    from the admin's edited reviewed_text when provided -- shared by
    build_lightweight_publish (legacy-shaped, re-OCRs/re-extracts upstream of
    this) and process_indexing_job (reuses persisted page texts, never
    re-OCRs). The admin's free-text edit has no page boundaries of its own,
    so it's treated as a single page, exactly like the legacy /ingest path's
    equivalent reviewed_text override already accepts (see
    knowledge_base_pipeline._best_review_text) -- page_number/page_start/
    page_end all collapse to 1 for every resulting chunk in that case.
    """
    reviewed = (reviewed_text or "").strip()
    if reviewed:
        chunks = build_chunks_with_pages(
            [reviewed],
            [0],
            chunk_size=settings.chunk_max_chars,
            chunk_overlap=settings.chunk_overlap,
            title=title,
            source_filename=source_filename,
        )
    else:
        chunks = build_chunks_with_pages(
            page_texts,
            _page_offsets_from_texts(page_texts),
            chunk_size=settings.chunk_max_chars,
            chunk_overlap=settings.chunk_overlap,
            title=title,
            source_filename=source_filename,
        )
    return _mirror_page_range_metadata(chunks)


def build_lightweight_publish(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    title: str | None = None,
    reviewed_text: str | None = None,
) -> dict[str, Any]:
    """Cloud-safe equivalent of
    knowledge_base_pipeline.ingest_document_into_knowledge_base for runtimes
    without local easyocr/sentence-transformers.

    Uses publish_new_version() -- staged add-new/verify/delete-old -- NEVER
    delete_by_source_filename()-then-add(). Returns a dict matching the
    IngestKnowledgeBaseResponse schema exactly.

    Superseded, for the admin UI, by the review_ready/indexing job split
    (start_extraction_job / process_indexing_job), which avoids re-running
    OCR here. Kept working and tested as its own independent entry point
    (e.g. for direct API use) -- see knowledge_base.py's /ingest route.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)
    display_title = title or (filename or "Untitled document").rsplit(".", 1)[0]
    source_document = filename or "Untitled document"

    page_texts, _page_offsets, extraction_method = _extract_or_ocr(file_bytes)

    chunks = chunks_from_pages_or_reviewed_text(
        page_texts, reviewed_text, title=display_title, source_filename=source_document
    )

    if not chunks:
        raise DigitalIngestionError("No chunks produced from extracted text.")

    store = get_knowledge_base_store()
    replaced_document_id = store.document_id_for_source_filename(source_document)

    new_document_id, indexed = publish_new_version(
        store,
        chunks=chunks,
        title=display_title,
        source_filename=source_document,
        replaced_document_id=replaced_document_id,
    )

    units = knowledge_units_for_extraction(None, chunks, kb_document_type=None)
    previews = chunk_preview(chunks)
    validation = validation_report(document_type="information", units=units, chunks=chunks)
    stages = pipeline_stages(
        extraction_method=extraction_method,
        structuring_method="generic_chunking",
        indexed=True,
        chunks_indexed=indexed,
    )
    index_text = (reviewed_text or "").strip() or "\n".join(page_texts)
    preview_text = index_text[:500] + ("..." if len(index_text) > 500 else "")

    return {
        "document_id": new_document_id,
        "document_type": "information",
        "source_filename": source_document,
        "title": display_title,
        "chunks_indexed": indexed,
        "page_count": len(page_texts),
        "extraction_method": extraction_method,
        "extracted_text_preview": preview_text,
        "structured": _lightweight_structured_response(index_text),
        "structuring_method": "generic_chunking",
        "pipeline_stages": stages,
        "diagnostic_report": None,
        "validation_report": validation,
        "detected_document_type": _lightweight_detected_document_type(
            reason="Lightweight cloud-safe pipeline: generic chunking, no document-type detection."
        ),
        "knowledge_units": units,
        "chunk_preview": previews,
        "kb_statistics": store.collection_statistics(),
    }


# --- review_ready / indexing job split (2026-10-05) --------------------------
#
# Splits the lightweight pipeline into two independently-triggered phases so
# a slow remote-OCR extraction never has to complete inside a single
# synchronous HTTP request (Heroku's router enforces a flat 30s timeout --
# H12 -- regardless of what the app is doing; see the 2026-10-05 production
# incident on /admin/knowledge-base/extract). Only the (possibly OCR'd) page
# texts are persisted (extracted_pages_json) -- everything else in the
# preview (cleaning, chunking, knowledge units, validation report) is cheap,
# local, pure-Python work and is rebuilt on demand by build_preview_from_job
# rather than stored.


def extracted_pages_payload(page_texts: list[str], extraction_method: str) -> str:
    return json.dumps({"pages": page_texts, "extraction_method": extraction_method})


def load_extracted_pages(job: IngestionJob) -> tuple[list[str], str]:
    if not job.extracted_pages_json:
        raise DigitalIngestionError(
            f"Job {job.id} has no persisted extraction result yet (status={job.status})."
        )
    try:
        data = json.loads(job.extracted_pages_json)
        pages = data["pages"]
        extraction_method = data.get("extraction_method", "unknown")
    except (ValueError, KeyError, TypeError) as exc:
        raise DigitalIngestionError(f"Job {job.id}'s persisted extraction result is corrupt.") from exc
    return pages, extraction_method


def build_preview_from_job(job: IngestionJob) -> dict[str, Any]:
    """Rebuilds the exact ExtractDocumentResponse-shaped payload for a
    review_ready/indexing/published job from its persisted
    extracted_pages_json -- no OCR, no Chroma access beyond the existing
    read-only knowledge_base_statistics() call inside assemble_preview_payload.
    """
    page_texts, extraction_method = load_extracted_pages(job)
    title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
    return assemble_preview_payload(
        page_texts, title=title, source_filename=job.source_filename, extraction_method=extraction_method
    )


_ACTIVE_JOB_STATUSES = ("queued", "processing", "indexing")


def start_extraction_job(
    file_bytes: bytes,
    *,
    filename: str | None,
    content_type: str | None,
    session: Session,
) -> IngestionJob:
    """Creates a brand-new IngestionJob row for this specific upload and
    returns it immediately with status="queued" -- the caller dispatches
    process_extraction_preview_job(job.id) as a background task and
    returns a {job_id, status: "processing"} response without waiting for
    any of it.

    ALWAYS asynchronous now, regardless of whether the document turns out
    to be digital-text-sufficient or needs OCR. This function used to run
    PyMuPDF extraction synchronously and, for digital-sufficient documents,
    also the full clean/chunk/preview-assembly pipeline inside the same
    HTTP request ("the fast path"). The 2026-10-05 LSPU Student Handbook
    incident proved that assumption false: a 198-page digital-text PDF's
    downstream work (specifically, at the time, a since-removed
    build_structured_document() call) took long enough to exceed Heroku's
    30s router timeout (H12) even though PyMuPDF extraction itself was
    fast. There is no size threshold under which the full pipeline can be
    proven fast enough for a single synchronous request, so every /extract
    call now goes through the same background-job path as OCR-required
    documents always did.

    Deliberately does NOT do sha256-based duplicate lookup/reuse of any
    existing row (unlike /ingest-digital's dedup) -- every call creates a
    fresh job explicitly for this operation, so this path can never return
    or attach an old job (including, critically, never the historical
    Student Handbook needs_reconciliation row, nor any other previously
    orphaned job) merely because it happens to share a filename or hash.
    The only existing-row check here is the single-dyno "something else is
    already running" concurrency guard, which never inspects job
    content/history, only current status.
    """
    validate_pdf_bytes(file_bytes, content_type=content_type)

    active = (
        session.query(IngestionJob)
        .filter(IngestionJob.status.in_(_ACTIVE_JOB_STATUSES))
        .first()
    )
    if active is not None:
        raise DigitalIngestionActiveJobError(active.id)

    job = IngestionJob(
        source_filename=filename or "untitled.pdf",
        sha256_hash=compute_sha256(file_bytes),
        status="queued",
        pdf_bytes=file_bytes,
        content_type=content_type,
        byte_size=len(file_bytes),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def process_extraction_preview_job(job_id: str) -> None:
    """Background-task entry point for the OCR-required extraction path.

    Mirrors process_ingestion_job's structure/error-handling conventions but
    STOPS at status="review_ready" -- it NEVER calls publish_new_version()
    and NEVER writes/deletes anything in Chroma. Only the (possibly OCR'd)
    page texts are persisted; cleaning/chunking/preview-building is re-done
    on demand by build_preview_from_job rather than stored here.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Extraction preview job %s vanished before processing started.", job_id)
            return

        job.status = "processing"
        job.status_detail = "Extracting digital text..."
        session.commit()

        try:
            page_texts, _page_offsets = extract_digital_text_only(job.pdf_bytes)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.page_count = len(page_texts)
        extraction_method = "pymupdf_digital"

        if not has_usable_digital_text(page_texts):
            if not ocr_worker_configured():
                job.status = "failed"
                job.error_message = (
                    "This document does not contain enough selectable/digital text, "
                    "and the remote OCR worker is not configured."
                )
                session.commit()
                return
            job.status_detail = (
                "Digital text insufficient; running OCR via the external worker "
                "(this can take several minutes for scanned documents)..."
            )
            session.commit()
            try:
                page_texts, _page_offsets = run_ocr_worker(job.pdf_bytes)
            except DigitalIngestionError as exc:
                job.status = "failed"
                job.error_message = str(exc)
                session.commit()
                return
            job.page_count = len(page_texts)
            extraction_method = "remote_ocr_worker"

        job.status_detail = "Cleaning and structuring..."
        session.commit()

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            # Validate the preview can actually be built (e.g. catches "no
            # usable text remained after cleaning") -- result discarded; the
            # fetch endpoint rebuilds it fresh from extracted_pages_json.
            assemble_preview_payload(
                page_texts, title=title, source_filename=job.source_filename, extraction_method=extraction_method
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.extracted_pages_json = extracted_pages_payload(page_texts, extraction_method)
        job.status = "review_ready"
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing extraction preview job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = "Unhandled internal error during extraction."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for extraction preview job %s", job_id)
    finally:
        session.close()


def start_indexing_job(job: IngestionJob, *, session: Session) -> None:
    """Validates and transitions a review_ready job to status="indexing".

    The actual publish happens in the caller's dispatched background task
    (process_indexing_job) -- this function only performs the synchronous
    state-transition part so the HTTP route can return immediately.
    """
    if job.status != "review_ready":
        raise DigitalIngestionJobStateError(job.status)
    job.status = "indexing"
    session.commit()


def process_indexing_job(job_id: str, reviewed_text: str | None) -> None:
    """Background-task entry point for the publish phase of a review_ready
    job. Reuses the job's persisted extracted_pages_json -- NEVER re-opens
    job.pdf_bytes and NEVER calls the OCR worker again. publish_new_version()
    remains the only Chroma-write primitive, identical to process_ingestion_job's
    publish tail and build_lightweight_publish.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Indexing job %s vanished before processing started.", job_id)
            return
        if job.status != "indexing":
            logger.error(
                "process_indexing_job called for job %s with unexpected status=%s (expected indexing).",
                job_id,
                job.status,
            )
            return

        try:
            page_texts, _extraction_method = load_extracted_pages(job)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            chunks = chunks_from_pages_or_reviewed_text(
                page_texts, reviewed_text, title=title, source_filename=job.source_filename
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        if not chunks:
            job.status = "failed"
            job.error_message = "No chunks produced from extracted text."
            session.commit()
            return

        store = get_knowledge_base_store()
        replaced_document_id = store.document_id_for_source_filename(job.source_filename)

        total_chunks = len(chunks)
        job.status_detail = f"Embedding and publishing {total_chunks} chunks..."
        job.replaced_document_id = replaced_document_id
        session.commit()

        def _on_batch_complete(added_so_far: int, total: int) -> None:
            job.status_detail = f"Embedding and publishing chunk {added_so_far}/{total}..."
            session.commit()

        try:
            new_document_id, indexed = publish_new_version(
                store,
                chunks=chunks,
                title=title,
                source_filename=job.source_filename,
                replaced_document_id=replaced_document_id,
                progress_callback=_on_batch_complete,
            )
        except DigitalIngestionReconciliationError as exc:
            job.status = "needs_reconciliation"
            job.error_message = str(exc)
            session.commit()
            return
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001 -- last-resort safety net, mirrors process_ingestion_job
            job.status = "needs_reconciliation"
            job.error_message = (
                f"New version published but cleanup of the old version may be incomplete: {exc}"
            )
            session.commit()
            return

        job.status = "published"
        job.document_id = new_document_id
        job.chunks_indexed = indexed
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing indexing job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                # needs_reconciliation (not failed): publish_new_version may
                # have partially run before the unhandled exception.
                job.status = "needs_reconciliation"
                job.error_message = "Unhandled internal error during indexing; manual verification required."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for indexing job %s", job_id)
    finally:
        session.close()


def _rollback_orphaned_new_version(
    store: KnowledgeBaseStore, new_document_id: str, *, add_error: Exception
) -> None:
    """Best-effort cleanup of whatever batches of the new version already
    landed in Chroma before a later batch or verification step failed.

    Deletes strictly by ``new_document_id`` (never by filename -- see
    module docstring), then re-queries to CONFIRM zero chunks remain
    rather than trusting the delete call's return value alone. Raises
    DigitalIngestionReconciliationError (never silently swallows) if the
    rollback cannot be verified complete, so the caller marks the job
    needs_reconciliation -- never 'failed', which would wrongly imply it's
    simply safe to retry while an orphan may still sit in Chroma.
    """
    try:
        store.delete_by_document_id(new_document_id)
        remaining = store.document_chunk_count(new_document_id)
    except Exception as cleanup_exc:
        raise DigitalIngestionReconciliationError(
            f"Adding the new version failed ({add_error}) and automatic rollback of its "
            f"partially-added chunks also failed ({cleanup_exc}). Partially-added chunks "
            f"may remain in Chroma under document_id={new_document_id}; manual cleanup is "
            "required before retrying this document."
        ) from cleanup_exc
    if remaining != 0:
        raise DigitalIngestionReconciliationError(
            f"Adding the new version failed ({add_error}) and {remaining} chunk(s) remain "
            f"in Chroma under document_id={new_document_id} after attempted rollback. "
            "Manual cleanup is required before retrying this document."
        )


def publish_new_version(
    store: KnowledgeBaseStore,
    *,
    chunks: list[DocumentChunk],
    title: str,
    source_filename: str,
    replaced_document_id: str | None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> tuple[str, int]:
    """Add the new version in batches, verify it, then (only then) delete
    the old version.

    Returns (new_document_id, chunks_indexed).

    The add is split into sequential Chroma ``add()`` calls of at most
    CHROMA_ADD_MAX_BATCH_SIZE records each (Chroma Cloud enforces a
    per-request "Number of records" quota on the Add action, independent
    of total collection size). Unlike a single atomic add, a later batch
    can fail after earlier batches already succeeded -- so failure here
    always attempts a rollback (delete-by-new-document_id, verified down
    to zero) before raising:

    - DigitalIngestionError: the new version never became visible and the
      rollback was verified complete. Old version untouched. Safe to retry.
    - DigitalIngestionReconciliationError: the new version failed AND its
      rollback could not be verified complete (an orphan may remain under
      new_document_id), OR the new version published successfully but
      deleting the old version failed/left chunks behind. Old version is
      never touched by this function in either case -- only ever read,
      never deleted, until the new version is fully confirmed below.
    """
    new_document_id = str(uuid.uuid4())
    expected = len(chunks)

    # Everything up to and including verification is "new version not yet
    # safe". A failure here means either a clean DigitalIngestionError
    # (rollback verified complete) or a DigitalIngestionReconciliationError
    # (rollback itself could not be verified) -- never silently nothing.
    try:
        store.add_document_chunks(
            document_id=new_document_id,
            title=title,
            source_filename=source_filename,
            document_type="information",
            chunks=chunks,
            max_batch_size=CHROMA_ADD_MAX_BATCH_SIZE,
            on_batch_complete=progress_callback,
        )
        actual_count = store.document_chunk_count(new_document_id)
    except Exception as exc:
        _rollback_orphaned_new_version(store, new_document_id, add_error=exc)
        raise DigitalIngestionError(f"Adding the new version failed: {exc}") from exc

    if actual_count != expected or actual_count == 0:
        _rollback_orphaned_new_version(
            store,
            new_document_id,
            add_error=RuntimeError(f"expected {expected} chunks, found {actual_count}"),
        )
        raise DigitalIngestionError(
            f"New version verification failed: expected {expected} chunks, found {actual_count}."
        )

    # From this point on, the new version is CONFIRMED published (exact
    # expected count verified, no partial batches). Only the old-version
    # cleanup remains, and its failures map to needs_reconciliation, never
    # failed -- the new version is already live and must not be re-added.
    if replaced_document_id and replaced_document_id != new_document_id:
        try:
            store.delete_by_document_id(replaced_document_id)
            remaining_old = store.document_chunk_count(replaced_document_id)
        except Exception as exc:
            raise DigitalIngestionReconciliationError(
                f"New version document_id={new_document_id} was published and verified "
                f"({expected} chunks), but deleting the OLD version "
                f"(document_id={replaced_document_id}) failed: {exc}. The old version may "
                "still be partially present; remove it manually after inspection."
            ) from exc
        if remaining_old != 0:
            raise DigitalIngestionReconciliationError(
                f"New version document_id={new_document_id} was published and verified "
                f"({expected} chunks), but {remaining_old} chunk(s) under the OLD "
                f"document_id={replaced_document_id} remain after cleanup and must be "
                "removed manually."
            )

    return new_document_id, expected


def process_ingestion_job(job_id: str) -> None:
    """Background-task entry point. Runs on the SAME web dyno process as an
    in-process asyncio task (mirrors citation_verification_jobs.py's
    fire-and-poll pattern) -- no new dyno, no new queue service.

    Opens its own DB session: the original HTTP request's session does not
    survive past that request/response cycle, and this function is invoked
    after the response has already been returned to the client.
    """
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    session: Session = session_factory()
    try:
        job = session.get(IngestionJob, job_id)
        if job is None:
            logger.error("Ingestion job %s vanished before processing started.", job_id)
            return

        job.status = "processing"
        job.status_detail = "Extracting digital text..."
        session.commit()

        try:
            page_texts, page_offsets = extract_digital_text_only(job.pdf_bytes)
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        job.page_count = len(page_texts)

        if not has_usable_digital_text(page_texts):
            if ocr_worker_configured():
                job.status_detail = (
                    "Digital text insufficient; running OCR via the external worker "
                    "(this can take several minutes for scanned documents)..."
                )
                session.commit()
                try:
                    page_texts, page_offsets = run_ocr_worker(job.pdf_bytes)
                except DigitalIngestionError as exc:
                    # OCR runs strictly before any Chroma write -- nothing
                    # was ever published for this attempt, exactly like any
                    # other pre-publish failure on this path. Original
                    # pdf_bytes remain in the job row for the admin to retry.
                    job.status = "failed"
                    job.error_message = str(exc)
                    session.commit()
                    return
                job.page_count = len(page_texts)
            else:
                job.status = "ocr_required"
                job.status_detail = (
                    "This document does not contain enough selectable/digital text. "
                    "OCR is required but is not available on this lightweight runtime -- "
                    "use the full local/Docker admin environment to ingest this document."
                )
                session.commit()
                return

        job.status_detail = "Cleaning and chunking..."
        session.commit()

        title = (job.source_filename or "Untitled document").rsplit(".", 1)[0]
        try:
            chunks = build_chunks_with_pages(
                page_texts,
                page_offsets,
                chunk_size=settings.chunk_max_chars,
                chunk_overlap=settings.chunk_overlap,
                title=title,
                source_filename=job.source_filename,
            )
        except DigitalIngestionError as exc:
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return

        store = get_knowledge_base_store()
        replaced_document_id = store.document_id_for_source_filename(job.source_filename)

        total_chunks = len(chunks)
        job.status_detail = f"Embedding and publishing {total_chunks} chunks..."
        job.replaced_document_id = replaced_document_id
        session.commit()

        def _on_batch_complete(added_so_far: int, total: int) -> None:
            job.status_detail = f"Embedding and publishing chunk {added_so_far}/{total}..."
            session.commit()

        try:
            new_document_id, indexed = publish_new_version(
                store,
                chunks=chunks,
                title=title,
                source_filename=job.source_filename,
                replaced_document_id=replaced_document_id,
                progress_callback=_on_batch_complete,
            )
        except DigitalIngestionReconciliationError as exc:
            # Either a failed add's rollback could not be verified complete
            # (an orphan may remain under some new document_id -- see the
            # message for it), or the new version published but deleting
            # the old version failed/left chunks behind. Never guess or
            # retry automatically: surface for manual reconciliation.
            job.status = "needs_reconciliation"
            job.error_message = str(exc)
            session.commit()
            return
        except DigitalIngestionError as exc:
            # New version never became visible (rollback verified complete);
            # old version (if any) is untouched. Safe for the admin to retry.
            job.status = "failed"
            job.error_message = str(exc)
            session.commit()
            return
        except Exception as exc:  # noqa: BLE001 -- last-resort safety net; see module docstring
            # Should not normally be reached now that publish_new_version
            # raises typed exceptions for every known failure mode above.
            job.status = "needs_reconciliation"
            job.error_message = (
                f"New version published but cleanup of the old version may be incomplete: {exc}"
            )
            session.commit()
            return

        job.status = "published"
        job.document_id = new_document_id
        job.chunks_indexed = indexed
        job.status_detail = None
        session.commit()
    except Exception:
        logger.exception("Unhandled error processing ingestion job %s", job_id)
        try:
            job = session.get(IngestionJob, job_id)
            if job is not None:
                job.status = "failed"
                job.error_message = "Unhandled internal error during processing."
                session.commit()
        except Exception:
            logger.exception("Failed to record failure state for ingestion job %s", job_id)
    finally:
        session.close()
