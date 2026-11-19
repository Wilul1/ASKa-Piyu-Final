"""Pure retrieval metrics: Hit@K, MRR, Precision@K, Recall@K, nDCG@K.

Takes already-retrieved ranked id lists plus labeled relevance judgments --
never calls Chroma or an embedding model itself. The same function is used
to score an embedding-only ranking and a post-reranking ranking; the
distinction between the two lives in how the caller (evaluation_service)
gathers ``retrieved_ids`` for each run, not here -- this keeps the
ablation comparison (approval condition 3) an apples-to-apples use of one
metric implementation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.services.evaluation.classification_metrics import EmptyDatasetError


@dataclass(frozen=True)
class RetrievalQueryResult:
    """One query's ranked retrieval result plus its labeled gold relevance.

    ``relevant_ids`` must be non-empty and must reflect real, reviewed
    relevance judgments -- never fabricated. A query with no labeled
    relevant ids has no gold signal to score against and must be excluded
    by the caller (see ``app.services.evaluation.datasets``) before
    reaching this function, rather than silently contributing a 0 here.

    ``graded_relevance`` is optional: a map of doc/chunk id -> relevance
    grade (e.g. 0.0-1.0) for nDCG. When omitted, every id in
    ``relevant_ids`` is treated as grade 1.0 (binary relevance).
    """

    query_id: str
    retrieved_ids: tuple[str, ...]
    relevant_ids: frozenset[str]
    graded_relevance: dict[str, float] | None = None


@dataclass(frozen=True)
class RetrievalMetrics:
    k: int
    query_count: int
    hit_at_k: float
    mrr: float
    precision_at_k: float
    recall_at_k: float
    ndcg_at_k: float


def _ndcg_at_k(result: RetrievalQueryResult, k: int) -> float:
    top_k = result.retrieved_ids[:k]
    graded = result.graded_relevance or {doc_id: 1.0 for doc_id in result.relevant_ids}
    dcg = sum(graded.get(doc_id, 0.0) / math.log2(rank + 1) for rank, doc_id in enumerate(top_k, start=1))
    if result.graded_relevance:
        ideal_grades = sorted(graded.values(), reverse=True)[:k]
    else:
        ideal_grades = [1.0] * min(k, len(result.relevant_ids))
    idcg = sum(grade / math.log2(rank + 1) for rank, grade in enumerate(ideal_grades, start=1))
    return dcg / idcg if idcg else 0.0


def evaluate_retrieval(results: list[RetrievalQueryResult], *, k: int) -> RetrievalMetrics:
    if k <= 0:
        raise ValueError(f"k must be a positive integer (got {k}).")
    if not results:
        raise EmptyDatasetError("Cannot compute retrieval metrics on an empty query set.")
    for result in results:
        if not result.relevant_ids:
            raise ValueError(
                f"query_id={result.query_id!r} has no labeled relevant_ids; exclude "
                "unlabeled queries before calling evaluate_retrieval."
            )

    hits: list[float] = []
    reciprocal_ranks: list[float] = []
    precisions: list[float] = []
    recalls: list[float] = []
    ndcgs: list[float] = []

    for result in results:
        top_k = result.retrieved_ids[:k]
        relevant_in_top_k = [doc_id for doc_id in top_k if doc_id in result.relevant_ids]
        hits.append(1.0 if relevant_in_top_k else 0.0)
        precisions.append(len(relevant_in_top_k) / k)
        recalls.append(len(set(relevant_in_top_k)) / len(result.relevant_ids))

        reciprocal_rank = 0.0
        for rank, doc_id in enumerate(result.retrieved_ids, start=1):
            if doc_id in result.relevant_ids:
                reciprocal_rank = 1.0 / rank
                break
        reciprocal_ranks.append(reciprocal_rank)
        ndcgs.append(_ndcg_at_k(result, k))

    query_count = len(results)
    return RetrievalMetrics(
        k=k,
        query_count=query_count,
        hit_at_k=round(sum(hits) / query_count, 4),
        mrr=round(sum(reciprocal_ranks) / query_count, 4),
        precision_at_k=round(sum(precisions) / query_count, 4),
        recall_at_k=round(sum(recalls) / query_count, 4),
        ndcg_at_k=round(sum(ndcgs) / query_count, 4),
    )
