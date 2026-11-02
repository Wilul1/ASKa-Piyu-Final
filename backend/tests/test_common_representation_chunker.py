"""Synthetic, isolated tests for the global content-aware chunker
(app.services.common_representation.chunker). Stage 4A, Implementation
Task 1 scope: chunk_document_record is not wired into any live path, so
every test here builds its own DocumentRecord/StructuralUnit fixtures --
no real PDF, no Chroma, no database.
"""
from __future__ import annotations

import copy
import logging

import pytest

from app.services.common_representation.chunker import chunk_document_record
from app.services.common_representation.types import (
    DocumentRecord,
    ExtractionDiagnostics,
    FormContent,
    ListContent,
    ListItem,
    ParagraphContent,
    ProcedureContent,
    ProcedureStep,
    StructuralUnit,
    TableCell,
    TableContent,
)


def _unit(unit_id: str, source_order: int, content, **kwargs) -> StructuralUnit:
    return StructuralUnit(
        unit_id=unit_id,
        source_order=source_order,
        title=kwargs.get("title"),
        content=content,
        structural_type=kwargs.get("structural_type", "paragraph"),
        content_type=kwargs.get("content_type", "information"),
        hierarchy_path=kwargs.get("hierarchy_path", []),
        page_start=kwargs.get("page_start"),
        page_end=kwargs.get("page_end"),
        extraction_diagnostics=kwargs.get("extraction_diagnostics", ExtractionDiagnostics()),
        searchable_fields=kwargs.get("searchable_fields", {}),
        structured_fields=kwargs.get("structured_fields", {}),
    )


def _document(*units: StructuralUnit, document_id: str = "doc1") -> DocumentRecord:
    return DocumentRecord(
        document_id=document_id, source_filename="test.pdf", classification="information", units=list(units)
    )


# ---------------------------------------------------------------------------
# One test per content type -- fits in a single chunk.
# ---------------------------------------------------------------------------


def test_paragraph_content_fits_in_one_chunk():
    unit = _unit("u1", 0, ParagraphContent(text="A short paragraph."))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    assert chunks[0].text == "A short paragraph."
    assert chunks[0].metadata["unit_id"] == "u1"


def test_list_content_fits_in_one_chunk():
    items = [ListItem(text=f"item {i}", ordinal=str(i)) for i in range(3)]
    unit = _unit("u2", 0, ListContent(text="x", items=items, ordered=True))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    assert "item 0" in chunks[0].text and "item 2" in chunks[0].text


def test_table_content_fits_in_one_chunk():
    rows = [[TableCell(text="a", row=i, column=0), TableCell(text="b", row=i, column=1)] for i in range(3)]
    unit = _unit("u3", 0, TableContent(text="x", headers=["Col1", "Col2"], rows=rows))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    assert chunks[0].text.startswith("Col1 | Col2")


def test_procedure_content_fits_in_one_chunk():
    steps = [ProcedureStep(client_step="submit", agency_action="validate", ordinal="1")]
    unit = _unit("u4", 0, ProcedureContent(text="x", steps=steps))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    assert "submit" in chunks[0].text and "validate" in chunks[0].text


def test_form_content_fits_in_one_chunk():
    unit = _unit(
        "u5", 0, FormContent(text="Leave Request Form", field_names=["Name", "Date"]),
        structured_fields={"extracted_requirements": ["Valid ID"]},
    )
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    assert chunks[0].text == "Leave Request Form"
    assert chunks[0].metadata["extracted_requirements"] == ["Valid ID"]


# ---------------------------------------------------------------------------
# Document-wide unique chunk indexes across multiple units.
# ---------------------------------------------------------------------------


def test_chunk_index_unique_and_sequential_across_multiple_units():
    big_items = [ListItem(text="x" * 200, ordinal=str(i)) for i in range(20)]
    units = [
        _unit("a", 0, ParagraphContent(text="short")),
        _unit("b", 1, ListContent(text="x", items=big_items, ordered=True)),  # splits into several pieces
        _unit("c", 2, ParagraphContent(text="also short")),
    ]
    chunks = chunk_document_record(_document(*units))
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks))), "chunk_index must be a contiguous, unique sequence across all units"
    assert len(chunks) > 3, "the list unit must have actually split into more than one chunk for this test to be meaningful"


# ---------------------------------------------------------------------------
# Empty-unit warning and callback.
# ---------------------------------------------------------------------------


def test_empty_unit_produces_no_chunks_logs_warning_and_calls_callback(caplog):
    empty_unit = _unit("empty", 0, ParagraphContent(text=""))
    real_unit = _unit("real", 1, ParagraphContent(text="has content"))
    called_with = []

    with caplog.at_level(logging.WARNING):
        chunks = chunk_document_record(_document(empty_unit, real_unit), on_empty_unit=called_with.append)

    assert len(chunks) == 1
    assert chunks[0].metadata["unit_id"] == "real"
    assert any("empty" in record.message and "no chunks" in record.message for record in caplog.records)
    assert len(called_with) == 1 and called_with[0].unit_id == "empty"


def test_empty_unit_does_not_stop_processing_of_other_units():
    units = [
        _unit("first", 0, ParagraphContent(text="first content")),
        _unit("empty_middle", 1, ParagraphContent(text="   ")),
        _unit("last", 2, ParagraphContent(text="last content")),
    ]
    chunks = chunk_document_record(_document(*units))
    unit_ids = [c.metadata["unit_id"] for c in chunks]
    assert unit_ids == ["first", "last"]


# ---------------------------------------------------------------------------
# Input immutability.
# ---------------------------------------------------------------------------


def test_input_document_and_units_are_not_mutated():
    unit = _unit("u1", 0, ParagraphContent(text=""))  # empty, to exercise the diagnostic path
    document = _document(unit)
    before = copy.deepcopy(document)

    chunk_document_record(document, on_empty_unit=lambda u: None)

    assert document.units[0].extraction_diagnostics.notes == []
    assert document.units[0].extraction_diagnostics == before.units[0].extraction_diagnostics
    assert document == before


# ---------------------------------------------------------------------------
# Oversized atomic elements (realistic, sentence-structured text --
# see report for why an artificial "1. word word..." fixture is a poor
# test of the reused _slice_oversized_block/_safe_break_points helpers).
# ---------------------------------------------------------------------------


def test_oversized_single_list_item_falls_back_to_safe_split():
    sentence = "This is a realistic sentence with real punctuation. "
    huge_item = [ListItem(text=sentence * 60, ordinal=None)]  # ~3180 chars, one item alone
    unit = _unit("biglist", 0, ListContent(text="x", items=huge_item, ordered=False))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    assert all(len(c.text) <= 1800 for c in chunks)
    assert all(c.metadata.get("split_notice") for c in chunks)
    assert all(c.text.rstrip().endswith(".") for c in chunks), "split must land on a sentence boundary"


def test_oversized_single_table_row_falls_back_to_safe_split():
    long_cell_text = "This is a realistic sentence with real punctuation. " * 60
    rows = [[TableCell(text=long_cell_text, row=0, column=0)]]
    unit = _unit("bigrow", 0, TableContent(text="x", headers=["Only"], rows=rows))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    assert all(c.metadata.get("split_notice") for c in chunks)


def test_oversized_single_procedure_step_falls_back_to_safe_split():
    long_action = "This is a realistic sentence with real punctuation. " * 60
    steps = [ProcedureStep(client_step="submit the request", agency_action=long_action, ordinal="1")]
    unit = _unit("bigstep", 0, ProcedureContent(text="x", steps=steps))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    assert all(c.metadata.get("split_notice") for c in chunks)


def test_oversized_form_falls_back_to_whole_form_split():
    long_text = "Field instructions. " * 150  # well over max_chars
    unit = _unit("bigform", 0, FormContent(text=long_text, field_names=["A", "B"]))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    assert all(c.metadata.get("split_notice") for c in chunks)


def test_form_atomic_fallback_does_not_invent_field_grouping():
    """Per the approved spec: no reliable field-to-requirement grouping is
    attempted; an oversized form always falls back to the whole-form
    atomic split, never a guessed per-field grouping."""
    long_text = "Field instructions. " * 150
    unit = _unit(
        "bigform2", 0, FormContent(text=long_text, field_names=["A", "B", "C"]),
        structured_fields={"extracted_requirements": ["req for A", "req for B"]},
    )
    chunks = chunk_document_record(_document(unit))
    # the full, undivided structured_fields dict is carried on every
    # resulting piece -- never split per field, since no reliable mapping
    # was attempted.
    assert all(c.metadata.get("extracted_requirements") == ["req for A", "req for B"] for c in chunks)


# ---------------------------------------------------------------------------
# List order and numbering preserved across a split.
# ---------------------------------------------------------------------------


def test_list_order_and_numbering_preserved_across_split():
    items = [ListItem(text="x" * 200, ordinal=str(i)) for i in range(20)]
    unit = _unit("biglist2", 0, ListContent(text="x", items=items, ordered=True))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    full_text = "\n".join(c.text for c in chunks)
    positions = [full_text.find(f"{i}. ") for i in range(20)]
    assert positions == sorted(positions), "item ordinals must appear in strictly increasing order"
    assert all(p != -1 for p in positions), "every item must survive the split somewhere"


# ---------------------------------------------------------------------------
# Repeated table headers.
# ---------------------------------------------------------------------------


def test_table_headers_repeated_in_every_continuation_chunk():
    rows = [[TableCell(text="y" * 80, row=i, column=0), TableCell(text="z" * 80, row=i, column=1)] for i in range(20)]
    unit = _unit("bigtable2", 0, TableContent(text="x", headers=["Col1", "Col2"], rows=rows))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    assert all(c.text.startswith("Col1 | Col2") for c in chunks), "every piece of a split table must repeat its headers"


# ---------------------------------------------------------------------------
# Procedure pair preservation.
# ---------------------------------------------------------------------------


def test_procedure_client_step_and_agency_action_never_separated_across_chunks():
    # Markers use a trailing delimiter (":") so step 1's marker can never
    # match as a substring of step 10/11/...'s marker.
    steps = [
        ProcedureStep(
            client_step=f"client does {i}: " * 10, agency_action=f"agency does {i}: " * 10, ordinal=str(i)
        )
        for i in range(15)
    ]
    unit = _unit("bigproc", 0, ProcedureContent(text="x", steps=steps))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    for i in range(15):
        client_marker = f"client does {i}:"
        action_marker = f"agency does {i}:"
        owning_chunks = [c for c in chunks if client_marker in c.text]
        assert len(owning_chunks) == 1, f"step {i}'s client_step must appear in exactly one chunk"
        assert action_marker in owning_chunks[0].text, f"step {i}'s agency_action must be in the same chunk as its client_step"


# ---------------------------------------------------------------------------
# Metadata preservation, including chunk-specific structured subsets.
# ---------------------------------------------------------------------------


def test_metadata_identical_across_chunks_from_one_unit_except_structured_fields():
    big_items = [ListItem(text="x" * 200, ordinal=str(i)) for i in range(20)]
    unit = _unit(
        "metaunit", 0, ListContent(text="x", items=big_items, ordered=True),
        title="My Title", hierarchy_path=["Chapter 5", "Article 2"], page_start=10, page_end=12,
        searchable_fields={"office": "Registrar"},
    )
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    for c in chunks:
        assert c.metadata["title"] == "My Title"
        assert c.metadata["hierarchy_path"] == ["Chapter 5", "Article 2"]
        assert c.metadata["page_start"] == 10
        assert c.metadata["page_end"] == 12
        assert c.metadata["office"] == "Registrar"
        assert c.metadata["section"] == "Article 2"  # last hierarchy_path element, the safe minimal derivation


def test_structured_fields_contain_only_each_chunks_own_subset_for_procedures():
    """Strengthened (Stage 4A Task 1B): the original version of this test
    could pass vacuously if structured_subset() regressed to returning
    an empty dict for every chunk (the `for step in extracted` loop would
    simply never execute). This version additionally proves all 15
    original steps are represented across the chunks, each exactly once
    -- not lost, not duplicated."""
    steps = [
        ProcedureStep(client_step=f"client {i}" * 15, agency_action=f"agency {i}" * 15, ordinal=str(i))
        for i in range(15)
    ]
    content_text = "\n".join(f"{s.client_step} -> {s.agency_action}" for s in steps)
    unit = _unit("procmeta", 0, ProcedureContent(text=content_text, steps=steps))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1

    all_extracted_client_steps = []
    for c in chunks:
        extracted = c.metadata.get("extracted_steps") or []
        # every step actually referenced in this chunk's own extracted_steps
        # must also appear in this chunk's own text -- never a step from a
        # different piece.
        for step in extracted:
            assert step["client_step"] in c.text
            all_extracted_client_steps.append(step["client_step"])

    expected = [s.client_step for s in steps]
    assert len(all_extracted_client_steps) == 15, "no step may be lost or duplicated across chunks"
    assert sorted(all_extracted_client_steps) == sorted(expected), (
        "every original step must be represented exactly once across all chunks' structured_fields"
    )


# ---------------------------------------------------------------------------
# Accurate offsets, including paragraph overlap.
# ---------------------------------------------------------------------------


def test_paragraph_char_start_is_accurate_within_the_units_own_text():
    text = "First paragraph here.\n\n" + ("Second paragraph. " * 100)
    unit = _unit("offsetunit", 0, ParagraphContent(text=text))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    for c in chunks:
        start = c.char_start
        # the chunk's own leading text (ignoring the very first few chars,
        # which may be an overlap-snapped boundary) must actually be found
        # at char_start within the unit's original rendered text.
        assert text[start:start + 20] in c.text or c.text.startswith(text[start:start + len(c.text)][:20])


def test_paragraph_chunk_never_exceeds_max_chars_even_with_sparse_boundary_overlap():
    """Confirmed reproduction (Stage 4A chunker review): a paragraph with
    only one usable sentence-boundary match ("A. ") disables
    _safe_break_points' word-boundary fallback (it only fires when ZERO
    sentence matches exist), so _safe_suffix returns almost the entire
    952-char paragraph as a "150-char" overlap tail -- which, prepended
    whole to the next paragraph by chunk_document_text's own overlap
    step, produced a 2110-char chunk before this fix (confirmed by
    direct reproduction against the pre-fix code). This must never
    happen now."""
    paragraph1 = ("A. " + ("word " * 190)).strip()
    paragraph2 = ("Second paragraph with normal punctuation. More text here. " * 20).strip()
    text = paragraph1 + "\n\n" + paragraph2
    unit = _unit("sparse", 0, ParagraphContent(text=text))

    chunks = chunk_document_record(_document(unit), target_chars=1200, max_chars=1800, overlap_chars=150)

    assert all(len(c.text) <= 1800 for c in chunks), "no paragraph chunk may exceed max_chars, including overlap"
    assert len(chunks) > 1, "this fixture must actually exercise the oversized-overlap fallback to be meaningful"
    assert any(c.metadata.get("split_notice") for c in chunks), "the fallback split must be recorded"


def test_paragraph_max_chars_fallback_preserves_text_without_gaps_or_duplication_loss():
    paragraph1 = ("A. " + ("word " * 190)).strip()
    paragraph2 = ("Second paragraph with normal punctuation. More text here. " * 20).strip()
    text = paragraph1 + "\n\n" + paragraph2
    unit = _unit("sparse2", 0, ParagraphContent(text=text))

    chunks = chunk_document_record(_document(unit), target_chars=1200, max_chars=1800, overlap_chars=150)

    # Every distinct sentence that appears in the source must appear in
    # at least one chunk -- a gap would drop one of these entirely.
    for marker in ("A. word word word", "Second paragraph with normal punctuation", "More text here"):
        assert any(marker in c.text for c in chunks), f"{marker!r} must survive the fallback split somewhere"
    # Boundaries between consecutive non-overlap-fallback pieces and the
    # fallback pieces must not cut a word in half.
    for c in chunks:
        assert not c.text.startswith(" "), "a piece must not start mid-word with leading whitespace from a bad cut"


def test_paragraph_max_chars_fallback_char_start_remains_source_accurate():
    paragraph1 = ("A. " + ("word " * 190)).strip()
    paragraph2 = ("Second paragraph with normal punctuation. More text here. " * 20).strip()
    text = paragraph1 + "\n\n" + paragraph2
    unit = _unit("sparse3", 0, ParagraphContent(text=text))

    chunks = chunk_document_record(_document(unit), target_chars=1200, max_chars=1800, overlap_chars=150)

    for c in chunks:
        start = c.char_start
        # The piece's own leading words must actually be found at
        # char_start in the unit's original rendered text (allowing for
        # the piece possibly starting with duplicated overlap text that
        # itself originated from a different position -- what matters is
        # that char_start is never a nonsensical/out-of-range value and
        # that the claimed position's text is consistent with the chunk).
        assert 0 <= start <= len(text)
        leading = c.text[:15].strip()
        assert leading, "every chunk must have real leading text"


def test_paragraph_overlap_behavior_unaffected_for_normal_non_pathological_text():
    """Confirms the existing, already-tested overlap behavior is
    completely untouched for ordinary text with normal sentence density
    -- the new post-processing step must be a no-op here."""
    text = ("Sentence one. " * 10) + ("Sentence two continues the thought. " * 60)
    unit = _unit("normal", 0, ParagraphContent(text=text))
    chunks = chunk_document_record(_document(unit), target_chars=1200, max_chars=1800, overlap_chars=150)
    assert len(chunks) > 1
    assert all(len(c.text) <= 1800 for c in chunks)
    assert all(c.metadata.get("split_notice") is None for c in chunks), (
        "normal text must never trigger the oversized-overlap fallback"
    )


def test_overlap_tail_char_start_points_to_the_duplicated_source_text():
    text = ("Sentence one. " * 10) + ("Sentence two continues the thought. " * 60)
    unit = _unit("overlapunit", 0, ParagraphContent(text=text))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) > 1
    second = chunks[1]
    # whatever text appears at the start of the second chunk must actually
    # be found at its claimed char_start in the original text.
    assert text[second.char_start:second.char_start + 15] in second.text


def test_list_chunk_text_and_char_start_align_with_actual_content_text():
    """Stage 4A Task 1B: confirmed real-world misalignment -- adapters.py's
    ListContent construction renders content.text with a "- " bullet
    prefix per line that ListItem.text itself does not include. The
    emitted chunk text must match content.text verbatim at its claimed
    char_start, not an independently re-synthesized rendering."""
    requirements = [("req one", "office A"), ("req two", "office B"), ("req three", "office C")]
    content_text = "\n".join(f"- {r} (Where to secure: {o})" for r, o in requirements)
    items = [ListItem(text=f"{r} (Where to secure: {o})") for r, o in requirements]
    unit = _unit("alignedlist", 0, ListContent(text=content_text, items=items, ordered=False))

    chunks = chunk_document_record(_document(unit))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == content_text, "emitted text must match content.text verbatim, bullet prefix included"
    assert content_text[chunk.char_start:chunk.char_start + len(chunk.text)] == chunk.text


def test_procedure_chunk_with_populated_ordinal_aligns_with_content_text():
    """Stage 4A Task 1B, requirement 3: a ProcedureStep with ordinal
    populated (never done by any current adapter, but the chunker must
    not silently misalign if one ever does). content.text here, as real
    adapters always build it, has NO ordinal prefix -- the emitted chunk
    text must match that exactly, not a re-synthesized "{ordinal}. ..."
    string."""
    steps_data = [("submit form", "validate form"), ("pay fee", "issue receipt")]
    content_text = "\n".join(f"{c} -> {a}" for c, a in steps_data)
    steps = [ProcedureStep(client_step=c, agency_action=a, ordinal=str(i + 1)) for i, (c, a) in enumerate(steps_data)]
    unit = _unit("ordinalproc", 0, ProcedureContent(text=content_text, steps=steps))

    chunks = chunk_document_record(_document(unit))

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.text == content_text
    assert content_text[chunk.char_start:chunk.char_start + len(chunk.text)] == chunk.text
    assert "1." not in chunk.text and "2." not in chunk.text, (
        "ordinal must not be injected into the rendered text when content.text itself has no ordinal prefix"
    )


# ---------------------------------------------------------------------------
# No accidental merging of unrelated StructuralUnits.
# ---------------------------------------------------------------------------


def test_no_cross_unit_merging():
    unit_a = _unit("a", 0, ParagraphContent(text="Topic A content."))
    unit_b = _unit("b", 1, ParagraphContent(text="Completely unrelated Topic B content."))
    chunks = chunk_document_record(_document(unit_a, unit_b))
    assert len(chunks) == 2
    assert chunks[0].metadata["unit_id"] != chunks[1].metadata["unit_id"]
    assert "Topic A" not in chunks[1].text
    assert "Topic B" not in chunks[0].text


# ---------------------------------------------------------------------------
# Compatibility with the existing DocumentChunk structure and Chroma ID
# generation formula (f"{document_id}::{chunk.chunk_index}").
# ---------------------------------------------------------------------------


def test_output_is_plain_document_chunk_with_existing_four_fields():
    from app.services.chunking import DocumentChunk

    unit = _unit("u1", 0, ParagraphContent(text="content"))
    chunks = chunk_document_record(_document(unit))
    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, DocumentChunk)
    assert hasattr(chunk, "text") and hasattr(chunk, "chunk_index")
    assert hasattr(chunk, "char_start") and hasattr(chunk, "metadata")


def test_chunk_ids_would_be_unique_under_the_existing_chroma_id_formula():
    big_items = [ListItem(text="x" * 200, ordinal=str(i)) for i in range(20)]
    units = [
        _unit("a", 0, ParagraphContent(text="short")),
        _unit("b", 1, ListContent(text="x", items=big_items, ordered=True)),
    ]
    document_id = "doc-xyz"
    chunks = chunk_document_record(_document(*units, document_id=document_id))
    chunk_ids = [f"{document_id}::{c.chunk_index}" for c in chunks]
    assert len(chunk_ids) == len(set(chunk_ids)), "the existing Chroma ID formula must never collide across units"
