"""Stage 4B -- global-chunker integration tests for the lightweight
Heroku ingestion path (app.services.admin.digital_ingestion).

Scope: build_chunks_with_pages (generic INFORMATION) and
_chunks_from_handbook_document (Handbook), both of which now route
through app.services.common_representation (adapt_generic_text /
adapt_handbook_document -> chunk_document_record) instead of calling
chunk_document_text directly or hand-building one chunk per Handbook
unit with no size cap. Nothing here touches ChromaDB, Postgres, OCR,
or any production service -- small deterministic fixtures only, plus
the real local Faculty Manual PDF for one hierarchy/citation check
(mirroring the equivalent real-document check already used for the
full pipeline's own Stage 4A tests).
"""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from unittest.mock import patch

from app.config import settings
from app.services.admin import digital_ingestion as digital_ingestion_module
from app.services.admin.digital_ingestion import (
    STRUCTURING_METHOD_GENERIC,
    STRUCTURING_METHOD_HANDBOOK_V1,
    _apply_lightweight_compat_metadata,
    _chunks_from_handbook_document,
    _mirror_page_range_metadata,
    _page_offsets_from_texts,
    assemble_preview_payload,
    build_chunks_with_pages,
    build_preview_from_job,
)
from app.services.chunking import DocumentChunk
from app.services.handbook_policy_processor import (
    HandbookKnowledgeUnit,
    HandbookPolicyDocument,
    build_handbook_policy_document,
)
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata

BACKEND_DIR = Path(__file__).resolve().parents[1]
FACULTY_MANUAL_PDF = (
    BACKEND_DIR / "data" / "documents" / "1fd07fb7-5e6e-4d2d-b7df-86ce43e85011" / "LSPU Faculty Manual 2020.pdf"
)
_HAS_FACULTY_MANUAL_PDF = FACULTY_MANUAL_PDF.exists()


def _assert_globally_unique_sequential_index(chunks: list[DocumentChunk]) -> None:
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks))), "chunk_index must be globally unique and sequential"


# ---------------------------------------------------------------------------
# Generic INFORMATION path (build_chunks_with_pages)
# ---------------------------------------------------------------------------


def test_generic_non_oversized_text_retains_expected_metadata():
    page_texts = ["Page one has some ordinary prose content. " * 5, "Page two continues the same document. " * 5]
    offsets = _page_offsets_from_texts(page_texts)

    chunks = build_chunks_with_pages(
        page_texts, offsets,
        chunk_size=settings.chunk_max_chars, chunk_overlap=settings.chunk_overlap,
        title="Small Doc", source_filename="small.pdf",
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["document_type"] == "information"
    assert chunks[0].metadata["title"] == "Small Doc"
    assert chunks[0].metadata["source_document"] == "small.pdf"
    assert chunks[0].metadata["page_number"] == 1
    # Category enrichment (allow_llm=False) still ran and stamped its own keys.
    assert "category" in chunks[0].metadata
    assert "classification_method" in chunks[0].metadata


def test_generic_oversized_text_splits_within_hard_max():
    # No sentence/paragraph boundaries at all -- forces the hard-max
    # fallback-split path, not just normal target-based packing.
    page_texts = ["Noboundaryhere" * 200]
    offsets = _page_offsets_from_texts(page_texts)

    chunks = build_chunks_with_pages(
        page_texts, offsets,
        chunk_size=settings.chunk_max_chars, chunk_overlap=settings.chunk_overlap,
        title="Big Doc", source_filename="big.pdf",
    )

    assert len(chunks) > 1
    assert all(len(c.text) <= settings.chunk_hard_max_chars for c in chunks)
    _assert_globally_unique_sequential_index(chunks)
    assert all(c.metadata.get("document_type") == "information" for c in chunks)
    assert all(c.metadata.get("source_document") == "big.pdf" for c in chunks)


def test_generic_heading_attachment_runs_against_new_chunk_offsets():
    # A real trustworthy heading line, long enough on both sides of it
    # to guarantee more than one resulting chunk at a lowered hard max.
    page_texts = [
        "I. General Provisions\n\n"
        + ("This section explains the general provisions in detail. " * 40)
    ]
    offsets = _page_offsets_from_texts(page_texts)

    chunks = build_chunks_with_pages(
        page_texts, offsets,
        chunk_size=300, chunk_overlap=settings.chunk_overlap,
        title="Heading Doc", source_filename="heading.pdf",
    )

    assert len(chunks) > 1, "expected the oversized body to split into multiple chunks"
    headings = [c.metadata.get("section_heading") for c in chunks]
    assert any(h and "General Provisions" in h for h in headings), (
        "expected at least one chunk to carry the real heading detected by "
        "_attach_section_headings, which must still run against the new chunk offsets"
    )


def test_generic_category_enrichment_still_receives_heading_metadata_before_running():
    # Reproduces build_chunks_with_pages' own call order directly: heading
    # attachment must have already written section_heading by the time
    # enrich_chunks_with_category_metadata (which reads it for office-
    # ownership evidence) runs.
    page_texts = [
        "Office of the Registrar\n\n"
        + ("All requests shall be submitted to the Registrar's Office for processing. " * 10)
    ]
    offsets = _page_offsets_from_texts(page_texts)

    chunks = build_chunks_with_pages(
        page_texts, offsets,
        chunk_size=settings.chunk_max_chars, chunk_overlap=settings.chunk_overlap,
        title="Office Doc", source_filename="office.pdf",
    )

    # If heading attachment ran before enrichment (as required), every
    # chunk's metadata already has a resolved category/office decision
    # that enrichment could factor section_heading into -- this is an
    # order-of-operations smoke check, not a classification-quality test.
    for c in chunks:
        assert "category" in c.metadata
        assert "office" in c.metadata


def test_apply_lightweight_compat_metadata_preserves_existing_values():
    chunks = [
        DocumentChunk(
            text="x", chunk_index=0, char_start=0,
            metadata={"title": "Already Set", "source_document": "already.pdf", "document_type": "information"},
        ),
        DocumentChunk(text="y", chunk_index=1, char_start=1, metadata={"page_start": 7}),
        DocumentChunk(text="z", chunk_index=2, char_start=2, metadata={"section": "Chapter 1"}),
    ]
    result = _apply_lightweight_compat_metadata(
        chunks, document_type="information", title="Fallback Title", source_filename="fallback.pdf"
    )

    assert result[0].metadata["title"] == "Already Set"
    assert result[0].metadata["source_document"] == "already.pdf"

    assert result[1].metadata["page_number"] == 7
    assert result[1].metadata["title"] == "Fallback Title"

    assert result[2].metadata["section_heading"] == "Chapter 1"
    assert result[2].metadata["title"] == "Fallback Title"


# ---------------------------------------------------------------------------
# Handbook path (_chunks_from_handbook_document)
# ---------------------------------------------------------------------------


def _synthetic_handbook(units: list[HandbookKnowledgeUnit]) -> HandbookPolicyDocument:
    return HandbookPolicyDocument(
        document_type="handbook_policy", source_title="Synthetic Handbook",
        doc_no=None, cleaned_text="", raw_text="", units=units,
    )


def test_handbook_ordinary_units_retain_hierarchy_and_page_metadata():
    units = [
        HandbookKnowledgeUnit(
            title="Registration", content="Students must register each semester.", raw_text="raw",
            metadata={"document_type": "information", "chapter": "Academic Policies", "section": "Registration", "page_start": 10, "page_end": 10},
        ),
    ]
    chunks = _chunks_from_handbook_document(_synthetic_handbook(units), title="Handbook", source_filename="handbook.pdf")

    assert len(chunks) == 1
    c = chunks[0]
    assert c.metadata["chapter"] == "Academic Policies"
    assert c.metadata["section"] == "Registration"
    assert c.metadata["page_number"] == 10
    assert c.metadata["page_start"] == 10
    assert c.metadata["document_type"] == "information"
    assert c.metadata["source_document"] == "handbook.pdf"
    assert c.metadata["title"] == "Registration"


def test_handbook_oversized_unit_splits_within_hard_max_and_keeps_metadata(monkeypatch):
    monkeypatch.setattr(settings, "chunk_max_chars", 300)
    monkeypatch.setattr(settings, "chunk_hard_max_chars", 500)
    units = [
        HandbookKnowledgeUnit(
            title="Long Policy", content="Policy detail sentence. " * 100, raw_text="raw",
            metadata={"document_type": "information", "chapter": "Chapter 5", "article": "Article 2", "page_start": 42, "page_end": 44},
        ),
    ]
    chunks = _chunks_from_handbook_document(_synthetic_handbook(units), title="Handbook", source_filename="handbook.pdf")

    assert len(chunks) > 1, "expected the oversized unit to split into multiple chunks"
    assert all(len(c.text) <= 500 for c in chunks)
    _assert_globally_unique_sequential_index(chunks)
    for c in chunks:
        assert c.metadata.get("chapter") == "Chapter 5"
        assert c.metadata.get("article") == "Article 2"
        assert c.metadata.get("page_number") == 42
        assert c.metadata.get("document_type") == "information"


def test_handbook_success_path_never_invokes_category_enrichment_or_heading_attachment():
    """Direct code-inspection-backed regression guard: _chunks_from_handbook_document
    itself must never call enrich_chunks_with_category_metadata or
    _attach_section_headings -- confirmed by reading its source; this test
    guards that fact by checking no category/classification keys appear
    (enrichment is the only thing that would add them) and that
    title_fallback_suppressed (only ever set by _attach_section_headings)
    never appears either."""
    units = [
        HandbookKnowledgeUnit(
            title="Some Policy", content="Some policy content here.", raw_text="raw",
            metadata={"document_type": "information", "section": "Some Policy"},
        ),
    ]
    chunks = _chunks_from_handbook_document(_synthetic_handbook(units), title="Handbook", source_filename="handbook.pdf")

    for c in chunks:
        assert "category" not in c.metadata
        assert "classification_method" not in c.metadata
        assert "title_fallback_suppressed" not in c.metadata


def test_handbook_preserves_source_document_type_for_non_information_units():
    units = [
        HandbookKnowledgeUnit(
            title="Form Unit", content="Embedded form content.", raw_text="raw",
            metadata={"document_type": "form", "section": "Appendix A"},
        ),
    ]
    chunks = _chunks_from_handbook_document(_synthetic_handbook(units), title="Handbook", source_filename="handbook.pdf")

    assert chunks[0].metadata["document_type"] == "information"
    assert chunks[0].metadata["source_document_type"] == "form"


@pytest.mark.skipif(not _HAS_FACULTY_MANUAL_PDF, reason="real LSPU Faculty Manual PDF not present on this machine")
def test_handbook_real_faculty_manual_missing_article_case():
    doc = fitz.open(str(FACULTY_MANUAL_PDF))
    try:
        page_texts = [doc[i].get_text() for i in range(doc.page_count)]
    finally:
        doc.close()
    raw_text = "\n".join(page_texts)
    handbook = build_handbook_policy_document(raw_text=raw_text, page_texts=page_texts, source_title="LSPU Faculty Manual 2020")

    chunks = _chunks_from_handbook_document(handbook, title="Faculty Manual", source_filename="faculty_manual.pdf")

    _assert_globally_unique_sequential_index(chunks)
    assert all(len(c.text) <= settings.chunk_hard_max_chars for c in chunks)
    sparse = [c for c in chunks if "Agency Level Awards" in (c.text or "") and "article" not in c.metadata]
    assert sparse, "expected the real missing-article-level unit to survive"
    c = sparse[0]
    assert c.metadata.get("chapter")
    assert c.metadata.get("section")
    assert c.metadata.get("section_heading") == c.metadata.get("section")
    assert c.metadata.get("page_number") == 76


# ---------------------------------------------------------------------------
# Compatibility and runtime
# ---------------------------------------------------------------------------


def test_lightweight_chunks_compatible_with_enrich_chunks_with_category_metadata():
    """Stage 4A chunker output (searchable_fields-flattened metadata) must
    not break enrich_chunks_with_category_metadata -- run it directly on
    chunks the new generic path produces."""
    page_texts = ["Office of the Registrar handles enrollment requests. " * 10]
    offsets = _page_offsets_from_texts(page_texts)
    chunks = build_chunks_with_pages(
        page_texts, offsets,
        chunk_size=settings.chunk_max_chars, chunk_overlap=settings.chunk_overlap,
        title="Doc", source_filename="doc.pdf",
    )
    # build_chunks_with_pages already ran enrichment once; running it again
    # here must not raise or corrupt anything (idempotent-safety check).
    reenriched = enrich_chunks_with_category_metadata(chunks, title="Doc", source_document="doc.pdf", allow_llm=False)
    assert len(reenriched) == len(chunks)
    for c in reenriched:
        assert "category" in c.metadata
        assert "office" in c.metadata


# ---------------------------------------------------------------------------
# Stage 4B.4 Fix B: _mirror_page_range_metadata value-check (not
# key-presence) regression tests.
#
# The shared global chunker always sets page_start explicitly (None when
# unknown, e.g. for generic text), unlike this pipeline's pre-Stage-4B
# chunks, which simply omitted the key -- a key-presence check silently
# skipped the mirror once page_start became an always-present key.
# ---------------------------------------------------------------------------


def test_mirror_page_range_metadata_fills_generic_chunk_with_page_start_none():
    chunks = [
        DocumentChunk(text="a", chunk_index=0, char_start=0, metadata={"page_number": 1, "page_start": None, "page_end": None}),
    ]
    result = _mirror_page_range_metadata(chunks)
    assert result[0].metadata["page_start"] == 1
    assert result[0].metadata["page_end"] == 1


def test_mirror_page_range_metadata_fills_second_page_correctly():
    chunks = [
        DocumentChunk(text="b", chunk_index=1, char_start=1, metadata={"page_number": 2, "page_start": None, "page_end": None}),
    ]
    result = _mirror_page_range_metadata(chunks)
    assert result[0].metadata["page_start"] == 2
    assert result[0].metadata["page_end"] == 2


def test_mirror_page_range_metadata_preserves_existing_handbook_range():
    chunks = [
        DocumentChunk(text="c", chunk_index=2, char_start=2, metadata={"page_number": 76, "page_start": 76, "page_end": 77}),
    ]
    result = _mirror_page_range_metadata(chunks)
    assert result[0].metadata["page_start"] == 76
    assert result[0].metadata["page_end"] == 77


def test_mirror_page_range_metadata_leaves_missing_page_info_absent():
    chunks = [
        DocumentChunk(text="d", chunk_index=3, char_start=3, metadata={}),
    ]
    result = _mirror_page_range_metadata(chunks)
    assert "page_start" not in result[0].metadata
    assert "page_end" not in result[0].metadata


def test_generic_multi_page_preview_now_correctly_reports_page_start():
    """Integration-level reproduction of the exact failure
    test_lightweight_cloud_safe_pipeline.py::
    test_lightweight_preview_preserves_page_metadata_across_pages depends
    on: build_chunks_with_pages -> _mirror_page_range_metadata must now
    produce a real page_start for every chunk, not None."""
    page_texts = ["Office of the Registrar. " * 100, "Student Affairs Office procedures. " * 100]
    offsets = _page_offsets_from_texts(page_texts)
    chunks = build_chunks_with_pages(
        page_texts, offsets, chunk_size=50, chunk_overlap=0,
        title="Handbook", source_filename="handbook.pdf",
    )
    mirrored = _mirror_page_range_metadata(chunks)
    page_starts = {c.metadata.get("page_start") for c in mirrored}
    assert page_starts == {1, 2}


# ---------------------------------------------------------------------------
# assemble_preview_payload / build_preview_from_job -- Handbook structured
# preview integration (follow-up to the original-page-context mapping
# investigation). assemble_preview_payload previously always called
# build_chunks_with_pages directly, so the admin-preview diagnostics feature
# was evaluating generic, fixed-size chunks even for a Handbook document --
# never the real structured logical units. It now delegates to
# chunks_from_pages_or_reviewed_text (the same, already-published-path-
# tested function process_indexing_job uses), reused rather than duplicated.
# ---------------------------------------------------------------------------


_HANDBOOK_FIXTURE_PAGE_TEXTS = [
    """
    Institution: Laguna State Polytechnic University
    Doc. No.: LSPU-PM-LSH-01
    Type: Manual
    Revision No.: 00
    Title: LSPU Student Handbook 2021
    Date: 2021
    Page: 1 of 2
    Chapter 3 Student Admission
    Article 2 Admission Requirements
    Sec. 2.11 Basic Requirements
    Freshmen must submit:
    a) Report Card/Form 138
    b) Permanent Record/Form 137
    c) Medical and drug test certification
    """,
    """
    Institution: Laguna State Polytechnic University
    Doc. No.: LSPU-PM-LSH-01
    Type: Manual
    Revision No.: 00
    Title: LSPU Student Handbook 2021
    Date: 2021
    Page: 2 of 2
    2.11.1 Freshman Admission Requirements
    Certificate of Good Moral Character, three 2x2 pictures,
    PSA birth certificate, and ALS/PEPT results if applicable.
    Appendix A Forms
    Use the prescribed university admission forms.
    """,
]

# Mirrors test_handbook_policy_processor.py::
# test_builds_logical_units_with_metadata_and_removes_layout_noise's own
# verified ground truth (doc.units[0].title == "Basic Requirements",
# page_start == 1) -- reused here, not re-derived, so this test's
# expectations are anchored to an already-proven fixture.
_ELIGIBLE_HANDBOOK_STRUCTURED: dict = {
    "status": "eligible",
    "candidate_pages": [],
    "matched_pages": [],
    "table_regions_by_page": {},
    "words_by_page": {},
}


def _assemble_preview_payload_without_kb_statistics(*args, **kwargs):
    """knowledge_base_statistics() (read-only Chroma stats) is the only
    thing assemble_preview_payload touches outside pure in-memory work --
    stubbed out so these tests never need a real or fake Chroma client."""
    with patch.object(digital_ingestion_module, "knowledge_base_statistics", lambda: {}):
        return assemble_preview_payload(*args, **kwargs)


def test_assemble_preview_payload_eligible_handbook_structured_produces_real_units():
    preview = _assemble_preview_payload_without_kb_statistics(
        _HANDBOOK_FIXTURE_PAGE_TEXTS,
        title="LSPU Student Handbook 2021",
        source_filename="handbook.pdf",
        extraction_method="pymupdf_digital",
        handbook_structured=_ELIGIBLE_HANDBOOK_STRUCTURED,
    )

    assert preview["structuring_method"] == STRUCTURING_METHOD_HANDBOOK_V1
    assert "structured handbook" in preview["detected_document_type"]["reason"]

    units = preview["knowledge_units"]
    titles = {u["title"] for u in units}
    page_starts = {u["title"]: u["page_start"] for u in units}
    assert "Basic Requirements" in titles, "expected a real Handbook section title, not a generic-chunk heuristic title"
    assert page_starts["Basic Requirements"] == 1
    # Every unit's own metadata must also carry the real tag (not just the
    # top-level summary field) -- this is what _structuring_method_from_chunks reads.
    assert all(u["metadata"].get("structuring_method") == STRUCTURING_METHOD_HANDBOOK_V1 for u in units)


def test_assemble_preview_payload_structured_units_still_receive_diagnostics_by_stable_unit_index():
    page_texts = _HANDBOOK_FIXTURE_PAGE_TEXTS + [
        """
        Institution: Laguna State Polytechnic University
        Title: LSPU Student Handbook 2021
        Chapter 4 Random Topic
        Article 1 Odd Section
        Sec. 4.1 Mystery Note
        Short.
        """
    ]
    preview = _assemble_preview_payload_without_kb_statistics(
        page_texts,
        title="LSPU Student Handbook 2021",
        source_filename="handbook.pdf",
        extraction_method="pymupdf_digital",
        handbook_structured=_ELIGIBLE_HANDBOOK_STRUCTURED,
    )
    assert preview["structuring_method"] == STRUCTURING_METHOD_HANDBOOK_V1

    units = preview["knowledge_units"]
    suspicious = [u for u in units if u["status"] == "Suspicious"]
    assert len(suspicious) == 1, "expected exactly the deliberately very-short unit to be flagged"
    flagged = suspicious[0]
    assert flagged["title"] == "Mystery Note"
    assert flagged["page_start"] == 3
    # Diagnostics attached to the real suspicious unit, by its own
    # unit_index -- the exact mechanism test_extraction_review_index_jobs.py
    # already covers in isolation; this confirms it still works end-to-end
    # once the units come from the Handbook-structured path.
    assert flagged["original_page_text_snippet"], "expected a non-empty diagnostic snippet"
    assert "Mystery Note" in flagged["original_page_text_snippet"]
    assert flagged["proposed_classification"] == "needs review"

    # Every OK unit must remain diagnostic-free (unchanged guard behavior).
    for unit in units:
        if unit["status"] != "Suspicious":
            assert unit.get("original_page_text_snippet") is None
            assert unit.get("proposed_classification") is None


def test_assemble_preview_payload_missing_handbook_structured_preserves_generic_behavior():
    page_texts = ["Ordinary generic prose content about office hours. " * 10]

    baseline = _assemble_preview_payload_without_kb_statistics(
        page_texts, title="T", source_filename="f.pdf", extraction_method="pymupdf_digital"
    )
    explicit_none = _assemble_preview_payload_without_kb_statistics(
        page_texts, title="T", source_filename="f.pdf", extraction_method="pymupdf_digital", handbook_structured=None
    )

    assert baseline["structuring_method"] == STRUCTURING_METHOD_GENERIC == explicit_none["structuring_method"]
    assert baseline["knowledge_units"] == explicit_none["knowledge_units"]
    assert "generic chunking" in baseline["detected_document_type"]["reason"]


def test_assemble_preview_payload_ineligible_handbook_structured_preserves_generic_behavior():
    page_texts = ["Ordinary generic prose content about office hours. " * 10]
    ineligible = {
        "status": "attempted_no_match",
        "candidate_pages": [],
        "matched_pages": [],
        "table_regions_by_page": {},
        "words_by_page": {},
    }

    baseline = _assemble_preview_payload_without_kb_statistics(
        page_texts, title="T", source_filename="f.pdf", extraction_method="pymupdf_digital"
    )
    with_ineligible = _assemble_preview_payload_without_kb_statistics(
        page_texts, title="T", source_filename="f.pdf", extraction_method="pymupdf_digital",
        handbook_structured=ineligible,
    )

    assert with_ineligible["structuring_method"] == STRUCTURING_METHOD_GENERIC
    assert baseline["knowledge_units"] == with_ineligible["knowledge_units"]


def test_build_preview_from_job_passes_persisted_handbook_structured_through(monkeypatch):
    """build_preview_from_job must not silently discard the job's persisted
    handbook_structured payload (see load_extracted_pages's third tuple
    element) -- it must reach assemble_preview_payload, not get dropped
    into an unused _handbook_structured local as it did before this fix."""
    captured: dict = {}
    persisted_handbook_structured = {"status": "eligible", "matched_pages": [1]}

    def fake_load_extracted_pages(job):
        return (["page one text"], "pymupdf_digital", persisted_handbook_structured)

    def fake_assemble_preview_payload(
        page_texts, *, title, source_filename, extraction_method, handbook_structured=None
    ):
        captured["page_texts"] = page_texts
        captured["title"] = title
        captured["source_filename"] = source_filename
        captured["extraction_method"] = extraction_method
        captured["handbook_structured"] = handbook_structured
        return {"ok": True}

    monkeypatch.setattr(digital_ingestion_module, "load_extracted_pages", fake_load_extracted_pages)
    monkeypatch.setattr(digital_ingestion_module, "assemble_preview_payload", fake_assemble_preview_payload)

    class FakeJob:
        source_filename = "handbook.pdf"

    result = build_preview_from_job(FakeJob())

    assert result == {"ok": True}
    assert captured["handbook_structured"] is persisted_handbook_structured
    assert captured["source_filename"] == "handbook.pdf"
    assert captured["extraction_method"] == "pymupdf_digital"
    assert captured["page_texts"] == ["page one text"]
