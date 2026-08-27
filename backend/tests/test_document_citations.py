"""Citation grounding: stored PDFs, chunk metadata, QA citations, source endpoint."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_session_factory, initialize_database
from app.main import app
from app.models.db_models import PublishedArticle, SourceDocument
from app.services.auth import get_current_user, get_optional_user
from app.services.chroma_store import RetrievedChunk, _enrich_chunk_citation_metadata
from app.services.document_storage import (
    persist_uploaded_document,
    resolve_stored_path,
    source_page_url,
    source_view_url,
)
from app.services.qa.question_answering import _citations_from_sources, _sources_from_chunks
from tests.db_helpers import cleanup_all_published_articles

client = TestClient(app)


@pytest.fixture
def auth_student():
    user = SimpleNamespace(id="u-student", role="student", email="student@test.edu")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)


@pytest.fixture
def auth_faculty():
    user = SimpleNamespace(id="u-faculty", role="faculty", email="faculty@test.edu")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_optional_user] = lambda: user
    yield user
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)


def test_source_view_url_includes_page():
    assert source_view_url("abc-123") == "/documents/abc-123/source"
    assert source_view_url("abc-123", 12) == "/documents/abc-123/source?page=12#page=12"


def test_persist_uploaded_document_writes_file_and_db_row(tmp_path, monkeypatch, auth_student):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    pdf_bytes = b"%PDF-1.4 citation-grounding-test"
    row = persist_uploaded_document(
        pdf_bytes,
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
        edition="1st Edition",
        page_count=40,
    )
    assert row.id == doc_id
    assert row.original_filename == "Citizens_Charter_2026.pdf"
    assert row.document_type == "citizen_charter"
    assert "Charter" in (row.source_label or "")
    path = resolve_stored_path(row.stored_file_path)
    assert path.is_file()
    assert path.read_bytes() == pdf_bytes

    session = get_session_factory()()
    try:
        stored = session.get(SourceDocument, doc_id)
        assert stored is not None
        assert stored.byte_size == len(pdf_bytes)
    finally:
        session.close()

    # Source PDFs require login (guests get 401).
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)
    guest_denied = client.get(f"/documents/{doc_id}/source")
    assert guest_denied.status_code == 401
    app.dependency_overrides[get_current_user] = lambda: auth_student
    app.dependency_overrides[get_optional_user] = lambda: auth_student

    meta = client.get(f"/documents/{doc_id}/source", params={"meta": "true", "page": 12})
    assert meta.status_code == 200
    body = meta.json()
    assert body["document_id"] == doc_id
    assert body["page_number"] == 12
    assert body["source_view_url"] == f"/documents/{doc_id}/source?page=12#page=12"

    pdf = client.get(f"/documents/{doc_id}/source", params={"page": 12})
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "application/pdf" in (pdf.headers.get("content-type") or "")


def test_chunk_citation_metadata_enrichment():
    meta = {
        "page_start": 12,
        "section_heading": "ID Validation",
        "document_type": "procedure",
    }
    _enrich_chunk_citation_metadata(
        meta,
        chunk_text="Present a valid school ID at the University Clinic for validation.",
    )
    assert meta["page_number"] == 12
    assert meta["source_section"] == "ID Validation"
    assert "school ID" in meta["source_excerpt"]


def test_sources_from_chunks_include_citation_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 citation-fields",
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
    )
    chunk = RetrievedChunk(
        document_id=doc_id,
        title="ID Validation",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=3,
        text="Students may validate their ID at the University Clinic.",
        relevance_score=0.9,
        metadata={
            "document_id": doc_id,
            "page_number": 12,
            "source_section": "ID Validation",
            "chunk_id": f"{doc_id}::3",
            "source_excerpt": "Students may validate their ID at the University Clinic.",
            "source_label": "Citizen’s Charter 2026",
            "article_type": "procedure",
        },
    )
    sources = _sources_from_chunks([chunk])
    assert len(sources) == 1
    source = sources[0]
    assert source["document_id"] == doc_id
    assert source["page_number"] == 12
    assert source["page"] == 12
    assert source["source_section"] == "ID Validation"
    assert source["source_view_url"] == f"/documents/{doc_id}/source?page=12#page=12"
    assert source["pdf_available"] is True
    assert source["citation_note"] is None
    assert source["citation_id"] == f"{doc_id}::3"
    assert source["page_end"] == 13
    assert source["source_page_url"].startswith(f"/documents/{doc_id}/source/page/12?")
    assert "end=13" in source["source_page_url"]
    assert "section=" in source["source_page_url"]

    citations = _citations_from_sources(sources)
    assert citations[0]["citation_id"] == f"{doc_id}::3"
    assert "#page=12" in citations[0]["source_view_url"]
    assert f"/documents/{doc_id}/source/page/12" in citations[0]["source_page_url"]


def test_orphan_legacy_chunk_has_no_clickable_source_view_url(tmp_path, monkeypatch):
    # Isolate from any real source_documents rows so filename fallback cannot rescue.
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    chunk = RetrievedChunk(
        document_id="missing-legacy-handbook-id",
        title="Validation of Subjects",
        source_filename="Student_Handbook_Does_Not_Exist.pdf",
        chunk_index=1,
        text="Validation of subjects requires payment of fees.",
        relevance_score=0.88,
        metadata={
            "document_id": "missing-legacy-handbook-id",
            "page_number": 40,
            "source_section": "Validation of Subjects",
            "chunk_id": "missing-legacy-handbook-id::1",
            "source_label": "Student Handbook",
        },
    )
    sources = _sources_from_chunks([chunk])
    assert sources[0]["source_view_url"] is None
    assert sources[0]["pdf_available"] is False
    assert "Re-index" in (sources[0]["citation_note"] or "")
    citations = _citations_from_sources(sources)
    assert citations[0]["source_view_url"] is None
    assert citations[0]["pdf_available"] is False


def test_stale_chroma_document_id_resolves_pdf_via_filename(tmp_path, monkeypatch):
    """Chroma UUIDs that no longer match Postgres still open the stored PDF."""
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    pg_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 remapped-citation",
        document_id=pg_id,
        filename="LSPU Student Handbook.pdf",
        content_type="application/pdf",
        document_type="student_handbook",
        title="LSPU Student Handbook",
    )
    stale_chroma_id = str(uuid.uuid4())
    chunk = RetrievedChunk(
        document_id=stale_chroma_id,
        title="VISION",
        source_filename="LSPU Student Handbook.pdf",
        chunk_index=2,
        text="LSPU envisions itself as...",
        relevance_score=0.95,
        metadata={
            "document_id": stale_chroma_id,
            "page_number": 8,
            "source_section": "VISION",
            "chunk_id": f"{stale_chroma_id}::2",
            "source_label": "LSPU Student Handbook",
        },
    )
    sources = _sources_from_chunks([chunk])
    assert sources[0]["pdf_available"] is True
    assert sources[0]["document_id"] == pg_id
    assert sources[0]["source_view_url"] == f"/documents/{pg_id}/source?page=8#page=8"
    assert sources[0]["citation_note"] is None


def test_published_article_exposes_source_view_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    cleanup_all_published_articles()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 article-source",
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
    )

    session = get_session_factory()()
    try:
        cleanup_all_published_articles()
        art = PublishedArticle(
            title="ID Validation",
            slug="id-validation",
            category="Student Services",
            summary="How to validate your ID.",
            content=(
                "Present your school ID at the window.\n\n"
                "----EXTRACTED METADATA----\n"
                '{"source_section":"ID Validation","page_number":12,'
                f'"document_id":"{doc_id}","document_type":"citizen_charter"}}'
            ),
            source_filename="Citizens_Charter_2026.pdf",
            source_document_id=doc_id,
            published=True,
        )
        session.add(art)
        session.commit()
    finally:
        session.close()

    response = client.get("/kb/articles")
    assert response.status_code == 200
    payload = response.json()
    items = payload.get("items") or payload.get("articles") or payload
    if isinstance(items, dict):
        items = items.get("items") or []
    match = next((item for item in items if item.get("title") == "ID Validation"), None)
    assert match is not None
    assert match.get("page") == 12 or match.get("page_number") == 12
    assert match.get("document_id") == doc_id
    assert match.get("source_view_url") == f"/documents/{doc_id}/source?page=12#page=12"
    assert match.get("source_section") == "ID Validation"

    cleanup_all_published_articles()


def test_level2_citizen_charter_source_endpoint_opens_successfully(
    tmp_path, monkeypatch, auth_student
):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 charter-level2",
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
    )
    response = client.get(f"/documents/{doc_id}/source", params={"page": 18})
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    assert "application/pdf" in (response.headers.get("content-type") or "")

    chunk = RetrievedChunk(
        document_id=doc_id,
        title="ID Validation",
        source_filename="Citizens_Charter_2026.pdf",
        chunk_index=2,
        text="Present school ID for validation.",
        relevance_score=0.95,
        metadata={
            "document_id": doc_id,
            "page_number": 18,
            "source_section": "ID Validation",
            "source_label": "Citizen’s Charter 2026",
        },
    )
    source = _sources_from_chunks([chunk])[0]
    assert source["source_view_url"] == f"/documents/{doc_id}/source?page=18#page=18"
    open_response = client.get(source["source_view_url"])
    assert open_response.status_code == 200
    assert open_response.content.startswith(b"%PDF")


def test_source_endpoint_requires_login_for_public_docs(
    tmp_path, monkeypatch, auth_student
):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 charter-auth",
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
    )
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_optional_user, None)
    assert client.get(f"/documents/{doc_id}/source").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: auth_student
    app.dependency_overrides[get_optional_user] = lambda: auth_student
    assert client.get(f"/documents/{doc_id}/source").status_code == 200


def test_faculty_source_pdf_blocked_for_student(tmp_path, monkeypatch, auth_student):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 faculty-manual",
        document_id=doc_id,
        filename="LSPU Faculty Manual 2020.pdf",
        content_type="application/pdf",
        document_type="faculty_manual",
        title="LSPU Faculty Manual 2020",
    )
    response = client.get(f"/documents/{doc_id}/source")
    assert response.status_code == 403


def test_faculty_source_pdf_allowed_for_faculty(tmp_path, monkeypatch, auth_faculty):
    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        b"%PDF-1.4 faculty-manual",
        document_id=doc_id,
        filename="LSPU Faculty Manual 2020.pdf",
        content_type="application/pdf",
        document_type="faculty_manual",
        title="LSPU Faculty Manual 2020",
    )
    response = client.get(f"/documents/{doc_id}/source")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


@patch("app.services.admin.knowledge_base_pipeline.get_knowledge_base_store")
@patch("app.services.admin.knowledge_base_pipeline.prepare_review_document")
@patch("app.services.admin.knowledge_base_pipeline.ingest_document")
def test_reindex_handbook_creates_source_documents_and_citation_metadata(
    mock_ingest,
    mock_prepare_review,
    mock_store,
    tmp_path,
    monkeypatch,
):
    from types import SimpleNamespace

    from app.services.admin.knowledge_base_pipeline import ingest_document_into_knowledge_base
    from app.services.chunking import DocumentChunk
    from app.services.document_ingestion import DocumentType

    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()

    extraction = SimpleNamespace(
        document_type=DocumentType.PDF,
        extracted_text="Validation of Subjects\nStudents must validate enrolled subjects.",
        cleaned_text="Validation of Subjects\nStudents must validate enrolled subjects.",
        raw_extracted_text="Validation of Subjects\nStudents must validate enrolled subjects.",
        page_count=2,
        extraction_method="digital",
        structured=None,
    )
    mock_ingest.return_value = extraction
    mock_prepare_review.return_value = SimpleNamespace(
        raw_text=extraction.raw_extracted_text,
        cleaned_text=extraction.cleaned_text,
        review_text=extraction.cleaned_text,
        structuring_method="deterministic",
    )
    store = mock_store.return_value
    store.add_document_chunks.return_value = 1
    store.collection_statistics.return_value = {
        "documents_indexed": 1,
        "total_chunks_indexed": 1,
        "embedding_model": "ChromaDB default embedding function",
        "vector_store": "ChromaDB",
        "last_indexed_document": None,
    }
    store.delete_document.return_value = None

    with patch(
        "app.services.admin.knowledge_base_pipeline._quality_payload",
        return_value=(
            [
                DocumentChunk(
                    text="Validation of Subjects\nStudents must validate enrolled subjects.",
                    chunk_index=0,
                    char_start=0,
                    metadata={"page_number": 40, "source_section": "Validation of Subjects"},
                )
            ],
            [],
            [],
            {"status": "ok"},
        ),
    ):
        result = ingest_document_into_knowledge_base(
            b"%PDF-1.4 handbook-reindex",
            filename="Student_Handbook.pdf",
            content_type="application/pdf",
            title="Student Handbook",
            document_type="handbook",
        )

    session = get_session_factory()()
    try:
        stored = session.get(SourceDocument, result.document_id)
        assert stored is not None
        assert stored.original_filename == "Student_Handbook.pdf"
        assert resolve_stored_path(stored.stored_file_path).is_file()
    finally:
        session.close()

    kwargs = store.add_document_chunks.call_args.kwargs
    assert kwargs["document_id"] == result.document_id
    assert kwargs["source_filename"] == "Student_Handbook.pdf"
    source = _sources_from_chunks(
        [
            RetrievedChunk(
                document_id=result.document_id,
                title="Validation of Subjects",
                source_filename="Student_Handbook.pdf",
                chunk_index=0,
                text="Validation of Subjects\nStudents must validate enrolled subjects.",
                relevance_score=0.9,
                metadata={
                    "document_id": result.document_id,
                    "page_number": 40,
                    "source_section": "Validation of Subjects",
                },
            )
        ]
    )[0]
    assert source["pdf_available"] is True
    assert source["source_view_url"] == f"/documents/{result.document_id}/source?page=40#page=40"


def test_source_page_preview_returns_only_requested_page(tmp_path, monkeypatch, auth_student):
    import fitz

    monkeypatch.setattr(
        "app.services.document_storage.settings.documents_persist_dir",
        str(tmp_path / "docs"),
    )
    initialize_database()
    pdf = fitz.open()
    for label in ("page-one", "page-two", "page-three"):
        page = pdf.new_page()
        page.insert_text((72, 72), label)
    pdf_bytes = pdf.tobytes()
    pdf.close()

    doc_id = str(uuid.uuid4())
    persist_uploaded_document(
        pdf_bytes,
        document_id=doc_id,
        filename="Citizens_Charter_2026.pdf",
        content_type="application/pdf",
        document_type="citizen_charter",
        title="Citizen’s Charter 2026",
        page_count=3,
    )

    response = client.get(f"/documents/{doc_id}/source/page/2")
    assert response.status_code == 200
    assert "application/pdf" in (response.headers.get("content-type") or "")
    assert response.headers.get("X-Source-Page") == "2"
    assert response.headers.get("X-Source-Page-Only") == "true"

    opened = fitz.open(stream=response.content, filetype="pdf")
    try:
        assert opened.page_count == 1
        assert "page-two" in opened[0].get_text()
        assert "page-one" not in opened[0].get_text()
    finally:
        opened.close()

    assert source_page_url(doc_id, 2) == f"/documents/{doc_id}/source/page/2"
