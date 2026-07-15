"""Ingest/extract response schemas must accept specific document types like handbook_policy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.models.schemas import DocumentTypeDetectionSchema, IngestKnowledgeBaseResponse
from app.services.admin.knowledge_base_pipeline import ingest_document_into_knowledge_base
from app.services.document_ingestion import DocumentType
from app.services.knowledge_document_types import (
    DOCUMENT_TYPE_VALUES,
    KnowledgeDocumentType,
    KnowledgeDocumentTypeName,
    coerce_document_type_name,
    to_base_document_type,
)


def test_document_type_values_include_handbook_and_specific_types():
    assert "handbook_policy" in DOCUMENT_TYPE_VALUES
    assert "manual_policy" in DOCUMENT_TYPE_VALUES
    assert "memo_announcement" in DOCUMENT_TYPE_VALUES
    assert "form_template" in DOCUMENT_TYPE_VALUES
    assert "citizen_charter" in DOCUMENT_TYPE_VALUES
    assert "unknown" in DOCUMENT_TYPE_VALUES
    assert set(DOCUMENT_TYPE_VALUES) == {item.value for item in KnowledgeDocumentTypeName}


def test_to_base_document_type_maps_specific_types():
    assert to_base_document_type("handbook_policy") == "information"
    assert to_base_document_type("citizen_charter") == "procedure"
    assert to_base_document_type("form_template") == "requirement"
    assert to_base_document_type(KnowledgeDocumentType.PROCEDURE) == "procedure"


def test_detection_schema_accepts_handbook_policy():
    schema = DocumentTypeDetectionSchema(
        document_type="handbook_policy",
        base_document_type="information",
        reason="Handbook structure detected.",
        scores={"information": 6},
    )
    assert schema.document_type == KnowledgeDocumentTypeName.HANDBOOK_POLICY
    assert schema.base_document_type == KnowledgeDocumentType.INFORMATION


def test_ingest_response_accepts_handbook_policy_detected_type():
    response = IngestKnowledgeBaseResponse(
        document_id="handbook-doc-1",
        document_type="handbook_policy",
        source_filename="Student_Handbook.pdf",
        title="Student Handbook",
        chunks_indexed=12,
        page_count=80,
        extraction_method="digital",
        structuring_method="handbook_policy",
        pipeline_stages=[],
        extracted_text_preview="Chapter I ...",
        structured={"fields": [], "formatted_text": "Chapter I ..."},
        detected_document_type={
            "document_type": "handbook_policy",
            "base_document_type": "information",
            "reason": "Handbook structure detected.",
            "scores": {"information": 8, "procedure": 0, "requirement": 0},
            "manual_override": False,
        },
    )
    assert response.detected_document_type is not None
    assert response.detected_document_type.document_type == KnowledgeDocumentTypeName.HANDBOOK_POLICY
    assert response.detected_document_type.base_document_type == KnowledgeDocumentType.INFORMATION
    assert response.document_type == "handbook_policy"


@patch("app.services.document_storage.persist_uploaded_document")
@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline._quality_payload")
@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_ingest_handbook_policy_does_not_raise_pydantic_validation(
    mock_ingest,
    mock_prepare_review,
    mock_quality_payload,
    mock_store,
    mock_persist,
):
    from app.services.chunking import DocumentChunk
    from app.services.handbook_policy_processor import HandbookPolicyDocument

    handbook_text = (
        "Chapter I\nGeneral Provisions\n"
        "Article 1\nAcademic Policies\n"
        "Section 1\nStudents shall follow the handbook rules and guidelines.\n"
    )
    extraction = SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text=handbook_text,
        cleaned_text=handbook_text,
        raw_extracted_text=handbook_text,
        page_count=2,
        extraction_method="digital",
        structured=HandbookPolicyDocument(
            document_type="handbook_policy",
            source_title="Student Handbook",
            doc_no=None,
            cleaned_text=handbook_text,
            raw_text=handbook_text,
            units=[],
        ),
        knowledge_document_type="handbook_policy",
        pdf_pages=None,
    )
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text=handbook_text,
        cleaned_text=handbook_text,
        review_text=handbook_text,
        structuring_method="handbook_policy",
    )
    mock_quality_payload.return_value = (
        [
            DocumentChunk(
                text=handbook_text,
                chunk_index=0,
                char_start=0,
                metadata={
                    "title": "Academic Policies",
                    "document_type": "handbook_policy",
                },
            )
        ],
        [
            {
                "unit_index": 0,
                "title": "Academic Policies",
                "content": handbook_text,
                "content_type": "policy",
                "hierarchy_path": "Chapter I > Article 1",
                "word_count": 12,
                "page_start": 1,
                "page_end": 1,
                "status": "ok",
                "suspicious_reasons": [],
                "metadata": {},
            }
        ],
        [],
        {
            "document_type": "handbook_policy",
            "total_knowledge_units": 1,
            "total_chunks": 1,
            "average_chunk_words": 12.0,
            "largest_chunk_words": 12,
            "smallest_chunk_words": 12,
            "missing_metadata_count": 0,
            "toc_like_units_count": 0,
            "empty_units_count": 0,
            "suspicious_units_count": 0,
            "oversized_chunks_count": 0,
            "status": "ok",
        },
    )
    mock_persist.return_value = SimpleNamespace(id="doc")

    store = MagicMock()
    store.add_document_chunks.side_effect = lambda **kwargs: max(1, len(kwargs.get("chunks") or []))
    store.delete_by_source_filename.return_value = 0
    store.collection_statistics.return_value = {
        "documents_indexed": 1,
        "total_chunks_indexed": 1,
        "embedding_model": "x",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }
    mock_store.return_value = store

    result = ingest_document_into_knowledge_base(
        b"%PDF-1.4 handbook",
        filename="Student_Handbook.pdf",
        content_type="application/pdf",
        title="Student Handbook",
        reviewed_text=handbook_text,
    )

    assert coerce_document_type_name(result.document_type) in {
        "handbook_policy",
        "information",
    }
    assert result.detected_document_type is not None
    assert result.detected_document_type["document_type"] == "handbook_policy"
    assert result.detected_document_type["base_document_type"] == "information"

    # This is the regression: building the API response must not ValidationError.
    response = IngestKnowledgeBaseResponse(
        status="success",
        flow="admin_knowledge_base_ingest",
        document_id=result.document_id,
        document_type=result.document_type,
        source_filename=result.source_filename,
        title=result.title,
        chunks_indexed=result.chunks_indexed,
        page_count=result.page_count,
        extraction_method=result.extraction_method,
        structuring_method=result.structuring_method,
        pipeline_stages=result.pipeline_stages or [],
        extracted_text_preview=result.extracted_text_preview,
        structured=result.structured,
        diagnostic_report=result.diagnostic_report,
        validation_report=result.validation_report,
        detected_document_type=result.detected_document_type,
        knowledge_units=result.knowledge_units or [],
        chunk_preview=result.chunk_preview or [],
        kb_statistics=result.kb_statistics,
    )
    assert response.detected_document_type.document_type.value == "handbook_policy"
    assert response.detected_document_type.base_document_type.value == "information"
