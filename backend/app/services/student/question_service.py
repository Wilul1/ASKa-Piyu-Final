"""
Student question flow.

Question → ChromaDB search → AI answer

No OCR. No document upload. Knowledge must already be indexed by admin.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import settings
from app.services.chroma_store import RetrievedChunk, get_knowledge_base_store
from app.services.rag_answer import generate_answer


@dataclass
class QuestionAnswerResult:
    question: str
    answer: str
    sources: list[RetrievedChunk]


class EmptyKnowledgeBaseError(ValueError):
    pass


def answer_student_question(question: str) -> QuestionAnswerResult:
    store = get_knowledge_base_store()

    if store.chunk_count == 0:
        raise EmptyKnowledgeBaseError(
            "Knowledge base is empty. An administrator must ingest documents first."
        )

    contexts = store.search(question.strip(), top_k=settings.rag_top_k)
    answer = generate_answer(question, contexts)

    return QuestionAnswerResult(
        question=question.strip(),
        answer=answer,
        sources=contexts,
    )
