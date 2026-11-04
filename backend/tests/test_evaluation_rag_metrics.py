from __future__ import annotations

import pytest

from app.services.evaluation.classification_metrics import EmptyDatasetError
from app.services.evaluation.rag_metrics import (
    RagCaseResult,
    aggregate_rag_metrics,
    citation_metrics_from_outcome,
)
from app.services.qa.citation_verification import Claim, VerificationOutcome


def _outcome(**overrides) -> VerificationOutcome:
    defaults = dict(
        mode="llm",
        claims=[Claim(claim_id="c1", text="claim one"), Claim(claim_id="c2", text="claim two")],
        candidate_citation_ids=["cand-1", "cand-2"],
        verifier_invoked=True,
        verifier_succeeded=True,
        per_claim_verified_ids={"c1": ["cand-1"], "c2": []},
        verified_citation_ids=["cand-1"],
    )
    defaults.update(overrides)
    return VerificationOutcome(**defaults)


def test_citation_metrics_from_successful_outcome():
    outcome = _outcome()
    metrics = citation_metrics_from_outcome(outcome, gold_citation_ids={"cand-1", "cand-3"})
    assert metrics["faithfulness"] == pytest.approx(0.5, abs=1e-4)  # 1 of 2 claims supported
    assert metrics["claim_support_rate"] == pytest.approx(0.5, abs=1e-4)
    assert metrics["citation_set_precision"] == pytest.approx(1.0, abs=1e-4)  # cand-1 in gold
    assert metrics["citation_set_recall"] == pytest.approx(0.5, abs=1e-4)  # 1 of 2 gold ids found


def test_citation_metrics_when_verifier_did_not_succeed_are_all_none():
    outcome = _outcome(verifier_succeeded=False, per_claim_verified_ids={}, verified_citation_ids=[])
    metrics = citation_metrics_from_outcome(outcome, gold_citation_ids={"cand-1"})
    # A failed verifier call means no LLM citation evaluation occurred for this
    # case -- scoring the empty predicted set against gold would misreport a
    # real "checked and found nothing" result, so every field stays None.
    assert metrics["faithfulness"] is None
    assert metrics["claim_support_rate"] is None
    assert metrics["citation_set_precision"] is None
    assert metrics["citation_set_recall"] is None


def test_citation_metrics_when_verifier_never_invoked_are_all_none():
    outcome = _outcome(
        verifier_invoked=False, verifier_succeeded=False,
        per_claim_verified_ids={}, verified_citation_ids=[],
    )
    metrics = citation_metrics_from_outcome(outcome, gold_citation_ids={"cand-1"})
    assert metrics == {
        "faithfulness": None,
        "claim_support_rate": None,
        "citation_set_precision": None,
        "citation_set_recall": None,
    }


def test_empty_gold_citation_ids_raises_rather_than_silently_scoring():
    outcome = _outcome()
    with pytest.raises(ValueError):
        citation_metrics_from_outcome(outcome, gold_citation_ids=set())


def test_aggregate_rag_metrics_ignores_none_values_per_metric():
    cases = [
        RagCaseResult(case_id="a", faithfulness=0.8, answer_correctness=None),
        RagCaseResult(case_id="b", faithfulness=0.4, answer_correctness=0.9),
    ]
    metrics = aggregate_rag_metrics(cases)
    assert metrics.faithfulness == pytest.approx(0.6, abs=1e-4)
    assert metrics.answer_correctness == pytest.approx(0.9, abs=1e-4)
    assert metrics.metric_contributing_counts["faithfulness"] == 2
    assert metrics.metric_contributing_counts["answer_correctness"] == 1


def test_aggregate_rag_metrics_distinguishes_human_verified_from_llm_judge():
    cases = [
        RagCaseResult(case_id="a", faithfulness=0.8, judge_source="llm_judge"),
        RagCaseResult(case_id="b", faithfulness=0.9, judge_source="human_verified"),
    ]
    metrics = aggregate_rag_metrics(cases)
    assert metrics.llm_judge_case_count == 1
    assert metrics.human_verified_case_count == 1


def test_metric_entirely_absent_across_all_cases_reports_none_not_zero():
    cases = [RagCaseResult(case_id="a"), RagCaseResult(case_id="b")]
    metrics = aggregate_rag_metrics(cases)
    assert metrics.answer_correctness is None
    assert metrics.metric_contributing_counts["answer_correctness"] == 0


def test_empty_case_list_raises():
    with pytest.raises(EmptyDatasetError):
        aggregate_rag_metrics([])
