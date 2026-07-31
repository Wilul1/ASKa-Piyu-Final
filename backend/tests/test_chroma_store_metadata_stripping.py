"""Regression tests: admin-generated KB articles append a debug
"----EXTRACTED METADATA----\n{json}" block after the student-facing body
(see article_content_formatter.py). If such an article gets indexed, that
raw block must never reach a student through retrieved chunk text — this
must hold for any chunk/document, not just a specific one.
"""

from app.services.chroma_store import _strip_indexed_metadata_block


def test_strip_indexed_metadata_block_removes_marker_and_json():
    raw = (
        "Overview\n\nThis service provides assistance for library reference queries."
        "\n\n----EXTRACTED METADATA----\n"
        '{"document_type": "citizen_charter", "office": "Library"}'
    )
    cleaned = _strip_indexed_metadata_block(raw)
    assert "EXTRACTED METADATA" not in cleaned
    assert "document_type" not in cleaned
    assert "Overview" in cleaned


def test_strip_indexed_metadata_block_is_a_noop_when_marker_absent():
    raw = "Enrollment requirements: submit COR and requirements to the Registrar."
    assert _strip_indexed_metadata_block(raw) == raw


def test_strip_indexed_metadata_block_handles_empty_string():
    assert _strip_indexed_metadata_block("") == ""


def test_strip_indexed_metadata_block_removes_trailing_source_information_footer():
    """Citizen's Charter articles append a fixed citation footer that is
    already surfaced separately via chunk metadata; it must never be echoed
    back as answer text for any document/question."""
    raw = (
        "4. Client Step: End transaction and ask for feedback\n"
        "   Agency Action: Log the transaction\n\n"
        "Fees\nNone\n\n"
        "Total Processing Time\n10 minutes\n\n"
        "Source Information\n"
        "Document: Laguna State Polytechnic University-CC_2026-1st Edition.pdf\n"
        "Service: Library Reference Assistance\n"
        "Office: Library\n"
        "Page: 15"
    )
    cleaned = _strip_indexed_metadata_block(raw)
    assert "Source Information" not in cleaned
    assert "Page: 15" not in cleaned
    assert "Total Processing Time" in cleaned


def test_strip_indexed_metadata_block_drops_footer_only_chunk_to_empty():
    """A chunk boundary can produce a chunk that is *only* the footer
    (sometimes missing its leading character from an off-by-one split) —
    stripping must leave nothing so downstream code treats it as unusable
    rather than surfacing a raw citation dump as the "answer"."""
    raw = (
        "ource Information\n"
        "Document: Laguna State Polytechnic University-CC_2026-1st Edition.pdf\n"
        "Service: Library Reference Assistance\n"
        "Office: Library\n"
        "Page: 15"
    )
    assert _strip_indexed_metadata_block(raw) == ""
