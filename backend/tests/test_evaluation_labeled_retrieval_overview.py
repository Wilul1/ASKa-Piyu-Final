"""Labeled retrieval overlay numbers must stay the verified 12-question scores."""

from __future__ import annotations

from app.services.evaluation.labeled_retrieval_overview import (
    load_labeled_retrieval_overview,
    overlay_retrieval_cases,
)


def test_retrieval_overlay_headline_metrics_are_unchanged():
    payload = load_labeled_retrieval_overview()
    assert payload is not None
    metrics = payload["metrics"]
    assert metrics["embedding_hit_at_k"] == 0.8333
    assert metrics["embedding_mrr"] == 0.6875
    assert metrics["embedding_ndcg_at_k"] == 0.6871
    assert metrics["reranked_hit_at_k"] == 0.9167
    assert metrics["reranked_mrr"] == 0.8125
    assert metrics["reranked_ndcg_at_k"] == 0.7812


def test_retrieval_overlay_case_hits_recompute_to_headline_hit_at_k():
    cases = overlay_retrieval_cases()
    assert cases is not None
    assert len(cases) == 12
    assert all(case.get("question") for case in cases)
    embedding_hits = sum(1 for case in cases if case.get("embedding_hit") is True)
    reranked_hits = sum(1 for case in cases if case.get("reranked_hit") is True)
    assert round(embedding_hits / 12, 4) == 0.8333
    assert round(reranked_hits / 12, 4) == 0.9167
    assert cases[2]["case_id"] == "rag_benchmark_03"
    assert cases[2]["embedding_hit"] is False
    assert cases[2]["reranked_hit"] is True
    assert cases[9]["case_id"] == "rag_benchmark_10"
    assert cases[9]["embedding_hit"] is False
    assert cases[9]["reranked_hit"] is False
