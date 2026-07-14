"""
Admin routes — knowledge base creation flow only.

OCR / PDF extraction → clean → chunk → embeddings → ChromaDB
"""

import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile

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


def require_admin_key(
    x_admin_key: str | None = Header(
        default=None,
        alias="x-admin-key",
        description="Administrator API key. Must match ASKA_ADMIN_API_KEY.",
    ),
    authorization: str | None = Header(
        default=None,
        alias="authorization",
        description="Bearer token for a logged-in admin account.",
    ),
) -> None:
    configured_key = settings.admin_api_key
    if configured_key and x_admin_key and x_admin_key == configured_key:
        return

    if authorization and authorization.lower().startswith("bearer "):
        _require_admin_bearer_token(authorization.split(" ", 1)[1].strip())
        return

    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured. Log in as admin or set ASKA_ADMIN_API_KEY.",
        )
    raise HTTPException(status_code=401, detail="Invalid admin key.")


def _require_admin_bearer_token(token: str) -> None:
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
    if str(user.role).strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Only admin accounts can use Knowledge Base Admin tools.")


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
        result = extract_document_preview(
            content,
            filename=file.filename,
            content_type=file.content_type,
            document_type=document_type,
            preview_file_path=preview_file_path,
        )
    except (UnsupportedDocumentError, EmptyDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
        result = ingest_document_into_knowledge_base(
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
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc

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
        raise HTTPException(status_code=500, detail=f"Retrieval test failed: {exc}") from exc

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
async def admin_rebuild_knowledge_base(_: None = Depends(require_admin_key)) -> dict:
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
            error=str(exc),
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
        return _rebuild_failure_payload(
            collection=collection,
            stage=stage,
            error=str(exc),
            reset_completed=reset_completed,
            started=started,
        )

    summary = _rebuild_success_payload(collection=collection, results=results, started=started)
    logger.info(
        "Knowledge base rebuild completed: collection=%s documents=%s chunks=%s processing_time_seconds=%s",
        collection,
        summary["documents_processed"],
        summary["chunks_created"],
        summary["processing_time_seconds"],
    )
    return summary


@chroma_router.delete(
    "/reset",
    responses={500: {"model": ErrorResponse}},
    summary="[Admin] Reset ChromaDB knowledge base collection",
)
async def admin_reset_chroma(_: None = Depends(require_admin_key)) -> dict:
    try:
        result = get_knowledge_base_store().reset_collection()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Chroma reset failed: {exc}") from exc

    return {
        "success": True,
        "message": "Chroma knowledge base has been reset.",
        "collection": result["collection"],
    }


def _configured_rebuild_document_paths() -> list[Path]:
    raw = settings.kb_rebuild_document_paths or ""
    values = [value.strip() for value in re.split(r"[;,\n]+", raw) if value.strip()]
    paths: list[Path] = []
    backend_root = Path(__file__).resolve().parents[3]
    for value in values:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = backend_root / path
        if not path.is_file():
            raise FileNotFoundError(f"Configured rebuild source document does not exist: {path}")
        paths.append(path)
    return paths


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
def admin_create_article(payload: AdminPublishedArticleCreate, _: None = Depends(require_admin_key)) -> AdminPublishedArticleSchema:
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
            art.title = payload.title
            art.slug = re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-")
            art.category = payload.category
            art.summary = payload.summary
            art.content = payload.content
            art.office = payload.office
            art.source_filename = payload.source_document
            art.chunk_count = len(payload.chunk_ids or []) if payload.chunk_ids else art.chunk_count
            art.published = bool(payload.publish_status)
            if art.published:
                art.published_at = datetime.now(timezone.utc)
            else:
                art.published_at = None
            session.add(art)
            session.commit()
            session.refresh(art)
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

        art = PublishedArticle(
            title=payload.title,
            slug=re.sub(r"[^a-z0-9]+", "-", payload.title.lower()).strip("-"),
            category=payload.category,
            subcategory=None,
            path=None,
            summary=payload.summary,
            content=payload.content,
            office=payload.office,
            source_filename=payload.source_document,
            chunk_count=len(payload.chunk_ids or []) if payload.chunk_ids else None,
            published=bool(payload.publish_status),
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
        session.add(art)
        session.commit()
        session.refresh(art)
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
def admin_update_article(article_id: str, payload: AdminPublishedArticleUpdate, _: None = Depends(require_admin_key)) -> AdminPublishedArticleSchema:
    from app.models.db_models import PublishedArticle
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
        if "publish_status" in updates:
            from datetime import datetime, timezone

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
            art.published = publish
            art.published_at = datetime.now(timezone.utc) if publish else None
        for field, value in updates.items():
            if hasattr(art, field):
                setattr(art, field, value)
        session.add(art)
        session.commit()
        session.refresh(art)
        return _admin_article_schema(art)
    finally:
        session.close()


@kb_tools_router.post("/articles/{article_id}/publish")
def admin_publish_article(article_id: str, _: None = Depends(require_admin_key)) -> dict[str, Any]:
    from app.models.db_models import PublishedArticle
    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        gate = _publish_gate_error(content=art.content)
        if gate:
            raise HTTPException(status_code=400, detail=gate)
        art.published = True
        from datetime import datetime, timezone

        art.published_at = datetime.now(timezone.utc)
        session.add(art)
        session.commit()
        session.refresh(art)
        schema = _admin_article_schema(art)
        return {
            "success": True,
            "id": art.id,
            "title": art.title,
            "published": True,
            "persistence_table": "published_articles",
            "persistence_debug": schema.persistence_debug,
        }
    finally:
        session.close()


@kb_tools_router.post("/articles/{article_id}/unpublish")
def admin_unpublish_article(article_id: str, _: None = Depends(require_admin_key)) -> dict[str, Any]:
    from app.models.db_models import PublishedArticle
    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        art.published = False
        art.published_at = None
        session.add(art)
        session.commit()
        return {"success": True, "id": art.id}
    finally:
        session.close()


@kb_tools_router.delete("/articles/{article_id}")
def admin_delete_article(article_id: str, _: None = Depends(require_admin_key)) -> dict[str, Any]:
    from app.models.db_models import PublishedArticle
    session_factory = get_session_factory()
    session = session_factory()
    try:
        art = session.get(PublishedArticle, article_id)
        if art is None:
            raise HTTPException(status_code=404, detail="Article not found")
        session.delete(art)
        session.commit()
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
    _: None = Depends(require_admin_key),
) -> AdminBulkArticlesResponse:
    return _bulk_persist_articles(payload, publish=True)


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
            art.published = False
            art.published_at = None
            session.add(art)
            session.commit()
            session.refresh(art)
            results.append(
                AdminBulkArticleResultItem(
                    success=True,
                    id=art.id,
                    title=art.title,
                    published=False,
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


def _bulk_persist_articles(
    payload: AdminBulkArticlesRequest,
    *,
    publish: bool,
) -> AdminBulkArticlesResponse:
    from datetime import datetime, timezone

    from app.models.db_models import PublishedArticle

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
                        art.title = item.title
                        art.slug = re.sub(r"[^a-z0-9]+", "-", item.title.lower()).strip("-")
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
                    art.published = publish
                    art.published_at = datetime.now(timezone.utc) if publish else None
                    session.add(art)
                    session.commit()
                    session.refresh(art)
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

                art = PublishedArticle(
                    title=title,
                    slug=re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-"),
                    category=category,
                    subcategory=None,
                    path=None,
                    summary=item.summary,
                    content=item.content,
                    office=item.office,
                    source_filename=item.source_document,
                    chunk_count=None,
                    published=publish,
                )
                if publish:
                    art.published_at = datetime.now(timezone.utc)
                session.add(art)
                session.commit()
                session.refresh(art)
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
                results.append(
                    AdminBulkArticleResultItem(
                        preview_id=preview_id,
                        success=False,
                        title=item.title,
                        error=str(exc),
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
        raise HTTPException(
            status_code=500,
            detail=f"Article candidate generation failed: {exc}",
        ) from exc

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
        raise HTTPException(status_code=500, detail=f"Article candidate generation failed: {exc}") from exc

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
