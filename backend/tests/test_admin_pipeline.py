from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.chunking import DocumentChunk, chunk_document_text
from app.services.admin.knowledge_base_pipeline import (
    extract_document_preview,
    ingest_document_into_knowledge_base,
    retrieval_test,
)
from app.services.chroma_store import RetrievedChunk
from app.services.document_ingestion import DocumentType
from app.services.handbook_policy_processor import (
    HandbookKnowledgeUnit,
    HandbookPolicyDocument,
)


def _extraction():
    return SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text="Service:\n  Enrollment",
        cleaned_text="Service: Enrollment\nSteps: Submit forms",
        raw_extracted_text="Service: Enrollment\nSteps: Submit forms",
        page_count=1,
        extraction_method="digital",
        structured=None,
    )


@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_document_id_requires_replace_existing(mock_ingest, mock_store):
    mock_ingest.return_value = _extraction()

    with pytest.raises(ValueError, match="replace_existing"):
        ingest_document_into_knowledge_base(
            b"%PDF",
            filename="handbook.pdf",
            content_type="application/pdf",
            document_id="doc-1",
        )

    mock_store.return_value.add_document_chunks.assert_not_called()


@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_replace_existing_requires_document_id(mock_ingest, mock_store):
    mock_ingest.return_value = _extraction()

    with pytest.raises(ValueError, match="document_id"):
        ingest_document_into_knowledge_base(
            b"%PDF",
            filename="handbook.pdf",
            content_type="application/pdf",
            replace_existing=True,
        )

    mock_store.return_value.add_document_chunks.assert_not_called()


def test_chunk_document_text_returns_store_compatible_chunks():
    chunks = chunk_document_text("A" * 950, chunk_size=900, chunk_overlap=120)

    assert chunks
    assert all(isinstance(chunk, DocumentChunk) for chunk in chunks)
    assert chunks[0].text == "A" * 900
    assert chunks[0].chunk_index == 0
    assert chunks[0].char_start == 0
    assert chunks[1].chunk_index == 1
    assert chunks[1].char_start == 780


@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_ingest_falls_back_to_cleaned_text_when_review_is_only_needs_review(
    mock_ingest,
    mock_store,
    mock_prepare_review,
):
    extraction = _extraction()
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text=extraction.raw_extracted_text,
        cleaned_text=extraction.cleaned_text,
        review_text="Office: [NEEDS REVIEW]\nService: [NEEDS REVIEW]",
        structuring_method="deterministic",
    )

    store = mock_store.return_value
    store.add_document_chunks.return_value = 1

    ingest_document_into_knowledge_base(
        b"%PDF",
        filename="handbook.pdf",
        content_type="application/pdf",
    )

    chunks = store.add_document_chunks.call_args.kwargs["chunks"]
    assert chunks[0].text.startswith("Service: Enrollment")


@patch("app.services.admin.knowledge_base_pipeline.knowledge_base_statistics")
@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_extract_preview_falls_back_to_cleaned_text_when_review_is_only_needs_review(
    mock_ingest,
    mock_prepare_review,
    mock_statistics,
):
    extraction = _extraction()
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text=extraction.raw_extracted_text,
        cleaned_text=extraction.cleaned_text,
        review_text="Office: [NEEDS REVIEW]\nService: [NEEDS REVIEW]",
        structuring_method="deterministic",
    )
    mock_statistics.return_value = {
        "documents_indexed": 0,
        "total_chunks_indexed": 0,
        "embedding_model": "ChromaDB default embedding function",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }

    result = extract_document_preview(
        b"%PDF",
        filename="handbook.pdf",
        content_type="application/pdf",
    )

    assert result["review_text"] == extraction.cleaned_text
    assert result["extracted_text"] == extraction.cleaned_text


@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_ingest_handbook_policy_uses_logical_units(
    mock_ingest,
    mock_store,
    mock_prepare_review,
):
    unit = HandbookKnowledgeUnit(
        title="Freshman Admission Requirements",
        content="Freshmen must submit Report Card/Form 138 and Form 137.",
        raw_text="Sec. 2.11 Freshman Admission Requirements",
        metadata={
            "source_title": "LSPU Student Handbook 2021",
            "doc_no": "LSPU-PM-LSH-01",
            "document_type": "handbook_policy",
            "chapter": "Chapter 3 > Student Admission",
            "article": "Article 2 > Admission Requirements",
            "section": "Sec. 2.11 > Basic Requirements",
            "page_start": 10,
            "page_end": 11,
        },
    )
    handbook = HandbookPolicyDocument(
        document_type="handbook_policy",
        source_title="LSPU Student Handbook 2021",
        doc_no="LSPU-PM-LSH-01",
        cleaned_text=unit.raw_text,
        raw_text=unit.raw_text,
        units=[unit],
    )
    extraction = SimpleNamespace(
        document_type=DocumentType.PDF,
        knowledge_document_type="handbook_policy",
        extracted_text=handbook.formatted_articles,
        cleaned_text=handbook.cleaned_text,
        raw_extracted_text=handbook.raw_text,
        page_count=20,
        extraction_method="digital",
        structured=handbook,
    )
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text=handbook.raw_text,
        cleaned_text=handbook.cleaned_text,
        review_text=handbook.formatted_articles,
        structuring_method="handbook_policy_logical",
    )
    store = mock_store.return_value
    store.add_document_chunks.return_value = 1

    result = ingest_document_into_knowledge_base(
        b"%PDF",
        filename="handbook.pdf",
        content_type="application/pdf",
    )

    chunks = store.add_document_chunks.call_args.kwargs["chunks"]
    assert result.document_type == "handbook_policy"
    assert len(chunks) == 1
    assert chunks[0].text.startswith("Freshman Admission Requirements")
    assert chunks[0].metadata["section"] == "Sec. 2.11 > Basic Requirements"
    assert store.add_document_chunks.call_args.kwargs["document_type"] == "handbook_policy"
    assert result.diagnostic_report["total_knowledge_units"] == 1
    assert result.diagnostic_report["total_chunks"] == 1


@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
def test_retrieval_test_returns_full_content_separate_from_preview(mock_store):
    full_text = (
        "Shifting of Course\n"
        "A student may shift course when all conditions are satisfied. "
        "The student must secure approval from the releasing and accepting colleges, "
        "meet grade and residency requirements, and submit the shifting form from the "
        "Office of the Registrar. "
        + "Additional condition. " * 40
    )
    store = mock_store.return_value
    store.search.return_value = [
        RetrievedChunk(
            document_id="doc-1",
            title="Student Handbook",
            source_filename="handbook.pdf",
            chunk_index=3,
            text=full_text,
            relevance_score=0.92,
            metadata={"section": "Shifting of Course", "page_start": 12, "page_end": 13},
        )
    ]
    store.collection_statistics.return_value = {
        "documents_indexed": 1,
        "total_chunks_indexed": 1,
        "embedding_model": "ChromaDB default embedding function",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }

    result = retrieval_test("How do I shift course?", top_k=1)

    chunk = result["results"][0]
    assert chunk["title"] == "Shifting of Course"
    assert chunk["content"] == full_text
    assert "Office of the Registrar" in chunk["content_preview"]
    assert len(chunk["content_preview"]) <= 703
    assert len(chunk["content"]) > len(chunk["content_preview"])
