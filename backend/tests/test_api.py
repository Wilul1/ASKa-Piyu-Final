import asyncio
import hashlib
import logging
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import DOTENV_PATH, settings
from app.main import app, validate_startup_configuration
from app.models.schemas import StructuredDocumentSchema
from app.services.admin.knowledge_base_pipeline import KnowledgeBaseIngestResult
from app.services.chroma_store import RetrievedChunk
from app.services.student.question_service import QuestionAnswerResult

client = TestClient(app)
ADMIN_HEADERS = {"X-Admin-Key": "test-admin-key"}
PIPELINE_STAGES = [
    {"key": "extract", "label": "OCR/PDF extraction", "status": "completed", "detail": "digital"},
    {"key": "clean", "label": "Automatic cleaning", "status": "completed", "detail": None},
    {"key": "structure", "label": "LLM structuring", "status": "completed", "detail": "deterministic"},
    {"key": "review", "label": "Admin review/edit", "status": "needs_review", "detail": None},
    {"key": "index", "label": "Index to ChromaDB", "status": "waiting", "detail": None},
]


def test_health():
    with patch("app.services.chroma_store.get_knowledge_base_store") as mock_get:
        mock_get.return_value.chunk_count = 3
        response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "admin" in data["flows"]
    assert "student" in data["flows"]


@patch("app.main.get_database_health")
def test_database_health(mock_database_health):
    mock_database_health.return_value = {
        "status": "ok",
        "configured": True,
        "database_url": "postgresql+psycopg://postgres:***@localhost:5432/aska_piyu",
    }

    response = client.get("/health/database")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert "password" not in response.text


def test_startup_warns_when_groq_model_configured_without_key(caplog):
    caplog.set_level(logging.WARNING)
    with (
        patch("app.main.settings.admin_api_key", "test-admin-key"),
        patch("app.main.settings.groq_model", "llama-3.3-70b-versatile"),
        patch("app.main.settings.groq_api_key", None),
    ):
        asyncio.run(validate_startup_configuration())

    assert "ASKA_GROQ_API_KEY is missing" in caplog.text


def test_settings_loads_backend_dotenv_with_absolute_path():
    env_file = settings.model_config.get("env_file")

    assert Path(env_file).is_absolute()
    assert Path(env_file) == DOTENV_PATH
    assert DOTENV_PATH.name == ".env"
    assert DOTENV_PATH.parent.name == "backend"


def test_startup_warns_when_admin_key_missing(caplog):
    caplog.set_level(logging.INFO)
    with (
        patch("app.main.settings.admin_api_key", ""),
        patch("app.main.settings.groq_model", ""),
    ):
        asyncio.run(validate_startup_configuration())

    assert "ASKA_ADMIN_API_KEY is missing" in caplog.text
    assert "Admin endpoints are disabled" in caplog.text
    assert "Configured admin key: False" in caplog.text
    assert "Admin key length: 0" in caplog.text
    assert str(DOTENV_PATH) in caplog.text


def test_startup_logs_admin_key_configured_without_secret(caplog):
    caplog.set_level(logging.INFO)
    with (
        patch("app.main.settings.admin_api_key", "my-secret-admin-key"),
        patch("app.main.settings.groq_model", ""),
    ):
        asyncio.run(validate_startup_configuration())

    assert "Configured admin key: True" in caplog.text
    assert "Admin key length: 19" in caplog.text
    expected_prefix = hashlib.sha256("my-secret-admin-key".encode("utf-8")).hexdigest()[:8]
    assert f"Admin key sha256 prefix: {expected_prefix}" in caplog.text
    assert "my-secret-admin-key" not in caplog.text


@patch("app.config.settings.admin_api_key", "my-secret-admin-key")
def test_admin_debug_config_returns_safe_diagnostics_without_auth():
    response = client.get("/admin/debug/config")

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "cwd",
        "dotenv_path",
        "admin_key_loaded",
        "admin_key_length",
        "admin_key_sha256_prefix",
        "header_name",
    }
    assert data["admin_key_loaded"] is True
    assert data["admin_key_length"] == 19
    assert data["admin_key_sha256_prefix"] == hashlib.sha256(
        "my-secret-admin-key".encode("utf-8")
    ).hexdigest()[:8]
    assert data["header_name"] == "x-admin-key"
    assert data["dotenv_path"] == str(DOTENV_PATH)
    assert "my-secret-admin-key" not in response.text


@patch("app.routes.qa.settings.groq_api_key", "test-groq-key")
@patch("app.routes.qa.settings.groq_model", "llama-3.3-70b-versatile")
@patch("app.routes.qa.get_knowledge_base_store")
def test_qa_health(mock_store):
    mock_store.return_value.chunk_count = 485

    response = client.get("/qa/health")

    assert response.status_code == 200
    assert response.json() == {
        "groq_configured": True,
        "model": "llama-3.3-70b-versatile",
        "retrieval_ready": True,
    }


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.extract_document_preview")
def test_admin_extract(mock_extract):
    mock_extract.return_value = {
        "document_type": "pdf",
        "raw_text": "Raw OCR",
        "cleaned_text": "Service:\n  LSPU Entrance Test",
        "review_text": "Service:\n  LSPU Entrance Test",
        "extracted_text": "Service:\n  LSPU Entrance Test",
        "page_count": 2,
        "extraction_method": "digital",
        "structuring_method": "deterministic",
        "pipeline_stages": PIPELINE_STAGES,
        "structured": StructuredDocumentSchema(
            fields=[],
            formatted_text="Service:\n  LSPU Entrance Test",
        ),
        "validation_report": {
            "document_type": "pdf",
            "total_knowledge_units": 1,
            "total_chunks": 1,
            "average_chunk_words": 5,
            "largest_chunk_words": 5,
            "smallest_chunk_words": 5,
            "missing_metadata_count": 0,
            "toc_like_units_count": 0,
            "empty_units_count": 0,
            "suspicious_units_count": 0,
            "oversized_chunks_count": 0,
            "status": "Ready for Indexing",
        },
        "knowledge_units": [],
        "chunk_preview": [],
        "kb_statistics": {
            "documents_indexed": 0,
            "total_chunks_indexed": 0,
            "embedding_model": "ChromaDB default embedding function",
            "vector_store": "ChromaDB",
            "last_indexed_document": None,
        },
    }
    response = client.post(
        "/admin/knowledge-base/extract",
        headers=ADMIN_HEADERS,
        files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["flow"] == "admin_extraction"
    assert data["document_type"] == "pdf"
    assert data["pipeline_stages"][-1]["label"] == "Index to ChromaDB"
    assert data["validation_report"]["status"] == "Ready for Indexing"


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.ingest_document_into_knowledge_base")
def test_admin_ingest(mock_ingest):
    mock_ingest.return_value = KnowledgeBaseIngestResult(
        document_id="doc-1",
        document_type="pdf",
        source_filename="handbook.pdf",
        title="Student Handbook",
        chunks_indexed=12,
        page_count=40,
        extraction_method="digital",
        structuring_method="deterministic",
        pipeline_stages=PIPELINE_STAGES,
        extracted_text_preview="Service:\n  LSPU Entrance Test",
        structured=StructuredDocumentSchema(
            fields=[],
            formatted_text="Service:\n  LSPU Entrance Test",
        ),
        validation_report={
            "document_type": "pdf",
            "total_knowledge_units": 1,
            "total_chunks": 1,
            "average_chunk_words": 5,
            "largest_chunk_words": 5,
            "smallest_chunk_words": 5,
            "missing_metadata_count": 0,
            "toc_like_units_count": 0,
            "empty_units_count": 0,
            "suspicious_units_count": 0,
            "oversized_chunks_count": 0,
            "status": "Ready for Indexing",
        },
        knowledge_units=[],
        chunk_preview=[],
        kb_statistics={
            "documents_indexed": 1,
            "total_chunks_indexed": 12,
            "embedding_model": "ChromaDB default embedding function",
            "vector_store": "ChromaDB",
            "last_indexed_document": {"title": "Student Handbook"},
        },
    )
    response = client.post(
        "/admin/knowledge-base/ingest",
        headers=ADMIN_HEADERS,
        files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
        data={"title": "Student Handbook"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["flow"] == "admin_knowledge_base_ingest"
    assert data["chunks_indexed"] == 12
    assert data["pipeline_stages"]
    assert data["kb_statistics"]["total_chunks_indexed"] == 12


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.retrieval_test")
def test_admin_retrieval_test(mock_retrieval):
    mock_retrieval.return_value = {
        "question": "What are the requirements for freshmen?",
        "top_k": 5,
        "results": [
            {
                "rank": 1,
                "title": "Freshman Admission Requirements",
                "similarity_score": 0.91,
                "hierarchy_path": "Chapter 3 > Admission",
                "page_start": 10,
                "page_end": 11,
                "content_preview": "Freshmen must submit credentials.",
                "content": "Freshmen must submit credentials. Full chunk text remains available.",
            }
        ],
        "kb_statistics": {
            "documents_indexed": 1,
            "total_chunks_indexed": 12,
            "embedding_model": "ChromaDB default embedding function",
            "vector_store": "ChromaDB",
            "last_indexed_document": {"title": "Student Handbook"},
        },
    }

    response = client.post(
        "/admin/kb/retrieval-test",
        headers=ADMIN_HEADERS,
        json={"question": "What are the requirements for freshmen?", "top_k": 5},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["flow"] == "admin_retrieval_test"
    assert data["results"][0]["rank"] == 1
    assert data["results"][0]["content_preview"] == "Freshmen must submit credentials."
    assert data["results"][0]["content"].endswith("Full chunk text remains available.")


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", None)
def test_admin_extract_requires_key():
    response = client.post(
        "/admin/knowledge-base/extract",
        files={"file": ("handbook.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 503


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_endpoint_missing_header_returns_401():
    response = client.delete("/admin/chroma/reset")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid admin key."


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
def test_admin_endpoint_wrong_header_returns_401():
    response = client.delete("/admin/chroma/reset", headers={"x-admin-key": "wrong-key"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid admin key."


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "test-admin-key")
@patch("app.routes.admin.knowledge_base.get_knowledge_base_store")
def test_admin_endpoint_correct_header_is_allowed(mock_get_store):
    mock_get_store.return_value.reset_collection.return_value = {
        "collection": "aska_knowledge_base",
        "vectors_removed": 0,
        "timestamp": "2026-06-28T00:00:00+00:00",
    }

    response = client.delete("/admin/chroma/reset", headers={"x-admin-key": "test-admin-key"})

    assert response.status_code == 200
    assert response.json()["success"] is True


@patch("app.routes.admin.knowledge_base.settings.admin_api_key", "")
def test_admin_endpoint_missing_environment_key_returns_503():
    response = client.delete("/admin/chroma/reset", headers={"x-admin-key": "test-admin-key"})

    assert response.status_code == 503
    assert "ASKA_ADMIN_API_KEY" in response.json()["detail"]


def test_admin_openapi_documents_x_admin_key_header():
    operation = client.get("/openapi.json").json()["paths"]["/admin/chroma/reset"]["delete"]
    header = next(param for param in operation["parameters"] if param["in"] == "header")

    assert header["name"] == "x-admin-key"
    assert header["description"] == "Administrator API key. Must match ASKA_ADMIN_API_KEY."


@patch("app.routes.student.chat.answer_student_question")
def test_student_ask(mock_answer):
    mock_answer.return_value = QuestionAnswerResult(
        question="How do I enroll?",
        answer="Based on official documents, enrollment requires...",
        sources=[
            RetrievedChunk(
                document_id="doc-1",
                title="Handbook",
                source_filename="handbook.pdf",
                chunk_index=0,
                text="Enrollment steps...",
                relevance_score=0.91,
            )
        ],
    )
    response = client.post(
        "/student/ask",
        json={"question": "How do I enroll?"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["flow"] == "student_question"
    assert data["answer"]
    assert len(data["sources"]) == 1


@patch("app.routes.student.chat.answer_student_question")
def test_student_ask_empty_kb(mock_answer):
    from app.services.student.question_service import EmptyKnowledgeBaseError

    mock_answer.side_effect = EmptyKnowledgeBaseError("Knowledge base is empty.")
    response = client.post("/student/ask", json={"question": "Hello?"})
    assert response.status_code == 503


@patch("app.routes.qa.answer_qa_question")
def test_qa_ask_endpoint_defaults_to_student_response(mock_answer):
    from app.services.qa.question_answering import QAResult

    mock_answer.return_value = QAResult(
        answer="Students should submit an excuse slip and medical certificate.",
        sources=[{"title": "Attendance Policy", "path": "Academic Policies > Attendance", "page": 46}],
        confidence="high",
        retrieved_chunks=[
            {
                "rank": 1,
                "title": "Attendance Policy",
                "path": "Academic Policies > Attendance",
                "page": 46,
                "content_preview": "Students should submit an excuse slip.",
                "original_score": 0.82,
                "reranked_score": 0.94,
                "boost_reasons": ["attendance_policy_match"],
                "selected_for_context": True,
                "context_filter_reasons": ["keep_rank_1"],
                "document_id": "doc-1",
                "source_filename": "handbook.pdf",
                "chunk_index": 4,
            }
        ],
        normalized_query="i absent due illness what should submit excuse slip",
        expanded_query="I was absent due to illness. What should I do? attendance excuse slip medical certificate osas",
        matched_expansion_rules=["attendance_excuse_slip"],
        query_expansions_used=["attendance_excuse_slip"],
        rerank_reasons=[
            {
                "rank": 1,
                "title": "Attendance Policy",
                "reranked_score": 0.94,
                "reasons": ["attendance_policy_match"],
            }
        ],
        fallback_used=True,
        fallback_reason="rate_limited",
        out_of_scope_detected=False,
    )

    response = client.post("/qa/ask", json={"question": "I was absent due to illness. What should I do?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"]
    assert data["confidence"] == "high"
    assert data["sources"][0]["title"] == "Attendance Policy"
    assert set(data) == {"answer", "sources", "confidence"}


@patch("app.routes.qa.answer_qa_question")
def test_qa_ask_endpoint_returns_debug_chunks_when_body_debug_enabled(mock_answer):
    from app.services.qa.question_answering import QAResult

    mock_answer.return_value = QAResult(
        answer="Students should submit an excuse slip and medical certificate.",
        sources=[{"title": "Attendance Policy", "path": "Academic Policies > Attendance", "page": 46}],
        confidence="high",
        retrieved_chunks=[
            {
                "rank": 1,
                "title": "Attendance Policy",
                "path": "Academic Policies > Attendance",
                "page": 46,
                "content_preview": "Students should submit an excuse slip.",
                "original_score": 0.82,
                "reranked_score": 0.94,
                "boost_reasons": ["attendance_policy_match"],
                "selected_for_context": True,
                "context_filter_reasons": ["keep_rank_1"],
                "document_id": "doc-1",
                "source_filename": "handbook.pdf",
                "chunk_index": 4,
            }
        ],
        normalized_query="i absent due illness what should submit excuse slip",
        expanded_query="I was absent due to illness. What should I do? attendance excuse slip medical certificate osas",
        matched_expansion_rules=["attendance_excuse_slip"],
        query_expansions_used=["attendance_excuse_slip"],
        rerank_reasons=[
            {
                "rank": 1,
                "title": "Attendance Policy",
                "reranked_score": 0.94,
                "reasons": ["attendance_policy_match"],
            }
        ],
        fallback_used=True,
        fallback_reason="rate_limited",
        out_of_scope_detected=False,
    )

    response = client.post(
        "/qa/ask",
        json={"question": "I was absent due to illness. What should I do?", "debug": True},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["retrieved_chunks"][0]["boost_reasons"] == ["attendance_policy_match"]
    assert data["retrieved_chunks"][0]["original_score"] == 0.82
    assert data["retrieved_chunks"][0]["reranked_score"] == 0.94
    assert data["retrieved_chunks"][0]["selected_for_context"] is True
    assert data["retrieved_chunks"][0]["context_filter_reasons"] == ["keep_rank_1"]
    assert data["normalized_query"]
    assert "excuse slip" in data["expanded_query"]
    assert data["matched_expansion_rules"] == ["attendance_excuse_slip"]
    assert data["query_expansions_used"] == ["attendance_excuse_slip"]
    assert data["rerank_reasons"][0]["reasons"] == ["attendance_policy_match"]
    assert data["fallback_used"] is True
    assert data["fallback_reason"] == "rate_limited"
    assert data["out_of_scope_detected"] is False


@patch("app.routes.qa.answer_qa_question")
def test_qa_ask_endpoint_returns_debug_chunks_when_query_debug_enabled(mock_answer):
    from app.services.qa.question_answering import QAResult

    mock_answer.return_value = QAResult(
        answer="Students should submit an excuse slip and medical certificate.",
        sources=[{"title": "Attendance Policy", "path": "Academic Policies > Attendance", "page": 46}],
        confidence="medium",
        retrieved_chunks=[
            {
                "rank": 1,
                "title": "Attendance Policy",
                "path": "Academic Policies > Attendance",
                "page": 46,
                "content_preview": "Students should submit an excuse slip.",
                "original_score": 0.82,
                "reranked_score": 0.94,
                "boost_reasons": ["attendance_policy_match"],
                "selected_for_context": True,
                "context_filter_reasons": ["keep_rank_1"],
                "document_id": "doc-1",
                "source_filename": "handbook.pdf",
                "chunk_index": 4,
            }
        ],
    )

    response = client.post(
        "/qa/ask?debug=true",
        json={"question": "I was absent due to illness. What should I do?"},
    )

    assert response.status_code == 200
    assert "retrieved_chunks" in response.json()


@patch("app.routes.qa.answer_qa_question")
def test_qa_ask_endpoint_returns_program_scope_debug_when_enabled(mock_answer):
    from app.services.qa.question_answering import QAResult

    mock_answer.return_value = QAResult(
        answer="Engineering programs are listed by college.",
        sources=[{"title": "College of Engineering", "path": "Curricular Offerings > College of Engineering"}],
        confidence="high",
        retrieved_chunks=[],
        detected_intent="PROGRAM_COLLECTION",
        collection_mode=True,
        program_scope={
            "detected_college_scope": "college of engineering",
            "detected_campus_scope": None,
            "scope_filter_applied": True,
            "chunks_before_scope_filter": 6,
            "chunks_after_scope_filter": 2,
            "excluded_scope_reasons": [{"title": "College of Agriculture", "reason": "college_scope_mismatch"}],
        },
    )

    response = client.post(
        "/qa/ask?debug=true",
        json={"question": "What programs does the College of Engineering offer?"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["detected_intent"] == "PROGRAM_COLLECTION"
    assert data["collection_mode"] is True
    assert data["program_scope"]["detected_college_scope"] == "college of engineering"
    assert data["program_scope"]["chunks_before_scope_filter"] == 6
    assert data["program_scope"]["chunks_after_scope_filter"] == 2
