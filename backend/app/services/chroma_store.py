"""ChromaDB persistence for the institutional knowledge base."""

from __future__ import annotations

import json
import logging
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
        }
        if count == 0:
            return stats

        data = self._collection.get(include=["metadatas"])
        metadatas = data.get("metadatas") or []
        document_ids = {str(meta.get("document_id")) for meta in metadatas if meta and meta.get("document_id")}
        stats["documents_indexed"] = len(document_ids)

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
                "title": latest.get("title"),
                "source_filename": latest.get("source_filename"),
                "indexed_at": latest.get("indexed_at"),
            }
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
