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
