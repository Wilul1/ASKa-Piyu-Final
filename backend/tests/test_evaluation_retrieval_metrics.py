from __future__ import annotations

import pytest

from app.services.evaluation.classification_metrics import EmptyDatasetError
from app.services.evaluation.retrieval_metrics import (
    RetrievalQueryResult,
    evaluate_retrieval,
)


def test_hand_computed_metrics_over_two_queries():
    results = [
        RetrievalQueryResult(
            query_id="q1",
            retrieved_ids=("d1", "d2", "d3", "d4"),
            relevant_ids=frozenset({"d2", "d4"}),
        ),
        RetrievalQueryResult(
            query_id="q2",
            retrieved_ids=("e1", "e2"),
            relevant_ids=frozenset({"e1"}),
        ),
    ]
    metrics = evaluate_retrieval(results, k=3)
    assert metrics.query_count == 2
    assert metrics.hit_at_k == pytest.approx(1.0, abs=1e-4)
    assert metrics.mrr == pytest.approx(0.75, abs=1e-4)
    assert metrics.precision_at_k == pytest.approx(1 / 3, abs=1e-4)
    assert metrics.recall_at_k == pytest.approx(0.75, abs=1e-4)
    assert metrics.ndcg_at_k == pytest.approx(0.69345, abs=1e-3)


def test_no_relevant_doc_retrieved_scores_zero_hit_and_mrr():
    results = [
        RetrievalQueryResult(
            query_id="q1",
            retrieved_ids=("d1", "d2"),
            relevant_ids=frozenset({"d9"}),
        )
    ]
    metrics = evaluate_retrieval(results, k=2)
    assert metrics.hit_at_k == 0.0
    assert metrics.mrr == 0.0
    assert metrics.precision_at_k == 0.0
    assert metrics.recall_at_k == 0.0
    assert metrics.ndcg_at_k == 0.0


def test_graded_relevance_changes_ndcg_from_binary_default():
    binary = RetrievalQueryResult(
        query_id="q1", retrieved_ids=("d1", "d2"), relevant_ids=frozenset({"d1", "d2"})
    )
    graded = RetrievalQueryResult(
        query_id="q1",
        retrieved_ids=("d1", "d2"),
        relevant_ids=frozenset({"d1", "d2"}),
        graded_relevance={"d1": 1.0, "d2": 0.2},
    )
    binary_metrics = evaluate_retrieval([binary], k=2)
    graded_metrics = evaluate_retrieval([graded], k=2)
    assert binary_metrics.ndcg_at_k == 1.0  # ideal order already achieved, binary
    assert graded_metrics.ndcg_at_k == 1.0  # still ideal order (d1 > d2 grade, d1 ranked first)


def test_empty_query_set_raises():
    with pytest.raises(EmptyDatasetError):
        evaluate_retrieval([], k=3)


def test_non_positive_k_raises():
    results = [RetrievalQueryResult(query_id="q1", retrieved_ids=("d1",), relevant_ids=frozenset({"d1"}))]
    with pytest.raises(ValueError):
        evaluate_retrieval(results, k=0)


def test_query_with_no_relevant_ids_raises_rather_than_silently_scoring():
    results = [RetrievalQueryResult(query_id="q1", retrieved_ids=("d1",), relevant_ids=frozenset())]
    with pytest.raises(ValueError):
        evaluate_retrieval(results, k=1)
