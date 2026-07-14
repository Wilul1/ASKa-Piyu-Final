"""Citizen's Charter chatbot indexing must create many service_procedure chunks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.chunking import DocumentChunk
from app.services.admin.knowledge_base_pipeline import (
    _is_citizens_charter_source,
    ingest_document_into_knowledge_base,
)
from app.services.document_ingestion import DocumentType
from app.services.knowledge_document_types import build_chunks_from_charter_v2_services


def _v2_service(title: str, page: int) -> dict:
    return {
        "service_title": title,
        "office_division": "Office of the Student Affairs and Services",
        "who_may_avail": "Students",
        "page_start": page,
        "requirements": [
            {"requirement": "Certificate of Registration", "where_to_secure": "Registrar"},
            {"requirement": "Student ID", "where_to_secure": "BAO"},
        ],
        "steps": [
            {
                "client_step": f"Present documents for {title}.",
                "agency_action": "Verify documents.",
                "fees": "None",
                "processing_time": "1 minute",
                "person_responsible": "OSAS Staff",
            }
        ],
        "total_processing_time": "4 minutes",
        "total_fees": "None",
        "extraction_quality": "clean",
    }


REQUIRED_SERVICE_TITLES = [
    "ID Validation",
    "Issuance of Good Moral Certificate",
    "Processing of Scholarship and Financial Assistance",
    "Assessment of Fees",
    "Completion of INC/Removal",
    "Dropping of Subjects",
    "Library Circulation Service",
    "Library Reference Assistance",
    "Processing of Student ID",
]


def test_is_citizens_charter_source_matches_unicode_dash_cc_filename():
    assert _is_citizens_charter_source(
        filename="Laguna State Polytechnic University\u2013CC_2026-1st Edition.pdf",
    )
    assert _is_citizens_charter_source(
        filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
    )


def test_build_chunks_from_charter_v2_services_indexes_multiple_services_with_pages():
    services = [
        _v2_service("ID Validation", 18),
        _v2_service("Issuance of Good Moral Certificate", 22),
        _v2_service("Processing of Scholarship and Financial Assistance", 30),
        {
            "service_title": "Requirement: Clearance, Request Form Accounting",
            "office_division": "Accounting",
            "page_start": 99,
            "requirements": [],
            "steps": [],
        },
    ]
    chunks = build_chunks_from_charter_v2_services(
        services,
        title="Citizen’s Charter 2026",
        source_document="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
    )
    titles = [chunk.metadata.get("title") for chunk in chunks]
    assert len(chunks) >= 3
    assert "ID Validation" in titles
    assert "Issuance of Good Moral Certificate" in titles
    assert "Processing of Scholarship and Financial Assistance" in titles
    assert all(not str(title).startswith("Requirement:") for title in titles)
    assert all(chunk.metadata.get("document_type") == "citizen_charter" for chunk in chunks)
    assert all(chunk.metadata.get("article_type") == "service_procedure" for chunk in chunks)
    assert all(isinstance(chunk.metadata.get("page_number"), int) for chunk in chunks)
    assert all(chunk.metadata.get("source_section") for chunk in chunks)
    assert all(chunk.metadata.get("source_excerpt") for chunk in chunks)


@patch("app.services.document_storage.persist_uploaded_document")
@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline._charter_v2_preview_payload")
@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_ingest_citizen_charter_indexes_many_service_chunks(
    mock_ingest,
    mock_prepare_review,
    mock_v2_payload,
    mock_store,
    mock_persist,
):
    extraction = SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text="Citizen's Charter",
        cleaned_text="Citizen's Charter",
        raw_extracted_text="Citizen's Charter",
        page_count=40,
        extraction_method="digital",
        structured=None,
        pdf_pages=[{"page": 1, "text": "ID Validation"}],
    )
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text="Citizen's Charter",
        cleaned_text="Citizen's Charter",
        review_text="Citizen's Charter",
        structuring_method="deterministic",
    )
    mock_v2_payload.return_value = {
        "charter_v2_services": [
            *[_v2_service(title, 10 + i) for i, title in enumerate(REQUIRED_SERVICE_TITLES)],
            {
                "service_title": "Requirement: Clearance, Request Form Accounting",
                "page_start": 90,
                "requirements": [],
                "steps": [],
            },
        ],
        "structured_extraction_text": "Structured charter services\n" * 20,
        "charter_v2_diagnostics": {},
    }
    mock_persist.return_value = SimpleNamespace(id="doc")

    store = MagicMock()
    store.add_document_chunks.side_effect = lambda **kwargs: len(kwargs["chunks"])
    store.delete_by_source_filename.return_value = 1
    store.collection_statistics.return_value = {
        "documents_indexed": 1,
        "total_chunks_indexed": 9,
        "chunks_with_page_number": 9,
        "embedding_model": "x",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
        "sample_titles": list(REQUIRED_SERVICE_TITLES),
        "document_type_counts": {"citizen_charter": 9},
        "article_type_counts": {"service_procedure": 9},
    }
    store.delete_document.return_value = None
    mock_store.return_value = store

    result = ingest_document_into_knowledge_base(
        b"%PDF-1.4 charter",
        filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
        # Trap: form-like reviewed_text must not collapse indexing to one card.
        reviewed_text="Requirement: Clearance, Request Form Accounting\nForm Preview only.",
    )

    assert result.chunks_indexed > 1
    assert result.chunks_indexed >= 8
    assert result.document_type == "citizen_charter"
    store.delete_by_source_filename.assert_called()
    kwargs = store.add_document_chunks.call_args.kwargs
    chunks = kwargs["chunks"]
    titles = [chunk.metadata.get("title") for chunk in chunks]
    for required in REQUIRED_SERVICE_TITLES:
        assert required in titles
    assert all(not str(title).startswith("Requirement:") for title in titles)
    assert all(chunk.metadata.get("article_type") == "service_procedure" for chunk in chunks)
    assert all(chunk.metadata.get("document_type") == "citizen_charter" for chunk in chunks)
    assert all(chunk.metadata.get("source_excerpt") for chunk in chunks)
    assert sum(1 for chunk in chunks if chunk.metadata.get("page_number")) > 0


@patch("app.services.document_storage.persist_uploaded_document")
@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline._charter_v2_preview_payload")
@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_ingest_rejects_requirement_only_charter_index(
    mock_ingest,
    mock_prepare_review,
    mock_v2_payload,
    mock_store,
    mock_persist,
):
    extraction = SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text="Requirement: Clearance, Request Form Accounting",
        cleaned_text="Requirement: Clearance, Request Form Accounting",
        raw_extracted_text="Requirement: Clearance, Request Form Accounting",
        page_count=1,
        extraction_method="digital",
        structured=None,
        pdf_pages=[],
        knowledge_document_type=None,
    )
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text="Requirement: Clearance",
        cleaned_text="Requirement: Clearance",
        review_text="Requirement: Clearance, Request Form Accounting",
        structuring_method="deterministic",
    )
    mock_v2_payload.return_value = {
        "charter_v2_services": [],
        "structured_extraction_text": "",
        "charter_v2_diagnostics": {"preview_has_charter_v2_services": False},
    }
    mock_persist.return_value = SimpleNamespace(id="doc")
    store = MagicMock()
    mock_store.return_value = store

    with patch(
        "app.services.admin.knowledge_base_pipeline._quality_payload",
        return_value=(
            [
                DocumentChunk(
                    text="form only",
                    chunk_index=0,
                    char_start=0,
                    metadata={
                        "title": "Requirement: Clearance, Request Form Accounting",
                        "article_type": "requirement_form",
                        "document_type": "requirement",
                    },
                )
            ],
            [],
            [],
            {},
        ),
    ):
        with pytest.raises(ValueError, match="requirement/form chunk"):
            ingest_document_into_knowledge_base(
                b"%PDF-1.4",
                filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
                content_type="application/pdf",
                document_type="citizen_charter",
            )
    store.add_document_chunks.assert_not_called()


def test_level2_citation_ready_false_when_page_numbers_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    monkeypatch.setattr(
        "app.services.chroma_store.settings.chroma_persist_dir",
        str(tmp_path / "chroma"),
    )
    monkeypatch.setattr(
        "app.services.chroma_store.settings.chroma_collection_name",
        "charter_index_stats_test",
    )
    from app.db.session import initialize_database
    from app.services.document_storage import persist_uploaded_document
    from app.services.chroma_store import get_knowledge_base_store

    # Reset cached store so monkeypatched paths apply.
    get_knowledge_base_store.cache_clear()
    initialize_database()
    store = get_knowledge_base_store()
    store.reset_collection()

    doc_id = "charter-stats-doc"
    persist_uploaded_document(
        b"%PDF-1.4",
        document_id=doc_id,
        filename="CC.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter",
    )
    store.add_document_chunks(
        document_id=doc_id,
        title="Citizen’s Charter",
        source_filename="CC.pdf",
        document_type="citizen_charter",
        chunks=[
            DocumentChunk(
                text="Service without page metadata",
                chunk_index=0,
                char_start=0,
                metadata={
                    "title": "ID Validation",
                    "source_section": "ID Validation",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                },
            )
        ],
    )
    stats = store.collection_statistics()
    assert stats["total_chunks_indexed"] == 1
    assert stats["chunks_with_page_number"] == 0
    entry = stats["indexed_documents"][0]
    assert entry["chunks_with_page_number"] == 0
    assert entry["level2_citation_ready"] is False
    assert "page_number" in (entry.get("message") or "")

    # With page numbers, Level-2 readiness becomes true.
    store.reset_collection()
    store.add_document_chunks(
        document_id=doc_id,
        title="Citizen’s Charter",
        source_filename="CC.pdf",
        document_type="citizen_charter",
        chunks=[
            DocumentChunk(
                text="Service with page metadata",
                chunk_index=0,
                char_start=0,
                metadata={
                    "title": "ID Validation",
                    "source_section": "ID Validation",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "page_number": 18,
                },
            ),
            DocumentChunk(
                text="Another service",
                chunk_index=1,
                char_start=20,
                metadata={
                    "title": "Issuance of Good Moral Certificate",
                    "source_section": "Issuance of Good Moral Certificate",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "page_number": 22,
                },
            ),
        ],
    )
    stats = store.collection_statistics()
    assert stats["total_chunks_indexed"] == 2
    assert stats["chunks_with_page_number"] == 2
    assert "ID Validation" in stats["sample_titles"]
    assert stats["document_type_counts"].get("citizen_charter") == 2
    assert stats["article_type_counts"].get("service_procedure") == 2
    entry = stats["indexed_documents"][0]
    assert entry["chunks_with_page_number"] == 2
    assert entry["level2_citation_ready"] is True
    assert "ID Validation" in entry["sample_titles"]
    assert entry["document_type_counts"].get("citizen_charter") == 2
    assert entry["article_type_counts"].get("service_procedure") == 2
    get_knowledge_base_store.cache_clear()


def test_requirement_form_cannot_be_only_charter_chunk_in_chroma(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.chroma_store.settings.chroma_persist_dir",
        str(tmp_path / "chroma"),
    )
    monkeypatch.setattr(
        "app.services.chroma_store.settings.chroma_collection_name",
        "charter_requirement_only_guard",
    )
    from app.services.chroma_store import get_knowledge_base_store

    get_knowledge_base_store.cache_clear()
    store = get_knowledge_base_store()
    store.reset_collection()
    filename = "Laguna State Polytechnic University-CC_2026-1st Edition.pdf"
    store.add_document_chunks(
        document_id="bad-doc",
        title="Citizen’s Charter",
        source_filename=filename,
        document_type="citizen_charter",
        chunks=[
            DocumentChunk(
                text="Requirement form only",
                chunk_index=0,
                char_start=0,
                metadata={
                    "title": "Requirement: Clearance, Request Form Accounting",
                    "source_section": "Requirement: Clearance, Request Form Accounting",
                    "document_type": "citizen_charter",
                    "article_type": "requirement_form",
                },
            )
        ],
    )
    deleted = store.delete_by_source_filename(filename)
    assert deleted == 1
    store.add_document_chunks(
        document_id="good-doc",
        title="Citizen’s Charter",
        source_filename=filename,
        document_type="citizen_charter",
        chunks=[
            DocumentChunk(
                text="ID Validation procedure",
                chunk_index=0,
                char_start=0,
                metadata={
                    "title": "ID Validation",
                    "source_section": "ID Validation",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "page_number": 18,
                    "source_excerpt": "Present ID for validation.",
                },
            ),
            DocumentChunk(
                text="Good Moral procedure",
                chunk_index=1,
                char_start=40,
                metadata={
                    "title": "Issuance of Good Moral Certificate",
                    "source_section": "Issuance of Good Moral Certificate",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "page_number": 22,
                    "source_excerpt": "Request good moral certificate.",
                },
            ),
            DocumentChunk(
                text="Scholarship procedure",
                chunk_index=2,
                char_start=80,
                metadata={
                    "title": "Processing of Scholarship and Financial Assistance",
                    "source_section": "Processing of Scholarship and Financial Assistance",
                    "document_type": "citizen_charter",
                    "article_type": "service_procedure",
                    "page_number": 30,
                    "source_excerpt": "Submit scholarship application.",
                },
            ),
        ],
    )
    stats = store.collection_statistics()
    assert stats["total_chunks_indexed"] > 1
    titles = set(stats["sample_titles"])
    assert "ID Validation" in titles
    assert "Issuance of Good Moral Certificate" in titles
    assert "Processing of Scholarship and Financial Assistance" in titles
    assert not (
        stats["total_chunks_indexed"] == 1
        and any(t.startswith("Requirement:") for t in titles)
    )
    get_knowledge_base_store.cache_clear()


def test_id_validation_question_retrieves_charter_service(tmp_path, monkeypatch):
    """Regression: ID question must prefer Citizen's Charter ID Validation over form noise."""
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    from app.db.session import initialize_database
    from app.services.chroma_store import RetrievedChunk
    from app.services.document_storage import persist_uploaded_document, source_page_url
    from app.services.qa.question_answering import answer_qa_question

    initialize_database()
    doc_id = "charter-id-qa-doc"
    persist_uploaded_document(
        b"%PDF-1.4 fake",
        document_id=doc_id,
        filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter",
        page_count=40,
    )

    id_chunk = RetrievedChunk(
        document_id=doc_id,
        title="Citizen’s Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=0,
        text=(
            "Service: ID Validation\nOffice / Division: Office of the Student Affairs and Services\n"
            "Who may avail: Students\nRequirements:\n"
            "- Certificate of Registration | Registrar\n- Student ID | BAO\n"
            "Client Steps:\n1. Present ID for validation at OSAS.\n"
            "Total Processing Time: 4 minutes\nTotal Fees: None"
        ),
        relevance_score=0.72,
        original_score=0.72,
        reranked_score=0.72,
        metadata={
            "document_id": doc_id,
            "title": "ID Validation",
            "source_section": "ID Validation",
            "document_type": "citizen_charter",
            "article_type": "service_procedure",
            "page_number": 18,
            "page_start": 18,
            "source_excerpt": "Present ID for validation at OSAS.",
            "source_filename": "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        },
    )
    form_chunk = RetrievedChunk(
        document_id=doc_id,
        title="Citizen’s Charter",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text="Requirement: Clearance, Request Form Accounting\nSubmit clearance form.",
        relevance_score=0.88,
        original_score=0.88,
        reranked_score=0.88,
        metadata={
            "document_id": doc_id,
            "title": "Requirement: Clearance, Request Form Accounting",
            "source_section": "Requirement: Clearance, Request Form Accounting",
            "document_type": "citizen_charter",
            "article_type": "requirement_form",
            "page_number": 90,
            "source_filename": "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        },
    )

    class _Store:
        chunk_count = 2

        def search(self, question, *, top_k=None, raw_k=None):
            return [form_chunk, id_chunk]

        def list_chunks(self):
            return []

    with (
        patch(
            "app.services.qa.question_answering.get_knowledge_base_store",
            return_value=_Store(),
        ),
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=AssertionError("Groq should not be required for typed procedure answers"),
        ),
    ):
        result = answer_qa_question("How do I validate my ID?")

    assert "ID Validation" in result.answer or "validate" in result.answer.lower()
    assert "Requirement: Clearance" not in result.answer
    assert result.sources
    assert result.sources[0]["source_section"] == "ID Validation"
    assert result.sources[0].get("page_number") in {18, "18"}
    page_url = (
        result.sources[0].get("source_page_url")
        or result.sources[0].get("source_view_url")
        or ""
    )
    assert "/source" in page_url
    assert (
        source_page_url(doc_id, 18) in page_url
        or "page=18" in page_url
        or "/page/18" in page_url
    )
