"""Stage 3.2B Phase 2: judging orchestration skeleton (no real judge calls).

This module routes an eligible capture record to two judge "slots" through
an injectable callable interface and combines their outcomes. It does not
construct a real judge prompt and does not call any LLM or HTTP service --
that is Phase 3. Everything here is exercised through test doubles.

Orchestration contract for a judge callable
--------------------------------------------
A judge callable has the shape ``JudgeCallFn = Callable[[Mapping], Mapping]``.
Given the eligible capture record, it must either:

* return a mapping shaped like the approved judge-response schema
  (``{"evaluation_status": "evaluated", "correctness": int, "completeness":
  int, "relevance": int, "faithfulness": int, ...}``) -- validated the same
  way ``aggregate_dual_ai_qa_scores`` validates each side, so a
  structurally-wrong return value (missing/out-of-range/non-int scores, or
  ``evaluation_status`` other than ``"evaluated"``) is classified as
  ``judge_malformed_response``, not silently accepted or crashed on; or
* raise :class:`JudgeTimeoutError` to signal a timeout
  (``judge_timeout``); or
* raise :class:`JudgeCallError` (or let any other exception propagate out
  of the callable) to signal a call failure, e.g. an auth/network error
  like the one behind run qac_capture_20261109T095436Z_892ed650
  (``judge_error``).

Phase 3 implements a real judge callable against this exact contract; this
phase only defines and tests the contract and the combination logic.

Combination rule
-----------------
* Both slots ``evaluated`` -> call the existing
  ``aggregate_dual_ai_qa_scores`` directly (never reimplemented here) ->
  ``judged``.
* Exactly one slot ``evaluated`` -> ``judging_failed_partial``.
  ``aggregate_dual_ai_qa_scores`` is never called with only one real score;
  a single judge's score is never presented as a dual-AI result. The
  surviving judge's parsed scores/raw response are kept on the record for
  diagnostics only.
* Neither slot ``evaluated`` -> ``judging_failed_total``.

Ineligible and not-applicable cases never reach a judge callable at all;
Phase 1's eligibility verdict is checked first and its reason is preserved
unchanged on the output record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_REFUSAL_NOT_QA_SCORED,
    EligibilityVerdict,
    classify_eligibility,
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
    DualAiQaResult,
    JudgeCriterionScores,
    JudgingAggregation,
    JudgingExecutionRecord,
    QaCitationMetricError,
    aggregate_dual_ai_qa_scores,
    aggregate_judging_records,
    _parse_judge_scores,  # reused rather than duplicating per-judge validation
)


class QaCitationJudgingError(ValueError):
    """Malformed judging-orchestration input (not a judge-call failure)."""


class JudgeCallError(Exception):
    """A judge call failed (auth/network/other error). Maps to judge_error."""


class JudgeTimeoutError(Exception):
    """A judge call exceeded its time budget. Maps to judge_timeout."""


JudgeCallFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class JudgeSlotOutcome:
    """One judge slot's result for one case."""

    judge_execution_status: str
    raw_response: Mapping[str, Any] | None
    parsed_scores: JudgeCriterionScores | None = None
    error_detail: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED


@dataclass(frozen=True)
class JudgingOutcome:
    """The full, per-case Stage 3.2B judging result.

    Exactly one of these is produced per input capture record -- whether it
    was excluded before judging, partially/totally failed, or judged.
    """

    case_id: str
    final_status: str
    eligibility_verdict: EligibilityVerdict
    primary_judge: JudgeSlotOutcome | None
    secondary_judge: JudgeSlotOutcome | None
    qa_result: DualAiQaResult | None


def _call_judge_slot(
    record: Mapping[str, Any],
    judge_fn: JudgeCallFn,
    *,
    slot: str,
) -> JudgeSlotOutcome:
    try:
        response = judge_fn(record)
    except JudgeTimeoutError as exc:
        return JudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_TIMEOUT,
            raw_response=None,
            error_detail=str(exc) or "judge call timed out",
        )
    except JudgeCallError as exc:
        return JudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or "judge call failed",
        )
    except Exception as exc:  # pragma: no cover - defensive: any other
        # unexpected exception from a judge callable is a call failure too,
        # not an orchestration crash. Phase 3's real callable should raise
        # the specific types above; this is a safety net for Phase 2 tests
        # that do not.
        return JudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or f"unexpected {type(exc).__name__}",
        )

    try:
        parsed = _parse_judge_scores(response, slot=slot)
    except QaCitationMetricError as exc:
        return JudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_MALFORMED,
            raw_response=response,
            error_detail=str(exc),
        )

    return JudgeSlotOutcome(
        judge_execution_status=JUDGE_EXECUTION_STATUS_EVALUATED,
        raw_response=response,
        parsed_scores=parsed,
    )


def judge_eligible_case(
    record: Mapping[str, Any],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> JudgingOutcome:
    """Run eligibility first; only call judges for an eligible record.

    No real judge call happens in this module -- ``primary_judge`` and
    ``secondary_judge`` are caller-supplied callables (mocks in tests,
    a real implementation in a future phase).
    """
    verdict = classify_eligibility(record)

    if not verdict.eligible:
        final_status = (
            JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
            if verdict.exclusion_reason == EXCLUSION_REFUSAL_NOT_QA_SCORED
            else JUDGING_STATUS_EXCLUDED_INELIGIBLE
        )
        return JudgingOutcome(
            case_id=verdict.case_id,
            final_status=final_status,
            eligibility_verdict=verdict,
            primary_judge=None,
            secondary_judge=None,
            qa_result=None,
        )

    primary_outcome = _call_judge_slot(record, primary_judge, slot="primary")
    secondary_outcome = _call_judge_slot(record, secondary_judge, slot="secondary")

    if primary_outcome.evaluated and secondary_outcome.evaluated:
        qa_result = aggregate_dual_ai_qa_scores(
            primary_outcome.raw_response, secondary_outcome.raw_response
        )
        final_status = JUDGING_STATUS_JUDGED
    elif primary_outcome.evaluated or secondary_outcome.evaluated:
        # Exactly one slot succeeded. aggregate_dual_ai_qa_scores is
        # deliberately never called here -- a single judge's score must
        # never be reported as a dual-AI result.
        qa_result = None
        final_status = JUDGING_STATUS_FAILED_PARTIAL
    else:
        qa_result = None
        final_status = JUDGING_STATUS_FAILED_TOTAL

    return JudgingOutcome(
        case_id=verdict.case_id,
        final_status=final_status,
        eligibility_verdict=verdict,
        primary_judge=primary_outcome,
        secondary_judge=secondary_outcome,
        qa_result=qa_result,
    )


def judge_eligible_cases(
    records: Sequence[Mapping[str, Any]],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> list[JudgingOutcome]:
    """Run ``judge_eligible_case`` over every record. One output per input;

    no case is dropped. Duplicate case_ids raise rather than overwrite.
    """
    outcomes: list[JudgingOutcome] = []
    seen_case_ids: set[str] = set()
    for record in records:
        outcome = judge_eligible_case(
            record, primary_judge=primary_judge, secondary_judge=secondary_judge
        )
        if outcome.case_id in seen_case_ids:
            raise QaCitationJudgingError(
                f"Duplicate case_id {outcome.case_id!r} in judging input."
            )
        seen_case_ids.add(outcome.case_id)
        outcomes.append(outcome)
    return outcomes


def summarize_judging_outcomes(
    outcomes: Sequence[JudgingOutcome],
) -> JudgingAggregation:
    """Aggregate a batch of JudgingOutcome into JudgingAggregation counts."""
    records = [
        JudgingExecutionRecord(case_id=outcome.case_id, final_status=outcome.final_status)
        for outcome in outcomes
    ]
    return aggregate_judging_records(records)
