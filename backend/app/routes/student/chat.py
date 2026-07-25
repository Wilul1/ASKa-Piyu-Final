"""
Student routes — question answering flow only.

Delegates to the same QA pipeline as ``POST /qa/ask`` (filters + answer engine).
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app.models.db_models import User
from app.models.schemas import AskQuestionRequest, AskQuestionResponse, ErrorResponse, SourceChunk
from app.services.auth import get_current_user
from app.services.qa.question_answering import answer_qa_question
from app.services.qa_rate_limit import enforce_qa_rate_limit
from app.services.student.question_service import EmptyKnowledgeBaseError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/student", tags=["Student — Ask ASKa-Piyu"])


def _source_chunk_index(item: dict) -> int:
    """Prefer real chunk_index; do not treat 0 as missing or confuse with page."""
    raw = item.get("chunk_index")
    if raw is None:
        raw = item.get("page")
    try:
        return int(raw if raw is not None else 0)
    except (TypeError, ValueError):
        return 0


@router.post(
    "/ask",
    response_model=AskQuestionResponse,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="[Student] Ask a question (RAG over existing knowledge base)",
)
async def student_ask_question(
    body: AskQuestionRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AskQuestionResponse:
    """Authenticated ask path — same pipeline and safety filters as ``POST /qa/ask``."""
    enforce_qa_rate_limit(request, current_user)

    try:
        history = [
            {"role": item.role, "content": item.content}
            for item in (body.history or [])
        ]
        result = answer_qa_question(
            body.question,
            user_role=current_user.role,
            history=history,
        )
    except EmptyKnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Student ask failed")
        raise HTTPException(
            status_code=500,
            detail="Question answering failed. Please try again later.",
        ) from exc

    sources: list[SourceChunk] = []
    for item in result.sources or []:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet") or item.get("text") or item.get("excerpt") or "")
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        sources.append(
            SourceChunk(
                document_id=str(item.get("document_id") or item.get("id") or ""),
                title=str(item.get("title") or item.get("source") or "Source"),
                source_filename=str(item.get("source_filename") or item.get("filename") or ""),
                chunk_index=_source_chunk_index(item),
                snippet=snippet,
                relevance_score=float(item.get("relevance_score") or item.get("score") or 0.0),
            )
        )

    return AskQuestionResponse(
        status="success",
        flow="student_question",
        question=body.question.strip(),
        answer=result.answer,
        sources=sources,
        confidence=result.confidence,
        degraded=bool(result.fallback_used),
    )
