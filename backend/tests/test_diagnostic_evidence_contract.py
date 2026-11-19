"""Phase 6.7: focused tests for the three new diagnostic evidence
dimensions (completeness, placeholder provenance, evidence origin) and
their propagation through common_representation's types, the three live
adapters, the shared chunker, and chunk metadata.

Synthetic/isolated at the types/chunker level -- no real PDF, no Chroma,
no database. Charter's own placeholder-field wiring (a separate,
non-common_representation code path -- see Phase 6.5/6.7 findings) is
covered in test_knowledge_document_types.py and
test_citizen_charter_services.py instead.
"""
from __future__ import annotations

from app.services.common_representation.adapters import (
    adapt_generic_text,
    adapt_handbook_document,
    adapt_prebuilt_chunks,
)
from app.services.common_representation.chunker import chunk_document_record
from app.services.common_representation.types import (
    PLACEHOLDER_FIELDS_KEY,
    Completeness,
    DocumentRecord,
    EvidenceOrigin,
    ExtractionDiagnostics,
    ParagraphContent,
    StructuralUnit,
    TableCell,
    TableContent,
    effective_evidence_origin,
)
from app.services.chunking import DocumentChunk


def _unit(unit_id: str, content, **kwargs) -> StructuralUnit:
    return StructuralUnit(
        unit_id=unit_id,
        source_order=kwargs.get("source_order", 0),
        title=kwargs.get("title"),
        content=content,
        structural_type=kwargs.get("structural_type", "paragraph"),
        content_type=kwargs.get("content_type", "information"),
        extraction_diagnostics=kwargs.get("extraction_diagnostics", ExtractionDiagnostics()),
        evidence_origin=kwargs.get("evidence_origin"),
    )


def _document(*units: StructuralUnit) -> DocumentRecord:
    return DocumentRecord(document_id="doc1", source_filename="test.pdf", classification="information", units=list(units))


# ---------------------------------------------------------------------------
# Completeness
# ---------------------------------------------------------------------------


def test_completeness_defaults_to_unknown_not_complete():
    diag = ExtractionDiagnostics()
    assert diag.completeness == Completeness.UNKNOWN


def test_completeness_complete_extraction():
    unit = _unit("u", ParagraphContent(text="full text"), extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE))
    chunks = chunk_document_record(_document(unit))
    assert chunks[0].metadata["completeness"] == "complete"


def test_completeness_partial_extraction():
    unit = _unit("u", ParagraphContent(text="partial text"), extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.PARTIAL))
    chunks = chunk_document_record(_document(unit))
    assert chunks[0].metadata["completeness"] == "partial"


def test_completeness_unknown_extraction_is_explicit_not_silently_omitted():
    unit = _unit("u", ParagraphContent(text="text"))
    chunks = chunk_document_record(_document(unit))
    # Always present -- never silently absent, since Completeness has no
    # "not evaluated" gap distinct from UNKNOWN itself.
    assert chunks[0].metadata["completeness"] == "unknown"


def test_content_absent_in_source_is_independent_of_completeness():
    # Genuinely-absent source content: completeness can be COMPLETE (the
    # extraction process correctly determined there was nothing to find)
    # while content_absent_in_source=True records the source fact.
    unit = _unit(
        "u",
        ParagraphContent(text="No requirements section in this document."),
        extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE, content_absent_in_source=True),
    )
    chunks = chunk_document_record(_document(unit))
    assert chunks[0].metadata["completeness"] == "complete"
    assert chunks[0].metadata["content_absent_in_source"] is True


def test_content_absent_in_source_unestablished_is_omitted_not_false():
    unit = _unit("u", ParagraphContent(text="text"))
    chunks = chunk_document_record(_document(unit))
    assert "content_absent_in_source" not in chunks[0].metadata


def test_unreadable_page_is_unknown_completeness_not_silently_complete():
    # An unreadable page produces no content at all -- it must never reach
    # chunk_document_record claiming completeness=complete merely because
    # "no content was extracted" trivially satisfies some naive check.
    # (This test documents the required caller-side behavior: a producer
    # facing an unreadable page must set UNKNOWN/PARTIAL explicitly, since
    # the type itself defaults to UNKNOWN and never auto-upgrades.)
    diag = ExtractionDiagnostics(page_info_unavailable=True)
    assert diag.completeness == Completeness.UNKNOWN


def test_one_units_completeness_does_not_contaminate_a_sibling_unit():
    partial = _unit("u1", ParagraphContent(text="partial"), source_order=0, extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.PARTIAL))
    complete = _unit("u2", ParagraphContent(text="complete"), source_order=1, extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE))
    chunks = chunk_document_record(_document(partial, complete))
    by_unit = {c.metadata["unit_id"]: c for c in chunks}
    assert by_unit["u1"].metadata["completeness"] == "partial"
    assert by_unit["u2"].metadata["completeness"] == "complete"


# ---------------------------------------------------------------------------
# Evidence origin
# ---------------------------------------------------------------------------


def test_effective_evidence_origin_cell_overrides_unit_fallback():
    assert effective_evidence_origin(EvidenceOrigin.LAYOUT_RECONSTRUCTED, EvidenceOrigin.VERBATIM_SOURCE) == EvidenceOrigin.LAYOUT_RECONSTRUCTED


def test_effective_evidence_origin_falls_back_to_unit_when_cell_unset():
    assert effective_evidence_origin(None, EvidenceOrigin.VERBATIM_SOURCE) == EvidenceOrigin.VERBATIM_SOURCE


def test_effective_evidence_origin_unclassified_when_neither_set():
    assert effective_evidence_origin(None, None) is None


def test_verbatim_paragraph_origin_propagates_to_metadata():
    unit = _unit("u", ParagraphContent(text="text"), evidence_origin=EvidenceOrigin.VERBATIM_SOURCE)
    chunks = chunk_document_record(_document(unit))
    assert chunks[0].metadata["evidence_origin"] == "verbatim_source"


def test_model_inferred_origin_propagates_to_metadata():
    unit = _unit("u", ParagraphContent(text="an ai-written summary"), evidence_origin=EvidenceOrigin.MODEL_INFERRED)
    chunks = chunk_document_record(_document(unit))
    assert chunks[0].metadata["evidence_origin"] == "model_inferred"


def test_missing_content_origin_is_a_real_value_not_an_absence():
    unit = _unit("u", ParagraphContent(text=""), evidence_origin=EvidenceOrigin.MISSING)
    # (empty text means no chunk is produced -- assert on the dataclass
    # directly, since chunk_document_record skips empty units entirely.)
    assert unit.evidence_origin == EvidenceOrigin.MISSING


def test_legacy_unit_with_unset_origin_stays_unclassified_not_verbatim():
    unit = _unit("u", ParagraphContent(text="pre-existing content, no provenance recorded"))
    chunks = chunk_document_record(_document(unit))
    assert "evidence_origin" not in chunks[0].metadata


def test_mixed_origin_table_preserves_per_cell_distinctions():
    rows = [
        [TableCell(text="LSPU", row=0, column=0, evidence_origin=EvidenceOrigin.VERBATIM_SOURCE),
         TableCell(text="18 minutes", row=0, column=1, evidence_origin=EvidenceOrigin.LAYOUT_RECONSTRUCTED)],
        [TableCell(text="Other agencies", row=1, column=0),  # unset -- unclassified
         TableCell(text="15 days", row=1, column=1, evidence_origin=EvidenceOrigin.MISSING)],
    ]
    unit = _unit(
        "t", TableContent(text="x", headers=["Agency", "Time"], rows=rows),
        structural_type="table", evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
    )
    chunks = chunk_document_record(_document(unit))
    origins = chunks[0].metadata["__cell_evidence_origin"]
    assert {"row": 0, "column": 0, "evidence_origin": "verbatim_source"} in origins
    assert {"row": 0, "column": 1, "evidence_origin": "layout_reconstructed"} in origins
    assert {"row": 1, "column": 1, "evidence_origin": "missing"} in origins
    # Row 1 col 0 was never classified -- must not appear as a false entry.
    assert not any(o["row"] == 1 and o["column"] == 0 for o in origins)
    # Table-level unit fallback still present alongside the cell-level data.
    assert chunks[0].metadata["evidence_origin"] == "verbatim_source"


def test_table_cell_more_specific_origin_not_overwritten_by_unit_fallback():
    rows = [[TableCell(text="x", row=0, column=0, evidence_origin=EvidenceOrigin.MODEL_INFERRED)]]
    unit = _unit("t", TableContent(text="x", rows=rows), structural_type="table", evidence_origin=EvidenceOrigin.VERBATIM_SOURCE)
    chunks = chunk_document_record(_document(unit))
    origins = chunks[0].metadata["__cell_evidence_origin"]
    assert origins == [{"row": 0, "column": 0, "evidence_origin": "model_inferred"}]
    # The unit-level fallback is reported separately, not used to overwrite the cell's own value.
    assert chunks[0].metadata["evidence_origin"] == "verbatim_source"


def test_splitting_oversized_table_preserves_each_pieces_own_cell_evidence():
    big_rows = []
    for i in range(400):
        origin = EvidenceOrigin.LAYOUT_RECONSTRUCTED if i < 5 else None
        big_rows.append([TableCell(text=f"row {i} with enough padding text to force a split boundary", row=i, column=0, evidence_origin=origin)])
    unit = _unit("t", TableContent(text="x", rows=big_rows), structural_type="table")
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    # Only the first piece(s) containing rows 0-4 should carry evidence; a
    # later piece containing only unclassified rows must carry none.
    any_with_evidence = [c for c in chunks if c.metadata.get("__cell_evidence_origin")]
    any_without = [c for c in chunks if not c.metadata.get("__cell_evidence_origin")]
    assert any_with_evidence and any_without


# ---------------------------------------------------------------------------
# Adapter propagation -- the three live adapters explicitly assign
# VERBATIM_SOURCE (genuinely known: deterministic extracted text, no model
# inference anywhere in these paths).
# ---------------------------------------------------------------------------


def test_adapt_generic_text_assigns_verbatim_source():
    record = adapt_generic_text("raw extracted text", document_id="d", source_filename="f.pdf")
    assert record.units[0].evidence_origin == EvidenceOrigin.VERBATIM_SOURCE


def test_adapt_prebuilt_chunks_assigns_verbatim_source():
    chunks = [DocumentChunk(text="x", chunk_index=0, char_start=0, metadata={"title": "t"})]
    record = adapt_prebuilt_chunks(chunks, document_id="d", source_filename="f.pdf", classification="procedure")
    assert record.units[0].evidence_origin == EvidenceOrigin.VERBATIM_SOURCE


def test_adapt_handbook_document_assigns_verbatim_source():
    from app.services.handbook_policy_processor import HandbookKnowledgeUnit, HandbookPolicyDocument

    doc = HandbookPolicyDocument(
        document_type="handbook_policy",
        source_title="Handbook",
        doc_no=None,
        cleaned_text="x",
        raw_text="x",
        units=[HandbookKnowledgeUnit(title="Art. 1", content="Body text.", raw_text="Art. 1\nBody text.", metadata={})],
    )
    record = adapt_handbook_document(doc, document_id="d")
    assert record.units[0].evidence_origin == EvidenceOrigin.VERBATIM_SOURCE


# ---------------------------------------------------------------------------
# Placeholder-field convention (types-level; Charter's real generation-point
# wiring is tested separately in test_knowledge_document_types.py /
# test_citizen_charter_services.py)
# ---------------------------------------------------------------------------


def test_placeholder_fields_key_constant_is_the_documented_dunder_name():
    assert PLACEHOLDER_FIELDS_KEY == "__placeholder_fields"


def test_structured_fields_placeholder_convention_is_additive_and_optional():
    unit = StructuralUnit(
        unit_id="u", source_order=0, title=None, content=ParagraphContent(text="x"),
        structural_type="paragraph", content_type="information",
        structured_fields={"office": "Registrar", PLACEHOLDER_FIELDS_KEY: ["who_may_avail"]},
    )
    assert unit.structured_fields[PLACEHOLDER_FIELDS_KEY] == ["who_may_avail"]
    # A unit that never populates it is unaffected -- absence, not a false "no placeholders" claim.
    other = StructuralUnit(unit_id="u2", source_order=0, title=None, content=ParagraphContent(text="x"), structural_type="paragraph", content_type="information")
    assert PLACEHOLDER_FIELDS_KEY not in other.structured_fields


# ---------------------------------------------------------------------------
# Existing metadata fields remain unchanged (regression anchor alongside
# the full existing suites run separately).
# ---------------------------------------------------------------------------


def test_existing_metadata_fields_unaffected_by_new_fields():
    unit = _unit(
        "u", ParagraphContent(text="text"), title="My Title", source_order=0,
        extraction_diagnostics=ExtractionDiagnostics(completeness=Completeness.COMPLETE),
        evidence_origin=EvidenceOrigin.VERBATIM_SOURCE,
    )
    chunks = chunk_document_record(_document(unit))
    m = chunks[0].metadata
    assert m["unit_id"] == "u"
    assert m["title"] == "My Title"
    assert m["content_type"] == "information"
    assert m["structural_type"] == "paragraph"
    assert m["completeness"] == "complete"
    assert m["evidence_origin"] == "verbatim_source"
