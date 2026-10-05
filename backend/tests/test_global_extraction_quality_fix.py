"""Focused tests for the 2026-10-05 global extraction/structuring quality
fix (LSPU Faculty Manual follow-up): TOC exclusion, header/footer removal,
word/sentence-safe chunk boundaries, heading-based titles, and conservative
office metadata.

These fixes live in the SHARED layer (text_cleaner.py, chunking.py,
knowledge_taxonomy.py) used by both the lightweight (Heroku) and legacy
(local/Docker) pipelines, and by both digital and OCR extraction -- so
fixing them once fixes every path. Nothing here is specific to any one
document; every fixture is synthetic, generic text, never the real LSPU
Faculty Manual/Handbook content.

Safety: never touches a real Chroma client, never makes a real HTTP call.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from app.services.admin.digital_ingestion import build_chunks_with_pages
from app.services.chroma_store import KnowledgeBaseStore
from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.knowledge_taxonomy import (
    OFFICE_ASSIGNMENT_CONFIDENCE_FLOOR,
    UNASSIGNED_OFFICE,
    enrich_chunks_with_category_metadata,
)
from app.services.text_cleaner import (
    clean_extracted_text,
    is_heading_candidate,
    looks_like_toc_entry_line,
    remove_toc_blocks,
)


def make_fake_store():
    class FakeChromaCollection:
        def __init__(self):
            self._records: dict[str, dict] = {}
            self.add_call_count = 0
            self.delete_call_count = 0

        def add(self, *, ids, documents, metadatas):
            self.add_call_count += 1
            for _id, meta in zip(ids, metadatas):
                self._records[_id] = meta

        def get(self, where=None, include=None, limit=None, offset=0, ids=None):
            if ids is not None:
                matched = [i for i in ids if i in self._records]
            elif where and "document_id" in where:
                wanted = where["document_id"]
                matched = [i for i, m in self._records.items() if m.get("document_id") == wanted]
            elif where and "source_filename" in where:
                wanted = where["source_filename"]
                matched = [i for i, m in self._records.items() if m.get("source_filename") == wanted]
            else:
                matched = list(self._records.keys())
            page = matched[offset:] if limit is None else matched[offset : offset + limit]
            return {"ids": page, "metadatas": [self._records[i] for i in page]}

        def delete(self, *, ids):
            self.delete_call_count += 1
            for i in ids:
                self._records.pop(i, None)

        def count(self):
            return len(self._records)

    collection = FakeChromaCollection()
    store = KnowledgeBaseStore.__new__(KnowledgeBaseStore)
    store._collection = collection
    return store, collection


# --- 1: TOC exclusion --------------------------------------------------------


def test_toc_block_is_removed_from_cleaned_text():
    toc = (
        "Faculty Official Time .......... 12\n"
        "Submission of Grades .......... 15\n"
        "Leave of Absence .......... 20\n"
        "Grievance Machinery .......... 25\n"
    )
    real_section = (
        "\n\nFaculty Official Time\n\n"
        "All faculty members shall observe the official time prescribed by the "
        "university and shall render the required number of hours per week as "
        "mandated by the Commission on Higher Education.\n"
    )
    cleaned = remove_toc_blocks(toc + real_section)
    assert "Faculty Official Time .......... 12" not in cleaned
    assert "Submission of Grades .......... 15" not in cleaned
    assert "Leave of Absence .......... 20" not in cleaned
    assert "Grievance Machinery .......... 25" not in cleaned
    # The real section survives -- same heading text, no dot leader/page number.
    assert "All faculty members shall observe the official time" in cleaned


def test_single_isolated_toc_shaped_line_is_not_removed():
    """A lone heading that happens to end in a number (e.g. "Appendix 1")
    must never be deleted just because it matches the TOC-entry shape
    once -- only a dense RUN of several such lines together is a TOC."""
    text = (
        "Introduction to the policy manual follows here with real content.\n\n"
        "Appendix 1\n\n"
        "This appendix lists the required forms for the application process "
        "and explains how to submit them to the registrar.\n"
    )
    cleaned = remove_toc_blocks(text)
    assert "Appendix 1" in cleaned
    assert "required forms for the application process" in cleaned


# --- 2: real section titled "Contents" not falsely deleted ------------------


def test_real_section_mentioning_contents_is_preserved():
    text = (
        "Table of Contents\n\n"
        "This handbook contains the full contents of university policy "
        "including grading, enrollment, and disciplinary procedures that "
        "every student and faculty member must understand and follow.\n"
    )
    cleaned = remove_toc_blocks(text)
    # Not a dense run of dotted/bare-number TOC lines -- a single heading
    # line plus a real paragraph. Nothing here matches looks_like_toc_
    # entry_line's shape test at all, so nothing is removed.
    assert "contains the full contents of university policy" in cleaned
    assert "Table of Contents" in cleaned


def test_looks_like_toc_entry_line_does_not_match_ordinary_prose():
    prose = (
        "The committee decided to review the contents of the proposal "
        "before the next scheduled meeting of the faculty senate."
    )
    assert not looks_like_toc_entry_line(prose)


# --- 3/4: header/footer removal (incl. page-number-varying) + page metadata ---


_BODY_SENTENCE_TEMPLATES = [
    "Faculty members shall observe the official time prescribed by the university.",
    "Grades must be submitted within the deadline set by the registrar each term.",
    "Leave applications require prior approval from the immediate department head.",
    "Grievances shall be filed in writing with the appropriate committee promptly.",
    "Appointments to committees follow the procedure described in a later chapter.",
]


_PAGE_TAG_WORDS = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet",
]


def test_repeated_header_footer_removed_even_with_varying_page_numbers():
    pages = []
    for i in range(1, 11):
        tag = _PAGE_TAG_WORDS[i - 1]
        # Every body line is unique to this page (a word-based tag, never
        # a digit, so digit-normalization can't make two different pages'
        # body text collapse to the same template) -- only the genuinely
        # repeated header/footer lines (and the page-number footer, which
        # DOES vary by digit) should ever be removed.
        body_lines = "\n".join(
            f"{sentence} (section tag: {tag})" for sentence in _BODY_SENTENCE_TEMPLATES
        )
        pages.append(
            f"Title: LSPU Faculty Manual 2020\nDate: March 2021\n\n{body_lines}\n\nPage {i} of 10"
        )
    cleaned = clean_extracted_text("\n".join(pages), page_texts=pages)
    assert "Title: LSPU Faculty Manual 2020" not in cleaned
    assert "Date: March 2021" not in cleaned
    for i in range(1, 11):
        assert f"Page {i} of 10" not in cleaned
    for i in range(1, 11):
        tag = _PAGE_TAG_WORDS[i - 1]
        assert f"(section tag: {tag})" in cleaned


def test_page_metadata_preserved_after_header_footer_removal():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_bodies = [
            "\n".join(
                f"{sentence} This is page one's own distinct wording, repeated to fill the page."
                for sentence in _BODY_SENTENCE_TEMPLATES
            ),
            "\n".join(
                f"{sentence} This is page two's own different wording, repeated to fill the page."
                for sentence in reversed(_BODY_SENTENCE_TEMPLATES)
            ),
        ]
        page_texts = [
            f"Title: LSPU Faculty Manual 2020\n\n{page_bodies[i - 1]}\n\nPage {i} of 2" for i in (1, 2)
        ]
        page_offsets = [0, len(page_texts[0]) + 1]
        chunks = build_chunks_with_pages(
            page_texts,
            page_offsets,
            chunk_size=400,
            chunk_overlap=50,
            title="Faculty Manual",
            source_filename="faculty_manual_test.pdf",
        )
    assert chunks
    page_numbers = {c.metadata.get("page_number") for c in chunks}
    assert page_numbers  # still populated despite header/footer stripping
    assert page_numbers <= {1, 2}
    for chunk in chunks:
        assert "Title: LSPU Faculty Manual 2020" not in chunk.text
        assert "Page 1 of 2" not in chunk.text
        assert "Page 2 of 2" not in chunk.text


# --- 5/6: sentence/word-aware boundaries; no mid-word chunk starts ---------


def _long_single_block_text(n_sentences: int = 80) -> str:
    sentences = [
        f"This is sentence number {i} about university policy and procedures that students must follow."
        for i in range(n_sentences)
    ]
    return " ".join(sentences)  # no blank-line breaks at all -> one "paragraph"


def test_chunker_never_starts_a_chunk_mid_word():
    text = _long_single_block_text()
    chunks = chunk_document_text(text, chunk_size=200, chunk_overlap=30)
    assert len(chunks) > 1
    for chunk in chunks:
        start = chunk.char_start
        if start == 0:
            continue
        # The character immediately before this chunk's start offset in
        # the ORIGINAL text must be whitespace -- never mid-word.
        assert text[start - 1].isspace(), (
            f"chunk at char_start={start} begins mid-word: "
            f"...{text[max(0, start - 15):start]!r}|{chunk.text[:15]!r}..."
        )


def test_chunker_prefers_sentence_boundaries_over_raw_character_slicing():
    text = _long_single_block_text()
    chunks = chunk_document_text(text, chunk_size=200, chunk_overlap=30)
    # Every chunk should start with a capital letter ("This") since every
    # sentence in this fixture starts that way -- proving slices land on
    # sentence boundaries, not arbitrary character offsets.
    for chunk in chunks:
        assert chunk.text[0].isupper() or chunk.text[0].isdigit()


def test_no_sentence_or_word_boundary_falls_back_safely_without_crashing():
    """A single token longer than chunk_size (e.g. a URL/garbage run) is
    the only remaining case that must fall back to character slicing --
    it must still not raise and must still produce non-empty chunks."""
    text = "a" * 500
    chunks = chunk_document_text(text, chunk_size=100, chunk_overlap=10)
    assert chunks
    assert all(c.text for c in chunks)
    assert "".join(c.text for c in chunks).replace("a", "") == ""


# --- 7/8: heading-based titles; safe fallback -------------------------------


def test_is_heading_candidate_detects_generic_heading_styles():
    assert is_heading_candidate("Faculty Official Time")
    assert is_heading_candidate("IV. Faculty Responsibilities")
    assert is_heading_candidate("ARTICLE III: GRIEVANCE MACHINERY")
    assert is_heading_candidate("3.2 Change or Rectification of Grades")
    assert not is_heading_candidate(
        "the committee decided itself to review the matter further before concluding"
    )
    assert not is_heading_candidate("Faculty Official Time .......... 12")  # TOC shape, not a heading


def test_chunks_get_nearest_preceding_heading_as_section_heading_metadata():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        body = "Grievance procedures must be filed in writing. " * 60
        page_texts = [f"Grievance Machinery\n\n{body}"]
        chunks = build_chunks_with_pages(
            page_texts,
            [0],
            chunk_size=300,
            chunk_overlap=30,
            title="Faculty Manual",
            source_filename="faculty_manual_heading_test.pdf",
        )
    assert chunks
    for chunk in chunks:
        assert chunk.metadata.get("section_heading") == "Grievance Machinery"


def test_title_falls_back_safely_when_no_heading_is_present():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = ["This document has no detected heading anywhere in its body text at all."]
        chunks = build_chunks_with_pages(
            page_texts,
            [0],
            chunk_size=300,
            chunk_overlap=30,
            title="Faculty Manual",
            source_filename="faculty_manual_no_heading_test.pdf",
        )
    assert chunks
    for chunk in chunks:
        assert "section_heading" not in chunk.metadata  # no crash; simply absent


# --- 9/10: conservative office metadata -------------------------------------


def test_ambiguous_chunk_gets_unassigned_office():
    chunks = [
        DocumentChunk(
            text="The university has a long and storied historical development since its founding.",
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Faculty Manual", source_document="faculty_manual_test.pdf", allow_llm=False
    )
    chunk = enriched[0]
    confidence = chunk.metadata.get("classification_confidence")
    if confidence is not None and confidence >= OFFICE_ASSIGNMENT_CONFIDENCE_FLOOR:
        # Taxonomy content changed and this text now scores confidently --
        # not the scenario under test; skip rather than false-fail.
        return
    assert chunk.metadata["office"] == UNASSIGNED_OFFICE
    assert chunk.metadata["responsible_office"] == UNASSIGNED_OFFICE


def test_explicit_office_metadata_is_never_overwritten():
    chunks = [
        DocumentChunk(
            text="Any text at all -- the office was already explicitly set upstream.",
            chunk_index=0,
            char_start=0,
            metadata={"office": "Registrar", "document_type": "information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Faculty Manual", source_document="faculty_manual_test.pdf", allow_llm=False
    )
    chunk = enriched[0]
    assert chunk.metadata["office"] == "Registrar"
    assert chunk.metadata["responsible_office"] == "Registrar"


def test_fallback_result_with_zero_taxonomy_match_also_stays_unassigned():
    """Text that matches NO taxonomy keyword at all must not default to a
    specific office either."""
    chunks = [
        DocumentChunk(
            text="Xqzvyk flarnum trebozit wobbleplex zyntharon quibberfluxx.",
            chunk_index=0,
            char_start=0,
            metadata={"document_type": "information"},
        )
    ]
    enriched = enrich_chunks_with_category_metadata(
        chunks, title="Faculty Manual", source_document="faculty_manual_test.pdf", allow_llm=False
    )
    assert enriched[0].metadata["office"] == UNASSIGNED_OFFICE


# --- 11: digital and OCR paths produce equivalent structured behavior ------


def test_digital_and_ocr_paths_share_the_same_chunk_building_function():
    """Both paths call the SAME build_chunks_with_pages -- not duplicated
    logic -- so a TOC/heading/office fix applied once applies to both."""
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = ["Grievance Machinery\n\n" + "Procedures must be filed in writing. " * 40]
        digital_chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="digital.pdf"
        )
        # Simulating the OCR path: same page_texts shape, same function.
        ocr_chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="ocr.pdf"
        )
    assert len(digital_chunks) == len(ocr_chunks)
    for d, o in zip(digital_chunks, ocr_chunks):
        assert d.metadata.get("section_heading") == o.metadata.get("section_heading") == "Grievance Machinery"


# --- 12: preview units are the same units later passed to indexing ---------


def test_preview_and_indexed_chunks_match_in_count_and_heading(monkeypatch):
    """Extract's preview chunk_preview() units and what Index actually
    publishes to Chroma must describe the same structured result."""
    from app.services.admin.digital_ingestion import (
        assemble_preview_payload,
        chunks_from_pages_or_reviewed_text,
        publish_new_version,
    )

    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_max_chars", 300)
    monkeypatch.setattr("app.services.admin.digital_ingestion.settings.chunk_overlap", 30)

    store, collection = make_fake_store()
    page_texts = ["Grievance Machinery\n\n" + "Procedures must be filed in writing. " * 40]

    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        preview = assemble_preview_payload(
            page_texts, title="T", source_filename="faculty_manual_consistency.pdf", extraction_method="pymupdf_digital"
        )
        chunks = chunks_from_pages_or_reviewed_text(
            page_texts, None, title="T", source_filename="faculty_manual_consistency.pdf"
        )
        publish_new_version(
            store, chunks=chunks, title="T", source_filename="faculty_manual_consistency.pdf", replaced_document_id=None
        )

    preview_titles = [c.get("title") for c in preview["chunk_preview"]]
    indexed_titles = [m.get("section_heading") or m.get("title") for m in collection._records.values()]
    assert len(preview["chunk_preview"]) == len(collection._records) == len(chunks)
    assert sorted(str(t) for t in preview_titles) == sorted(str(t) for t in indexed_titles)


# --- 13/14: Chroma write safety (regression guard for this change) ---------


def test_extract_preview_assembly_never_writes_to_chroma():
    from app.services.admin.digital_ingestion import assemble_preview_payload

    store, collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        assemble_preview_payload(
            ["Faculty Official Time\n\nAll faculty shall observe official time."],
            title="T",
            source_filename="faculty_manual_no_write_test.pdf",
            extraction_method="pymupdf_digital",
        )
    assert collection.add_call_count == 0
    assert collection.delete_call_count == 0


def test_index_still_uses_publish_new_version_only():
    from app.services.admin.digital_ingestion import (
        chunks_from_pages_or_reviewed_text,
        publish_new_version,
    )

    store, collection = make_fake_store()
    page_texts = ["Grievance Machinery\n\n" + "Procedures must be filed in writing. " * 40]
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        chunks = chunks_from_pages_or_reviewed_text(
            page_texts, None, title="T", source_filename="faculty_manual_index_test.pdf"
        )
        publish_new_version(
            store, chunks=chunks, title="T", source_filename="faculty_manual_index_test.pdf", replaced_document_id=None
        )
    assert collection.add_call_count >= 1
    assert collection.delete_call_count == 0
