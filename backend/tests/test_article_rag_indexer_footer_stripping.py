"""Citizen's Charter articles (citizen_charter_services.build_charter_article_body)
end with a fixed "Source Information / Document: / Service: / Office: / Page:"
citation footer, already captured structurally in chunk metadata. Character-
count-based chunking has no awareness of this footer's boundaries, so it can
land mid-footer and produce a chunk that is only an unreadable fragment with
no real content — for any article, not one specific document. These tests
confirm the footer is stripped before chunking so that class of chunk can
never be created in the first place.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.article_rag_indexer import _build_faq_chunks, _strip_charter_source_footer

_FOOTER = (
    "\n\nSource Information\n"
    "Document: Laguna State Polytechnic University-CC_2026-1st Edition.pdf\n"
    "Service: Library Reference Assistance\n"
    "Office: Library\n"
    "Page: 15"
)


def test_strip_charter_source_footer_removes_trailing_block():
    body = "Overview\n\nSome real service content here." + _FOOTER
    cleaned = _strip_charter_source_footer(body)
    assert "Source Information" not in cleaned
    assert "Page: 15" not in cleaned
    assert cleaned == "Overview\n\nSome real service content here."


def test_strip_charter_source_footer_is_noop_without_footer():
    body = "Overview\n\nSome real service content with no footer at all."
    assert _strip_charter_source_footer(body) == body


def test_strip_charter_source_footer_removes_metadata_block_appearing_after_footer():
    """Admin-edited articles can append a "----EXTRACTED METADATA----\\n{json}"
    debug block *after* the Source Information footer -- both must be
    stripped, in the right order, regardless of which one comes last."""
    body = (
        "Overview\n\nSome real service content here."
        + _FOOTER
        + "\n\n----EXTRACTED METADATA----\n"
        + '{"document_type": "citizen_charter", "parser_debug": {"a": 1}}'
    )
    cleaned = _strip_charter_source_footer(body)
    assert "Source Information" not in cleaned
    assert "EXTRACTED METADATA" not in cleaned
    assert "parser_debug" not in cleaned
    assert cleaned == "Overview\n\nSome real service content here."


def test_build_faq_chunks_never_produces_a_footer_only_chunk():
    # Short body: without stripping, a naive char-count chunker could easily
    # split right around/within the footer and leave a chunk that's only the
    # citation block (or a fragment of it).
    content = (
        "Overview\n\nThis service helps students with reference queries.\n\n"
        "Requirements\n- Requirement: Valid student ID\n" + _FOOTER
    )
    article = SimpleNamespace(
        id="article-1",
        title="Library Reference Assistance",
        summary="",
        content=content,
        category="",
        office="Library",
        audience="student",
        kb_origin="citizen_charter",
        source_ticket_id="",
    )
    chunks = _build_faq_chunks(article)
    assert chunks, "expected at least one chunk"
    for chunk in chunks:
        assert "Source Information" not in chunk.text
        assert "Page: 15" not in chunk.text
        # Every chunk must retain some real, non-footer content.
        assert len(chunk.text.strip()) > 20


def test_build_faq_chunks_indexes_content_sections_from_extracted_metadata():
    content = (
        "Overview\nOfficial grading sheets go to the Registrar within ten (10) days.\n\n"
        "----EXTRACTED METADATA----\n"
        '{"content_sections":['
        '{"heading":"Overview","body":"This article explains the i. submission of grades."},'
        '{"heading":"Process","body":"If twenty-five percent (25%) and above the class need a grade change, '
        'seek approval of the University President for an Academic Council Meeting."}'
        "]}"
    )
    article = SimpleNamespace(
        id="article-grades",
        title="Submission of Grades",
        summary="",
        content=content,
        category="",
        office="Registrar",
        audience="faculty",
        kb_origin="document",
        source_ticket_id="",
    )
    chunks = _build_faq_chunks(article)
    blob = " ".join(chunk.text for chunk in chunks)
    assert "EXTRACTED METADATA" not in blob
    assert "content_sections" not in blob
    assert "Academic Council Meeting" in blob
    assert "twenty-five percent" in blob
