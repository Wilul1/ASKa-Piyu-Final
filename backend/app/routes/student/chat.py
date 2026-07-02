"""
Student routes — question answering flow only.

Question → ChromaDB search → AI response

No OCR. No document upload.
"""

from fastapi import APIRouter, HTTPException

from app.models.schemas import AskQuestionRequest, AskQuestionResponse, ErrorResponse, SourceChunk
from app.services.student.question_service import EmptyKnowledgeBaseError, answer_student_question

router = APIRouter(prefix="/student", tags=["Student — Ask ASKa-Piyu"])


@router.post(
    "/ask",
    response_model=AskQuestionResponse,
    responses={422: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    summary="[Student] Ask a question (RAG over existing knowledge base)",
)
async def student_ask_question(body: AskQuestionRequest) -> AskQuestionResponse:
    """
    Student Q&A flow:

    **Question → ChromaDB retrieval → AI answer**

    Institutional documents must already be ingested by an administrator.
    This endpoint does not accept file uploads or run OCR.
    """
    try:
        result = answer_student_question(body.question)
    except EmptyKnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources = [
        SourceChunk(
            document_id=s.document_id,
            title=s.title,
            source_filename=s.source_filename,
            chunk_index=s.chunk_index,
            snippet=s.text[:300] + ("..." if len(s.text) > 300 else ""),
            relevance_score=s.relevance_score,
        )
        for s in result.sources
    ]

    return AskQuestionResponse(
        status="success",
        flow="student_question",
        question=result.question,
        answer=result.answer,
        sources=sources,
    )
