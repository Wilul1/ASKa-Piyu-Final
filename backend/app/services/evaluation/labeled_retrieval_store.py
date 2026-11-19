"""Read-only retrieval store for the 12-question labeled evaluation set.

The human-reviewed ``relevant_ids`` in
``benchmarks/evaluation/retrieval_relevance_dataset.json`` refer to chunks
in the isolated ``data/chroma_evaluation`` / ``aska_evaluation`` index
(691 records), not the live student knowledge base. Scoring those labels
against live Chroma would silently measure the wrong corpus.

This store is evaluation-only: it never writes, never opens production
Chroma, and is the same index ``run_retrieval_benchmark_local.py`` already
used successfully.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from app.services.chroma_store import (
    RetrievedChunk,
    _clamp_embedding_query_text,
    _strip_indexed_metadata_block,
)
from app.services.embeddings import E5EmbeddingFunction
from app.services.retrieval_reranker import prepare_retrieval_query, rerank_chunks

BACKEND_ROOT = Path(__file__).resolve().parents[3]
LABELED_RETRIEVAL_INDEX_PATH = BACKEND_ROOT / "data" / "chroma_evaluation"
LABELED_RETRIEVAL_COLLECTION = "aska_evaluation"
EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT = 691


class LabeledRetrievalStore:
    """Minimal ``.search()`` surface compatible with ``evaluate_retrieval``."""

    def __init__(self, *, index_path: Path | None = None, collection_name: str | None = None) -> None:
        path = Path(index_path or LABELED_RETRIEVAL_INDEX_PATH)
        name = collection_name or LABELED_RETRIEVAL_COLLECTION
        if not path.exists():
            raise FileNotFoundError(f"Labeled retrieval index not found: {path}")
        self._client = chromadb.PersistentClient(path=str(path))
        self._collection = self._client.get_collection(name)
        self._embedding = E5EmbeddingFunction()

    @property
    def chunk_count(self) -> int:
        return int(self._collection.count())

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        raw_k: int | None = None,
        user_role: str | None = None,
        ablation: Any = None,
    ) -> list[RetrievedChunk]:
        k = top_k or 5
        candidate_k = max(k, raw_k or k)
        prepared = prepare_retrieval_query(query.strip(), ablation=ablation)
        embedding_text = _clamp_embedding_query_text(prepared.expanded_query)
        query_vector = self._embedding.embed_query([embedding_text])[0]
        result = self._collection.query(
            query_embeddings=[query_vector],
            n_results=candidate_k,
            include=["documents", "metadatas", "distances"],
        )
        documents = (result.get("documents") or [[]])[0] or []
        metadatas = (result.get("metadatas") or [[]])[0] or []
        distances = (result.get("distances") or [[]])[0] or []
        chunks: list[RetrievedChunk] = []
        for raw_text, metadata, distance in zip(documents, metadatas, distances):
            if not raw_text or not metadata:
                continue
            text = _strip_indexed_metadata_block(raw_text)
            if not text:
                continue
            similarity = max(0.0, 1.0 - float(distance))
            chunks.append(
                RetrievedChunk(
                    document_id=str(metadata.get("document_id", "")),
                    title=str(metadata.get("title", "")),
                    source_filename=str(metadata.get("source_filename", "")),
                    chunk_index=int(metadata.get("chunk_index", 0)),
                    text=text,
                    relevance_score=round(similarity, 4),
                    original_score=round(similarity, 4),
                    reranked_score=round(similarity, 4),
                    rerank_reasons=[],
                    metadata=dict(metadata),
                )
            )
        ranked = rerank_chunks(prepared.expanded_query, chunks, ablation=ablation)
        return ranked[:k]


def open_labeled_retrieval_store() -> LabeledRetrievalStore | None:
    """Return the isolated evaluation index, or None if it is not present."""
    if not LABELED_RETRIEVAL_INDEX_PATH.exists():
        return None
    store = LabeledRetrievalStore()
    if store.chunk_count != EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT:
        raise RuntimeError(
            f"Expected {EXPECTED_LABELED_RETRIEVAL_CHUNK_COUNT} evaluation chunks, "
            f"found {store.chunk_count}. Refusing to score the 12-question labels "
            "against an unexpected corpus."
        )
    return store
