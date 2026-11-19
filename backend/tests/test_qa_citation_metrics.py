"""Deterministic unit tests for Stage 2 QA, citation, and completion metrics."""

from __future__ import annotations

import pytest

from app.services.evaluation.qa_citation_metrics import (
    CLAIM_STATUS_MEANINGS,
    CLAIM_STATUS_NOT_ASSESSABLE,
    CLAIM_STATUS_SUPPORTED,
    CLAIM_STATUS_UNSUPPORTED,
    EXECUTION_STATUS_DEFINITIONS,
    FAITHFULNESS_EVIDENCE_BASIS,
    RETRY_POLICY,
    ClaimMetricInput,
    ExecutionRecord,
    FractionMetric,
    QaCitationMetricError,
    aggregate_dual_ai_qa_scores,
    aggregate_execution_records,
    compute_citation_metrics,
    compute_completion_rate,
)

VALID_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee::0"
INVALID_ID = "not-a-real-doc::99"
OTHER_VALID_ID = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff::1"


def _claim(
    claim_id: str,
    *,
    support: str,
    supporting: tuple[str, ...] = (),
    requires_citation: bool = True,
) -> ClaimMetricInput:
    return ClaimMetricInput(
        claim_id=claim_id,
        requires_citation=requires_citation,
        claim_support=support,
        supporting_displayed_ids=supporting,
    )


def test_claim_status_meanings_are_explicit():
    assert set(CLAIM_STATUS_MEANINGS) == {
        CLAIM_STATUS_SUPPORTED,
        CLAIM_STATUS_UNSUPPORTED,
        CLAIM_STATUS_NOT_ASSESSABLE,
    }
    assert "denominator" in CLAIM_STATUS_MEANINGS[CLAIM_STATUS_NOT_ASSESSABLE]


def test_citation_precision_includes_invalid_displayed_ids():
    # Unique displayed: VALID_ID (supports a claim) + INVALID_ID (does not).
    # Precision = 1 / 2 = 0.5. Invalid id stays in the denominator.
    metrics = compute_citation_metrics(
        displayed_citation_ids=[VALID_ID, INVALID_ID, VALID_ID],
        claims=[
            _claim("c1", support=CLAIM_STATUS_SUPPORTED, supporting=(VALID_ID,)),
        ],
        citation_validity_by_id={
            VALID_ID: "valid",
            INVALID_ID: "unresolved",
        },
    )
    assert metrics.unique_displayed_citation_ids == (VALID_ID, INVALID_ID)
    assert metrics.citation_precision == FractionMetric(1, 2, 0.5)
    assert metrics.citation_validity == FractionMetric(1, 2, 0.5)


def test_citation_completeness_with_missing_citations():
    # Three citation-required claims; two have a supporting displayed citation.
    metrics = compute_citation_metrics(
        displayed_citation_ids=[VALID_ID],
        claims=[
            _claim("c1", support=CLAIM_STATUS_SUPPORTED, supporting=(VALID_ID,)),
            _claim("c2", support=CLAIM_STATUS_SUPPORTED, supporting=(VALID_ID,)),
            _claim("c3", support=CLAIM_STATUS_UNSUPPORTED, supporting=()),
        ],
        citation_validity_by_id={VALID_ID: "valid"},
    )
    assert metrics.citation_completeness == FractionMetric(2, 3, 2 / 3)
    assert metrics.citation_precision == FractionMetric(1, 1, 1.0)


def test_supported_unsupported_and_not_assessable_claim_handling():
    # Four citation-required claims: 2 supported, 1 unsupported, 1 not_assessable.
    # Support rate = 2/4; unsupported rate = 1/4. not_assessable is denom-only.
    metrics = compute_citation_metrics(
        displayed_citation_ids=[VALID_ID, OTHER_VALID_ID],
        claims=[
            _claim("c1", support=CLAIM_STATUS_SUPPORTED, supporting=(VALID_ID,)),
            _claim("c2", support=CLAIM_STATUS_SUPPORTED, supporting=(OTHER_VALID_ID,)),
            _claim("c3", support=CLAIM_STATUS_UNSUPPORTED, supporting=()),
            _claim("c4", support=CLAIM_STATUS_NOT_ASSESSABLE, supporting=()),
        ],
        citation_validity_by_id={
            VALID_ID: "valid",
            OTHER_VALID_ID: "valid",
        },
    )
    assert metrics.citation_required_claim_count == 4
    assert metrics.supported_claim_count == 2
    assert metrics.unsupported_claim_count == 1
    assert metrics.not_assessable_claim_count == 1
    assert metrics.claim_support_rate == FractionMetric(2, 4, 0.5)
    assert metrics.unsupported_claim_rate == FractionMetric(1, 4, 0.25)
    assert metrics.citation_completeness == FractionMetric(2, 4, 0.5)
    assert metrics.citation_precision == FractionMetric(2, 2, 1.0)


def test_not_assessable_is_not_counted_as_supported_or_unsupported():
    metrics = compute_citation_metrics(
        displayed_citation_ids=[VALID_ID],
        claims=[
            _claim("c1", support=CLAIM_STATUS_NOT_ASSESSABLE, supporting=()),
            _claim("c2", support=CLAIM_STATUS_NOT_ASSESSABLE, supporting=()),
        ],
        citation_validity_by_id={VALID_ID: "valid"},
    )
    assert metrics.claim_support_rate == FractionMetric(0, 2, 0.0)
    assert metrics.unsupported_claim_rate == FractionMetric(0, 2, 0.0)
    assert metrics.not_assessable_claim_count == 2


def test_zero_denominator_returns_null_not_zero():
    metrics = compute_citation_metrics(
        displayed_citation_ids=[],
        claims=[],
        citation_validity_by_id={},
    )
    assert metrics.citation_precision == FractionMetric(0, 0, None)
    assert metrics.citation_validity == FractionMetric(0, 0, None)
    assert metrics.citation_completeness == FractionMetric(0, 0, None)
    assert metrics.claim_support_rate == FractionMetric(0, 0, None)
    assert metrics.unsupported_claim_rate == FractionMetric(0, 0, None)


def test_zero_displayed_ids_with_claims_nulls_precision_only():
    metrics = compute_citation_metrics(
        displayed_citation_ids=[],
        claims=[_claim("c1", support=CLAIM_STATUS_UNSUPPORTED, supporting=())],
        citation_validity_by_id={},
    )
    assert metrics.citation_precision.value is None
    assert metrics.citation_validity.value is None
    assert metrics.citation_completeness == FractionMetric(0, 1, 0.0)
    assert metrics.claim_support_rate == FractionMetric(0, 1, 0.0)
    assert metrics.unsupported_claim_rate == FractionMetric(1, 1, 1.0)


def test_invalid_ids_are_not_silently_removed_from_validity_denominator():
    metrics = compute_citation_metrics(
        displayed_citation_ids=[INVALID_ID, "also-missing::3"],
        claims=[],
        citation_validity_by_id={
            INVALID_ID: "unresolved",
            "also-missing::3": "wrong_document",
        },
    )
    assert metrics.unique_displayed_citation_ids == (INVALID_ID, "also-missing::3")
    assert metrics.citation_validity == FractionMetric(0, 2, 0.0)
    assert metrics.citation_precision == FractionMetric(0, 2, 0.0)


def test_missing_validity_annotation_is_rejected_not_defaulted():
    with pytest.raises(QaCitationMetricError, match="missing displayed id"):
        compute_citation_metrics(
            displayed_citation_ids=[VALID_ID, INVALID_ID],
            claims=[],
            citation_validity_by_id={VALID_ID: "valid"},
        )


def test_supported_claim_requires_supporting_displayed_id():
    with pytest.raises(QaCitationMetricError, match="at least one supporting displayed"):
        compute_citation_metrics(
            displayed_citation_ids=[VALID_ID],
            claims=[_claim("c1", support=CLAIM_STATUS_SUPPORTED, supporting=())],
            citation_validity_by_id={VALID_ID: "valid"},
        )


def test_unsupported_claim_must_not_list_supporting_ids():
    with pytest.raises(QaCitationMetricError, match="must not list supporting"):
        compute_citation_metrics(
            displayed_citation_ids=[VALID_ID],
            claims=[_claim("c1", support=CLAIM_STATUS_UNSUPPORTED, supporting=(VALID_ID,))],
            citation_validity_by_id={VALID_ID: "valid"},
        )


def test_not_assessable_remains_distinct_from_supported():
    with pytest.raises(QaCitationMetricError, match="not_assessable"):
        compute_citation_metrics(
            displayed_citation_ids=[VALID_ID],
            claims=[_claim("c1", support=CLAIM_STATUS_NOT_ASSESSABLE, supporting=(VALID_ID,))],
            citation_validity_by_id={VALID_ID: "valid"},
        )


def test_legacy_not_applicable_status_is_rejected():
    with pytest.raises(QaCitationMetricError, match="not_assessable"):
        compute_citation_metrics(
            displayed_citation_ids=[VALID_ID],
            claims=[
                ClaimMetricInput(
                    claim_id="c1",
                    requires_citation=True,
                    claim_support="not_applicable",
                    supporting_displayed_ids=(),
                )
            ],
            citation_validity_by_id={VALID_ID: "valid"},
        )


def test_qa_mean_of_two_judges_matches_hand_calculation():
    # Primary 4,4,4,4 and secondary 4,3,4,3.
    # Reported criteria: 4.0, 3.5, 4.0, 3.5. Overall = 15/4 = 3.75.
    # Completeness/faithfulness use the mean, never max(4, 3)=4.
    result = aggregate_dual_ai_qa_scores(
        {
            "evaluation_status": "evaluated",
            "correctness": 4,
            "completeness": 4,
            "relevance": 4,
            "faithfulness": 4,
        },
        {
            "evaluation_status": "evaluated",
            "correctness": 4,
            "completeness": 3,
            "relevance": 4,
            "faithfulness": 3,
        },
    )
    assert result.primary.completeness == 4
    assert result.secondary.completeness == 3
    assert result.reported_correctness == 4.0
    assert result.reported_completeness == 3.5
    assert result.reported_relevance == 4.0
    assert result.reported_faithfulness == 3.5
    assert result.reported_overall == 3.75
    assert result.faithfulness_evidence_basis == FAITHFULNESS_EVIDENCE_BASIS


def test_judge_disagreement_uses_absolute_differences_and_keeps_the_mean():
    result = aggregate_dual_ai_qa_scores(
        {"correctness": 4, "completeness": 4, "relevance": 2, "faithfulness": 1},
        {"correctness": 4, "completeness": 3, "relevance": 2, "faithfulness": 4},
    )
    assert result.absolute_differences == {
        "correctness": 0,
        "completeness": 1,
        "relevance": 0,
        "faithfulness": 3,
    }
    assert result.disagreement_by_criterion == {
        "correctness": False,
        "completeness": True,
        "relevance": False,
        "faithfulness": True,
    }
    assert result.disagreement is True
    # Mean of faithfulness 1 and 4 is 2.5, not 4.
    assert result.reported_faithfulness == 2.5
    assert result.reported_overall == (4.0 + 3.5 + 2.0 + 2.5) / 4


def test_identical_judges_have_no_disagreement():
    scores = {"correctness": 3, "completeness": 3, "relevance": 3, "faithfulness": 3}
    result = aggregate_dual_ai_qa_scores(scores, scores)
    assert result.disagreement is False
    assert result.reported_overall == 3.0
    assert all(delta == 0 for delta in result.absolute_differences.values())


def test_reject_out_of_range_judge_score():
    with pytest.raises(QaCitationMetricError, match="outside"):
        aggregate_dual_ai_qa_scores(
            {"correctness": 5, "completeness": 4, "relevance": 4, "faithfulness": 4},
            {"correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
        )


def test_reject_missing_judge_score():
    with pytest.raises(QaCitationMetricError, match="missing faithfulness"):
        aggregate_dual_ai_qa_scores(
            {"correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
            {"correctness": 4, "completeness": 4, "relevance": 4},
        )


def test_reject_non_integer_and_boolean_scores():
    with pytest.raises(QaCitationMetricError, match="integer"):
        aggregate_dual_ai_qa_scores(
            {"correctness": 4.0, "completeness": 4, "relevance": 4, "faithfulness": 4},
            {"correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
        )
    with pytest.raises(QaCitationMetricError, match="integer"):
        aggregate_dual_ai_qa_scores(
            {"correctness": True, "completeness": 4, "relevance": 4, "faithfulness": 4},
            {"correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
        )


def test_reject_unevaluated_judge_instead_of_dropping_it():
    with pytest.raises(QaCitationMetricError, match="evaluated"):
        aggregate_dual_ai_qa_scores(
            {"evaluation_status": "evaluated", "correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
            {"evaluation_status": "error", "correctness": 4, "completeness": 4, "relevance": 4, "faithfulness": 4},
        )


def test_failed_executions_remain_in_case_count_and_completion_rate():
    records = [
        ExecutionRecord(case_id="a", execution_status="ok", has_qa_scores=True, has_citation_scores=True),
        ExecutionRecord(case_id="b", execution_status="error"),
        ExecutionRecord(case_id="c", execution_status="oos_or_refusal", has_qa_scores=True),
        ExecutionRecord(case_id="d", execution_status="incomplete"),
    ]
    aggregation = aggregate_execution_records(records)
    assert aggregation.case_count == 4
    assert aggregation.successful_executions == 2
    assert aggregation.failed_executions == 2
    assert aggregation.failed_case_ids == ("b", "d")
    assert aggregation.completion_rate == FractionMetric(2, 4, 0.5)
    assert compute_completion_rate(records) == FractionMetric(2, 4, 0.5)


def test_completion_rate_is_null_when_there_are_no_cases():
    aggregation = aggregate_execution_records([])
    assert aggregation.case_count == 0
    assert aggregation.completion_rate == FractionMetric(0, 0, None)


def test_failed_execution_with_scores_is_rejected():
    with pytest.raises(QaCitationMetricError, match="must not carry QA or citation scores"):
        aggregate_execution_records(
            [
                ExecutionRecord(
                    case_id="failed",
                    execution_status="error",
                    has_qa_scores=True,
                )
            ]
        )


def test_unknown_execution_status_is_rejected_not_counted_as_success():
    with pytest.raises(QaCitationMetricError, match="execution_status"):
        aggregate_execution_records(
            [ExecutionRecord(case_id="x", execution_status="success")]
        )


def test_execution_status_definitions_and_retry_policy():
    assert EXECUTION_STATUS_DEFINITIONS["ok"].startswith("Answer capture completed")
    assert "not establish answer correctness" in EXECUTION_STATUS_DEFINITIONS["ok"]
    assert "not as a correct answer" in EXECUTION_STATUS_DEFINITIONS["oos_or_refusal"]
    assert EXECUTION_STATUS_DEFINITIONS["error"] == "Capture failed."
    assert "did not complete" in EXECUTION_STATUS_DEFINITIONS["incomplete"]
    assert "one final execution record per case_id" in RETRY_POLICY
    assert "rather than overwritten" in RETRY_POLICY


def test_duplicate_case_id_is_rejected_not_overwritten():
    with pytest.raises(QaCitationMetricError, match="does not overwrite"):
        aggregate_execution_records(
            [
                ExecutionRecord(case_id="same", execution_status="error"),
                ExecutionRecord(case_id="same", execution_status="ok", has_qa_scores=True),
            ]
        )
