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
from app.models.schemas import (
    ErrorResponse,
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
from app.services.chroma_store import get_knowledge_base_store
from app.services.document_ingestion import (
    EmptyDocumentError,
    UnsupportedDocumentError,
)

router = APIRouter(prefix="/admin/knowledge-base", tags=["Admin — Knowledge Base"])

kb_tools_router = APIRouter(prefix="/admin/kb", tags=["Admin Knowledge Base"])
chroma_router = APIRouter(prefix="/admin/chroma", tags=["Admin ChromaDB"])

logger = logging.getLogger(__name__)


def require_admin_key(
    x_admin_key: str | None = Header(
        default=None,
        alias="x-admin-key",
        description="Administrator API key. Must match ASKA_ADMIN_API_KEY.",
    )
) -> None:
    configured_key = settings.admin_api_key
    if not configured_key:
        raise HTTPException(
            status_code=503,
            detail="Admin API key is not configured. Set ASKA_ADMIN_API_KEY on the backend.",
        )
    if not x_admin_key or x_admin_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid admin key.")


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
        )
    except (UnsupportedDocumentError, EmptyDocumentError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return ExtractDocumentResponse(
        status="success",
        flow="admin_extraction",
        document_type=result["document_type"],
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
        knowledge_units=result.get("knowledge_units") or [],
        chunk_preview=result.get("chunk_preview") or [],
        kb_statistics=result.get("kb_statistics"),
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
