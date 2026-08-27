"""
Admin routes — knowledge base creation flow only.

OCR / PDF extraction → clean → chunk → embeddings → ChromaDB
"""

import asyncio
import hmac
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile

from app.config import settings
from app.db.session import get_session_factory
from app.models.db_models import User
from app.models.schemas import (
    ErrorResponse,
    AdminBulkArticlesRequest,
    AdminBulkArticlesResponse,
    AdminBulkArticleResultItem,
    AdminBulkIdsRequest,
    AdminPublishedArticleCreate,
    AdminPublishedArticleUpdate,
    AdminPublishedArticleSchema,
    GenerateArticleCandidatesFromPreviewRequest,
    ExtractDocumentResponse,
    IngestKnowledgeBaseResponse,
    KnowledgeBaseStatisticsSchema,
    RetrievalTestRequest,
    RetrievalTestResponse,
)
from app.services.admin.knowledge_base_pipeline import (
    extract_document_preview,
    ingest_document_into_knowledge_base,
    knowledge_base_statistics,
    retrieval_test,
)
from app.services.admin.article_candidate_generator import (
    find_similar_article,
    generate_candidates_from_upload,
    generate_candidates_from_preview,
)
from app.services.chroma_store import get_knowledge_base_store
from app.services.document_ingestion import (
    EmptyDocumentError,
    UnsupportedDocumentError,
)
from app.services.auth import decode_access_token

router = APIRouter(prefix="/admin/knowledge-base", tags=["Admin — Knowledge Base"])

kb_tools_router = APIRouter(prefix="/admin/kb", tags=["Admin Knowledge Base"])
chroma_router = APIRouter(prefix="/admin/chroma", tags=["Admin ChromaDB"])

logger = logging.getLogger(__name__)

_METADATA_MARKER = "----EXTRACTED METADATA----"
_LOW_QUALITY_BUCKETS = {"low_quality", "low-quality", "needs_cleanup"}
_RAG_ONLY_BUCKETS = {"rag_only", "rag-only"}


def _normalize_planner_bucket(value: str | None) -> str:
    return (value or "").strip().lower()


def _main_article_body(content: str | None) -> str:
    text = content or ""
    if _METADATA_MARKER in text:
        text = text.split(_METADATA_MARKER, 1)[0]
    # Source Information may legitimately include "Page: Not specified".
    lower = text.lower()
    idx = lower.find("source information")
    if idx >= 0:
        text = text[:idx]
    return text


def _embedded_article_metadata(content: str | None) -> dict[str, Any]:
    from app.services.article_content_formatter import extract_embedded_article_metadata

    meta = extract_embedded_article_metadata(content) if content else {}
    return meta if isinstance(meta, dict) else {}


def _content_blocks_publish(content: str | None) -> str | None:
    """Block publish when placeholders / empty structured steps remain."""
    main = _main_article_body(content)
    if not main.strip():
        return "Article content is empty. Correct it and save as draft before publishing."
    if "[NEEDS REVIEW]" in main:
        return (
            "Article still contains [NEEDS REVIEW] placeholders. "
            "Correct the draft before publishing."
        )
    if re.search(r"\bNot specified\b", main):
        return (
            "Article still contains 'Not specified'. "
            "Correct the draft before publishing."
        )
    # Empty / fully unspecified steps block public publish.
    if re.search(
        r"(?im)^\s*(?:\d+\.\s*)?Client Step:\s*Not specified\s*$",
        main,
    ) and re.search(
        r"(?im)^\s*Agency Action:\s*Not specified\s*$",
        main,
    ):
        return (
            "Article steps are empty or still Not specified. "
            "Correct the draft before publishing."
        )
    # Broken OCR / fragment markers often left in unrepaired cleanup bodies.
    if re.search(
        r"(?i)\b(?:ocr\s*error|garbled|illegible|\[?\s*unclear\s*\]?)\b",
        main,
    ):
        return (
            "Article still contains broken OCR fragments. "
            "Correct the draft before publishing."
        )
    return None


def _direct_bucket_publish_blocked(
    *,
    planner_bucket: str | None,
    content: str | None = None,
) -> str | None:
    """Reject direct publish from Low Quality / RAG-only unless promoted after manual draft."""
    meta = _embedded_article_metadata(content)
    bucket = _normalize_planner_bucket(
        planner_bucket
        or str(meta.get("planner_bucket") or meta.get("final_bucket") or "")
    )
    promoted = (
        meta.get("manual_review_from_low_quality") is True
        and str(meta.get("review_status") or "").strip() == "manually_corrected_draft"
        and bucket in {"needs_review", "needs-review", "recommended", "consolidated_parent"}
    )
    if bucket in _LOW_QUALITY_BUCKETS and not promoted:
        return "Low Quality / Cleanup candidates cannot be published directly. Save as a review draft first."
    if bucket in _RAG_ONLY_BUCKETS:
        return "RAG-only sections cannot be published as Knowledge Base articles."
    return None


def _publish_gate_error(
    *,
    content: str | None,
    planner_bucket: str | None = None,
) -> str | None:
    blocked = _direct_bucket_publish_blocked(
        planner_bucket=planner_bucket,
        content=content,
    )
    if blocked:
        return blocked
    return _content_blocks_publish(content)


def _revert_article_to_draft_after_rag_failure(session, article_id: str, exc: BaseException) -> None:
    """Fail-closed: never leave published=true without searchable RAG chunks."""
    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import cleanup_failed_faq_index
    from app.services.ticket_knowledge import sync_ticket_kb_status

    session.rollback()
    cleanup_failed_faq_index(exc, article_id)
    art = session.get(PublishedArticle, article_id)
    if art is None:
        return
    art.published = False
    art.published_at = None
    art.rag_indexed = False
    art.rag_document_id = None
    sync_ticket_kb_status(session, art)
    session.add(art)
    session.commit()


def _rag_publish_failure_detail(_exc: BaseException | None = None) -> str:
    """Public admin message — never embed exception text (paths/DB/Chroma internals)."""
    return (
        "RAG indexing failed; article was reverted to unpublished "
        "(rag_indexed=false). Check server logs for details."
    )


def _public_admin_error(exc: BaseException, *, fallback: str) -> str:
    """Sanitize exception text for admin JSON bodies (no paths/stack internals)."""
    del exc  # logged by caller; never returned
    return fallback


def _admin_internal_error(public_detail: str, exc: BaseException) -> HTTPException:
    logger.error("%s", public_detail, exc_info=exc)
    return HTTPException(status_code=500, detail=public_detail)


def _admin_bad_gateway(public_detail: str, exc: BaseException) -> HTTPException:
    logger.error("%s", public_detail, exc_info=exc)
    return HTTPException(status_code=502, detail=public_detail)


def require_admin_key(
    x_admin_key: str | None = Header(
        default=None,
        alias="x-admin-key",
        description="Administrator API key. Must match ASKA_ADMIN_API_KEY when key auth is enabled.",
    ),
    authorization: str | None = Header(
        default=None,
        alias="authorization",
        description="Bearer token for a logged-in admin or office account.",
    ),
) -> str | None:
    """Authorize KB editor access (admin or office).

    Returns the user id when Bearer auth is used; ``None`` for API-key auth
    (no user actor is available for attribution).

    In production, shared X-Admin-Key auth is disabled unless
    ``ASKA_ALLOW_ADMIN_API_KEY=true``.
    """
    from app.config import admin_api_key_auth_enabled

    configured_key = settings.admin_api_key
    if (
        admin_api_key_auth_enabled()
        and configured_key
        and x_admin_key
    ):
        try:
            key_ok = hmac.compare_digest(x_admin_key, configured_key)
        except (TypeError, ValueError):
            key_ok = False
        if key_ok:
            return None

    if authorization and authorization.lower().startswith("bearer "):
        return _require_kb_editor_bearer_token(authorization.split(" ", 1)[1].strip())

    if x_admin_key and not admin_api_key_auth_enabled():
        raise HTTPException(
            status_code=401,
            detail=(
                "Shared admin API key auth is disabled. "
                "Log in with an admin or office account (Bearer token)."
            ),
        )

    if not configured_key and not admin_api_key_auth_enabled():
        raise HTTPException(
            status_code=401,
            detail="Admin authorization failed. Log in as admin or office staff.",
        )

    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured. Log in as admin or set ASKA_ADMIN_API_KEY.",
        )
    raise HTTPException(status_code=401, detail="Invalid admin key.")


def require_admin_only_key(
    x_admin_key: str | None = Header(
        default=None,
        alias="x-admin-key",
        description="Administrator API key. Must match ASKA_ADMIN_API_KEY when key auth is enabled.",
    ),
    authorization: str | None = Header(
        default=None,
        alias="authorization",
        description="Bearer token for a logged-in admin account.",
    ),
) -> str | None:
    """Authorize destructive admin-only KB operations (reset / full rebuild)."""
    from app.config import admin_api_key_auth_enabled

    configured_key = settings.admin_api_key
    if (
        admin_api_key_auth_enabled()
        and configured_key
        and x_admin_key
    ):
        try:
            key_ok = hmac.compare_digest(x_admin_key, configured_key)
        except (TypeError, ValueError):
            key_ok = False
        if key_ok:
            return None

    if authorization and authorization.lower().startswith("bearer "):
        return _require_admin_bearer_token(authorization.split(" ", 1)[1].strip())

    if x_admin_key and not admin_api_key_auth_enabled():
        raise HTTPException(
            status_code=401,
            detail=(
                "Shared admin API key auth is disabled. "
                "Log in with an admin account (Bearer token)."
            ),
        )

    if not configured_key and not admin_api_key_auth_enabled():
        raise HTTPException(
            status_code=401,
            detail="Admin authorization failed. Log in as admin.",
        )

    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured. Log in as admin or set ASKA_ADMIN_API_KEY.",
        )
    raise HTTPException(status_code=401, detail="Invalid admin key.")


def _require_kb_editor_bearer_token(token: str) -> str:
    """Allow admin or office staff to use extract / generate / article tools."""
    user = _load_user_from_bearer(token)
    role = str(user.role).strip().lower()
    if role not in {"admin", "office"}:
        raise HTTPException(
            status_code=403,
            detail="Only admin or office accounts can use Knowledge Base tools.",
        )
    return str(user.id)


def _require_admin_bearer_token(token: str) -> str:
    """Same revoke/disable rules as get_current_user, plus role=admin."""
    user = _load_user_from_bearer(token)
    if str(user.role).strip().lower() != "admin":
        raise HTTPException(
            status_code=403,
            detail="Only admin accounts can use Knowledge Base Admin tools.",
        )
    return str(user.id)


def _load_user_from_bearer(token: str) -> User:
    try:
        payload = decode_access_token(token)
        session_factory = get_session_factory()
        session = session_factory()
        try:
            user = session.get(User, payload["sub"])
        finally:
            session.close()
    except HTTPException:
        raise HTTPException(status_code=401, detail="Admin authorization failed.") from None
    except Exception:
        raise HTTPException(status_code=401, detail="Admin authorization failed.") from None

    if user is None:
        raise HTTPException(status_code=401, detail="Admin authorization failed.")
    if not bool(getattr(user, "is_active", True)):
        raise HTTPException(status_code=401, detail="Account is disabled.")
    try:
        token_cv_int = int(payload.get("cv", 0))
    except (TypeError, ValueError):
        token_cv_int = 0
    if token_cv_int != int(getattr(user, "credentials_version", 0) or 0):
        raise HTTPException(status_code=401, detail="Authentication token has been revoked.")
    return user


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read()
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.max_upload_bytes // (1024 * 1024)} MB.",
        )
    return content


@router.post(
    "/extract",
    response_model=ExtractDocumentResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="[Admin] Extract text only (preview, no ChromaDB)",
)
async def admin_extract_document(
    file: UploadFile = File(..., description="Handbook, policy PDF, or scanned image"),
    document_type: str | None = Form(
        None,
        description="Knowledge document type: auto, information, procedure, or requirement",
    ),
    preview_file_path: str | None = Form(
        None,
        description="Optional preview path for requirement/form documents",
    ),
    _: None = Depends(require_admin_key),
) -> ExtractDocumentResponse:
    """
    Preview step for admins: run OCR/PDF extraction and cleaning without indexing.

    Use before full ingest, or to verify scan quality.
    """
    content = await _read_upload(file)
    try:
        # OCR/structuring is CPU-bound; keep the event loop free for /health.
        result = await asyncio.to_thread(
            extract_document_preview,
            content,
            filename=file.filename,
            content_type=file.content_type,
            document_type=document_type,
            preview_file_path=preview_file_path,
        )
    except (UnsupportedDocumentError, EmptyDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _admin_internal_error("Document extraction failed.", exc) from exc

    return ExtractDocumentResponse(
        status="success",
        flow="admin_extraction",
        document_type=result["document_type"],
        document_profile=result.get("document_profile"),
        admin_selected_document_type=result.get("admin_selected_document_type"),
        parser_document_type=result.get("parser_document_type"),
        source_type=result.get("source_type"),
        raw_text=result["raw_text"],
        cleaned_text=result["cleaned_text"],
        review_text=result["review_text"],
        extracted_text=result["extracted_text"],
        page_count=result["page_count"],
        extraction_method=result["extraction_method"],
        structuring_method=result["structuring_method"],
        pipeline_stages=result["pipeline_stages"],
        structured=result["structured"],
        diagnostic_report=result.get("diagnostic_report"),
        validation_report=result.get("validation_report"),
        detected_document_type=result.get("detected_document_type"),
        knowledge_units=result.get("knowledge_units") or [],
        chunk_preview=result.get("chunk_preview") or [],
        kb_statistics=result.get("kb_statistics"),
        charter_v2_services=result.get("charter_v2_services") or [],
        charter_v2_detected_count=int(result.get("charter_v2_detected_count") or 0),
        charter_v2_clean_count=int(result.get("charter_v2_clean_count") or 0),
        charter_v2_needs_review_count=int(result.get("charter_v2_needs_review_count") or 0),
        charter_v2_low_quality_count=int(result.get("charter_v2_low_quality_count") or 0),
        charter_v2_rag_only_count=int(result.get("charter_v2_rag_only_count") or 0),
        charter_v2_diagnostics=result.get("charter_v2_diagnostics") or {},
    )


@router.post(
    "/ingest",
    response_model=IngestKnowledgeBaseResponse,
    responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="[Admin] Full ingest into ChromaDB",
)
async def admin_ingest_document(
    file: UploadFile = File(..., description="Document to add to the knowledge base"),
    title: str | None = Form(None, description="Display title (defaults to filename)"),
    reviewed_text: str | None = Form(
        None, description="Admin-reviewed text to index instead of raw OCR output"
    ),
    document_type: str | None = Form(
        None,
        description="Knowledge document type: auto, information, procedure, or requirement",
    ),
    preview_file_path: str | None = Form(
        None,
        description="Optional preview path for requirement/form documents",
    ),
    replace_existing: bool = Form(
        False, description="Replace chunks when document_id is provided"
    ),
    document_id: str | None = Form(
        None, description="Existing document ID to update (requires replace_existing)"
    ),
    _: None = Depends(require_admin_key),
) -> IngestKnowledgeBaseResponse:
    """
    Full admin pipeline:

    **Upload → Extract → Clean → Chunk → Embed → ChromaDB**

    Run at deployment, policy updates, and maintenance — not from the student app.
    """
    content = await _read_upload(file)
    try:
        result = await asyncio.to_thread(
            ingest_document_into_knowledge_base,
            content,
            filename=file.filename,
            content_type=file.content_type,
            title=title,
            reviewed_text=reviewed_text,
            document_type=document_type,
            preview_file_path=preview_file_path,
            replace_existing=replace_existing,
            document_id=document_id,
        )
    except (UnsupportedDocumentError, EmptyDocumentError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise _admin_internal_error("Ingest failed.", exc) from exc

    return IngestKnowledgeBaseResponse(
        status="success",
        flow="admin_knowledge_base_ingest",
        document_id=result.document_id,
        document_type=result.document_type,
        source_filename=result.source_filename,
        title=result.title,
        chunks_indexed=result.chunks_indexed,
        page_count=result.page_count,
        extraction_method=result.extraction_method,
        structuring_method=result.structuring_method,
        pipeline_stages=result.pipeline_stages,
        extracted_text_preview=result.extracted_text_preview,
        structured=result.structured,
        diagnostic_report=result.diagnostic_report,
        validation_report=result.validation_report,
        detected_document_type=result.detected_document_type,
        knowledge_units=result.knowledge_units or [],
        chunk_preview=result.chunk_preview or [],
        kb_statistics=result.kb_statistics,
    )


@kb_tools_router.post(
    "/retrieval-test",
    response_model=RetrievalTestResponse,
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Test retrieval against indexed ChromaDB chunks",
)
async def admin_retrieval_test(
    payload: RetrievalTestRequest,
    _: None = Depends(require_admin_key),
) -> RetrievalTestResponse:
    try:
        result = retrieval_test(payload.question, top_k=payload.top_k)
    except Exception as exc:
        raise _admin_internal_error("Retrieval test failed.", exc) from exc

    return RetrievalTestResponse(
        status="success",
        flow="admin_retrieval_test",
        question=result["question"],
        top_k=result["top_k"],
        results=result["results"],
        kb_statistics=result.get("kb_statistics"),
    )


@kb_tools_router.get(
    "/statistics",
    response_model=KnowledgeBaseStatisticsSchema,
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Knowledge base collection statistics",
)
async def admin_kb_statistics(_: None = Depends(require_admin_key)) -> KnowledgeBaseStatisticsSchema:
    return KnowledgeBaseStatisticsSchema(**knowledge_base_statistics())


@kb_tools_router.post(
    "/rebuild",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Reset and rebuild the ChromaDB knowledge base",
)
async def admin_rebuild_knowledge_base(_: None = Depends(require_admin_only_key)) -> dict:
    started = time.perf_counter()
    collection = settings.chroma_collection_name
    logger.info("Knowledge base rebuild requested: collection=%s", collection)

    try:
        source_paths = _configured_rebuild_document_paths()
    except Exception as exc:
        logger.exception("Knowledge base rebuild failed before reset: collection=%s", collection)
        return _rebuild_failure_payload(
            collection=collection,
            stage="source_documents",
            error=_public_admin_error(
                exc,
                fallback=(
                    "Invalid or unreadable ASKA_KB_REBUILD_DOCUMENT_PATHS. "
                    "Check server logs for details."
                ),
            ),
            reset_completed=False,
            started=started,
        )

    if not source_paths:
        message = (
            "No rebuild source documents configured. Set ASKA_KB_REBUILD_DOCUMENT_PATHS "
            "to one or more existing handbook/document paths."
        )
        logger.error("Knowledge base rebuild failed before reset: collection=%s error=%s", collection, message)
        return _rebuild_failure_payload(
            collection=collection,
            stage="source_documents",
            error=message,
            reset_completed=False,
            started=started,
        )

    reset_completed = False
    results = []
    try:
        store = get_knowledge_base_store()
        logger.info("Knowledge base rebuild reset starting: collection=%s", collection)
        store.reset_collection()
        reset_completed = True
        logger.info("Knowledge base rebuild reset completed: collection=%s", collection)

        for path in source_paths:
            logger.info("Knowledge base rebuild document ingestion started: collection=%s file=%s", collection, path)
            result = ingest_document_into_knowledge_base(
                path.read_bytes(),
                filename=path.name,
                content_type=_content_type_for_path(path),
                title=path.stem,
            )
            results.append(result)
            logger.info(
                "Knowledge base rebuild document indexed: collection=%s file=%s chunks=%s",
                collection,
                path,
                result.chunks_indexed,
            )
    except Exception as exc:
        stage = "ingest" if reset_completed else "reset"
        logger.exception(
            "Knowledge base rebuild failed: collection=%s reset_completed=%s stage=%s",
            collection,
            reset_completed,
            stage,
        )
        failure = _rebuild_failure_payload(
            collection=collection,
            stage=stage,
            error=_public_admin_error(
                exc,
                fallback=(
                    f"Knowledge base rebuild failed during {stage}. "
                    "Check server logs for details."
                ),
            ),
            reset_completed=reset_completed,
            started=started,
        )
        # Chroma was wiped — never leave Postgres claiming FAQs are still indexed.
        if reset_completed:
            failure.update(_clear_rag_flags_after_chroma_wipe())
        return failure

    summary = _rebuild_success_payload(collection=collection, results=results, started=started)
    # Rebuild wipes Chroma; restore published ticket FAQs after PDF ingest.
    session_factory = get_session_factory()
    session = session_factory()
    try:
        from app.services.article_rag_indexer import (
            clear_all_article_rag_flags,
            reindex_published_faq_articles,
        )

        clear_all_article_rag_flags(session)
        session.commit()
        faq_summary = reindex_published_faq_articles(session)
        summary["faq_reindexed"] = faq_summary.get("faq_reindexed", 0)
        summary["faq_reindex_failed"] = faq_summary.get("faq_reindex_failed", 0)
        summary["faq_reindex_errors"] = faq_summary.get("faq_reindex_errors") or []
    except Exception:
        session.rollback()
        logger.exception("Rebuild finished PDF ingest but FAQ re-index failed")
        summary["faq_reindexed"] = 0
        summary["faq_reindex_failed"] = -1
        summary["faq_reindex_errors"] = [{"error": "FAQ re-index failed after rebuild"}]
    finally:
        session.close()

    faq_failed = int(summary.get("faq_reindex_failed") or 0)
    if faq_failed:
        summary["success"] = False
        summary["message"] = (
            "Knowledge base PDF rebuild finished, but published FAQ re-index failed. "
            "Check faq_reindex_errors and re-index stale FAQs from Article Library."
        )

    logger.info(
        "Knowledge base rebuild completed: collection=%s documents=%s chunks=%s faq_reindexed=%s success=%s processing_time_seconds=%s",
        collection,
        summary["documents_processed"],
        summary["chunks_created"],
        summary.get("faq_reindexed"),
        summary.get("success"),
        summary["processing_time_seconds"],
    )
    return summary


@chroma_router.delete(
    "/reset",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Reset ChromaDB knowledge base collection",
)
async def admin_reset_chroma(
    _: None = Depends(require_admin_only_key),
    allow_skip_documents: bool = Query(
        default=False,
        description=(
            "If true, allow reset when ASKA_KB_REBUILD_DOCUMENT_PATHS is empty "
            "(FAQ-only recovery). Default false so missing handbook paths fail loudly."
        ),
    ),
) -> dict:
    # Validate rebuild sources BEFORE wiping Chroma — never leave an empty KB by accident.
    try:
        source_paths = _configured_rebuild_document_paths()
    except Exception as exc:
        logger.exception("Invalid ASKA_KB_REBUILD_DOCUMENT_PATHS: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid ASKA_KB_REBUILD_DOCUMENT_PATHS. "
                "Fix the paths before resetting Chroma (see server logs)."
            ),
        ) from exc
    if not source_paths and not allow_skip_documents:
        raise HTTPException(
            status_code=400,
            detail=(
                "ASKA_KB_REBUILD_DOCUMENT_PATHS is empty. "
                "Set handbook/charter paths before resetting, or pass "
                "allow_skip_documents=true for FAQ-only recovery."
            ),
        )

    try:
        result = get_knowledge_base_store().reset_collection()
    except Exception as exc:
        raise _admin_internal_error("Chroma reset failed.", exc) from exc

    # Clear stale FAQ flags, re-ingest configured PDF/manual corpora, then re-index FAQs.
    articles_rag_flags_cleared = 0
    document_summary = _reingest_configured_documents_after_reset()
    reindex_summary: dict[str, Any] = {
        "faq_reindexed": 0,
        "faq_reindex_failed": 0,
        "faq_reindex_errors": [],
        "published_article_count": 0,
    }
    session_factory = get_session_factory()
    session = session_factory()
    try:
        from app.services.article_rag_indexer import (
            clear_all_article_rag_flags,
            reindex_published_faq_articles,
        )

        articles_rag_flags_cleared = clear_all_article_rag_flags(session)
        session.commit()
        reindex_summary = reindex_published_faq_articles(session)
    except Exception:
        session.rollback()
        logger.exception("Chroma was reset but FAQ flag clear / re-index failed")
        raise HTTPException(
            status_code=500,
            detail=(
                "Chroma was reset, but clearing/re-indexing published FAQ articles failed. "
                "Run a knowledge-base rebuild or re-publish FAQs manually."
            ),
        ) from None
    finally:
        session.close()

    faq_failed = int(reindex_summary.get("faq_reindex_failed") or 0)
    faq_reindexed = int(reindex_summary.get("faq_reindexed") or 0)
    docs_failed = int(document_summary.get("document_reingest_failed") or 0)
    docs_ok = int(document_summary.get("documents_reingested") or 0)
    docs_skipped = bool(document_summary.get("skipped"))
    success = faq_failed == 0 and docs_failed == 0 and (not docs_skipped or allow_skip_documents)
    message = (
        "Chroma knowledge base has been reset; configured PDF/manual corpora and "
        "published FAQs were restored."
    )
    if docs_skipped:
        message = (
            "Chroma knowledge base was reset and published FAQs were re-indexed, but "
            "ASKA_KB_REBUILD_DOCUMENT_PATHS is empty — handbook/charter corpora were NOT restored. "
            "Set the paths and reset again, or pass allow_skip_documents=true for FAQ-only recovery."
        )
    if faq_failed or docs_failed:
        message = (
            "Chroma knowledge base has been reset with partial recovery. "
            f"Documents re-ingested={docs_ok} failed={docs_failed}; "
            f"FAQs re-indexed={faq_reindexed} failed={faq_failed}."
        )

    return {
        "success": success,
        "message": message,
        "collection": result["collection"],
        "articles_rag_flags_cleared": articles_rag_flags_cleared,
        "documents_reingested": docs_ok,
        "document_reingest_failed": docs_failed,
        "document_reingest_errors": document_summary.get("document_reingest_errors") or [],
        "document_reingest_skipped": docs_skipped,
        "faq_reindexed": faq_reindexed,
        "faq_reindex_failed": faq_failed,
        "faq_reindex_errors": reindex_summary.get("faq_reindex_errors") or [],
        "published_article_count": int(reindex_summary.get("published_article_count") or 0),
    }


def _reingest_configured_documents_after_reset() -> dict[str, Any]:
    """Re-ingest handbook/charter PDFs after a Chroma wipe (collection already empty)."""
    try:
        source_paths = _configured_rebuild_document_paths()
    except Exception as exc:
        logger.exception("Configured rebuild document paths are invalid after Chroma reset")
        return {
            "skipped": False,
            "documents_reingested": 0,
            "document_reingest_failed": 1,
            "document_reingest_errors": [
                {
                    "path": "",
                    "error": _public_admin_error(
                        exc,
                        fallback="Invalid rebuild document paths. Check server logs.",
                    ),
                }
            ],
        }
    if not source_paths:
        return {
            "skipped": True,
            "documents_reingested": 0,
            "document_reingest_failed": 0,
            "document_reingest_errors": [],
        }

    from app.services.admin.knowledge_base_pipeline import ingest_document_into_knowledge_base

    ok = 0
    errors: list[dict[str, str]] = []
    for path in source_paths:
        try:
            ingest_document_into_knowledge_base(
                path.read_bytes(),
                filename=path.name,
                content_type=_content_type_for_path(path),
                title=path.stem,
            )
            ok += 1
        except Exception as exc:
            logger.exception("Failed to re-ingest %s after Chroma reset", path)
            errors.append(
                {
                    "path": path.name,
                    "error": _public_admin_error(
                        exc,
                        fallback="Document re-ingest failed. Check server logs.",
                    ),
                }
            )
    return {
        "skipped": False,
        "documents_reingested": ok,
        "document_reingest_failed": len(errors),
        "document_reingest_errors": errors[:20],
    }


def _documents_persist_root() -> Path:
    raw = (settings.documents_persist_dir or "./data/documents").strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[3]
        path = backend_root / path
    return path


def _resolve_rebuild_source_path(configured: str) -> Path:
    """Resolve handbook/charter paths for host uvicorn and Docker Compose.

    Host .env often uses ``./data/documents/<id>/handbook.pdf``. Compose mounts
    the same files at ``ASKA_DOCUMENTS_PERSIST_DIR`` (``/data/documents``), so a
    naive resolve under ``/app/data/documents`` would skip rebuild PDFs.
    """
    text = configured.strip()
    raw = Path(text).expanduser()
    backend_root = Path(__file__).resolve().parents[3]
    persist = _documents_persist_root()
    candidates: list[Path] = []

    if raw.is_absolute():
        candidates.append(raw)
    else:
        candidates.append((backend_root / raw).resolve())
        candidates.append((Path.cwd() / raw).resolve())
        candidates.append((persist / raw).resolve())

    normalized = text.replace("\\", "/")
    marker = "data/documents/"
    lower = normalized.lower()
    idx = lower.find(marker)
    if idx >= 0:
        relative = normalized[idx + len(marker) :]
        if relative:
            candidates.append((persist / relative).resolve())

    # Deduplicate while preserving order.
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate

    # Prefer the persist-mapped path in the error when the host-style prefix was used.
    if idx >= 0 and normalized[idx + len(marker) :]:
        return (persist / normalized[idx + len(marker) :]).resolve()
    if raw.is_absolute():
        return raw
    return (backend_root / raw).resolve()


def _configured_rebuild_document_paths() -> list[Path]:
    raw = settings.kb_rebuild_document_paths or ""
    values = [value.strip() for value in re.split(r"[;,\n]+", raw) if value.strip()]
    paths: list[Path] = []
    for value in values:
        path = _resolve_rebuild_source_path(value)
        if not path.is_file():
            raise FileNotFoundError(
                "Configured rebuild source document does not exist: "
                f"{path} (from ASKA_KB_REBUILD_DOCUMENT_PATHS={value!r}; "
                f"ASKA_DOCUMENTS_PERSIST_DIR={settings.documents_persist_dir!r}). "
                "In Docker, use paths under /data/documents/... or keep "
                "./data/documents/... and ensure the file is in the documents volume."
            )
        paths.append(path)
    return paths


def _clear_rag_flags_after_chroma_wipe() -> dict[str, Any]:
    """Clear ``rag_indexed`` after a Chroma wipe so Library shows RAG-stale honestly."""
    session_factory = get_session_factory()
    session = session_factory()
    try:
        from app.services.article_rag_indexer import clear_all_article_rag_flags

        cleared = clear_all_article_rag_flags(session)
        session.commit()
        return {
            "articles_rag_flags_cleared": cleared,
            "message": (
                "Knowledge base rebuild failed after Chroma reset. "
                "Published FAQ rag_indexed flags were cleared — use Reindex stale FAQs "
                "after fixing the ingest error."
            ),
        }
    except Exception:
        session.rollback()
        logger.exception("Failed to clear FAQ rag_indexed flags after rebuild wipe")
        return {
            "articles_rag_flags_cleared": -1,
            "message": (
                "Knowledge base rebuild failed after Chroma reset, and clearing "
                "rag_indexed flags also failed. Check logs and reindex stale FAQs."
            ),
        }
    finally:
        session.close()


@kb_tools_router.get("/articles", response_model=list[AdminPublishedArticleSchema])
def admin_list_articles(_: None = Depends(require_admin_key)) -> list[AdminPublishedArticleSchema]:
    from app.models.db_models import PublishedArticle

    session_factory = get_session_factory()
    session = session_factory()
    try:
        results = []
        for art in session.query(PublishedArticle).order_by(PublishedArticle.created_at.desc()).all():
            results.append(_admin_article_schema(art))
        return results
    finally:
        session.close()


@kb_tools_router.post("/articles", response_model=AdminPublishedArticleSchema)
def admin_create_article(
    payload: AdminPublishedArticleCreate,
    admin_actor_id: str | None = Depends(require_admin_key),
) -> AdminPublishedArticleSchema:
    from datetime import datetime, timezone

    from app.models.db_models import PublishedArticle

    if bool(payload.publish_status):
        gate = _publish_gate_error(
            content=payload.content,
            planner_bucket=payload.planner_bucket,
        )
        if gate:
            raise HTTPException(status_code=400, detail=gate)

    session_factory = get_session_factory()
    session = session_factory()
    try:
        if payload.update_existing_id:
            art = session.get(PublishedArticle, payload.update_existing_id)
            if art is None:
                raise HTTPException(status_code=404, detail="Article not found")
            # Protect public visibility: content updates must not silently unpublish.
            if bool(art.published) and not bool(payload.publish_status):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Article is already published. "
                        "Use the Unpublish endpoint to remove it from the public Knowledge Base."
                    ),
                )
            from app.services.ticket_knowledge import ensure_unique_article_slug

            art.title = payload.title
            art.slug = ensure_unique_article_slug(
                session, payload.title, exclude_id=art.id
            )
            art.category = payload.category
            art.summary = payload.summary
            art.content = payload.content
            art.office = payload.office
            art.source_filename = payload.source_document
            if payload.audience is not None:
                art.audience = payload.audience
            art.chunk_count = len(payload.chunk_ids or []) if payload.chunk_ids else art.chunk_count
            becoming_published = bool(payload.publish_status) and not bool(art.published)
            art.published = bool(payload.publish_status)
            if art.published:
                art.published_at = datetime.now(timezone.utc)
                if becoming_published:
                    art.rag_indexed = False
                if admin_actor_id:
                    art.published_by_user_id = admin_actor_id
            else:
                art.published_at = None
            session.add(art)
            from app.services.ticket_knowledge import sync_ticket_kb_status

            sync_ticket_kb_status(session, art)
            # Commit Postgres before Chroma so orphans cannot outlive unpublished rows.
            session.commit()
            session.refresh(art)
            if art.published:
                try:
                    from app.services.article_rag_indexer import index_published_article

                    index_published_article(session, art)
                    session.commit()
                    session.refresh(art)
                except Exception as exc:
                    logger.exception("Failed to index article %s into Chroma", art.id)
                    _revert_article_to_draft_after_rag_failure(session, art.id, exc)
                    raise HTTPException(
                        status_code=502,
                        detail=_rag_publish_failure_detail(exc),
                    ) from exc
            return _admin_article_schema(art)

        if not payload.force_create:
            existing = find_similar_article(
                session,
                title=payload.title,
                source_filename=payload.source_document,
            )
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "similar_article_exists",
                        "message": (
                            "A similar article already exists. Do you want to update the "
                            "existing draft or create a new one?"
                        ),
                        "existing": {
                            "id": existing.id,
                            "title": existing.title,
                            "published": bool(existing.published),
                            "source_filename": existing.source_filename,
                        },
                    },
                )

        from app.services.ticket_knowledge import ensure_unique_article_slug

        art = PublishedArticle(
            title=payload.title,
            slug=ensure_unique_article_slug(session, payload.title),
            category=payload.category,
            subcategory=None,
            path=None,
            summary=payload.summary,
            content=payload.content,
            office=payload.office,
            source_filename=payload.source_document,
            chunk_count=len(payload.chunk_ids or []) if payload.chunk_ids else None,
            published=bool(payload.publish_status),
            audience=_resolve_bulk_article_audience(payload),
            kb_origin="ticket_resolution" if payload.source_ticket_id else "document",
            source_ticket_id=payload.source_ticket_id,
        )
        try:
            from app.services.article_content_formatter import extract_embedded_article_metadata
            from app.services.document_storage import find_source_document_by_filename, get_source_document

            meta = extract_embedded_article_metadata(payload.content)
            linked_id = str(meta.get("document_id") or meta.get("source_document_id") or "").strip()
            source_row = get_source_document(linked_id) if linked_id else None
            if source_row is None and payload.source_document:
                source_row = find_source_document_by_filename(payload.source_document, session=session)
            if source_row is not None:
                art.source_document_id = source_row.id
        except Exception:
            logger.exception("Could not link published article to source_documents")
        if art.published:
            art.published_at = datetime.now(timezone.utc)
            art.rag_indexed = False
            if admin_actor_id:
                art.published_by_user_id = admin_actor_id
        session.add(art)
        from app.services.ticket_knowledge import sync_ticket_kb_status

        sync_ticket_kb_status(session, art)
        session.commit()
        session.refresh(art)
        if art.published:
            try:
                from app.services.article_rag_indexer import index_published_article

                index_published_article(session, art)
                session.commit()
                session.refresh(art)
            except Exception as exc:
                logger.exception("Failed to index article %s into Chroma", art.id)
                _revert_article_to_draft_after_rag_failure(session, art.id, exc)
                raise HTTPException(
                    status_code=502,
                    detail=_rag_publish_failure_detail(exc),
                ) from exc
        return _admin_article_schema(art)
    finally:
        session.close()


@kb_tools_router.get("/articles/{article_id}", response_model=AdminPublishedArticleSchema)
def admin_get_article(article_id: str, _: None = Depends(require_admin_key)) -> AdminPublishedArticleSchema:
    from app.models.db_models import PublishedArticle
    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        return _admin_article_schema(art)
    finally:
        session.close()


@kb_tools_router.patch("/articles/{article_id}", response_model=AdminPublishedArticleSchema)
def admin_update_article(
    article_id: str,
    payload: AdminPublishedArticleUpdate,
    admin_actor_id: str | None = Depends(require_admin_key),
) -> AdminPublishedArticleSchema:
    from datetime import datetime, timezone

    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import (
        cleanup_failed_faq_index,
        index_published_article,
    )
    from app.services.ticket_knowledge import ensure_unique_article_slug, sync_ticket_kb_status

    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        updates = payload.model_dump(exclude_unset=True)
        if "source_document" in updates:
            updates["source_filename"] = updates.pop("source_document")
        if "content" in updates:
            from app.services.article_content_formatter import merge_article_content_update

            updates["content"] = merge_article_content_update(art.content, updates["content"])

        # Map API publish_status onto the DB published column.
        becoming_published = False
        if "publish_status" in updates:
            publish = bool(updates.pop("publish_status"))
            if bool(art.published) and not publish:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Article is already published. "
                        "Use the Unpublish endpoint to remove it from the public Knowledge Base."
                    ),
                )
            if publish:
                next_content = updates.get("content", art.content)
                gate = _publish_gate_error(content=next_content)
                if gate:
                    raise HTTPException(status_code=400, detail=gate)
                if admin_actor_id:
                    art.published_by_user_id = admin_actor_id
                becoming_published = not bool(art.published)
            art.published = publish
            art.published_at = datetime.now(timezone.utc) if publish else None
            if becoming_published:
                art.rag_indexed = False
        if "title" in updates and updates["title"]:
            updates["slug"] = ensure_unique_article_slug(
                session, str(updates["title"]), exclude_id=art.id
            )
        for field, value in updates.items():
            if hasattr(art, field):
                setattr(art, field, value)
        session.add(art)
        if becoming_published:
            sync_ticket_kb_status(session, art)
        # Commit Postgres first when newly publishing so Chroma cannot outlive an unpublished row.
        if becoming_published:
            session.commit()
            session.refresh(art)
        else:
            session.flush()
        # Keep Chroma aligned with Postgres for any published article edit/publish.
        if art.published:
            try:
                index_published_article(session, art)
                session.commit()
            except Exception as exc:
                if becoming_published:
                    _revert_article_to_draft_after_rag_failure(session, article_id, exc)
                    raise _admin_bad_gateway(
                        _rag_publish_failure_detail(exc),
                        exc,
                    ) from exc
                session.rollback()
                cleanup_failed_faq_index(exc, article_id)
                raise _admin_bad_gateway(
                    "Article was not saved because RAG indexing failed. "
                    "Check server logs for details.",
                    exc,
                ) from exc
        else:
            session.commit()
        session.refresh(art)
        return _admin_article_schema(art)
    finally:
        session.close()


@kb_tools_router.post("/articles/{article_id}/publish")
def admin_publish_article(
    article_id: str,
    admin_actor_id: str | None = Depends(require_admin_key),
) -> dict[str, Any]:
    from datetime import datetime, timezone

    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import index_published_article
    from app.services.ticket_knowledge import (
        TicketKnowledgeError,
        assert_no_duplicate_published_topic,
        sync_ticket_kb_status,
    )

    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        gate = _publish_gate_error(content=art.content)
        if gate:
            raise HTTPException(status_code=400, detail=gate)
        if art.source_ticket_id or str(art.kb_origin or "") == "ticket_resolution":
            try:
                assert_no_duplicate_published_topic(
                    session,
                    title=art.title,
                    exclude_article_id=art.id,
                )
            except TicketKnowledgeError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        # Commit published first so a later Chroma write cannot outlive an unpublished row.
        art.published = True
        art.published_at = datetime.now(timezone.utc)
        art.rag_indexed = False
        if admin_actor_id:
            art.published_by_user_id = admin_actor_id
        session.add(art)
        sync_ticket_kb_status(session, art)
        session.commit()
        session.refresh(art)
        try:
            chunk_count = index_published_article(session, art)
            session.commit()
            session.refresh(art)
        except Exception as exc:
            _revert_article_to_draft_after_rag_failure(session, article_id, exc)
            raise _admin_bad_gateway(_rag_publish_failure_detail(exc), exc) from exc
        schema = _admin_article_schema(art)
        return {
            "success": True,
            "id": art.id,
            "title": art.title,
            "published": True,
            "rag_indexed": bool(art.rag_indexed),
            "chunk_count": chunk_count,
            "published_by_user_id": art.published_by_user_id,
            "persistence_table": "published_articles",
            "persistence_debug": schema.persistence_debug,
        }
    finally:
        session.close()


@kb_tools_router.post("/articles/{article_id}/reindex")
def admin_reindex_article(
    article_id: str,
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Re-index a published article into Chroma (fixes RAG-stale FAQs)."""
    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import (
        cleanup_failed_faq_index,
        index_published_article,
    )

    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        if not art.published:
            raise HTTPException(
                status_code=400,
                detail="Only published articles can be re-indexed for the chatbot.",
            )
        gate = _publish_gate_error(content=art.content)
        if gate:
            raise HTTPException(status_code=400, detail=gate)
        try:
            chunk_count = index_published_article(session, art)
            session.commit()
            session.refresh(art)
        except Exception as exc:
            session.rollback()
            cleanup_failed_faq_index(exc, article_id)
            raise _admin_bad_gateway(
                "Re-index failed. Check server logs for details.",
                exc,
            ) from exc
        return {
            "success": True,
            "id": art.id,
            "rag_indexed": bool(art.rag_indexed),
            "chunk_count": chunk_count,
        }
    finally:
        session.close()


@kb_tools_router.post(
    "/articles/reindex-stale",
    summary="[Admin] Re-index all published FAQs missing from Chroma",
)
def admin_reindex_stale_articles(_: None = Depends(require_admin_key)) -> dict[str, Any]:
    """One-click recovery for RAG-stale published articles after rebuild/reset issues."""
    from app.services.article_rag_indexer import reindex_stale_published_faq_articles

    session_factory = get_session_factory()
    session = session_factory()
    try:
        summary = reindex_stale_published_faq_articles(session)
        failed = int(summary.get("faq_reindex_failed") or 0)
        return {
            "success": failed == 0,
            "faq_reindexed": summary.get("faq_reindexed", 0),
            "faq_reindex_failed": failed,
            "faq_reindex_errors": summary.get("faq_reindex_errors") or [],
            "stale_article_count": summary.get("published_article_count", 0),
            "message": (
                "All stale FAQs were re-indexed."
                if failed == 0
                else "Some stale FAQs failed to re-index. Check faq_reindex_errors."
            ),
        }
    finally:
        session.close()


@kb_tools_router.post("/articles/{article_id}/unpublish")
def admin_unpublish_article(article_id: str, _: None = Depends(require_admin_key)) -> dict[str, Any]:
    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import best_effort_remove_faq_document
    from app.services.ticket_knowledge import sync_ticket_kb_status

    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        # Commit unpublished first so Chroma leftovers cannot answer after a PG rollback.
        art.published = False
        art.published_at = None
        art.rag_indexed = False
        art.rag_document_id = None
        art.chunk_count = 0
        session.add(art)
        sync_ticket_kb_status(session, art)
        session.commit()
        best_effort_remove_faq_document(article_id)
        return {
            "success": True,
            "id": art.id,
            "published": False,
            "rag_indexed": False,
        }
    finally:
        session.close()


@kb_tools_router.delete("/articles/{article_id}")
def admin_delete_article(article_id: str, _: None = Depends(require_admin_key)) -> dict[str, Any]:
    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import best_effort_remove_faq_document

    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        if art.source_ticket_id:
            from app.models.db_models import Ticket

            ticket = session.get(Ticket, art.source_ticket_id)
            if ticket is not None:
                ticket.kb_article_id = None
                ticket.kb_conversion_status = "none"
                session.add(ticket)
        # Delete Postgres row first; orphan Chroma FAQ vectors are filtered at ask-time.
        session.delete(art)
        session.commit()
        best_effort_remove_faq_document(article_id)
        return {"success": True, "id": article_id}
    finally:
        session.close()


@kb_tools_router.post(
    "/articles/bulk-save-draft",
    response_model=AdminBulkArticlesResponse,
    summary="[Admin] Bulk save article candidates as drafts (published=false)",
)
def admin_bulk_save_draft(
    payload: AdminBulkArticlesRequest,
    _: None = Depends(require_admin_key),
) -> AdminBulkArticlesResponse:
    return _bulk_persist_articles(payload, publish=False)


@kb_tools_router.post(
    "/articles/bulk-publish",
    response_model=AdminBulkArticlesResponse,
    summary="[Admin] Bulk publish safe article candidates (published=true)",
)
def admin_bulk_publish(
    payload: AdminBulkArticlesRequest,
    admin_actor_id: str | None = Depends(require_admin_key),
) -> AdminBulkArticlesResponse:
    return _bulk_persist_articles(
        payload,
        publish=True,
        published_by_user_id=admin_actor_id,
    )


@kb_tools_router.post(
    "/articles/bulk-unpublish",
    response_model=AdminBulkArticlesResponse,
    summary="[Admin] Bulk unpublish articles (published=false, keep rows)",
)
def admin_bulk_unpublish(
    payload: AdminBulkIdsRequest,
    _: None = Depends(require_admin_key),
) -> AdminBulkArticlesResponse:
    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import best_effort_remove_faq_document
    from app.services.ticket_knowledge import sync_ticket_kb_status

    results: list[AdminBulkArticleResultItem] = []
    session_factory = get_session_factory()
    session = session_factory()
    try:
        for raw_id in payload.article_ids:
            article_id = (raw_id or "").strip()
            if not article_id:
                results.append(
                    AdminBulkArticleResultItem(
                        success=False,
                        error="article id is required",
                        code="validation_error",
                    )
                )
                continue
            art = session.get(PublishedArticle, article_id)
            if art is None:
                results.append(
                    AdminBulkArticleResultItem(
                        success=False,
                        id=article_id,
                        error="Article not found",
                        code="not_found",
                    )
                )
                continue
            try:
                art.published = False
                art.published_at = None
                art.rag_indexed = False
                art.rag_document_id = None
                art.chunk_count = 0
                session.add(art)
                sync_ticket_kb_status(session, art)
                session.commit()
                best_effort_remove_faq_document(article_id)
                results.append(
                    AdminBulkArticleResultItem(
                        success=True,
                        id=art.id,
                        title=art.title,
                        published=False,
                    )
                )
            except Exception as exc:
                session.rollback()
                logger.exception("Bulk unpublish failed for %s", article_id)
                results.append(
                    AdminBulkArticleResultItem(
                        success=False,
                        id=article_id,
                        title=art.title,
                        error=_public_admin_error(
                            exc,
                            fallback="Unpublish failed. Check server logs.",
                        ),
                        code="unpublish_failed",
                    )
                )
    finally:
        session.close()

    success_count = sum(1 for item in results if item.success)
    return AdminBulkArticlesResponse(
        success_count=success_count,
        failure_count=len(results) - success_count,
        results=results,
    )


def _bulk_item_blocked(*, publish: bool, planner_bucket: str, needs_review: bool) -> str | None:
    """Return an error message when a bulk item is not allowed for the action."""
    if planner_bucket in {"rag_only", "rag-only"}:
        return "RAG-only sections cannot be saved or published as Knowledge Base articles."
    if planner_bucket in {"low_quality", "low-quality", "needs_cleanup"}:
        return "Low Quality / Cleanup candidates cannot be bulk saved or published."
    if publish:
        if planner_bucket in {"needs_review", "needs-review"} or needs_review:
            return "Needs Review candidates cannot be bulk published."
        if planner_bucket and planner_bucket not in {
            "recommended",
            "consolidated_parent",
            "consolidated-parent",
            "",
        }:
            return f"Planner bucket '{planner_bucket}' cannot be bulk published."
    return None


def _resolve_bulk_article_audience(item: Any) -> str:
    """Resolve audience for bulk create/update (explicit field, else filename/title heuristics)."""
    from app.services.article_rag_indexer import infer_rag_audience_from_document

    explicit = str(getattr(item, "audience", None) or "").strip().lower()
    if explicit in {"student", "faculty", "both"}:
        return explicit
    return infer_rag_audience_from_document(
        filename=getattr(item, "source_document", None),
        title=getattr(item, "title", None),
        document_type=getattr(item, "document_type", None),
    )


def _bulk_persist_articles(
    payload: AdminBulkArticlesRequest,
    *,
    publish: bool,
    published_by_user_id: str | None = None,
) -> AdminBulkArticlesResponse:
    from datetime import datetime, timezone

    from app.models.db_models import PublishedArticle
    from app.services.article_rag_indexer import index_published_article
    from app.services.ticket_knowledge import sync_ticket_kb_status

    results: list[AdminBulkArticleResultItem] = []
    session_factory = get_session_factory()
    session = session_factory()
    try:
        for item in payload.articles:
            preview_id = item.preview_id
            bucket = _normalize_planner_bucket(item.planner_bucket)
            blocked = _bulk_item_blocked(
                publish=publish,
                planner_bucket=bucket,
                needs_review=bool(item.needs_review),
            )
            if blocked:
                results.append(
                    AdminBulkArticleResultItem(
                        preview_id=preview_id,
                        success=False,
                        title=item.title,
                        error=blocked,
                        code="bucket_not_allowed",
                    )
                )
                continue

            if publish:
                content_gate = _content_blocks_publish(item.content)
                if content_gate:
                    results.append(
                        AdminBulkArticleResultItem(
                            preview_id=preview_id,
                            success=False,
                            title=item.title,
                            error=content_gate,
                            code="content_not_ready",
                        )
                    )
                    continue

            try:
                existing_id = (item.existing_article_id or item.update_existing_id or "").strip()
                if existing_id:
                    art = session.get(PublishedArticle, existing_id)
                    if art is None:
                        results.append(
                            AdminBulkArticleResultItem(
                                preview_id=preview_id,
                                success=False,
                                title=item.title,
                                error="Article not found",
                                code="not_found",
                            )
                        )
                        continue
                    # Never silently unpublish via bulk save-draft. Use /unpublish.
                    if bool(art.published) and not publish:
                        results.append(
                            AdminBulkArticleResultItem(
                                preview_id=preview_id,
                                success=False,
                                id=art.id,
                                title=art.title,
                                published=True,
                                error=(
                                    "Article is already published. "
                                    "Use Unpublish to remove it from the public Knowledge Base."
                                ),
                                code="already_published",
                            )
                        )
                        continue
                    if item.title:
                        from app.services.ticket_knowledge import ensure_unique_article_slug

                        art.title = item.title
                        art.slug = ensure_unique_article_slug(
                            session, item.title, exclude_id=art.id
                        )
                    if item.category:
                        art.category = item.category
                    if item.summary is not None:
                        art.summary = item.summary
                    if item.content is not None:
                        art.content = item.content
                    if item.office is not None:
                        art.office = item.office
                    if item.source_document is not None:
                        art.source_filename = item.source_document
                    if item.audience is not None or item.title or item.source_document:
                        art.audience = _resolve_bulk_article_audience(item)
                    art.published = publish
                    art.published_at = datetime.now(timezone.utc) if publish else None
                    if publish:
                        art.rag_indexed = False
                        if published_by_user_id:
                            art.published_by_user_id = published_by_user_id
                    session.add(art)
                    if publish:
                        sync_ticket_kb_status(session, art)
                    # Commit Postgres before Chroma so orphans cannot outlive unpublished rows.
                    session.commit()
                    session.refresh(art)
                    if publish:
                        try:
                            index_published_article(session, art)
                            session.commit()
                            session.refresh(art)
                        except Exception as exc:
                            logger.exception(
                                "Failed to index bulk article %s into Chroma", art.id
                            )
                            _revert_article_to_draft_after_rag_failure(session, art.id, exc)
                            results.append(
                                AdminBulkArticleResultItem(
                                    preview_id=preview_id,
                                    success=False,
                                    id=art.id,
                                    title=art.title,
                                    published=False,
                                    error=_rag_publish_failure_detail(exc),
                                    code="rag_index_failed",
                                )
                            )
                            continue
                    results.append(
                        AdminBulkArticleResultItem(
                            preview_id=preview_id,
                            success=True,
                            id=art.id,
                            title=art.title,
                            published=bool(art.published),
                        )
                    )
                    continue

                title = (item.title or "").strip()
                category = (item.category or "").strip()
                if not title or not category:
                    results.append(
                        AdminBulkArticleResultItem(
                            preview_id=preview_id,
                            success=False,
                            title=item.title,
                            error="title and category are required to create an article",
                            code="validation_error",
                        )
                    )
                    continue

                if not item.force_create:
                    existing = find_similar_article(
                        session,
                        title=title,
                        source_filename=item.source_document,
                    )
                    if existing is not None:
                        results.append(
                            AdminBulkArticleResultItem(
                                preview_id=preview_id,
                                success=False,
                                title=title,
                                error="A similar article already exists.",
                                code="similar_article_exists",
                                existing={
                                    "id": existing.id,
                                    "title": existing.title,
                                    "published": bool(existing.published),
                                    "source_filename": existing.source_filename,
                                },
                            )
                        )
                        continue

                from app.services.ticket_knowledge import ensure_unique_article_slug

                art = PublishedArticle(
                    title=title,
                    slug=ensure_unique_article_slug(session, title),
                    category=category,
                    subcategory=None,
                    path=None,
                    summary=item.summary,
                    content=item.content,
                    office=item.office,
                    source_filename=item.source_document,
                    chunk_count=None,
                    published=publish,
                    rag_indexed=False,
                    audience=_resolve_bulk_article_audience(item),
                )
                if publish:
                    art.published_at = datetime.now(timezone.utc)
                    if published_by_user_id:
                        art.published_by_user_id = published_by_user_id
                session.add(art)
                if publish:
                    sync_ticket_kb_status(session, art)
                session.commit()
                session.refresh(art)
                if publish:
                    try:
                        index_published_article(session, art)
                        session.commit()
                        session.refresh(art)
                    except Exception as exc:
                        logger.exception(
                            "Failed to index bulk article %s into Chroma", art.id
                        )
                        _revert_article_to_draft_after_rag_failure(session, art.id, exc)
                        results.append(
                            AdminBulkArticleResultItem(
                                preview_id=preview_id,
                                success=False,
                                id=art.id,
                                title=title,
                                published=False,
                                error=_rag_publish_failure_detail(exc),
                                code="rag_index_failed",
                            )
                        )
                        continue
                results.append(
                    AdminBulkArticleResultItem(
                        preview_id=preview_id,
                        success=True,
                        id=art.id,
                        title=art.title,
                        published=bool(art.published),
                    )
                )
            except Exception as exc:  # noqa: BLE001 — per-item isolation
                session.rollback()
                logger.exception("Bulk persist failed for preview %s", preview_id)
                results.append(
                    AdminBulkArticleResultItem(
                        preview_id=preview_id,
                        success=False,
                        title=item.title,
                        error=_public_admin_error(
                            exc,
                            fallback="Save failed. Check server logs.",
                        ),
                        code="persist_error",
                    )
                )
    finally:
        session.close()

    success_count = sum(1 for item in results if item.success)
    return AdminBulkArticlesResponse(
        success_count=success_count,
        failure_count=len(results) - success_count,
        results=results,
    )


@kb_tools_router.post(
    "/articles/generate-preview",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Generate unsaved article candidate previews from an extraction preview",
)
def admin_generate_article_candidate_previews(
    payload: GenerateArticleCandidatesFromPreviewRequest,
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Return article candidate previews without writing to published_articles."""
    return _generate_article_candidates_from_preview_payload(payload, save_mode="preview_only")


@kb_tools_router.post(
    "/articles/generate-from-preview",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Generate article candidates from an existing extraction preview",
)
def admin_generate_article_candidates_from_preview(
    payload: GenerateArticleCandidatesFromPreviewRequest,
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Generate article candidate previews or drafts from a prior extract/structure preview."""
    save_mode = (payload.save_mode or "preview_only").strip().lower()
    return _generate_article_candidates_from_preview_payload(payload, save_mode=save_mode)


def _generate_article_candidates_from_preview_payload(
    payload: GenerateArticleCandidatesFromPreviewRequest,
    *,
    save_mode: str,
) -> dict[str, Any]:
    preview = payload.preview if isinstance(payload.preview, dict) else {}
    has_units = bool(preview.get("knowledge_units"))
    has_v2 = bool(preview.get("charter_v2_services"))
    if not has_units and not has_v2:
        raise HTTPException(
            status_code=422,
            detail=(
                "Preview must include knowledge_units or charter_v2_services "
                "from a completed extraction."
            ),
        )
    # Ensure generate_candidates_from_preview always sees a list for units.
    if not isinstance(preview.get("knowledge_units"), list):
        preview = {**preview, "knowledge_units": []}
    try:
        result = generate_candidates_from_preview(
            preview,
            filename=payload.filename,
            max_candidates=payload.max_candidates,
            save_mode=save_mode,
        )
    except Exception as exc:
        raise _admin_internal_error("Article candidate generation failed.", exc) from exc

    return _article_candidate_generation_payload(result)


@kb_tools_router.post(
    "/articles/generate-from-source",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Generate article candidates from uploaded/extracted document",
)
async def admin_generate_article_candidates(
    file: UploadFile = File(..., description="Document to analyze for article candidates"),
    document_type: str | None = Form(
        None,
        description="Optional hint: information, procedure, requirement",
    ),
    preview_file_path: str | None = Form(None, description="Optional preview path for requirement/form documents"),
    max_candidates: int | None = Form(
        None,
        description="Optional dev cap on Recommended bucket previews only",
    ),
    save_mode: str = Form("preview_only", description="preview_only or save_drafts"),
    _: None = Depends(require_admin_key),
) -> dict[str, Any]:
    """Generate article candidate previews or drafts from an uploaded document."""
    content = await _read_upload(file)
    try:
        result = generate_candidates_from_upload(
            content,
            filename=file.filename,
            document_type=document_type,
            preview_file_path=preview_file_path,
            max_candidates=max_candidates,
            save_mode=save_mode,
        )
    except Exception as exc:
        raise _admin_internal_error("Article candidate generation failed.", exc) from exc

    return _article_candidate_generation_payload(result)


def _article_candidate_generation_payload(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "success",
        "save_mode": result.get("save_mode", "preview_only"),
        "total_detected": int(result.get("total_detected", 0)),
        "recommended_count": int(result.get("recommended_count", 0)),
        "overflow_count": int(result.get("overflow_count", 0)),
        "skipped_low_quality_count": int(result.get("skipped_low_quality_count", 0)),
        "skipped_duplicate_count": int(result.get("skipped_duplicate_count", 0)),
        "needs_review_count": int(result.get("needs_review_count", 0)),
        "created_count": int(result.get("created_count", 0)),
        "preview_count": int(result.get("preview_count", result.get("created_count", 0))),
        "saved_count": int(result.get("saved_count", 0)),
        "skipped_duplicate": int(result.get("skipped_duplicate", 0)),
        "skipped_low_quality": int(result.get("skipped_low_quality", 0)),
        "recommended_candidates": result.get("recommended_candidates", []),
        "needs_review_candidates": result.get("needs_review_candidates", []),
        "low_confidence_candidates": result.get("low_confidence_candidates", []),
        "skipped_duplicates": result.get("skipped_duplicates", []),
        "overflow_candidates": result.get("overflow_candidates", []),
        "all_candidates": result.get("all_candidates", []),
        "grouped_candidates": result.get("grouped_candidates", []),
        "groups": result.get("grouped_candidates", []),
        "coverage": result.get("coverage", []),
        "blueprints": result.get("blueprints", []),
        "blueprint_count": int(result.get("blueprint_count", 0)),
        "article_eligible_count": int(result.get("article_eligible_count", 0)),
        "rag_only_count": int(result.get("rag_only_count", 0)),
        "consolidated_parent_count": int(result.get("consolidated_parent_count", 0)),
        "consolidated_parent_candidates": result.get("consolidated_parent_candidates", []),
        "created": result.get("created", []),
        "charter_report": result.get("charter_report"),
    }


def _admin_article_schema(art) -> AdminPublishedArticleSchema:
    from app.services.article_content_formatter import extract_embedded_article_metadata

    meta = extract_embedded_article_metadata(art.content) if art.content else {}
    if not isinstance(meta, dict):
        meta = {}
    source_section = str(meta.get("source_section") or meta.get("canonical_topic") or "").strip() or None
    article_type = str(meta.get("article_type") or "").strip() or None
    document_type = str(meta.get("document_type") or "").strip() or None
    published = bool(art.published)
    debug = {
        "article_id": art.id,
        "title": art.title,
        "source_filename": art.source_filename,
        "source_section": source_section,
        "published": published,
        "database_table": "published_articles",
        "article_type": article_type,
        "document_type": document_type,
    }
    logger.info(
        "published_articles persistence: id=%s title=%r published=%s source_filename=%r source_section=%r",
        art.id,
        art.title,
        published,
        art.source_filename,
        source_section,
    )
    return AdminPublishedArticleSchema(
        id=art.id,
        title=art.title,
        slug=art.slug,
        category=art.category,
        subcategory=art.subcategory,
        path=art.path,
        summary=art.summary,
        content=art.content,
        office=art.office,
        source_filename=art.source_filename,
        chunk_count=int(art.chunk_count or 0),
        published=published,
        published_at=art.published_at.isoformat() if art.published_at else None,
        created_at=art.created_at.isoformat() if art.created_at else None,
        updated_at=art.updated_at.isoformat() if art.updated_at else None,
        persistence_table="published_articles",
        persistence_debug=debug,
        source_section=source_section,
        article_type=article_type,
        document_type=document_type,
        audience=getattr(art, "audience", None) or "student",
        kb_origin=getattr(art, "kb_origin", None) or "document",
        source_ticket_id=getattr(art, "source_ticket_id", None),
        resolution_summary=getattr(art, "resolution_summary", None),
        published_by_user_id=getattr(art, "published_by_user_id", None),
        rag_indexed=bool(getattr(art, "rag_indexed", False)),
        rag_document_id=getattr(art, "rag_document_id", None),
    )


def _content_type_for_path(path: Path) -> str | None:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix.lower() == ".pdf":
        return "application/pdf"
    return None


def _rebuild_success_payload(*, collection: str, results: list, started: float) -> dict[str, Any]:
    metadata_summary = _metadata_summary_from_results(results)
    validation_summary = _validation_summary_from_results(results)
    chunks_created = sum(int(getattr(result, "chunks_indexed", 0) or 0) for result in results)
    return {
        "success": True,
        "message": "Knowledge base rebuilt successfully.",
        "collection": collection,
        "documents_processed": len(results),
        "chunks_created": chunks_created,
        "categories": len(metadata_summary["unique_categories"]),
        "campuses": len(metadata_summary["unique_campuses"]),
        "processing_time_seconds": round(time.perf_counter() - started, 3),
        "suspicious_units": validation_summary["suspicious_units"],
        "toc_like_units": validation_summary["toc_like_units"],
        "invalid_campus_values": validation_summary["invalid_campus_values"],
        "unique_categories": metadata_summary["unique_categories"],
        "unique_subcategories": metadata_summary["unique_subcategories"],
        "unique_offices": metadata_summary["unique_offices"],
        "unique_campuses": metadata_summary["unique_campuses"],
    }


def _rebuild_failure_payload(
    *,
    collection: str,
    stage: str,
    error: str,
    reset_completed: bool,
    started: float,
) -> dict[str, Any]:
    return {
        "success": False,
        "message": "Knowledge base rebuild failed.",
        "collection": collection,
        "stage": stage,
        "error": error,
        "reset_completed": reset_completed,
        "processing_time_seconds": round(time.perf_counter() - started, 3),
    }


def _metadata_summary_from_results(results: list) -> dict[str, list[str]]:
    categories: set[str] = set()
    subcategories: set[str] = set()
    offices: set[str] = set()
    campuses: set[str] = set()
    for result in results:
        for preview in getattr(result, "chunk_preview", None) or []:
            metadata = preview.get("metadata") if isinstance(preview, dict) else {}
            if not isinstance(metadata, dict):
                continue
            _add_value(categories, metadata.get("category"))
            _add_value(subcategories, metadata.get("subcategory"))
            _add_value(offices, metadata.get("responsible_office") or metadata.get("office"))
            _add_campus_values(campuses, metadata.get("campus"))
            _add_campus_values(campuses, metadata.get("campuses"))
    return {
        "unique_categories": sorted(categories),
        "unique_subcategories": sorted(subcategories),
        "unique_offices": sorted(offices),
        "unique_campuses": sorted(campuses),
    }


def _validation_summary_from_results(results: list) -> dict[str, Any]:
    invalid_campus_values: list[dict] = []
    suspicious_units = 0
    toc_like_units = 0
    for result in results:
        report = getattr(result, "validation_report", None) or {}
        if not isinstance(report, dict):
            continue
        suspicious_units += int(report.get("suspicious_units_count") or 0)
        toc_like_units += int(report.get("toc_like_units_count") or 0)
        invalid = report.get("invalid_campus_values") or []
        if isinstance(invalid, list):
            invalid_campus_values.extend(item for item in invalid if isinstance(item, dict))
    return {
        "suspicious_units": suspicious_units,
        "toc_like_units": toc_like_units,
        "invalid_campus_values": invalid_campus_values,
    }


def _add_value(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        values.add(value.strip())


def _add_campus_values(values: set[str], value: Any) -> None:
    if isinstance(value, str) and value.strip():
        for item in value.split(","):
            _add_value(values, item)
    elif isinstance(value, list):
        for item in value:
            _add_value(values, item)
