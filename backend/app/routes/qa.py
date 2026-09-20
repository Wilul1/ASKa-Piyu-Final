"""Production ASKa-Piyu QA chatbot endpoint."""

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request

from app.config import settings
from app.models.db_models import User
from app.models.schemas import CitationVerificationStatusResponse, QAAskRequest, QAAskResponse
from app.services.auth import get_optional_user, require_admin_user
from app.services.chroma_store import get_knowledge_base_store
from app.services.qa import citation_verification_jobs
from app.services.qa.question_answering import (
    EmptyKnowledgeBaseError,
    answer_qa_question,
    _citations_from_sources,
)
from app.services.qa_rate_limit import enforce_qa_rate_limit


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
    background_tasks: BackgroundTasks,
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
        # Populated in-place by answer_qa_question only when
        # citation_verification_mode is "async_shadow"/"async_llm" -- see
        # question_answering._display_sources_for_answer. Read AFTER the
        # call returns, never during, since answer_qa_question runs
        # synchronously on a worker thread below.
        async_verification_sink: dict = {}
        # answer_qa_question is sync (embeddings + HTTP). Run off the event
        # loop so health checks and KB routes stay responsive during slow LLM calls.
        result = await asyncio.to_thread(
            answer_qa_question,
            payload.question,
            user_role=user_role,
            history=history,
            client_active_service=payload.active_service,
            async_verification_sink=async_verification_sink,
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
    verification_id = citation_verification_jobs.schedule_verification(
        background_tasks, async_verification_sink
    )
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
        active_service=result.active_service,
        citation_status=result.citation_status,
        citation_verification_id=verification_id,
    )


@router.get(
    "/citation-verifications/{verification_id}",
    response_model=CitationVerificationStatusResponse,
    response_model_exclude_none=True,
    summary="Poll the status of an async Citation V2 verification job",
)
async def qa_citation_verification_status(
    verification_id: str,
) -> CitationVerificationStatusResponse:
    # Capability-based access only, by design -- see
    # citation_verification_jobs.py and the async-architecture investigation
    # artifact. An unknown, malformed, expired, or restart-lost id all
    # resolve identically to "unknown"; never a different error shape that
    # would let a caller distinguish "never existed" from "expired".
    status, safe_citations = citation_verification_jobs.status_and_citations_for_poll(
        verification_id
    )
    return CitationVerificationStatusResponse(
        status=status,
        citations=[
            {
                "citation_id": c.citation_id,
                "title": c.title,
                "source_section": c.source_section,
                "source_filename": c.source_filename,
            }
            for c in safe_citations
        ],
    )
