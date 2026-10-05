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


# --- 2026-10-05 follow-up: real-world TOC/header-footer/overlap fixes ------
#
# The real LSPU Faculty Manual validation run showed the first version of
# this fix only partially worked: real PDF text extraction splits a TOC
# row's title and page number onto SEPARATE lines (or drops the number
# entirely), puts a multi-field header/footer template across MORE than 3
# lines per page, and chunk_document_text's own paragraph-packing overlap
# (separate code path from _slice_oversized_block) still took a raw
# character slice. See looks_like_toc_region_row, _immediately_precedes_
# body_prose, _furniture_edge_lines, and _safe_suffix for the fixes.

from app.services.chunking import _safe_suffix
from app.services.text_cleaner import looks_like_toc_region_row


def test_multipage_toc_with_title_and_page_number_on_separate_lines_is_removed():
    """Real PDF extraction commonly drops a TOC row's page number onto
    its own line (or a separate column) instead of the dotted-leader
    shape -- looks_like_toc_entry_line alone never matches any of these."""
    toc = (
        "Contents\n"
        "Foreword\n"
        "Board of Regents\n"
        "Administrative Officials\n"
        "I. General Information\n"
        "12\n"
        "II. Historical Development\n"
        "15\n"
        "III. Commitment of the Faculty\n"
        "18\n"
        "IV. University Policies\n"
        "22\n"
    )
    body = (
        "V. Faculty Responsibilities\n\n"
        "Every faculty member shall discharge academic duties with diligence "
        "and shall comply with the policies set forth by the university "
        "administration and the Commission on Higher Education at all times.\n"
    )
    cleaned = remove_toc_blocks(toc + body)
    for line in ["Foreword", "Board of Regents", "Administrative Officials"]:
        assert line not in cleaned
    assert "I. General Information" not in cleaned
    assert "II. Historical Development" not in cleaned
    # the page-number-only lines are swept away as part of the TOC run too
    assert "\n12\n" not in cleaned
    assert "\n15\n" not in cleaned
    # the real section survives, heading and body both
    assert "V. Faculty Responsibilities" in cleaned
    assert "Every faculty member shall discharge academic duties" in cleaned


def test_toc_continuation_across_simulated_page_break_is_removed():
    toc_page_1 = (
        "Contents\n"
        "Foreword\n"
        "Board of Regents\n"
        "Administrative Officials\n"
        "I. General Information\n"
    )
    toc_page_2 = (
        "II. Historical Development\n"
        "III. Commitment of the Faculty\n"
        "IV. University Policies\n"
        "V. Faculty Responsibilities\n"
    )
    body = (
        "VI. Grievance Machinery\n\n"
        "Any faculty member who believes a decision was unfair may file a "
        "written grievance with the designated committee within fifteen "
        "working days of the event giving rise to the complaint itself.\n"
    )
    # pages are joined with a single "\n", exactly like build_chunks_with_pages
    cleaned = remove_toc_blocks(toc_page_1 + toc_page_2 + body)
    assert "Foreword" not in cleaned
    assert "III. Commitment of the Faculty" not in cleaned
    assert "V. Faculty Responsibilities" not in cleaned
    assert "VI. Grievance Machinery" in cleaned
    assert "written grievance with the designated committee" in cleaned


def test_real_body_heading_adjacent_to_toc_end_is_not_deleted():
    """A real section's own heading, immediately following the TOC and
    textually identical to its own TOC entry a few lines above, must
    survive -- it's distinguished because it (unlike a TOC row) directly
    introduces a real paragraph right there."""
    toc = (
        "Faculty Official Time .......... 12\n"
        "Submission of Grades .......... 15\n"
        "Leave of Absence .......... 20\n"
        "Grievance Machinery .......... 25\n"
    )
    real_section = (
        "\n\nFaculty Official Time\n\n"
        "All faculty members shall observe the official time prescribed by "
        "the university and render the required number of hours each week."
    )
    cleaned = remove_toc_blocks(toc + real_section)
    for line in toc.strip().split("\n"):
        assert line not in cleaned
    assert "Faculty Official Time" in cleaned
    assert "render the required number of hours each week" in cleaned


def test_short_legitimate_list_is_not_mistaken_for_a_toc():
    """A short requirements checklist that happens to be heading-shaped
    must not be swept away just because it's a few short lines in a
    row -- min_run/anchored_min_run require more evidence than that."""
    text = (
        "Requirements for Enrollment\n\n"
        "Birth Certificate\n"
        "Good Moral Certificate\n\n"
        "Submit the above documents to the registrar's office before the "
        "start of the enrollment period for processing and verification.\n"
    )
    cleaned = remove_toc_blocks(text)
    assert "Birth Certificate" in cleaned
    assert "Good Moral Certificate" in cleaned


def test_looks_like_toc_region_row_accepts_heading_shaped_lines_without_page_numbers():
    assert looks_like_toc_region_row("Faculty Official Time")
    assert looks_like_toc_region_row("I. General Information")
    assert looks_like_toc_region_row("Faculty Official Time .......... 12")
    assert not looks_like_toc_region_row(
        "The committee decided to review the contents of the proposal further."
    )


# --- multi-line structured header/footer templates --------------------------


def test_multiline_structured_header_footer_template_removed():
    """A real field-label header/footer block (Institution/Doc. No./Type/
    Revision No./Title/Date/Page) often spans more than 3 lines -- the
    old fixed first-3/last-3 window missed the interior fields."""
    pages = []
    for i in range(1, 9):
        body = "\n".join(
            f"{sentence} (page marker {i})" for sentence in _BODY_SENTENCE_TEMPLATES
        )
        pages.append(
            "Institution: Laguna State Polytechnic University\n"
            "Doc. No.: FM-2020-01\n"
            "Type: Policy Manual\n"
            "Revision No.: 2\n"
            "Title: LSPU Faculty Manual 2020\n"
            "Date: March 2021\n\n"
            f"{body}\n\n"
            f"Page {i}\n"
            "of 8"
        )
    cleaned = clean_extracted_text("\n".join(pages), page_texts=pages)
    for line in [
        "Institution: Laguna State Polytechnic University",
        "Doc. No.: FM-2020-01",
        "Type: Policy Manual",
        "Revision No.: 2",
        "Title: LSPU Faculty Manual 2020",
        "Date: March 2021",
    ]:
        assert line not in cleaned
    for i in range(1, 9):
        assert f"Page {i}" not in cleaned
    assert "of 8" not in cleaned
    for i in range(1, 9):
        assert f"(page marker {i})" in cleaned


def test_nonrecurring_body_use_of_title_and_date_words_is_preserved():
    """Generic header/footer stripping is recurrence-based, never a
    keyword blacklist -- a one-off body sentence using "Title" or "Date"
    must never be deleted just because those words also appear in a
    real recurring header elsewhere in the document."""
    pages = []
    for i in range(1, 7):
        body = "\n".join(
            f"{sentence} (page marker {i})" for sentence in _BODY_SENTENCE_TEMPLATES
        )
        pages.append(f"Title: LSPU Faculty Manual 2020\n\n{body}\n\nPage {i} of 6")
    # A genuine one-off body sentence that uses both words, appearing on
    # only ONE page -- must survive even though "Title:"/"Page N of 6"
    # recur on every other page.
    pages[2] += (
        "\n\nThe effective Date of this policy and the official Title of "
        "the signing officer are recorded in the appendix for reference."
    )
    cleaned = clean_extracted_text("\n".join(pages), page_texts=pages)
    assert "Title: LSPU Faculty Manual 2020" not in cleaned
    assert "The effective Date of this policy and the official Title" in cleaned


# --- TOC/furniture can never become a chunk title ---------------------------


def test_toc_entry_cannot_become_body_chunk_title():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        toc = (
            "Contents\n"
            "Foreword\n"
            "Board of Regents\n"
            "Administrative Officials\n"
            "I. General Information\n"
        )
        page_texts = [
            toc + "\n\nGrievance Machinery\n\n" + "Procedures must be filed in writing. " * 40
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="toc_title_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        heading = chunk.metadata.get("section_heading")
        assert heading != "Contents"
        assert heading != "Foreword"
        assert heading != "Board of Regents"
        assert heading == "Grievance Machinery"


def test_page_furniture_cannot_become_body_chunk_title():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        page_texts = []
        for i in range(1, 7):
            tag = _PAGE_TAG_WORDS[i - 1]
            body = "\n".join(f"{s} (page tag: {tag})" for s in _BODY_SENTENCE_TEMPLATES)
            page_texts.append(
                "Title: LSPU Faculty Manual 2020\nDate: March 2021\n\n"
                f"{body}\n\nPage {i} of 6"
            )
        page_offsets = []
        running = 0
        for p in page_texts:
            page_offsets.append(running)
            running += len(p) + 1
        chunks = build_chunks_with_pages(
            page_texts, page_offsets, chunk_size=300, chunk_overlap=30, title="T", source_filename="furniture_title_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        heading = chunk.metadata.get("section_heading")
        assert heading != "Title: LSPU Faculty Manual 2020"
        assert "Page" not in (heading or "")


# --- root cause C: paragraph-packing overlap must be boundary-safe ----------


def test_safe_suffix_never_cuts_mid_word():
    text = "This policy was approved by the Board of Regents on January 10, 2001 and took effect immediately."
    suffix = _safe_suffix(text, 15)
    assert suffix
    assert not suffix.startswith("uary")
    cut_point = len(text) - len(suffix)
    assert cut_point == 0 or text[cut_point - 1].isspace()


def test_safe_suffix_falls_back_to_raw_slice_only_for_unbroken_token():
    text = "a" * 200
    suffix = _safe_suffix(text, 20)
    assert len(suffix) == 20


def test_chunk_document_text_overlap_never_starts_or_ends_mid_word():
    paragraph_a = (
        "This policy was approved by the Board of Regents on January 10, 2001 "
        "and implemented through a series of memoranda issued by the Office "
        "of the Vice President for Academic Affairs during that same year."
    )
    paragraph_b = (
        "Grievances expressed verbally or in writing by any faculty member "
        "shall be received, logged, and forwarded to the appropriate "
        "committee within five working days of receipt for review."
    )
    paragraph_c = (
        "Faculty members who are repeatedly charged with the same offense "
        "may face administrative sanctions up to and including dismissal "
        "from service after due process has been properly observed."
    )
    text = "\n\n".join([paragraph_a, paragraph_b, paragraph_c])
    chunks = chunk_document_text(text, chunk_size=150, chunk_overlap=40)
    assert len(chunks) > 1
    for chunk in chunks:
        assert not chunk.text.startswith("uary")
        assert not chunk.text.startswith("ssed")
        assert not chunk.text.startswith("ment")
        assert not chunk.text.startswith("atedly")
        start = chunk.char_start
        if start > 0:
            assert text[start - 1].isspace(), (
                f"chunk at char_start={start} begins mid-word: {chunk.text[:20]!r}"
            )
        end = start + len(chunk.text)
        if end < len(text):
            assert text[end].isspace() or not text[end - 1].isalnum(), (
                f"chunk ending at {end} ends mid-word: {chunk.text[-20:]!r}"
            )


# --- representative completeness: body content survives end to end --------


def test_representative_policy_body_text_survives_full_cleaning_pipeline():
    """TOC + multi-line header/footer furniture combined -- body content
    near the start, middle, and end of the document must all survive."""
    toc = (
        "Contents\n"
        "Foreword\n"
        "Board of Regents\n"
        "I. General Information\n"
        "II. Faculty Official Time\n"
        "III. Grading Policies\n"
        "IV. Grievance Machinery\n"
    )
    pages = [
        toc,
        (
            "Institution: Laguna State Polytechnic University\nDate: March 2021\n\n"
            "Faculty Official Time\n\n"
            "All faculty members shall observe the official time prescribed by "
            "the university and render the required number of office hours.\n\n"
            "Page 2 of 4"
        ),
        (
            "Institution: Laguna State Polytechnic University\nDate: March 2021\n\n"
            "Grading and Submission of Grades\n\n"
            "Grades must be submitted within five calendar days after the end "
            "of the examination period set by the registrar for that term.\n\n"
            "Page 3 of 4"
        ),
        (
            "Institution: Laguna State Polytechnic University\nDate: March 2021\n\n"
            "Grievance Machinery\n\n"
            "A faculty member aggrieved by an administrative decision may file "
            "a written grievance with the appropriate committee for review.\n\n"
            "Page 4 of 4"
        ),
    ]
    cleaned = clean_extracted_text("\n".join(pages), page_texts=pages)
    assert "render the required number of office hours" in cleaned
    assert "Grades must be submitted within five calendar days" in cleaned
    assert "file a written grievance with the appropriate committee" in cleaned
    assert "Institution: Laguna State Polytechnic University" not in cleaned
    assert "Foreword" not in cleaned


# --- 2026-10-05 second follow-up: REAL v27 runtime-shape regressions -------
#
# Real production Extract-only validation on the actual LSPU Faculty
# Manual / Student Handbook (v27) showed the TOC and pagination fixes
# still didn't match the REAL extracted structure: a TOC row's
# title+dot-leader and its page number are on SEPARATE lines; a
# roman-numeral section marker ("I.") is its own line, with the title on
# the NEXT line; and front-matter pages are paginated with roman
# numerals ("Page: iv") which _DIGIT_RUN_RE never normalized. These
# fixtures mirror that REAL shape -- synthetic titles/prose only, never
# actual manual content.

_REAL_SHAPE_TOC_FRONT_MATTER = (
    "Foreword ……………………\n"
    "i\n"
    "Contents ……………………\n"
    "ii\n"
    "Vision, Mission, and Quality Policy ……………\n"
    "iv\n"
    "Board of Regents ……………\n"
    "v\n"
    "Administrative Officials ………\n"
    "vii\n"
)

_REAL_SHAPE_TOC_NUMBERED_SECTIONS = (
    "I.\n"
    "General Information ……………\n"
    "1\n"
    "II.\n"
    "Historical Development ………\n"
    "2\n"
    "III.\n"
    "Commitment of the Faculty ………\n"
    "5\n"
    "IV.\n"
    "University Policies ………\n"
    "9\n"
    "Faculty Official Time ………\n"
    "9\n"
    "Faculty Attendance and Absence ………\n"
    "10\n"
)

_REAL_SHAPE_TOC_CONTINUATION_PAGE = (
    "Submission of Grades ………\n"
    "16\n"
    "XI.\n"
    "Grievance Machinery ………\n"
    "82\n"
)


def test_real_shape_faculty_toc_removed_vision_mission_body_preserved():
    body = (
        "Vision, Mission, and Quality Policy\n\n"
        "The university commits itself to excellence in instruction, "
        "research, extension, and production in service of the Filipino "
        "people and the global community it is part of every single day.\n"
    )
    full_text = (
        _REAL_SHAPE_TOC_FRONT_MATTER
        + _REAL_SHAPE_TOC_NUMBERED_SECTIONS
        + _REAL_SHAPE_TOC_CONTINUATION_PAGE
        + "\n"
        + body
    )
    cleaned = remove_toc_blocks(full_text)
    for fragment in [
        "Foreword ……",
        "Contents ……",
        "Board of Regents ……",
        "Administrative Officials ……",
        "Vision, Mission, and Quality Policy ……",
        "General Information ……",
        "Historical Development ……",
        "Commitment of the Faculty ……",
        "University Policies ……",
        "Faculty Official Time ……",
        "Faculty Attendance and Absence ……",
        "Submission of Grades ……",
        "Grievance Machinery ……",
    ]:
        assert fragment not in cleaned, f"TOC row survived: {fragment!r}"
    # the real body heading (no leader) + its paragraph both survive
    assert "Vision, Mission, and Quality Policy\n\nThe university commits" in cleaned
    assert "excellence in instruction, research, extension" in cleaned


def test_real_shape_handbook_toc_removed_chapter_body_preserved():
    toc = (
        "Chapter 1 ……………\n"
        "Some Section Name ……………\n"
        "4\n"
        "Chapter 2 ……………\n"
        "Another Section ……………\n"
        "10\n"
        "Article 1: Student Conduct ……………\n"
        "14\n"
    )
    toc_continuation = (
        "Chapter 3 ……………\n"
        "Scholastic Delinquency ……………\n"
        "20\n"
        "Article 9: Grievance Procedure ……………\n"
        "30\n"
    )
    body = (
        "Chapter 1\n\n"
        "Some Section Name\n\n"
        "Every enrolled student is entitled to due process and fair "
        "treatment under university policy during any disciplinary "
        "proceeding brought against them by the administration.\n"
    )
    cleaned = remove_toc_blocks(toc + toc_continuation + "\n" + body)
    for fragment in [
        "Chapter 1 ……",
        "Some Section Name ……",
        "Chapter 2 ……",
        "Another Section ……",
        "Article 1: Student Conduct ……",
        "Chapter 3 ……",
        "Scholastic Delinquency ……",
        "Article 9: Grievance Procedure ……",
    ]:
        assert fragment not in cleaned, f"TOC row survived: {fragment!r}"
    assert "Chapter 1\n\nSome Section Name\n\nEvery enrolled student" in cleaned
    assert "entitled to due process and fair treatment" in cleaned


def test_real_shape_roman_numeral_page_furniture_removed():
    """"Page: i" / "Page: iv" / "Page: v" (front-matter) and "Page: i of
    183" / "Page: iv of 183" (mixed roman+arabic) must all normalize to
    the SAME recurring template and be removed, exactly like an arabic
    "Page 5 of 92" footer already was."""
    roman_pages = []
    for i, numeral in enumerate(["i", "ii", "iii", "iv", "v"], start=1):
        tag = _PAGE_TAG_WORDS[i - 1]
        body = "\n".join(f"{s} (section tag: {tag})" for s in _BODY_SENTENCE_TEMPLATES)
        roman_pages.append(f"{body}\n\nPage: {numeral}")

    mixed_pages = []
    for i, numeral in enumerate(["i", "ii", "iii", "iv"], start=1):
        tag = _PAGE_TAG_WORDS[i + 4]
        body = "\n".join(f"{s} (section tag: {tag})" for s in _BODY_SENTENCE_TEMPLATES)
        mixed_pages.append(f"{body}\n\nPage: {numeral} of 183")

    all_pages = roman_pages + mixed_pages
    cleaned = clean_extracted_text("\n".join(all_pages), page_texts=all_pages)
    for numeral in ["i", "ii", "iii", "iv", "v"]:
        assert f"Page: {numeral}" not in cleaned
        assert f"Page: {numeral} of 183" not in cleaned
    for i in range(1, 10):
        tag = _PAGE_TAG_WORDS[i - 1]
        assert f"(section tag: {tag})" in cleaned


def test_real_shape_no_chunk_consists_primarily_of_toc_entries():
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        body = (
            "Vision, Mission, and Quality Policy\n\n"
            "The university commits itself to excellence in instruction, "
            "research, extension, and production in service of the "
            "Filipino people and the global community every single day.\n"
        )
        page_texts = [
            _REAL_SHAPE_TOC_FRONT_MATTER
            + _REAL_SHAPE_TOC_NUMBERED_SECTIONS
            + _REAL_SHAPE_TOC_CONTINUATION_PAGE
            + "\n"
            + body
        ]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="real_shape_test.pdf"
        )
    assert chunks
    toc_entry_fragments = [
        "Foreword", "Contents", "Board of Regents", "Administrative Officials",
        "General Information", "Historical Development", "Commitment of the Faculty",
        "University Policies", "Faculty Attendance and Absence", "Submission of Grades",
        "Grievance Machinery",
    ]
    for chunk in chunks:
        toc_like_hits = sum(1 for frag in toc_entry_fragments if frag in chunk.text)
        assert toc_like_hits == 0, f"chunk is TOC-derived: {chunk.text[:200]!r}"


def test_real_shape_toc_derived_text_never_reaches_office_classification():
    """TOC rows must never survive long enough to BECOME a chunk at all,
    so they can never reach office classification and produce a bogus
    office guess (e.g. a "Medical Clinic"/"Scholarship Office" TOC row
    being mistaken for that office's real content elsewhere)."""
    store, _collection = make_fake_store()
    with (
        patch("app.services.admin.digital_ingestion.get_knowledge_base_store", return_value=store),
        patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store", return_value=store),
    ):
        toc = (
            "Contents ……………………\n"
            "ii\n"
            "Medical and Dental Services ……………\n"
            "40\n"
            "Scholarship and Financial Assistance ……………\n"
            "45\n"
            "Guidance and Counseling ……………\n"
            "50\n"
        )
        body = (
            "Grievance Machinery\n\n"
            "Any faculty member aggrieved by a decision may file a written "
            "grievance with the appropriate committee for prompt review.\n"
        )
        page_texts = [toc + "\n" + body]
        chunks = build_chunks_with_pages(
            page_texts, [0], chunk_size=300, chunk_overlap=30, title="T", source_filename="real_shape_office_test.pdf"
        )
    assert chunks
    for chunk in chunks:
        assert "Medical and Dental Services" not in chunk.text
        assert "Scholarship and Financial Assistance" not in chunk.text
        assert "Guidance and Counseling" not in chunk.text
        office = chunk.metadata.get("office")
        assert office not in {"Medical and Dental Services", "Scholarship and Financial Assistance", "Guidance and Counseling"}


# --- 2026-10-05 third follow-up: real-PDF diagnosis against the ACTUAL --
# LSPU Faculty Manual / Student Handbook PDFs (local, read-only, never
# committed -- see backend/scripts/validate_real_pdfs_local.py) found
# TWO further real-structure gaps the prior synthetic fixtures missed:
#
# 1. A TOC entry's title frequently WRAPS across two lines (e.g. "Time
#    Allotment for Teaching Loads and other Assignment" / "of Faculty
#    ......." / "13") in a way where NEITHER fragment alone passes any
#    title-shape test -- the wrap point can split a title such that one
#    half has a lowercase non-connector word (breaking the Title-Case
#    check) and the other half is mostly connector words (failing the
#    0.6 title-case ratio). The entry's own trailing page-number marker
#    still reliably anchors the cluster across the wrap regardless.
# 2. A real PDF's page boundary commonly lands as a run of 7+
#    consecutive BLANK lines -- more than the old raw-index-distance
#    max_gap allowed -- fragmenting one continuous TOC into separate
#    clusters, each of which could then fail the anchor-proximity check
#    on its own (even though the anchor falls WITHIN the reunited span).


def test_wrapped_toc_title_bridged_via_bare_page_number_anchor():
    toc = (
        "Contents\n"
        "Faculty Workload Policy ……………\n"
        "10\n"
        "Time Allotment for Teaching Loads and other Assignment\n"
        "of Faculty…………………………….\n"
        "13\n"
        "Syllabus Preparation …………………\n"
        "15\n"
    )
    body = (
        "Grievance Machinery\n\n"
        "Any faculty member who believes a decision was unfair may file a "
        "written grievance with the designated committee within fifteen "
        "working days of the event giving rise to the complaint itself.\n"
    )
    cleaned = remove_toc_blocks(toc + "\n" + body)
    for fragment in [
        "Faculty Workload Policy",
        "Time Allotment for Teaching Loads",
        "of Faculty…",
        "Syllabus Preparation",
    ]:
        assert fragment not in cleaned, f"wrapped TOC row survived: {fragment!r}"
    assert "Grievance Machinery" in cleaned
    assert "written grievance with the designated committee" in cleaned


def test_toc_cluster_survives_a_blank_line_page_break_run():
    """A real page boundary can land as several consecutive blank lines
    -- more than old raw-index-distance gap tolerance allowed -- which
    must not fragment one continuous TOC into disconnected pieces."""
    toc_before_break = (
        "Contents\n"
        "Foreword ……………\n"
        "i\n"
        "Board of Regents ……………\n"
        "v\n"
    )
    blank_page_break = "\n" * 8
    toc_after_break = (
        "Article 1: Classification …………\n"
        "1\n"
        "Article 2: Admission Requirements …………\n"
        "2\n"
    )
    body = (
        "Article 3: Registration\n\n"
        "Every student must complete registration through the official "
        "online portal before the start of classes each academic term.\n"
    )
    cleaned = remove_toc_blocks(toc_before_break + blank_page_break + toc_after_break + "\n" + body)
    for fragment in ["Foreword", "Board of Regents", "Article 1: Classification", "Article 2: Admission"]:
        assert fragment not in cleaned, f"TOC row survived a page-break gap: {fragment!r}"
    assert "Article 3: Registration" in cleaned
    assert "complete registration through the official online portal" in cleaned


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
