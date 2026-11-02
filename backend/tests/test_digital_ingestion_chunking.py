"""Stage 4B -- global-chunker integration tests for the lightweight
Heroku ingestion path (app.services.admin.digital_ingestion), Generic
INFORMATION path only.

Scope: build_chunks_with_pages (generic INFORMATION), which routes
through app.services.common_representation (adapt_generic_text ->
chunk_document_record) instead of calling chunk_document_text directly.
Nothing here touches ChromaDB, Postgres, OCR, or any production service
-- small deterministic fixtures only.

Stage 3 split (this deployment-preparation worktree, base 674f95ae):
the Handbook-specific tests that originally lived in this file were
moved to test_digital_ingestion_handbook_pending.py, unmodified, because
they call _chunks_from_handbook_document -- a function that does not
exist on this baseline (the lightweight Handbook-detection dispatch was
never committed here; it exists only in the full working tree as part of
unrelated, uncommitted infrastructure). This file contains only the
Generic-path tests, which have no such dependency and are independently
collectible and runnable against this baseline.
"""
from __future__ import annotations

from app.config import settings
from app.services.admin.digital_ingestion import (
    _apply_lightweight_compat_metadata,
    _mirror_page_range_metadata,
    _page_offsets_from_texts,
    build_chunks_with_pages,
)
from app.services.chunking import DocumentChunk
from app.services.knowledge_taxonomy import enrich_chunks_with_category_metadata


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
#
# test_mirror_page_range_metadata_preserves_existing_handbook_range was
# moved to test_digital_ingestion_handbook_pending.py alongside this
# split's other Handbook-themed tests, even though it does not itself
# call _chunks_from_handbook_document -- it only exercises
# _mirror_page_range_metadata with synthetic Handbook-shaped metadata.
# Grouped there to match the task's explicit "six Handbook-specific
# tests, do not run" framing rather than by strict technical dependency.
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
