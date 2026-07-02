"""Production ASKa-Piyu QA chatbot endpoint."""

from fastapi import APIRouter, HTTPException, Query

from app.config import settings
from app.models.schemas import QAAskRequest, QAAskResponse
from app.services.chroma_store import get_knowledge_base_store
from app.services.qa.question_answering import answer_qa_question
from app.services.student.question_service import EmptyKnowledgeBaseError


router = APIRouter(prefix="/qa", tags=["ASKa-Piyu QA"])


@router.get("/health", summary="Check ASKa-Piyu QA readiness")
async def qa_health() -> dict:
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
    summary="Ask ASKa-Piyu",
)
async def qa_ask(
    payload: QAAskRequest,
    debug: bool | None = Query(default=None),
) -> QAAskResponse:
    try:
        result = answer_qa_question(payload.question)
    except EmptyKnowledgeBaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"QA request failed: {exc}") from exc

    debug_enabled = payload.debug if debug is None else debug
    return QAAskResponse(
        answer=result.answer,
        sources=result.sources,
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
        fallback_used=result.fallback_used if debug_enabled else None,
        fallback_reason=result.fallback_reason if debug_enabled else None,
        out_of_scope_detected=result.out_of_scope_detected if debug_enabled else None,
        ticket_routing=result.ticket_routing,
    )
