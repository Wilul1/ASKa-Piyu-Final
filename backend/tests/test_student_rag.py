from unittest.mock import patch

from app.services.chroma_store import RetrievedChunk
from app.services.rag_answer import generate_answer
from app.services.student.question_service import EmptyKnowledgeBaseError, answer_student_question


def test_generate_answer_no_context():
    answer = generate_answer("What is enrollment?", [])
    assert "could not find" in answer.lower()


def test_generate_answer_with_context():
    contexts = [
        RetrievedChunk(
            document_id="1",
            title="Handbook",
            source_filename="h.pdf",
            chunk_index=0,
            text="Students must complete enrollment forms.",
            relevance_score=0.9,
        )
    ]
    answer = generate_answer("How do I enroll?", contexts)
    assert "enrollment" in answer.lower() or "Handbook" in answer


@patch("app.services.student.question_service.get_knowledge_base_store")
def test_answer_requires_indexed_kb(mock_get_store):
    store = mock_get_store.return_value
    store.chunk_count = 0
    try:
        answer_student_question("test?")
        assert False, "expected EmptyKnowledgeBaseError"
    except EmptyKnowledgeBaseError:
        pass


@patch("app.services.student.question_service.generate_answer", return_value="ok")
@patch("app.services.student.question_service.get_knowledge_base_store")
def test_answer_student_question_filters_unpublished_and_audience(
    mock_get_store, _mock_answer
):
    store = mock_get_store.return_value
    store.chunk_count = 3
    store.search.return_value = [
        RetrievedChunk(
            document_id="faq:draft",
            title="Draft FAQ",
            source_filename="t",
            chunk_index=0,
            text="draft",
            relevance_score=0.9,
            metadata={"article_id": "missing", "article_type": "faq", "audience": "both"},
        ),
        RetrievedChunk(
            document_id="handbook",
            title="Handbook",
            source_filename="h.pdf",
            chunk_index=0,
            text="Students enroll online.",
            relevance_score=0.8,
            metadata={"audience": "student"},
        ),
        RetrievedChunk(
            document_id="faculty-only",
            title="Faculty Manual",
            source_filename="f.pdf",
            chunk_index=0,
            text="Faculty load rules.",
            relevance_score=0.7,
            metadata={"audience": "faculty"},
        ),
    ]

    with patch(
        "app.services.article_rag_indexer.filter_unpublished_faq_chunks",
        side_effect=lambda chunks: [c for c in chunks if not str(c.document_id).startswith("faq:")],
    ):
        result = answer_student_question("enroll?", user_role="student")

    assert [c.document_id for c in result.sources] == ["handbook"]
