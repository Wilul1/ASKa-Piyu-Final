"""ChromaDB persistence for the institutional knowledge base."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    document_id: str
    title: str
    source_filename: str
    chunk_index: int
    text: str
    relevance_score: float
    original_score: float | None = None
    reranked_score: float | None = None
    rerank_reasons: list[str] | None = None
    metadata: dict[str, Any] | None = None


class KnowledgeBaseStore:
    def __init__(self) -> None:
        self._client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def chunk_count(self) -> int:
        return self._collection.count()

    def reset_collection(self) -> dict[str, Any]:
        """Delete and recreate only the configured Chroma knowledge-base collection."""
        collection_name = settings.chroma_collection_name
        removed_count = self._safe_collection_count()
        timestamp = datetime.now(timezone.utc).isoformat()

        try:
            self._client.delete_collection(name=collection_name)
        except Exception as exc:
            if not _is_missing_collection_error(exc):
                raise

        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "Chroma collection reset: collection=%s vectors_removed=%s timestamp=%s",
            collection_name,
            removed_count,
            timestamp,
        )
        return {
            "collection": collection_name,
            "vectors_removed": removed_count,
            "timestamp": timestamp,
        }

    def _safe_collection_count(self) -> int | None:
        try:
            return int(self._collection.count())
        except Exception:
            return None

    def add_document_chunks(
        self,
        *,
        document_id: str,
        title: str,
        source_filename: str,
        document_type: str,
        chunks: list,
        document_metadata: dict[str, Any] | None = None,
    ) -> int:
        if not chunks:
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for chunk in chunks:
            chunk_id = f"{document_id}::{chunk.chunk_index}"
            ids.append(chunk_id)
            documents.append(chunk.text)
            metadata: dict[str, Any] = {
                "document_id": document_id,
                "title": title,
                "source_filename": source_filename,
                "document_type": document_type,
                "chunk_index": chunk.chunk_index,
                "chunk_id": chunk_id,
                "char_start": chunk.char_start,
                "indexed_at": datetime.now(timezone.utc).isoformat(),
            }
            for key, value in (getattr(chunk, "metadata", None) or {}).items():
                if isinstance(value, (str, int, float, bool)):
                    metadata[key] = value
                elif isinstance(value, (list, dict)):
                    metadata[key] = json.dumps(value)
            for key, value in (document_metadata or {}).items():
                if isinstance(value, (str, int, float, bool)):
                    metadata[f"doc_{key}"] = value
            _enrich_chunk_citation_metadata(metadata, chunk_text=chunk.text)
            metadatas.append(metadata)

        self._collection.add(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    def collection_statistics(self) -> dict[str, Any]:
        count = self._collection.count()
        stats: dict[str, Any] = {
            "documents_indexed": 0,
            "total_chunks_indexed": count,
            "embedding_model": "ChromaDB default embedding function",
            "vector_store": "ChromaDB",
            "last_indexed_document": None,
            "citation_ready_documents": 0,
            "citation_reindex_required": 0,
            "chunks_missing_document_id": 0,
            "chunks_with_page_number": 0,
            "document_type_counts": {},
            "article_type_counts": {},
            "sample_titles": [],
            "indexed_documents": [],
        }
        if count == 0:
            return stats

        data = self._collection.get(include=["metadatas"])
        metadatas = data.get("metadatas") or []
        document_ids = {
            str(meta.get("document_id")).strip()
            for meta in metadatas
            if meta and str(meta.get("document_id") or "").strip()
        }
        stats["documents_indexed"] = len(document_ids)
        stats["chunks_missing_document_id"] = sum(
            1 for meta in metadatas if not meta or not str(meta.get("document_id") or "").strip()
        )
        sample_titles: list[str] = []
        chunks_with_page = 0
        for meta in metadatas:
            if not meta:
                continue
            page = meta.get("page_number") or meta.get("page_start") or meta.get("page")
            if isinstance(page, int) or (isinstance(page, str) and str(page).isdigit()):
                chunks_with_page += 1
            title = str(
                meta.get("source_section")
                or meta.get("canonical_topic")
                or meta.get("title")
                or ""
            ).strip()
            if title and title not in sample_titles and len(sample_titles) < 20:
                sample_titles.append(title)
        stats["chunks_with_page_number"] = chunks_with_page
        stats["sample_titles"] = sample_titles

        latest = None
        for meta in metadatas:
            if not meta:
                continue
            indexed_at = str(meta.get("indexed_at") or "")
            if latest is None or indexed_at > str(latest.get("indexed_at") or ""):
                latest = meta
        if latest:
            stats["last_indexed_document"] = {
                "document_id": latest.get("document_id"),
                "title": latest.get("doc_display_title")
                or latest.get("doc_source_label")
                or latest.get("source_filename")
                or "Untitled",
                "source_filename": latest.get("source_filename"),
                "indexed_at": latest.get("indexed_at"),
                "chunk_title": latest.get("source_section") or latest.get("title"),
            }

        # Level-2 citation readiness per indexed document.
        from app.services.document_storage import citation_readiness_for_document_id
        from collections import Counter

        by_doc: dict[str, dict[str, Any]] = {}
        document_type_counts: Counter[str] = Counter()
        article_type_counts: Counter[str] = Counter()
        for meta in metadatas:
            if not meta:
                continue
            doc_id = str(meta.get("document_id") or "").strip()
            if not doc_id:
                continue
            entry = by_doc.setdefault(
                doc_id,
                {
                    "document_id": doc_id,
                    "source_filename": str(meta.get("source_filename") or ""),
                    "title": str(
                        meta.get("doc_display_title")
                        or meta.get("doc_source_label")
                        or meta.get("source_filename")
                        or meta.get("title")
                        or ""
                    ),
                    "chunk_count": 0,
                    "chunks_with_document_id": True,
                    "chunks_with_page_number": 0,
                    "document_type_counts": Counter(),
                    "article_type_counts": Counter(),
                    "sample_titles": [],
                },
            )
            entry["chunk_count"] += 1
            if not entry.get("source_filename") and meta.get("source_filename"):
                entry["source_filename"] = str(meta.get("source_filename"))
            chunk_title = str(
                meta.get("source_section")
                or meta.get("canonical_topic")
                or meta.get("title")
                or ""
            ).strip()
            if chunk_title and chunk_title not in entry["sample_titles"] and len(entry["sample_titles"]) < 12:
                entry["sample_titles"].append(chunk_title)
            doc_type = str(meta.get("document_type") or meta.get("parser_document_type") or "unknown").strip() or "unknown"
            article_type = str(meta.get("article_type") or "").strip() or "unspecified"
            entry["document_type_counts"][doc_type] += 1
            entry["article_type_counts"][article_type] += 1
            document_type_counts[doc_type] += 1
            article_type_counts[article_type] += 1
            page = meta.get("page_number") or meta.get("page_start") or meta.get("page")
            if isinstance(page, int) or (isinstance(page, str) and page.isdigit()):
                entry["chunks_with_page_number"] += 1

        indexed_documents: list[dict[str, Any]] = []
        ready_count = 0
        reindex_count = 0
        for doc_id, entry in sorted(by_doc.items(), key=lambda item: item[1].get("source_filename") or item[0]):
            readiness = citation_readiness_for_document_id(doc_id)
            pdf_stored = bool(readiness.get("pdf_stored"))
            row_ok = bool(readiness.get("source_documents_row"))
            has_pages = int(entry.get("chunks_with_page_number") or 0) > 0
            # Level-2 citation viewing needs PDF + row + page-grounded chunks.
            level2_ready = (
                bool(readiness.get("level2_citation_ready"))
                and entry["chunk_count"] > 0
                and has_pages
            )
            if level2_ready:
                ready_count += 1
                message = None
            else:
                reindex_count += 1
                if not has_pages:
                    message = "Re-index required: chunks are missing page_number for PDF citation viewing."
                else:
                    message = "Re-index required for PDF citation viewing."
            indexed_documents.append(
                {
                    "document_id": entry["document_id"],
                    "source_filename": entry.get("source_filename"),
                    "title": entry.get("title"),
                    "chunk_count": entry["chunk_count"],
                    "chunks_with_document_id": True,
                    "chunks_with_page_number": entry["chunks_with_page_number"],
                    "pdf_stored": pdf_stored,
                    "source_documents_row": row_ok,
                    "level2_citation_ready": level2_ready,
                    "reindex_required": not level2_ready,
                    "message": message,
                    "source_label": readiness.get("source_label"),
                    "document_type_counts": dict(entry["document_type_counts"]),
                    "article_type_counts": dict(entry["article_type_counts"]),
                    "sample_titles": list(entry["sample_titles"]),
                }
            )
        stats["indexed_documents"] = indexed_documents
        stats["citation_ready_documents"] = ready_count
        stats["citation_reindex_required"] = reindex_count
        stats["document_type_counts"] = dict(document_type_counts)
        stats["article_type_counts"] = dict(article_type_counts)
        return stats

    def list_chunks(self) -> list[dict[str, Any]]:
        """Return stored chunks and metadata without mutating the collection."""
        if self._collection.count() == 0:
            return []

        data = self._collection.get(include=["documents", "metadatas"])
        ids = data.get("ids") or []
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []

        chunks: list[dict[str, Any]] = []
        for chunk_id, text, metadata in zip(ids, documents, metadatas):
            chunks.append(
                {
                    "id": str(chunk_id),
                    "text": text or "",
                    "metadata": dict(metadata or {}),
                }
            )
        return chunks

    def get_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """Return one stored chunk by Chroma id without mutating the collection."""
        data = self._collection.get(
            ids=[chunk_id],
            include=["documents", "metadatas"],
        )
        ids = data.get("ids") or []
        if not ids:
            return None

        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []
        return {
            "id": str(ids[0]),
            "text": documents[0] if documents else "",
            "metadata": dict(metadatas[0] if metadatas else {}),
        }

    def delete_document(self, document_id: str) -> None:
        existing = self._collection.get(where={"document_id": document_id})
        if existing["ids"]:
            self._collection.delete(ids=existing["ids"])

    def delete_by_source_filename(self, source_filename: str) -> int:
        """Remove all chunks previously indexed for the same source PDF/filename.

        Re-index from Admin must replace the full document, not leave an old
        single form chunk alongside (or instead of) a fresh multi-service set.
        """
        name = (source_filename or "").strip()
        if not name or self._collection.count() == 0:
            return 0
        existing = self._collection.get(where={"source_filename": name})
        ids = list(existing.get("ids") or [])
        if not ids:
            # Case-insensitive / unicode-dash fallback when exact match misses.
            normalized = re.sub(r"[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]+", "-", name.casefold())
            data = self._collection.get(include=["metadatas"])
            for chunk_id, meta in zip(data.get("ids") or [], data.get("metadatas") or []):
                if not meta:
                    continue
                stored = str(meta.get("source_filename") or "")
                stored_norm = re.sub(
                    r"[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]+",
                    "-",
                    stored.casefold(),
                )
                if stored_norm == normalized:
                    ids.append(chunk_id)
            ids = list(dict.fromkeys(ids))
        if ids:
            self._collection.delete(ids=ids)
        return len(ids)

    def search(self, query: str, *, top_k: int | None = None, raw_k: int | None = None) -> list[RetrievedChunk]:
        from app.services.retrieval_reranker import prepare_retrieval_query, rerank_chunks

        k = top_k or settings.rag_top_k
        if self._collection.count() == 0:
            return []

        candidate_k = raw_k or max(k, 10)
        candidate_k = max(k, candidate_k)
        prepared_query = prepare_retrieval_query(query.strip())

        result = self._collection.query(
            query_texts=[prepared_query.expanded_query],
            n_results=min(candidate_k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[RetrievedChunk] = []
        docs = result.get("documents") or [[]]
        metas = result.get("metadatas") or [[]]
        distances = result.get("distances") or [[]]

        for text, meta, distance in zip(docs[0], metas[0], distances[0]):
            if not text or not meta:
                continue
            # Chroma cosine distance: lower = more similar; convert to 0–1 relevance
            relevance = max(0.0, 1.0 - float(distance))
            chunks.append(
                RetrievedChunk(
                    document_id=str(meta.get("document_id", "")),
                    title=str(meta.get("title", "")),
                    source_filename=str(meta.get("source_filename", "")),
                    chunk_index=int(meta.get("chunk_index", 0)),
                    text=text,
                    relevance_score=round(relevance, 4),
                    original_score=round(relevance, 4),
                    reranked_score=round(relevance, 4),
                    rerank_reasons=[],
                    metadata=dict(meta),
                )
            )
        return rerank_chunks(prepared_query.expanded_query, chunks)[:k]


@lru_cache(maxsize=1)
def get_knowledge_base_store() -> KnowledgeBaseStore:
    return KnowledgeBaseStore()


def _enrich_chunk_citation_metadata(metadata: dict[str, Any], *, chunk_text: str) -> None:
    """Ensure Level-2 citation fields exist on every indexed chunk.

    Level-3 fields (bbox, page_width, page_height, text_position) are preserved
    when already present on the chunk, but are not required.
    """
    page = metadata.get("page_number")
    if page is None:
        page = metadata.get("page_start") or metadata.get("page")
    if isinstance(page, str) and page.isdigit():
        page = int(page)
    if isinstance(page, int) and page > 0:
        metadata["page_number"] = page
        metadata.setdefault("page", page)
        metadata.setdefault("page_start", page)

    section = (
        metadata.get("source_section")
        or metadata.get("section_heading")
        or metadata.get("section")
        or metadata.get("article")
        or metadata.get("canonical_topic")
        or ""
    )
    section = str(section).strip()
    if section:
        metadata["source_section"] = section

    if not metadata.get("article_type"):
        article_type = metadata.get("doc_article_type") or metadata.get("document_type")
        if article_type:
            metadata["article_type"] = str(article_type)

    excerpt = str(metadata.get("source_excerpt") or "").strip()
    if not excerpt:
        cleaned = re.sub(r"\s+", " ", (chunk_text or "")).strip()
        excerpt = cleaned[:400]
        if len(cleaned) > 400:
            excerpt = excerpt.rstrip() + "…"
    if excerpt:
        metadata["source_excerpt"] = excerpt

    # Keep optional Level-3 geometry if upstream provided it (do not invent).
    for key in ("bbox", "page_width", "page_height", "text_position"):
        if key in metadata and metadata[key] in ("", None):
            metadata.pop(key, None)


def _is_missing_collection_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "does not exist",
            "not found",
            "not exists",
            "no collection",
            "invalidcollection",
        )
    )
