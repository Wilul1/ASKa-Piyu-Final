"""Regression tests for chunk_document_text (raw/unstructured document
chunking). This is the fallback chunker used for any INFORMATION-type
document content that isn't already broken into structured units (Charter
services, Handbook policy units) — e.g. Faculty Manual freeform sections.
Before this change it blindly sliced by character count with zero regard
for paragraph boundaries, which could cut a sentence in half and hand the
LLM a garbled chunk regardless of which document/question hit it. These
tests must hold for any document's text, not one specific file.
"""

from app.services.chunking import chunk_document_text


def test_chunk_document_text_keeps_whole_paragraphs_together_when_they_fit():
    """Two short paragraphs that together fit under chunk_size must stay in
    a single chunk rather than being split at an arbitrary character
    offset."""
    text = "First paragraph about enrollment steps." + "\n\n" + "Second paragraph about requirements."
    chunks = chunk_document_text(text, chunk_size=200, chunk_overlap=20)

    assert len(chunks) == 1
    assert "First paragraph" in chunks[0].text
    assert "Second paragraph" in chunks[0].text


def test_chunk_document_text_never_splits_a_paragraph_that_fits_alone():
    """When paragraphs collectively exceed chunk_size, the boundary must
    fall *between* paragraphs — no paragraph that individually fits under
    chunk_size should ever be cut in half."""
    paragraphs = [
        "Paragraph one describes the general admission policy for new students.",
        "Paragraph two describes the specific requirements for transferees.",
        "Paragraph three describes the appeals process for rejected applicants.",
    ]
    text = "\n\n".join(paragraphs)
    # Small enough that paragraphs 1+2 don't both fit, forcing a boundary.
    chunks = chunk_document_text(text, chunk_size=140, chunk_overlap=10)

    assert len(chunks) >= 2
    for paragraph in paragraphs:
        # Every paragraph must appear intact (not truncated mid-sentence)
        # in at least one chunk.
        assert any(paragraph in chunk.text for chunk in chunks), (
            f"paragraph was split across chunks or truncated: {paragraph!r}"
        )


def test_chunk_document_text_oversized_single_paragraph_falls_back_to_char_slicing():
    """A single paragraph (or a whole unbroken block with no blank lines at
    all) that alone exceeds chunk_size has no paragraph boundary to use, so
    it must still fall back to character-count slicing rather than
    producing one giant oversized chunk."""
    long_paragraph = "word " * 400  # no blank lines anywhere
    chunks = chunk_document_text(long_paragraph, chunk_size=300, chunk_overlap=30)

    assert len(chunks) > 1
    assert all(len(chunk.text) <= 300 for chunk in chunks)


def test_chunk_document_text_preserves_backward_compatible_char_slicing_for_unbroken_text():
    """Pinned regression: plain text with no paragraph structure at all
    (e.g. a wall of characters) must still slice exactly like the legacy
    blind character-window behavior other callers depend on."""
    chunks = chunk_document_text("A" * 950, chunk_size=900, chunk_overlap=120)

    assert chunks[0].text == "A" * 900
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_start == 0
    assert chunks[1].chunk_index == 1
    assert chunks[1].char_start == 780


def test_chunk_document_text_empty_input_returns_no_chunks():
    assert chunk_document_text("") == []
    assert chunk_document_text("   \n\n  ") == []


def test_chunk_document_text_applies_overlap_between_paragraph_chunks():
    """When a paragraph boundary forces a new chunk, the new chunk should
    still carry a small overlap tail from the previous chunk so context
    isn't lost right at the seam — matching the overlap behavior already
    used for FAQ article chunking."""
    paragraphs = [
        "A" * 100,
        "B" * 100,
    ]
    text = "\n\n".join(paragraphs)
    chunks = chunk_document_text(text, chunk_size=110, chunk_overlap=20)

    assert len(chunks) == 2
    assert chunks[0].text == "A" * 100
    # Second chunk should start with the overlap tail from chunk 1 (some A's)
    # followed by the full second paragraph.
    assert chunks[1].text.endswith("B" * 100)
    assert "A" in chunks[1].text
