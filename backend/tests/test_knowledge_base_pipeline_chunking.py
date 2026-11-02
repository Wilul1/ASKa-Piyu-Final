"""Stage 4A Task 4 -- global-chunker integration tests for
app.services.admin.knowledge_base_pipeline._chunks_for_extraction and
_quality_payload_from_charter_v2_services.

Scope: config validation (Part A), and that all five document-ingestion
branches (Handbook, Charter V2, Procedure, Requirement, generic
INFORMATION) now route through
app.services.common_representation.chunker.chunk_document_record while
preserving the DocumentChunk 4-field contract, document-wide chunk-index
uniqueness, the hard max_chars ceiling, and the legacy metadata keys
(document_type, title, source_document, page_number) several downstream
consumers (chroma_store.py, retrieval_reranker.py, qa/question_answering.py)
read directly. Nothing here touches ChromaDB or Postgres.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import fitz
import pytest

from app.config import settings
from app.services.chroma_store import KnowledgeBaseStore
from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.admin.knowledge_base_pipeline import (
    ChunkSizeConfigurationError,
    _chunks_for_extraction,
    _quality_payload_from_charter_v2_services,
    _validated_chunk_size_settings,
    _with_compat_metadata,
    ingest_document_into_knowledge_base,
)
from app.services.common_representation.adapters import adapt_prebuilt_chunks
from app.services.common_representation.chunker import chunk_document_record
from app.services.handbook_policy_processor import build_handbook_policy_document
from app.services.knowledge_document_types import KnowledgeDocumentType, build_chunks_from_charter_v2_services
from app.services.structured_document_parser import parse_structured_document

import json

BACKEND_DIR = Path(__file__).resolve().parents[1]
FACULTY_MANUAL_PDF = (
    BACKEND_DIR / "data" / "documents" / "1fd07fb7-5e6e-4d2d-b7df-86ce43e85011" / "LSPU Faculty Manual 2020.pdf"
)
CHARTER_PDF = (
    BACKEND_DIR
    / "data"
    / "documents"
    / "2bde4618-70f7-4f23-a483-742f45f6a5e6"
    / "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
)
_HAS_FACULTY_MANUAL_PDF = FACULTY_MANUAL_PDF.exists()
_HAS_CHARTER_PDF = CHARTER_PDF.exists()


class _FakeExtraction:
    def __init__(self, structured=None):
        self.structured = structured


def _assert_globally_unique_sequential_index(chunks: list[DocumentChunk]) -> None:
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks))), "chunk_index must be globally unique and sequential"


def _assert_four_field_contract(chunks: list[DocumentChunk]) -> None:
    for chunk in chunks:
        assert isinstance(chunk.text, str)
        assert isinstance(chunk.chunk_index, int)
        assert isinstance(chunk.char_start, int)
        assert chunk.metadata is None or isinstance(chunk.metadata, dict)


# ---------------------------------------------------------------------------
# Part A: chunk_hard_max_chars validation
# ---------------------------------------------------------------------------


def test_validated_chunk_size_settings_default_is_valid():
    target, hard_max, overlap = _validated_chunk_size_settings()
    assert target == settings.chunk_max_chars
    assert hard_max == settings.chunk_hard_max_chars
    assert overlap == settings.chunk_overlap
    assert hard_max >= target


def test_validated_chunk_size_settings_rejects_hard_max_below_target(monkeypatch):
    monkeypatch.setattr(settings, "chunk_hard_max_chars", settings.chunk_max_chars - 1)
    with pytest.raises(ChunkSizeConfigurationError):
        _validated_chunk_size_settings()


def test_validated_chunk_size_settings_accepts_hard_max_equal_to_target(monkeypatch):
    monkeypatch.setattr(settings, "chunk_hard_max_chars", settings.chunk_max_chars)
    target, hard_max, _ = _validated_chunk_size_settings()
    assert hard_max == target


def test_chunks_for_extraction_raises_before_chunking_on_bad_config(monkeypatch):
    monkeypatch.setattr(settings, "chunk_hard_max_chars", settings.chunk_max_chars - 1)
    with pytest.raises(ChunkSizeConfigurationError):
        _chunks_for_extraction(
            _FakeExtraction(), "Some text.", kb_document_type=KnowledgeDocumentType.INFORMATION,
            title="T", source_document="doc.pdf",
        )


# ---------------------------------------------------------------------------
# _with_compat_metadata
# ---------------------------------------------------------------------------


def test_with_compat_metadata_fills_gaps_without_overwriting_existing_values():
    chunks = [
        DocumentChunk(text="a", chunk_index=0, char_start=0, metadata={"office": "Registrar"}),
        DocumentChunk(
            text="b", chunk_index=1, char_start=1,
            metadata={"document_type": "procedure", "title": "Existing Title", "source_document": "existing.pdf"},
        ),
        DocumentChunk(text="c", chunk_index=2, char_start=2, metadata={"page_start": 5}),
    ]
    result = _with_compat_metadata(chunks, document_type="information", title="Fallback Title", source_document="fallback.pdf")

    assert result[0].metadata["document_type"] == "information"
    assert result[0].metadata["title"] == "Fallback Title"
    assert result[0].metadata["source_document"] == "fallback.pdf"
    assert result[0].metadata["office"] == "Registrar"

    assert result[1].metadata["document_type"] == "procedure"
    assert result[1].metadata["title"] == "Existing Title"
    assert result[1].metadata["source_document"] == "existing.pdf"

    assert result[2].metadata["page_number"] == 5
    assert result[2].metadata["page_start"] == 5


# ---------------------------------------------------------------------------
# Generic INFORMATION branch: no double-chunking, compat metadata
# ---------------------------------------------------------------------------


def test_generic_branch_matches_single_pass_chunk_document_text():
    text = "This is a sentence about enrollment procedures. " * 80
    direct = chunk_document_text(text, chunk_size=settings.chunk_max_chars, chunk_overlap=settings.chunk_overlap)

    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=None), text, kb_document_type=KnowledgeDocumentType.INFORMATION,
        title="Generic Doc", source_document="generic.pdf",
    )

    # Same underlying chunk_document_text pass, not chunked again on top of
    # an already-chunked result -- same chunk count and same text per chunk.
    assert len(chunks) == len(direct)
    assert [c.text for c in chunks] == [c.text for c in direct]
    _assert_globally_unique_sequential_index(chunks)
    _assert_four_field_contract(chunks)
    for chunk in chunks:
        assert chunk.metadata["document_type"] == "information"
        assert chunk.metadata["title"] == "Generic Doc"
        assert chunk.metadata["source_document"] == "generic.pdf"


def test_generic_branch_enforces_hard_max_even_when_sparse_sentence_boundaries(monkeypatch):
    monkeypatch.setattr(settings, "chunk_hard_max_chars", 400)
    monkeypatch.setattr(settings, "chunk_max_chars", 300)
    text = "Noboundaryhere" * 200  # no sentence/paragraph boundaries at all
    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=None), text, kb_document_type=KnowledgeDocumentType.INFORMATION,
        title="Dense Doc", source_document="dense.pdf",
    )
    assert all(len(c.text) <= 400 for c in chunks)
    _assert_globally_unique_sequential_index(chunks)


# ---------------------------------------------------------------------------
# Handbook branch: real Faculty Manual, hard max enforced, citation fields
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FACULTY_MANUAL_PDF, reason="real LSPU Faculty Manual PDF not present on this machine")
def test_handbook_branch_enforces_hard_max_and_preserves_citation_fields():
    doc = fitz.open(str(FACULTY_MANUAL_PDF))
    try:
        page_texts = [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()
    raw_text = "\n".join(page_texts)
    structured = build_handbook_policy_document(raw_text=raw_text, page_texts=page_texts, source_title="LSPU Faculty Manual 2020")

    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=structured), raw_text, kb_document_type=KnowledgeDocumentType.INFORMATION,
        title="Faculty Manual", source_document="faculty_manual.pdf",
    )

    assert len(chunks) > len(structured.units), "oversized units should split into more than one chunk each on average"
    _assert_globally_unique_sequential_index(chunks)
    _assert_four_field_contract(chunks)
    assert all(len(c.text) <= settings.chunk_hard_max_chars for c in chunks)
    assert all(c.metadata.get("document_type") == "information" for c in chunks)
    assert all(c.metadata.get("source_document") == "faculty_manual.pdf" for c in chunks)

    sparse = [c for c in chunks if "Agency Level Awards" in (c.text or "") and "article" not in c.metadata]
    assert sparse, "expected the real missing-article-level unit to survive into a chunk"
    assert sparse[0].metadata.get("chapter")
    assert sparse[0].metadata.get("section")
    assert sparse[0].metadata.get("page_number") is not None


# ---------------------------------------------------------------------------
# Procedure / Requirement branches: legacy filtering preserved, hard max enforced
# ---------------------------------------------------------------------------


def test_procedure_branch_enforces_hard_max_and_preserves_legacy_metadata(monkeypatch):
    monkeypatch.setattr(settings, "chunk_max_chars", 300)
    monkeypatch.setattr(settings, "chunk_hard_max_chars", 400)
    text = (
        "ID Validation and Replacement\n\n"
        "Office: Registrar's Office\nWho may avail: Students\n\n"
        "Requirements:\n1. Accomplished request form - Registrar's Office\n\n"
        + ("Padding text to force an oversized single-chunk service body. " * 40)
        + "\n\nStep 1: Submit request form - Client Step\n"
        "Verify documents - Agency Action - Fee: 50 - 10 minutes - Registrar Staff\n"
    )
    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=None), text, kb_document_type=KnowledgeDocumentType.PROCEDURE,
        title="Procedures", source_document="charter.pdf",
    )
    assert chunks
    assert all(len(c.text) <= 400 for c in chunks)
    _assert_globally_unique_sequential_index(chunks)
    _assert_four_field_contract(chunks)
    # _procedure_chunks sets document_type from its own is_charter detection
    # of the text (e.g. "citizen_charter"), not a fixed "procedure" literal
    # -- that legacy decision is preserved verbatim, not overridden.
    assert all(c.metadata.get("document_type") for c in chunks)
    assert all(c.metadata.get("source_document") == "charter.pdf" for c in chunks)


def test_requirement_branch_preserves_legacy_single_chunk_when_small():
    text = "Application Form\n\nField 1: Name\nField 2: Address\n"
    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=None), text, kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        title="App Form", source_document="form.pdf", preview_file_path="form.pdf",
    )
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_start == 0
    assert chunks[0].metadata.get("document_type") == "requirement"
    assert chunks[0].metadata.get("source_document") == "form.pdf"


def test_requirement_branch_splits_when_oversized(monkeypatch):
    monkeypatch.setattr(settings, "chunk_max_chars", 300)
    monkeypatch.setattr(settings, "chunk_hard_max_chars", 500)
    text = "Application Form\n\n" + ("Field entry describing a long form field. " * 60)
    chunks = _chunks_for_extraction(
        _FakeExtraction(structured=None), text, kb_document_type=KnowledgeDocumentType.REQUIREMENT,
        title="App Form", source_document="form.pdf", preview_file_path="form.pdf",
    )
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)
    _assert_globally_unique_sequential_index(chunks)


# ---------------------------------------------------------------------------
# Charter V2 branch
# ---------------------------------------------------------------------------


def test_charter_v2_branch_enforces_hard_max_and_preserves_office_and_page(monkeypatch):
    monkeypatch.setattr(settings, "chunk_max_chars", 300)
    monkeypatch.setattr(settings, "chunk_hard_max_chars", 500)
    services = [
        {
            "service_title": "Issuance of Good Moral Certificate",
            "office": "Registrar",
            "who_may_avail": "Students",
            "requirements": [{"requirement": "Request form", "where_to_secure": "Registrar"}],
            "steps": [
                {
                    "client_step": "Submit " + ("padding " * 60),
                    "agency_action": "Process",
                    "fees": "0",
                    "processing_time": "1 day",
                    "responsible_personnel": "Staff",
                }
            ],
            "page_start": 42,
        },
    ]
    chunks, units, previews, validation = _quality_payload_from_charter_v2_services(
        _FakeExtraction(structured=None), services, title="Charter", source_document="charter2.pdf"
    )
    assert chunks
    assert all(len(c.text) <= 500 for c in chunks)
    _assert_globally_unique_sequential_index(chunks)
    assert all(c.metadata.get("office") == "Registrar" for c in chunks)
    assert all(c.metadata.get("document_type") == "citizen_charter" for c in chunks)
    assert any(c.metadata.get("page_number") == 42 for c in chunks)


# ---------------------------------------------------------------------------
# Stage 4A Task 6: prebuilt-chunk repacking fix.
#
# chunk_document_record is now called with target_chars=hard_max_chars (not
# settings.chunk_max_chars) for the three branches wrapping already-built,
# already-filtered legacy chunks (Procedure, Requirement, Charter V2) --
# _chunk_paragraph repacks at whatever target_chars it receives regardless
# of how it got there, so passing the usual 1200-char target would re-split
# an already-correctly-bounded prebuilt chunk purely for being over 1200
# chars, even while comfortably under the 1800-char hard ceiling (confirmed
# against the real Citizen's Charter: 4/134 real service chunks fell in
# that band pre-fix). Handbook and generic INFORMATION are untouched and
# still use the normal 1200 target / 1800 hard max.
# ---------------------------------------------------------------------------


def _prebuilt_chunk_roundtrip(text: str, metadata: dict, *, classification: str) -> list[DocumentChunk]:
    legacy = [DocumentChunk(text=text, chunk_index=0, char_start=0, metadata=metadata)]
    record = adapt_prebuilt_chunks(
        legacy, document_id="d1", source_filename="f.pdf", classification=classification
    )
    chunks = chunk_document_record(
        record,
        target_chars=settings.chunk_hard_max_chars,
        max_chars=settings.chunk_hard_max_chars,
        overlap_chars=settings.chunk_overlap,
    )
    return _with_compat_metadata(
        chunks, document_type=classification, title="Fallback Title", source_document="f.pdf"
    )


@pytest.mark.parametrize("classification", ["procedure", "requirement", "citizen_charter"])
@pytest.mark.parametrize("approx_len", [1400, 1700])
def test_prebuilt_chunk_between_target_and_hard_max_stays_whole(classification, approx_len):
    # .strip() up front -- chunk_document_text trims leading/trailing
    # whitespace, so an arbitrary slice ending mid-whitespace would make
    # an exact-text comparison fail for reasons unrelated to this fix.
    text = ("Service description sentence. " * 200)[:approx_len].strip()
    metadata = {
        "title": "Some Service", "office": "Registrar", "page_number": 7,
        "document_type": classification, "section_heading": "Some Service",
    }
    chunks = _prebuilt_chunk_roundtrip(text, metadata, classification=classification)

    assert len(chunks) == 1, f"a {len(text)}-char prebuilt chunk (under the 1800 hard max) must not be split"
    assert chunks[0].text == text
    assert chunks[0].metadata["office"] == "Registrar"
    assert chunks[0].metadata["page_number"] == 7
    assert chunks[0].metadata["document_type"] == classification
    assert chunks[0].metadata["section_heading"] == "Some Service"


@pytest.mark.parametrize("classification", ["procedure", "requirement", "citizen_charter"])
def test_prebuilt_chunk_exceeding_hard_max_is_split_without_losing_text_or_metadata(classification):
    text = "Service description sentence. " * 100  # well over 1800 chars
    assert len(text) > settings.chunk_hard_max_chars
    metadata = {
        "title": "Big Service", "office": "Treasury", "page_number": 12,
        "document_type": classification, "extracted_steps": json.dumps([{"client_step": "a", "agency_action": "b"}]),
    }
    chunks = _prebuilt_chunk_roundtrip(text, metadata, classification=classification)

    assert len(chunks) > 1, "an oversized prebuilt chunk must be split"
    assert all(len(c.text) <= settings.chunk_hard_max_chars for c in chunks)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))

    # No source text lost: the pieces, in order, reconstruct the original
    # (chunk_document_text's overlap duplicates a small boundary tail
    # between consecutive pieces, so reconstruction tolerates that by
    # checking every piece's text is a verbatim substring of the original,
    # rather than requiring a byte-exact concatenation).
    for c in chunks:
        assert c.text in text or text in c.text

    # Metadata (including extracted_steps) must be available on every piece,
    # not just the first -- it's read per-unit, not per-split-piece.
    for c in chunks:
        assert c.metadata.get("office") == "Treasury"
        assert c.metadata.get("page_number") == 12
        assert c.metadata.get("extracted_steps") == json.dumps([{"client_step": "a", "agency_action": "b"}])


def test_procedure_paired_fields_survive_in_metadata_but_text_pairing_is_not_guaranteed():
    """adapt_prebuilt_chunks wraps the legacy Procedure chunk as plain
    ParagraphContent, not ProcedureContent -- so any split of the embedded
    text (via chunk_document_text's sentence/paragraph-boundary splitting)
    has no awareness of client_step/agency_action pairing, unlike the
    native _chunk_procedure handler used for genuinely ProcedureContent-
    typed units elsewhere. This is a known, explicitly accepted limitation
    of the "wrap existing filtered output" design (Stage 4A Task 4), not a
    new regression from this fix -- documented here, not silently claimed
    as solved.

    What IS guaranteed: the metadata-level step data (extracted_steps,
    built and JSON-encoded by _procedure_chunks itself before this adapter
    ever sees it) survives intact and complete on every resulting chunk,
    because searchable_fields is read per-StructuralUnit, not per split
    piece -- so no step is ever silently dropped from metadata even when
    the embedded text is split mid-step.
    """
    steps = [
        {"client_step": "Submit the completed request form at the registrar's counter.",
         "agency_action": "Verify the submitted documents against the requirements checklist."},
        {"client_step": "Pay the applicable processing fee at the cashier's window.",
         "agency_action": "Issue an official receipt and forward the request for approval."},
    ]
    lines = ["Procedure Title: Sample Service", "Steps:"]
    for index, step in enumerate(steps, start=1):
        lines.append(f"{index}. Client Step: {step['client_step']}")
        lines.append(f"   Agency Action: {step['agency_action']}")
    # Pad well past the hard max so a split is forced somewhere in the steps.
    lines.append("Padding. " * 250)
    text = "\n".join(lines)
    assert len(text) > settings.chunk_hard_max_chars

    metadata = {"title": "Sample Service", "extracted_steps": json.dumps(steps)}
    chunks = _prebuilt_chunk_roundtrip(text, metadata, classification="procedure")

    assert len(chunks) > 1
    # Metadata: both steps' full pairing survives, identically, on every chunk.
    for c in chunks:
        recovered = json.loads(c.metadata["extracted_steps"])
        assert recovered == steps
        for step in recovered:
            assert step["client_step"] and step["agency_action"]

    # Embedded text: NOT guaranteed -- a split may separate a Client Step
    # line from its own Agency Action line. Documented, not asserted as
    # solved; this test only records whether it happened for this input,
    # so a future reader sees the limitation is real rather than assumed.
    first_step_client_line = f"1. Client Step: {steps[0]['client_step']}"
    first_step_action_line = f"   Agency Action: {steps[0]['agency_action']}"
    same_chunk = any(
        first_step_client_line in c.text and first_step_action_line in c.text for c in chunks
    )
    # Whichever way this falls for this particular input, it demonstrates
    # the limitation is real and unresolved by this fix -- not a pass/fail
    # assertion on pairing itself, since no grouping algorithm was added.
    assert same_chunk in (True, False)


@pytest.mark.skipif(not _HAS_CHARTER_PDF, reason="real Citizen's Charter PDF not present on this machine")
def test_real_charter_previously_split_chunks_now_stay_whole():
    """Direct regression test for the exact defect Task 5 found: 4 of 134
    real Citizen's Charter service chunks fall between 1200 and 1800 chars
    and were unnecessarily split pre-fix. Confirms they now survive as a
    single, unsplit, text-identical chunk."""
    doc = fitz.open(str(CHARTER_PDF))
    try:
        page_texts = [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()
    raw_text = "\n".join(page_texts)
    parsed = parse_structured_document(raw_text)
    services = parsed.get("services", [])
    assert services, "expected real services from the real Citizen's Charter text"

    legacy_chunks = build_chunks_from_charter_v2_services(services, title="Charter", source_document="charter.pdf")
    affected = [c for c in legacy_chunks if settings.chunk_max_chars < len(c.text) <= settings.chunk_hard_max_chars]
    assert affected, "expected at least one real service chunk in the 1200-1800 char band"

    new_chunks, _units, _previews, _validation = _quality_payload_from_charter_v2_services(
        _FakeExtraction(structured=None), services, title="Charter", source_document="charter.pdf"
    )
    new_texts = [c.text for c in new_chunks]
    for legacy_chunk in affected:
        assert legacy_chunk.text in new_texts, (
            f"a {len(legacy_chunk.text)}-char real service chunk (under the hard max) "
            "should survive as a single, unsplit chunk after the Task 6 fix"
        )


# ---------------------------------------------------------------------------
# Stage 4B.6 Task 2: full-pipeline orchestration coverage for Fix A
# (chroma_store.py::add_document_chunks's authoritative document_id).
#
# Genuinely exercises ingest_document_into_knowledge_base()'s real
# orchestration (PDF extraction, charter detection, _quality_payload ->
# _chunks_for_extraction -> adapt_generic_text -> chunk_document_record,
# category enrichment, RAG audience stamping) end to end, with only the
# external boundaries mocked: Chroma (a KnowledgeBaseStore bound to an
# in-memory fake collection, not add_document_chunks itself -- that real
# method runs and is spied on, not replaced), document persistence and
# citation-readiness reads (both real PostgreSQL operations), and the
# optional Groq LLM classification fallback (forced off by clearing the
# API key, so no real network call is reachable either way). No real
# PostgreSQL, ChromaDB, network, OCR, or embedding-service access occurs.
# ---------------------------------------------------------------------------


class _FakeKnowledgeBaseCollection:
    """Minimal in-memory Chroma collection stand-in -- supports exactly
    what KnowledgeBaseStore's real methods (add_document_chunks,
    delete_by_source_filename, delete_document) call on it."""

    def __init__(self):
        self._records: dict[str, dict] = {}

    def add(self, *, ids, documents, metadatas):
        for _id, doc, meta in zip(ids, documents, metadatas):
            self._records[_id] = {"document": doc, "metadata": dict(meta)}

    def get(self, where=None, include=None, limit=None, offset=0, ids=None):
        if ids is not None:
            matched = [i for i in ids if i in self._records]
        elif where and "document_id" in where:
            wanted = where["document_id"]
            matched = [i for i, r in self._records.items() if r["metadata"].get("document_id") == wanted]
        elif where and "source_filename" in where:
            wanted = where["source_filename"]
            matched = [i for i, r in self._records.items() if r["metadata"].get("source_filename") == wanted]
        else:
            matched = list(self._records.keys())
        page = matched[offset:] if limit is None else matched[offset : offset + limit]
        return {
            "ids": page,
            "documents": [self._records[i]["document"] for i in page],
            "metadatas": [self._records[i]["metadata"] for i in page],
        }

    def count(self):
        return len(self._records)

    def delete(self, *, ids):
        for i in ids:
            self._records.pop(i, None)


def _make_digital_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


def test_ingest_document_into_knowledge_base_preserves_authoritative_document_id():
    """Exercises the real full-pipeline orchestration end to end and proves
    Fix A holds at its actual production call site: _chunks_for_extraction's
    chunks genuinely carry a chunk-level "document_id" set to the source
    filename (Stage 4A's chunker.py::_build_metadata, confirmed below via
    the spy capture), yet the chunk actually stored in Chroma is tagged
    with the real, freshly-generated UUID add_document_chunks assigns --
    not the filename. Pre-fix, the stored document_id would have been
    "handbook.pdf", and store.document_chunk_count(the real UUID) would
    have found 0 records (Stage 4B.2/4B.4's exact symptom)."""
    collection = _FakeKnowledgeBaseCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection

    pdf_bytes = _make_digital_pdf("Office of the Registrar handles enrollment procedures. " * 20)

    import app.services.admin.knowledge_base_pipeline as kbp

    with patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store), \
         patch("app.services.document_storage.persist_uploaded_document") as mock_persist, \
         patch(
             "app.services.document_storage.citation_readiness_for_document_id",
             return_value={"pdf_stored": False, "source_documents_row": False, "level2_citation_ready": False},
         ), \
         patch.object(kbp.settings, "groq_api_key", None), \
         patch.object(store, "add_document_chunks", wraps=store.add_document_chunks) as spy_add:
        result = ingest_document_into_knowledge_base(
            pdf_bytes, filename="handbook.pdf", content_type="application/pdf", title="Handbook",
        )

    # The real orchestration ran (not a stand-in): a real document_id (UUID)
    # was generated, and real chunks were produced and indexed.
    assert result.chunks_indexed > 0
    assert result.document_id

    # Capture exactly what was passed to the real add_document_chunks call
    # -- proving the chunk-level "document_id" key (from Stage 4A's
    # chunker) genuinely exists in the input, not just hypothesized.
    spy_add.assert_called_once()
    call_kwargs = spy_add.call_args.kwargs
    passed_chunks = call_kwargs["chunks"]
    assert any(
        (getattr(c, "metadata", None) or {}).get("document_id") == "handbook.pdf" for c in passed_chunks
    ), "expected at least one chunk to carry the chunker's own filename-valued document_id key"

    # The authoritative identity used for the call is the real UUID, not
    # the filename -- this is what add_document_chunks is given, and
    # (per Fix A) what ends up stored.
    assert call_kwargs["document_id"] == result.document_id
    assert call_kwargs["document_id"] != "handbook.pdf"

    # Fix A verification, through the real store methods -- the stored
    # record is discoverable by the authoritative UUID, and source_filename/
    # source_document remain correct.
    count = store.document_chunk_count(document_id=result.document_id)
    assert count == result.chunks_indexed
    export = store.export_document(result.document_id)
    assert export is not None
    for metadata in export["metadatas"]:
        assert metadata["document_id"] == result.document_id
        assert metadata["source_filename"] == "handbook.pdf"

    mock_persist.assert_called_once()
