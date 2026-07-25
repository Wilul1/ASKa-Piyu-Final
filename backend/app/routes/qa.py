"""Production ASKa-Piyu QA chatbot endpoint."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.config import settings
from app.models.db_models import User
from app.models.schemas import QAAskRequest, QAAskResponse
from app.services.auth import get_optional_user, require_admin_user
from app.services.chroma_store import get_knowledge_base_store
from app.services.qa.question_answering import answer_qa_question, _citations_from_sources
from app.services.qa_rate_limit import enforce_qa_rate_limit
from app.services.student.question_service import EmptyKnowledgeBaseError


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/qa", tags=["ASKa-Piyu QA"])


@router.get("/health", summary="Check ASKa-Piyu QA readiness")
async def qa_health(_: User = Depends(require_admin_user)) -> dict:
    store = get_knowledge_base_store()
    return {
        "groq_configured": bool(settings.groq_api_key),
        "model": settings.groq_model,
        "retrieval_ready": store.chunk_count > 0,
    }


@router.post(
    "/ask",
    response_model=QAAskResponse,
    response_model_exclude_none=True,
    summary="Ask ASKa-Piyu (guests and signed-in users)",
)
async def qa_ask(
    payload: QAAskRequest,
    request: Request,
    debug: bool | None = Query(default=None),
    current_user: User | None = Depends(get_optional_user),
) -> QAAskResponse:
    # Guests use the student audience; login is not required for Ask.
    enforce_qa_rate_limit(request, current_user)
    user_role = (current_user.role if current_user is not None else "student") or "student"

    try:
        history = [
            {"role": item.role, "content": item.content}
            for item in (payload.history or [])
        ]
        result = answer_qa_question(
            payload.question,
            user_role=user_role,
            history=history,
        )
    except EmptyKnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("QA request failed")
        raise HTTPException(
            status_code=500,
            detail="QA request failed. Please try again later.",
        ) from exc

    # Retrieval internals only for admins — never for students/faculty/office/guests.
    wants_debug = bool(payload.debug if debug is None else debug)
    debug_enabled = (
        wants_debug
        and current_user is not None
        and (current_user.role or "").strip().lower() == "admin"
    )
    sources = result.sources or []
    citations = _citations_from_sources(sources)
    return QAAskResponse(
        answer=result.answer,
        sources=sources,
        citations=citations,
        confidence=result.confidence,
        retrieved_chunks=result.retrieved_chunks if debug_enabled else None,
        normalized_query=result.normalized_query if debug_enabled else None,
        expanded_query=result.expanded_query if debug_enabled else None,
        matched_expansion_rules=result.matched_expansion_rules if debug_enabled else None,
        broad_query=result.broad_query if debug_enabled else None,
        broad_query_reason=result.broad_query_reason if debug_enabled else None,
        selected_context_count=result.selected_context_count if debug_enabled else None,
        grouped_context_summary=result.grouped_context_summary if debug_enabled else None,
        detected_intent=result.detected_intent if debug_enabled else None,
        collection_mode=result.collection_mode if debug_enabled else None,
        collection_articles=result.collection_articles if debug_enabled else None,
        collection_chunk_count=result.collection_chunk_count if debug_enabled else None,
        group_count=result.group_count if debug_enabled else None,
        program_scope=result.program_scope if debug_enabled else None,
        query_expansions_used=result.query_expansions_used if debug_enabled else None,
        rerank_reasons=result.rerank_reasons if debug_enabled else None,
        degraded=bool(result.fallback_used),
        fallback_used=result.fallback_used if debug_enabled else None,
        fallback_reason=result.fallback_reason if debug_enabled else None,
        out_of_scope_detected=result.out_of_scope_detected if debug_enabled else None,
        ticket_routing=result.ticket_routing,
    )
