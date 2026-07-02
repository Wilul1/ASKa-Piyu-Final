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
