"""Stage 3.2B Phase 2 judging-orchestration tests.

All judge calls are mocks/stubs in this file. No real HTTP/LLM call is made
anywhere here -- Phase 2 only builds and tests the orchestration skeleton
and contract; Phase 3 implements a real judge callable against it.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_FALLBACK_NOT_GENUINE,
)
from app.services.evaluation.qa_citation_judging import (
    JudgeCallError,
    JudgeTimeoutError,
    QaCitationJudgingError,
    judge_eligible_case,
    judge_eligible_cases,
    summarize_judging_outcomes,
)
from app.services.evaluation.qa_citation_metrics import (
    JUDGE_EXECUTION_STATUS_ERROR,
    JUDGE_EXECUTION_STATUS_EVALUATED,
    JUDGE_EXECUTION_STATUS_MALFORMED,
    JUDGE_EXECUTION_STATUS_TIMEOUT,
    JUDGING_STATUS_EXCLUDED_INELIGIBLE,
    JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE,
    JUDGING_STATUS_FAILED_PARTIAL,
    JUDGING_STATUS_FAILED_TOTAL,
    JUDGING_STATUS_JUDGED,
)


def _base_record(**overrides) -> dict:
    record = {
        "case_id": "qac_001_example",
        "execution_status": "ok",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "generated_answer": "The fee is P75.00/page.",
    }
    record.update(overrides)
    return record


def _good_judge_response(**overrides) -> dict:
    response = {
        "evaluation_status": "evaluated",
        "correctness": 3,
        "completeness": 2,
        "relevance": 4,
        "faithfulness": 3,
    }
    response.update(overrides)
    return response


def _fixed_judge(response: Mapping[str, Any]):
    def _judge(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        return response

    return _judge


def _raising_judge(exc: Exception):
    def _judge(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        raise exc

    return _judge


# ---------------------------------------------------------------------------
# Success
# ---------------------------------------------------------------------------


def test_both_judges_succeed_produces_judged_with_hand_computed_mean():
    primary_response = _good_judge_response(
        correctness=4, completeness=2, relevance=4, faithfulness=2
    )
    secondary_response = _good_judge_response(
        correctness=2, completeness=4, relevance=4, faithfulness=4
    )

    outcome = judge_eligible_case(
        _base_record(),
        primary_judge=_fixed_judge(primary_response),
        secondary_judge=_fixed_judge(secondary_response),
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.qa_result is not None
    # Hand-computed means: (4+2)/2=3.0, (2+4)/2=3.0, (4+4)/2=4.0, (2+4)/2=3.0
    assert outcome.qa_result.reported_correctness == 3.0
    assert outcome.qa_result.reported_completeness == 3.0
    assert outcome.qa_result.reported_relevance == 4.0
    assert outcome.qa_result.reported_faithfulness == 3.0
    assert outcome.qa_result.reported_overall == pytest.approx((3.0 + 3.0 + 4.0 + 3.0) / 4)
    assert outcome.qa_result.disagreement is True  # correctness/completeness/faithfulness deltas are 2


# ---------------------------------------------------------------------------
# Partial failure
# ---------------------------------------------------------------------------


def test_one_judge_succeeds_one_raises_is_partial_failure_not_a_dual_score():
    outcome = judge_eligible_case(
        _base_record(),
        primary_judge=_fixed_judge(_good_judge_response()),
        secondary_judge=_raising_judge(JudgeTimeoutError("slow provider")),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT
    # The hard requirement: a single surviving judge is never promoted to a
    # dual-AI result.
    assert outcome.qa_result is None
    # The surviving judge's response is still preserved for diagnostics.
    assert outcome.primary_judge.raw_response == _good_judge_response()


def test_one_judge_malformed_one_succeeds_is_partial_failure():
    malformed = _good_judge_response()
    del malformed["faithfulness"]  # missing a required criterion

    outcome = judge_eligible_case(
        _base_record(),
        primary_judge=_fixed_judge(malformed),
        secondary_judge=_fixed_judge(_good_judge_response()),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.qa_result is None


# ---------------------------------------------------------------------------
# Total failure -- at least two distinct failure modes
# ---------------------------------------------------------------------------


def test_both_judges_fail_timeout_and_malformed_is_total_failure():
    malformed = _good_judge_response(correctness=9)  # out of [0, 4]

    outcome = judge_eligible_case(
        _base_record(),
        primary_judge=_raising_judge(JudgeTimeoutError("no response")),
        secondary_judge=_fixed_judge(malformed),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_TOTAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED
    assert outcome.qa_result is None
    assert "no response" in outcome.primary_judge.error_detail


def test_both_judges_fail_call_error_both_sides():
    outcome = judge_eligible_case(
        _base_record(),
        primary_judge=_raising_judge(JudgeCallError("401 Unauthorized")),
        secondary_judge=_raising_judge(JudgeCallError("401 Unauthorized")),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_TOTAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.qa_result is None


# ---------------------------------------------------------------------------
# Ineligible / not-applicable cases never reach a judge
# ---------------------------------------------------------------------------


def test_ineligible_fallback_record_never_calls_a_judge():
    calls: list[str] = []

    def _tracking_judge(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        calls.append("called")
        return _good_judge_response()

    record = _base_record(
        is_genuine_model_output=False,
        fallback_used=True,
        generated_answer="Extractive fallback text, not a real answer.",
    )

    outcome = judge_eligible_case(
        record, primary_judge=_tracking_judge, secondary_judge=_tracking_judge
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.eligibility_verdict.exclusion_reason == EXCLUSION_FALLBACK_NOT_GENUINE
    assert outcome.primary_judge is None
    assert outcome.secondary_judge is None
    assert outcome.qa_result is None
    assert calls == []  # the judge mocks were never invoked


def test_refusal_record_is_excluded_not_applicable_and_never_calls_a_judge():
    calls: list[str] = []

    def _tracking_judge(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        calls.append("called")
        return _good_judge_response()

    record = _base_record(
        execution_status="oos_or_refusal",
        generated_answer="I can't help with that out-of-scope request.",
    )

    outcome = judge_eligible_case(
        record, primary_judge=_tracking_judge, secondary_judge=_tracking_judge
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
    assert calls == []


def test_missing_eligibility_fields_excluded_before_any_judge_call():
    calls: list[str] = []

    def _tracking_judge(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        calls.append("called")
        return _good_judge_response()

    record = _base_record()
    del record["is_genuine_model_output"]

    outcome = judge_eligible_case(
        record, primary_judge=_tracking_judge, secondary_judge=_tracking_judge
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert calls == []


# ---------------------------------------------------------------------------
# Full batch
# ---------------------------------------------------------------------------


def test_full_batch_aggregate_counts_and_no_case_dropped():
    records = [
        _base_record(case_id="c_judged"),
        _base_record(
            case_id="c_ineligible",
            is_genuine_model_output=False,
            fallback_used=True,
            generated_answer="fallback text",
        ),
        _base_record(case_id="c_refusal", execution_status="oos_or_refusal"),
        _base_record(case_id="c_partial"),
        _base_record(case_id="c_total"),
    ]

    def primary_judge(record: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = record["case_id"]
        if case_id == "c_total":
            raise JudgeTimeoutError("timed out")
        return _good_judge_response()

    def secondary_judge(record: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = record["case_id"]
        if case_id == "c_partial":
            raise JudgeCallError("auth failed")
        if case_id == "c_total":
            raise JudgeCallError("auth failed")
        return _good_judge_response()

    outcomes = judge_eligible_cases(
        records, primary_judge=primary_judge, secondary_judge=secondary_judge
    )

    assert len(outcomes) == 5  # one output per input, nothing dropped
    by_case = {outcome.case_id: outcome for outcome in outcomes}
    assert by_case["c_judged"].final_status == JUDGING_STATUS_JUDGED
    assert by_case["c_ineligible"].final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert by_case["c_refusal"].final_status == JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
    assert by_case["c_partial"].final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert by_case["c_total"].final_status == JUDGING_STATUS_FAILED_TOTAL

    aggregation = summarize_judging_outcomes(outcomes)
    assert aggregation.case_count == 5
    assert aggregation.judged_count == 1
    assert aggregation.excluded_ineligible_count == 1
    assert aggregation.excluded_not_applicable_count == 1
    assert aggregation.judging_failed_partial_count == 1
    assert aggregation.judging_failed_total_count == 1
    assert set(aggregation.judged_case_ids) == {"c_judged"}
    assert set(aggregation.excluded_case_ids) == {"c_ineligible", "c_refusal"}
    assert set(aggregation.failed_case_ids) == {"c_partial", "c_total"}


def test_duplicate_case_id_raises_rather_than_silently_merging():
    records = [_base_record(case_id="dup"), _base_record(case_id="dup")]
    with pytest.raises(QaCitationJudgingError):
        judge_eligible_cases(
            records,
            primary_judge=_fixed_judge(_good_judge_response()),
            secondary_judge=_fixed_judge(_good_judge_response()),
        )
