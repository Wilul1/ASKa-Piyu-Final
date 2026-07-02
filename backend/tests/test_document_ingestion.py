import pytest

from app.services.document_ingestion import (
    DocumentType,
    UnsupportedDocumentError,
    detect_document_type,
)


def test_detect_image_png():
    assert detect_document_type("scan.png", "image/png") == DocumentType.IMAGE


def test_detect_pdf():
    assert detect_document_type("memo.pdf", "application/pdf") == DocumentType.PDF


def test_unsupported_type():
    with pytest.raises(UnsupportedDocumentError):
        detect_document_type("notes.docx", "application/msword")
