"""Equivalence tests for Stage 1's common-structured-representation adapters.

These tests compare each existing producer's actual output against what the
new adapter in app.services.common_representation.adapters converts it
into. Nothing here touches ChromaDB, Postgres, or any live ingestion path.

Real-document coverage:
- Handbook adapter: the real LSPU Student Handbook PDF already present in
  this repository's local data directory.
- ServiceRecord-shaped adapter: real raw text extracted from the real LSPU
  Citizen's Charter PDF, fed through the actual
  structured_document_parser.parse_structured_document().
- Generic adapter: a real plain-prose excerpt taken from the Handbook's own
  extracted text.

Honestly-labeled synthetic coverage (no real fixture available -- stated
explicitly, not silently substituted for a real one):
- Charter V2 (CharterServiceV2-shaped dict) adapter: running the live V2
  extractor end-to-end was out of this task's scope; a synthetic dict
  matching CharterServiceV2's confirmed field names is used instead.
- FormRecord-shaped adapter: none of the 4 real documents available in this
  repository are classified REQUIREMENT (Handbook/Faculty Manual are
  INFORMATION via the handbook override; the Citizen's Charter goes through
  the V2-services path) -- so no real FormRecord-producing document exists
  to test against. A synthetic dict matching parse_form_document()'s actual
  ["form"] shape is used instead.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from app.services.chunking import DocumentChunk
from app.services.common_representation.adapters import (
    adapt_charter_v2_services,
    adapt_form_record,
    adapt_generic_chunks,
    adapt_generic_text,
    adapt_handbook_document,
    adapt_prebuilt_chunks,
    adapt_service_records,
)
from app.services.common_representation.types import (
    FormContent,
    ListContent,
    ParagraphContent,
    ProcedureContent,
)
from app.services.chunking import chunk_document_text
from app.services.handbook_policy_processor import build_handbook_policy_document
from app.services.structured_document_parser import parse_structured_document

BACKEND_DIR = Path(__file__).resolve().parents[1]
HANDBOOK_PDF = (
    BACKEND_DIR / "data" / "documents" / "36adaba5-1e7c-4615-a986-755b612a511e" / "LSPU Student Handbook.pdf"
)
CHARTER_PDF = (
    BACKEND_DIR
    / "data"
    / "documents"
    / "2bde4618-70f7-4f23-a483-742f45f6a5e6"
    / "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
)
FACULTY_MANUAL_PDF = (
    BACKEND_DIR / "data" / "documents" / "1fd07fb7-5e6e-4d2d-b7df-86ce43e85011" / "LSPU Faculty Manual 2020.pdf"
)

_HAS_HANDBOOK_PDF = HANDBOOK_PDF.exists()
_HAS_CHARTER_PDF = CHARTER_PDF.exists()
_HAS_FACULTY_MANUAL_PDF = FACULTY_MANUAL_PDF.exists()


def _extract_page_texts(path: Path) -> list[str]:
    doc = fitz.open(str(path))
    try:
        return [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# 1. Handbook adapter -- real document
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_HANDBOOK_PDF, reason="real LSPU Student Handbook PDF not present on this machine")
def test_adapt_handbook_document_preserves_real_document_content():
    page_texts = _extract_page_texts(HANDBOOK_PDF)
    raw_text = "\n".join(page_texts)
    document = build_handbook_policy_document(raw_text=raw_text, page_texts=page_texts, source_title="LSPU Student Handbook")

    record = adapt_handbook_document(document, document_id="test-handbook")

    assert len(record.units) == len(document.units)
    assert record.source_filename == document.source_title
    assert record.classification == "information"

    for index, (unit, source_order_check) in enumerate(zip(record.units, document.units, strict=True)):
        assert unit.source_order == index
        assert unit.title == (source_order_check.title or None)
        assert isinstance(unit.content, ParagraphContent)
        # unit.article_text (not unit.content) -- the live Handbook
        # chunk-building path embeds the title+breadcrumb-prefixed
        # article_text as each chunk's actual indexed/embedded text, so
        # the adapter must preserve that, not just the bare body.
        assert unit.content.text == source_order_check.article_text
        metadata = dict(source_order_check.metadata)
        assert unit.content_type == str(metadata.get("content_type") or "policy")
        assert unit.page_start == metadata.get("page_start")
        assert unit.page_end == metadata.get("page_end")
        # Handbook units carry a true page range today -- confirmed, not estimated.
        if unit.page_start is not None or unit.page_end is not None:
            assert unit.extraction_diagnostics.page_info_unavailable is False
        else:
            assert unit.extraction_diagnostics.page_info_unavailable is True

    # Spot-check: known, previously-reviewed real content survives unchanged.
    # Stage 6 investigation: this real Handbook's heading structure groups the
    # Cyber bullying provision under a "Major Offense" heading repeated across
    # 6 units in this document -- not a unit titled "Cyber bullying" -- a
    # pre-existing characteristic of the unmodified baseline parser
    # (handbook_policy_processor.py), reproduced identically by production's
    # own _information_chunks (knowledge_document_types.py), not something
    # this candidate's adapter introduced. Located by its own body text
    # (confirmed unique in this document) rather than by title, so this
    # cannot accidentally match one of the other 5 same-titled units.
    cyberbullying = [u for u in record.units if u.content and "Cyber bullying" in u.content.text]
    assert cyberbullying, "expected the Cyber bullying provision's text to survive adaptation"
    assert cyberbullying[0].title == "Major Offense"
    assert "Suspension" in cyberbullying[0].content.text


# ---------------------------------------------------------------------------
# 2. Charter V2 services adapter -- SYNTHETIC input, explicitly labeled
# ---------------------------------------------------------------------------


def test_adapt_charter_v2_services_preserves_structured_fields_and_real_page_range():
    """SYNTHETIC input: no real CharterServiceV2 extraction was run for this
    test (out of Stage 1's scope). The dict below matches CharterServiceV2's
    confirmed field names (citizen_charter_extractor_v2.py), not real
    extracted content."""
    synthetic_services = [
        {
            "service_title": "Synthetic Enrollment Service",
            "office_division": "Registrar",
            "classification": "Simple",
            "who_may_avail": "All",
            "requirements": [{"requirement": "Form 137", "where_to_secure": "Previous school"}],
            "steps": [
                {
                    "client_step": "Submit requirements",
                    "agency_action": "Validate requirements",
                    "fees": "None",
                    "processing_time": "5 minutes",
                    "person_responsible": "Registrar Staff",
                }
            ],
            "page_start": 10,
            "page_end": 10,
        }
    ]

    record = adapt_charter_v2_services(
        synthetic_services, document_id="test-charter", source_filename="synthetic-charter.pdf"
    )

    assert len(record.units) == 1
    unit = record.units[0]
    assert unit.title == "Synthetic Enrollment Service"
    assert isinstance(unit.content, ProcedureContent)
    assert unit.content.steps[0].client_step == "Submit requirements"
    assert unit.page_start == 10 and unit.page_end == 10
    assert unit.extraction_diagnostics.page_info_unavailable is False
    assert unit.searchable_fields["office"] == "Registrar"
    assert unit.searchable_fields["who_may_avail"] == "All"
    assert unit.structured_fields["extracted_requirements"] == synthetic_services[0]["requirements"]
    assert unit.structured_fields["extracted_steps"] == synthetic_services[0]["steps"]


def test_adapt_charter_v2_services_handles_missing_page_honestly():
    services_without_pages = [{"service_title": "No Page Info", "office_division": "Admin"}]
    record = adapt_charter_v2_services(
        services_without_pages, document_id="test-charter-2", source_filename="synthetic.pdf"
    )
    unit = record.units[0]
    assert unit.page_start is None and unit.page_end is None
    assert unit.extraction_diagnostics.page_info_unavailable is True
    assert isinstance(unit.content, ParagraphContent)


# ---------------------------------------------------------------------------
# 3. ServiceRecord-shaped dict adapter -- real text, real parser
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_CHARTER_PDF, reason="real Citizen's Charter PDF not present on this machine")
def test_adapt_service_records_against_real_charter_text():
    page_texts = _extract_page_texts(CHARTER_PDF)
    raw_text = "\n".join(page_texts)

    parsed = parse_structured_document(raw_text)
    real_services = parsed.get("services", [])
    assert real_services, "expected parse_structured_document to find at least one service in the real Charter text"

    record = adapt_service_records(real_services, document_id="test-procedure", source_filename="charter.pdf")

    assert len(record.units) == len(real_services)
    for unit, source in zip(record.units, real_services, strict=True):
        assert unit.title == (source.get("service") or None)
        assert unit.page_start is None and unit.page_end is None
        assert unit.extraction_diagnostics.page_info_unavailable is True
        if source.get("requirements"):
            assert unit.structured_fields.get("extracted_requirements") == source["requirements"]
        if source.get("steps"):
            assert unit.structured_fields.get("extracted_steps") == source["steps"]
            assert isinstance(unit.content, ProcedureContent)


# ---------------------------------------------------------------------------
# 4. FormRecord-shaped dict adapter -- SYNTHETIC input, explicitly labeled
# ---------------------------------------------------------------------------


def test_adapt_form_record_preserves_fields_and_absent_page_info():
    """SYNTHETIC input: no real document among the 4 available in this
    repository is classified REQUIREMENT, so no real FormRecord-producing
    document exists to test against (reported, not silently substituted).
    The dict below matches parse_form_document()["form"]'s confirmed shape
    (structured_document_parser.py), not real extracted content."""
    synthetic_form = {
        "form_title": "Synthetic Leave Request Form",
        "office": "HR Office",
        "form_code": "HR-001",
        "fields": ["Employee Name", "Leave Type", "Date"],
        "requirements": ["Valid ID"],
        "related_services": ["Leave Approval"],
    }

    record = adapt_form_record(synthetic_form, document_id="test-requirement", source_filename="form.pdf")

    assert len(record.units) == 1
    unit = record.units[0]
    assert unit.title == "Synthetic Leave Request Form"
    assert isinstance(unit.content, FormContent)
    assert unit.content.field_names == ["Employee Name", "Leave Type", "Date"]
    assert unit.page_start is None and unit.page_end is None
    assert unit.extraction_diagnostics.page_info_unavailable is True
    assert unit.searchable_fields["office"] == "HR Office"
    assert unit.searchable_fields["form_code"] == "HR-001"
    assert unit.structured_fields["extracted_requirements"] == ["Valid ID"]
    assert unit.structured_fields["related_services"] == ["Leave Approval"]
    # Stage 1 preserves the existing one-form-per-document limitation; it
    # does not attempt multi-form detection (out of scope for this task).
    assert len(record.units) == 1


# ---------------------------------------------------------------------------
# 5. Generic chunk_document_text() adapter -- real text, real chunker
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_HANDBOOK_PDF, reason="real LSPU Student Handbook PDF not present on this machine")
def test_adapt_generic_chunks_against_real_prose_excerpt():
    page_texts = _extract_page_texts(HANDBOOK_PDF)
    # A real plain-prose excerpt (foreword, page 5) -- not synthetic text.
    real_excerpt = page_texts[4]
    assert real_excerpt.strip(), "expected page 5 of the real Handbook to contain text"

    real_chunks = chunk_document_text(real_excerpt, chunk_size=200, chunk_overlap=20)
    assert real_chunks, "expected chunk_document_text to produce at least one chunk from real text"

    record = adapt_generic_chunks(real_chunks, document_id="test-generic", source_filename="handbook.pdf")

    assert len(record.units) == len(real_chunks)
    for unit, chunk in zip(record.units, real_chunks, strict=True):
        assert isinstance(unit.content, ParagraphContent)
        assert unit.content.text == chunk.text
        assert unit.source_order == chunk.chunk_index
        # chunk_document_text() itself sets no metadata at all -- confirmed
        # by reading its source; nothing is invented here either.
        assert unit.title is None
        assert unit.page_start is None and unit.page_end is None
        assert unit.hierarchy_path == []
        assert unit.extraction_diagnostics.page_info_unavailable is True


# ---------------------------------------------------------------------------
# 6. Handbook adapter -- missing-intermediate-hierarchy-level regression
# (Stage 4A Task 4, Part B): real Faculty Manual case where a unit has a
# chapter and section but no article, confirming searchable_fields leaves
# "article" absent (not None-valued) rather than inferring it from
# hierarchy_path's position, which cannot be trusted once any level is
# sparse.
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FACULTY_MANUAL_PDF, reason="real LSPU Faculty Manual PDF not present on this machine")
def test_adapt_handbook_document_searchable_fields_omit_missing_article_level():
    page_texts = _extract_page_texts(FACULTY_MANUAL_PDF)
    raw_text = "\n".join(page_texts)
    document = build_handbook_policy_document(raw_text=raw_text, page_texts=page_texts, source_title="LSPU Faculty Manual 2020")

    record = adapt_handbook_document(document, document_id="test-faculty-manual")

    sparse_units = [
        unit
        for unit in record.units
        if unit.title and "Agency Level Awards" in unit.title and "article" not in unit.searchable_fields
    ]
    assert sparse_units, "expected at least one real Faculty Manual unit with chapter+section but no article"
    unit = sparse_units[0]
    assert "chapter" in unit.searchable_fields
    assert "section" in unit.searchable_fields
    assert "article" not in unit.searchable_fields
    # hierarchy_path itself stays untouched -- still a plain, position-based list.
    assert unit.hierarchy_path == [unit.searchable_fields["chapter"], unit.searchable_fields["section"]]


# ---------------------------------------------------------------------------
# 7. adapt_generic_text -- real text, verbatim/single-unit/empty-input
# (Stage 4A Task 4, Part C)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_HANDBOOK_PDF, reason="real LSPU Student Handbook PDF not present on this machine")
def test_adapt_generic_text_preserves_real_text_verbatim_as_one_unit():
    page_texts = _extract_page_texts(HANDBOOK_PDF)
    real_excerpt = page_texts[4]
    assert real_excerpt.strip()

    record = adapt_generic_text(real_excerpt, document_id="test-generic-text", source_filename="handbook.pdf")

    assert len(record.units) == 1
    unit = record.units[0]
    assert isinstance(unit.content, ParagraphContent)
    assert unit.content.text == real_excerpt
    assert unit.title is None
    assert record.document_id == "test-generic-text"
    assert record.source_filename == "handbook.pdf"


def test_adapt_generic_text_produces_exactly_one_unit_for_long_text():
    long_text = "Sentence. " * 500
    record = adapt_generic_text(long_text, document_id="d", source_filename="f.pdf")
    assert len(record.units) == 1
    assert record.units[0].content.text == long_text


@pytest.mark.parametrize("raw_text", ["", "   ", "\n\n\t"])
def test_adapt_generic_text_handles_empty_and_whitespace_input(raw_text):
    record = adapt_generic_text(raw_text, document_id="d", source_filename="f.pdf")
    assert len(record.units) == 1
    assert record.units[0].content.text == raw_text


# ---------------------------------------------------------------------------
# 8. adapt_prebuilt_chunks -- wraps already-built/filtered DocumentChunks
# (Stage 4A Task 4, Part D support): used for Procedure/Requirement/
# Charter V2, whose recognition+filtering logic lives in
# knowledge_document_types.py and cannot be reproduced here.
# ---------------------------------------------------------------------------


def test_adapt_prebuilt_chunks_preserves_text_and_metadata_as_searchable_fields():
    chunks = [
        DocumentChunk(
            text="Service A details.",
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "citizen_charter", "title": "Service A", "office": "Registrar", "page_number": 7},
        ),
        DocumentChunk(
            text="Service B details.",
            chunk_index=1,
            char_start=50,
            metadata={"document_type": "citizen_charter", "title": "Service B", "office": "Treasury"},
        ),
    ]

    record = adapt_prebuilt_chunks(
        chunks, document_id="d1", source_filename="charter.pdf", classification="citizen_charter"
    )

    assert len(record.units) == 2
    assert record.classification == "citizen_charter"
    first, second = record.units
    assert first.title == "Service A"
    assert isinstance(first.content, ParagraphContent)
    assert first.content.text == "Service A details."
    assert first.source_order == 0
    # title is consumed into StructuralUnit.title, not duplicated into
    # searchable_fields; every other key survives as a scalar searchable field.
    assert "title" not in first.searchable_fields
    assert first.searchable_fields["office"] == "Registrar"
    assert first.searchable_fields["page_number"] == 7
    assert first.searchable_fields["document_type"] == "citizen_charter"
    assert second.title == "Service B"
    assert second.source_order == 1
    assert "page_number" not in second.searchable_fields


def test_adapt_prebuilt_chunks_json_encodes_non_scalar_metadata_values():
    chunks = [
        DocumentChunk(
            text="Service with structured extras.",
            chunk_index=0,
            char_start=0,
            metadata={"title": "Service C", "extracted_requirements": [{"requirement": "Form 1"}]},
        )
    ]
    record = adapt_prebuilt_chunks(chunks, document_id="d", source_filename="f.pdf", classification="procedure")
    unit = record.units[0]
    assert unit.searchable_fields["extracted_requirements"] == json.dumps([{"requirement": "Form 1"}])
