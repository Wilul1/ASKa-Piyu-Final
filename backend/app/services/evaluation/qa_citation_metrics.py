"""Pure QA and citation metric calculations for ``qa_citation_v1`` (Stage 2).

These functions take already-recorded judge scores, claims, and execution
statuses. They do not call an LLM, the chatbot, or any external service.

Claim statuses
--------------
``supported``
    A citation-required claim is backed by at least one displayed citation.
``unsupported``
    A citation-required claim is not backed by displayed citation evidence.
``not_assessable``
    Support cannot be determined (for example the claim is too vague to
    check, or the displayed citation cannot be assessed). Counted in the
    denominator of claim-level rates, never as supported or unsupported.

Zero denominators return ``value=None``. Invalid citation IDs and
``not_assessable`` claims are never dropped. Failed executions remain in
``case_count`` and are not assigned QA or citation scores.

Faithfulness is a judge criterion scored against retrieved/cited evidence,
not similarity to the reference answer. This module only aggregates those
already-assigned scores; it does not compute faithfulness itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

CLAIM_STATUS_SUPPORTED = "supported"
CLAIM_STATUS_UNSUPPORTED = "unsupported"
CLAIM_STATUS_NOT_ASSESSABLE = "not_assessable"
CLAIM_STATUSES = frozenset(
    {
        CLAIM_STATUS_SUPPORTED,
        CLAIM_STATUS_UNSUPPORTED,
        CLAIM_STATUS_NOT_ASSESSABLE,
    }
)

CLAIM_STATUS_MEANINGS = {
    CLAIM_STATUS_SUPPORTED: (
        "Citation-required claim is backed by at least one displayed citation."
    ),
    CLAIM_STATUS_UNSUPPORTED: (
        "Citation-required claim is not backed by displayed citation evidence."
    ),
    CLAIM_STATUS_NOT_ASSESSABLE: (
        "Support cannot be determined. Included in claim-level denominators "
        "but never counted as supported or unsupported."
    ),
}

CITATION_VALIDITY_VALID = "valid"
CITATION_VALIDITY_UNRESOLVED = "unresolved"
CITATION_VALIDITY_WRONG_DOCUMENT = "wrong_document"
CITATION_VALIDITY_STATUSES = frozenset(
    {
        CITATION_VALIDITY_VALID,
        CITATION_VALIDITY_UNRESOLVED,
        CITATION_VALIDITY_WRONG_DOCUMENT,
    }
)

QA_CRITERIA = ("correctness", "completeness", "relevance", "faithfulness")
QA_SCORE_MIN = 0
QA_SCORE_MAX = 4
QA_DISAGREEMENT_THRESHOLD = 1
FAITHFULNESS_EVIDENCE_BASIS = (
    "retrieved_context_and_displayed_citations_not_reference_similarity"
)

EXECUTION_STATUS_OK = "ok"
EXECUTION_STATUS_OOS_OR_REFUSAL = "oos_or_refusal"
EXECUTION_STATUS_ERROR = "error"
EXECUTION_STATUS_INCOMPLETE = "incomplete"
SUCCESSFUL_EXECUTION_STATUSES = frozenset(
    {EXECUTION_STATUS_OK, EXECUTION_STATUS_OOS_OR_REFUSAL}
)
FAILED_EXECUTION_STATUSES = frozenset(
    {EXECUTION_STATUS_ERROR, EXECUTION_STATUS_INCOMPLETE}
)
EXECUTION_STATUSES = SUCCESSFUL_EXECUTION_STATUSES | FAILED_EXECUTION_STATUSES

EXECUTION_STATUS_DEFINITIONS = {
    EXECUTION_STATUS_OK: (
        "Answer capture completed. This does not establish answer correctness."
    ),
    EXECUTION_STATUS_OOS_OR_REFUSAL: (
        "Refusal or out-of-scope handling completed. Counts as execution "
        "completion, not as a correct answer."
    ),
    EXECUTION_STATUS_ERROR: "Capture failed.",
    EXECUTION_STATUS_INCOMPLETE: (
        "Capture did not complete or produced an incomplete result."
    ),
}

RETRY_POLICY = (
    "Stage 2 retains one final execution record per case_id per run. Duplicate "
    "case_ids are rejected rather than overwritten. Retry history is not "
    "supported here; a later stage must introduce a distinct attempt/execution "
    "identifier if attempts are retained. Completion rate uses unique cases "
    "in the run (one record each), never extra retry rows as extra dataset cases."
)

# Stage 3.2B Phase 2: judging-specific status contract.
#
# This is a distinct concept from EXECUTION_STATUSES above (Stage 2's
# capture-status contract) and must never be confused with or substituted
# for it. execution_status describes whether Stage 3.1's capture process
# completed; the statuses below describe what happened to an eligible (or
# excluded) case during Stage 3.2B judging. A case can have
# execution_status == "ok" and still never reach ordinary QA judging (see
# qa_citation_eligibility.py) -- that gap is exactly what produced run
# qac_capture_20261109T095436Z_892ed650's all-fallback, all-"ok" records.

JUDGING_STATUS_JUDGED = "judged"
JUDGING_STATUS_EXCLUDED_INELIGIBLE = "excluded_ineligible"
JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE = "excluded_not_applicable"
JUDGING_STATUS_FAILED_PARTIAL = "judging_failed_partial"
JUDGING_STATUS_FAILED_TOTAL = "judging_failed_total"
JUDGING_STATUSES = frozenset(
    {
        JUDGING_STATUS_JUDGED,
        JUDGING_STATUS_EXCLUDED_INELIGIBLE,
        JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE,
        JUDGING_STATUS_FAILED_PARTIAL,
        JUDGING_STATUS_FAILED_TOTAL,
    }
)

JUDGING_STATUS_DEFINITIONS = {
    JUDGING_STATUS_JUDGED: (
        "Both judge slots evaluated successfully; a dual-AI score was produced "
        "via aggregate_dual_ai_qa_scores()."
    ),
    JUDGING_STATUS_EXCLUDED_INELIGIBLE: (
        "The case never reached judging: Stage 3.2B Phase 1's eligibility "
        "filter excluded it (missing fields, no result, or fallback content "
        "recorded as if it were genuine output)."
    ),
    JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE: (
        "The case never reached judging: a completed refusal/out-of-scope "
        "capture (execution_status == oos_or_refusal), not routed to ordinary "
        "QA answer-quality judging."
    ),
    JUDGING_STATUS_FAILED_PARTIAL: (
        "Exactly one of the two judge slots evaluated successfully. No "
        "dual-AI score is produced -- a single judge's score is never "
        "presented as a dual-AI result. The surviving judge's response is "
        "preserved for diagnostics only."
    ),
    JUDGING_STATUS_FAILED_TOTAL: (
        "Both judge slots failed (any mix of judge_error, judge_timeout, or "
        "judge_malformed_response). No score is produced."
    ),
}

# Per-judge-slot outcome. Independent of JUDGING_STATUSES above: a judge
# slot's own status describes whether that one call succeeded, not what the
# combined case-level outcome is.
JUDGE_EXECUTION_STATUS_EVALUATED = "evaluated"
JUDGE_EXECUTION_STATUS_ERROR = "judge_error"
JUDGE_EXECUTION_STATUS_TIMEOUT = "judge_timeout"
JUDGE_EXECUTION_STATUS_MALFORMED = "judge_malformed_response"
JUDGE_EXECUTION_STATUSES = frozenset(
    {
        JUDGE_EXECUTION_STATUS_EVALUATED,
        JUDGE_EXECUTION_STATUS_ERROR,
        JUDGE_EXECUTION_STATUS_TIMEOUT,
        JUDGE_EXECUTION_STATUS_MALFORMED,
    }
)


class QaCitationMetricError(ValueError):
    """Malformed metric input (scores, claims, or execution records)."""


@dataclass(frozen=True)
class FractionMetric:
    """A rate that keeps its fraction visible.

    ``value`` is ``numerator / denominator``, or ``None`` when the
    denominator is zero. Never a fabricated 0.0.
    """

    numerator: int
    denominator: int
    value: float | None

    @staticmethod
    def from_counts(numerator: int, denominator: int) -> "FractionMetric":
        if denominator < 0 or numerator < 0:
            raise QaCitationMetricError(
                f"Fraction counts must be non-negative, got {numerator}/{denominator}."
            )
        if denominator == 0:
            return FractionMetric(numerator=numerator, denominator=0, value=None)
        return FractionMetric(
            numerator=numerator,
            denominator=denominator,
            value=numerator / denominator,
        )


@dataclass(frozen=True)
class JudgeCriterionScores:
    correctness: int
    completeness: int
    relevance: int
    faithfulness: int

    def as_dict(self) -> dict[str, int]:
        return {
            "correctness": self.correctness,
            "completeness": self.completeness,
            "relevance": self.relevance,
            "faithfulness": self.faithfulness,
        }


@dataclass(frozen=True)
class DualAiQaResult:
    """Two judges preserved independently; reported scores are arithmetic means."""

    primary: JudgeCriterionScores
    secondary: JudgeCriterionScores
    reported_correctness: float
    reported_completeness: float
    reported_relevance: float
    reported_faithfulness: float
    reported_overall: float
    absolute_differences: dict[str, int]
    disagreement_by_criterion: dict[str, bool]
    disagreement: bool
    faithfulness_evidence_basis: str = FAITHFULNESS_EVIDENCE_BASIS


@dataclass(frozen=True)
class ClaimMetricInput:
    claim_id: str
    requires_citation: bool
    claim_support: str | None
    supporting_displayed_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CitationMetrics:
    unique_displayed_citation_ids: tuple[str, ...]
    citation_precision: FractionMetric
    citation_completeness: FractionMetric
    claim_support_rate: FractionMetric
    unsupported_claim_rate: FractionMetric
    citation_validity: FractionMetric
    citation_required_claim_count: int
    supported_claim_count: int
    unsupported_claim_count: int
    not_assessable_claim_count: int


@dataclass(frozen=True)
class ExecutionRecord:
    case_id: str
    execution_status: str
    has_qa_scores: bool = False
    has_citation_scores: bool = False


@dataclass(frozen=True)
class ExecutionAggregation:
    case_count: int
    successful_executions: int
    failed_executions: int
    successful_case_ids: tuple[str, ...]
    failed_case_ids: tuple[str, ...]
    completion_rate: FractionMetric


@dataclass(frozen=True)
class JudgingExecutionRecord:
    """One case's final judging-stage status. Mirrors ExecutionRecord's role

    for capture statuses, but for JUDGING_STATUSES -- a separate contract.
    """

    case_id: str
    final_status: str


@dataclass(frozen=True)
class JudgingAggregation:
    case_count: int
    judged_count: int
    excluded_ineligible_count: int
    excluded_not_applicable_count: int
    judging_failed_partial_count: int
    judging_failed_total_count: int
    judged_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]
    failed_case_ids: tuple[str, ...]


def unique_preserve_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return tuple(ordered)


def aggregate_dual_ai_qa_scores(
    primary: Mapping[str, Any],
    secondary: Mapping[str, Any],
) -> DualAiQaResult:
    """Mean of two independent judges per criterion; overall is the mean of those four.

    Never selects the maximum score. Never discards a judge. Faithfulness in
    the input must already have been judged against retrieved/cited evidence.
    """
    primary_scores = _parse_judge_scores(primary, slot="primary")
    secondary_scores = _parse_judge_scores(secondary, slot="secondary")

    reported: dict[str, float] = {}
    differences: dict[str, int] = {}
    disagreement_by_criterion: dict[str, bool] = {}
    for criterion in QA_CRITERIA:
        left = getattr(primary_scores, criterion)
        right = getattr(secondary_scores, criterion)
        reported[criterion] = (left + right) / 2
        delta = abs(left - right)
        differences[criterion] = delta
        disagreement_by_criterion[criterion] = delta >= QA_DISAGREEMENT_THRESHOLD

    overall = sum(reported[criterion] for criterion in QA_CRITERIA) / len(QA_CRITERIA)
    return DualAiQaResult(
        primary=primary_scores,
        secondary=secondary_scores,
        reported_correctness=reported["correctness"],
        reported_completeness=reported["completeness"],
        reported_relevance=reported["relevance"],
        reported_faithfulness=reported["faithfulness"],
        reported_overall=overall,
        absolute_differences=differences,
        disagreement_by_criterion=disagreement_by_criterion,
        disagreement=any(disagreement_by_criterion.values()),
        faithfulness_evidence_basis=FAITHFULNESS_EVIDENCE_BASIS,
    )


def compute_citation_metrics(
    *,
    displayed_citation_ids: Sequence[str],
    claims: Sequence[ClaimMetricInput],
    citation_validity_by_id: Mapping[str, str],
) -> CitationMetrics:
    """Answer-level citation metrics. Invalid IDs stay in precision/validity denominators."""
    unique_displayed = unique_preserve_order(list(displayed_citation_ids))
    _validate_validity_map(unique_displayed, citation_validity_by_id)

    seen_claim_ids: set[str] = set()
    citation_required: list[ClaimMetricInput] = []
    for claim in claims:
        if not claim.claim_id or not isinstance(claim.claim_id, str):
            raise QaCitationMetricError("Each claim must have a non-empty claim_id.")
        if claim.claim_id in seen_claim_ids:
            raise QaCitationMetricError(
                f"Duplicate claim_id {claim.claim_id!r}. Claims are not silently merged."
            )
        seen_claim_ids.add(claim.claim_id)
        if not claim.requires_citation:
            continue
        if claim.claim_support not in CLAIM_STATUSES:
            raise QaCitationMetricError(
                f"Claim {claim.claim_id!r}: claim_support must be one of "
                f"{sorted(CLAIM_STATUSES)!r}, got {claim.claim_support!r}. "
                "Use not_assessable (not not_applicable) when support cannot be determined."
            )
        displayed_set = set(unique_displayed)
        for supporting_id in claim.supporting_displayed_ids:
            if supporting_id not in displayed_set:
                raise QaCitationMetricError(
                    f"Claim {claim.claim_id!r}: supporting displayed id {supporting_id!r} "
                    "is not in the answer's displayed_citation_ids."
                )
        if claim.claim_support == CLAIM_STATUS_SUPPORTED and not claim.supporting_displayed_ids:
            raise QaCitationMetricError(
                f"Claim {claim.claim_id!r}: supported claims must have at least one "
                "supporting displayed citation ID."
            )
        if claim.claim_support == CLAIM_STATUS_UNSUPPORTED and claim.supporting_displayed_ids:
            raise QaCitationMetricError(
                f"Claim {claim.claim_id!r}: unsupported claims must not list supporting "
                "displayed citation IDs."
            )
        if claim.claim_support == CLAIM_STATUS_NOT_ASSESSABLE and claim.supporting_displayed_ids:
            raise QaCitationMetricError(
                f"Claim {claim.claim_id!r}: not_assessable claims must not list supporting "
                "displayed citation IDs; that would collapse into supported."
            )
        citation_required.append(claim)

    supporting_displayed: set[str] = set()
    completeness_hits = 0
    supported_count = 0
    unsupported_count = 0
    not_assessable_count = 0
    for claim in citation_required:
        if claim.supporting_displayed_ids:
            completeness_hits += 1
            supporting_displayed.update(claim.supporting_displayed_ids)
        if claim.claim_support == CLAIM_STATUS_SUPPORTED:
            supported_count += 1
        elif claim.claim_support == CLAIM_STATUS_UNSUPPORTED:
            unsupported_count += 1
        else:
            not_assessable_count += 1

    precision_numerator = sum(1 for citation_id in unique_displayed if citation_id in supporting_displayed)
    validity_numerator = sum(
        1
        for citation_id in unique_displayed
        if citation_validity_by_id[citation_id] == CITATION_VALIDITY_VALID
    )
    required_count = len(citation_required)

    return CitationMetrics(
        unique_displayed_citation_ids=unique_displayed,
        citation_precision=FractionMetric.from_counts(precision_numerator, len(unique_displayed)),
        citation_completeness=FractionMetric.from_counts(completeness_hits, required_count),
        claim_support_rate=FractionMetric.from_counts(supported_count, required_count),
        unsupported_claim_rate=FractionMetric.from_counts(unsupported_count, required_count),
        citation_validity=FractionMetric.from_counts(validity_numerator, len(unique_displayed)),
        citation_required_claim_count=required_count,
        supported_claim_count=supported_count,
        unsupported_claim_count=unsupported_count,
        not_assessable_claim_count=not_assessable_count,
    )


def compute_completion_rate(records: Sequence[ExecutionRecord]) -> FractionMetric:
    aggregation = aggregate_execution_records(records)
    return aggregation.completion_rate


def aggregate_execution_records(records: Sequence[ExecutionRecord]) -> ExecutionAggregation:
    """Retain failed executions in case_count. Do not score them.

    Stage 2: one final execution record per case_id. Duplicates raise instead
    of overwriting a failed attempt. See ``RETRY_POLICY``.
    """
    successful_ids: list[str] = []
    failed_ids: list[str] = []
    seen_case_ids: set[str] = set()
    for index, record in enumerate(records):
        if not record.case_id:
            raise QaCitationMetricError(f"Execution record at index {index} is missing case_id.")
        if record.case_id in seen_case_ids:
            raise QaCitationMetricError(
                f"Duplicate execution case_id {record.case_id!r}. Stage 2 keeps one final "
                "execution record per case and does not overwrite failed attempts. Retry "
                "history requires a later-stage attempt identifier."
            )
        seen_case_ids.add(record.case_id)
        if record.execution_status not in EXECUTION_STATUSES:
            raise QaCitationMetricError(
                f"Case {record.case_id!r}: execution_status must be one of "
                f"{sorted(EXECUTION_STATUSES)!r}, got {record.execution_status!r}."
            )
        if record.execution_status in FAILED_EXECUTION_STATUSES:
            if record.has_qa_scores or record.has_citation_scores:
                raise QaCitationMetricError(
                    f"Case {record.case_id!r}: failed execution_status "
                    f"{record.execution_status!r} must not carry QA or citation scores."
                )
            failed_ids.append(record.case_id)
        else:
            successful_ids.append(record.case_id)

    case_count = len(records)
    return ExecutionAggregation(
        case_count=case_count,
        successful_executions=len(successful_ids),
        failed_executions=len(failed_ids),
        successful_case_ids=tuple(successful_ids),
        failed_case_ids=tuple(failed_ids),
        completion_rate=FractionMetric.from_counts(len(successful_ids), case_count),
    )


def aggregate_judging_records(
    records: Sequence[JudgingExecutionRecord],
) -> JudgingAggregation:
    """Aggregate Stage 3.2B judging outcomes. Separate contract from capture

    execution statuses (EXECUTION_STATUSES / aggregate_execution_records):
    a case can be execution_status == "ok" and still land in
    excluded_ineligible here. One record per case_id; duplicates raise
    rather than overwrite.
    """
    seen_case_ids: set[str] = set()
    judged_ids: list[str] = []
    excluded_ids: list[str] = []
    failed_ids: list[str] = []
    counts = {status: 0 for status in JUDGING_STATUSES}

    for index, record in enumerate(records):
        if not record.case_id:
            raise QaCitationMetricError(f"Judging record at index {index} is missing case_id.")
        if record.case_id in seen_case_ids:
            raise QaCitationMetricError(
                f"Duplicate judging case_id {record.case_id!r}. One final judging "
                "record per case is kept; duplicates are rejected, not merged."
            )
        seen_case_ids.add(record.case_id)
        if record.final_status not in JUDGING_STATUSES:
            raise QaCitationMetricError(
                f"Case {record.case_id!r}: final_status must be one of "
                f"{sorted(JUDGING_STATUSES)!r}, got {record.final_status!r}."
            )
        counts[record.final_status] += 1
        if record.final_status == JUDGING_STATUS_JUDGED:
            judged_ids.append(record.case_id)
        elif record.final_status in (
            JUDGING_STATUS_EXCLUDED_INELIGIBLE,
            JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE,
        ):
            excluded_ids.append(record.case_id)
        else:
            failed_ids.append(record.case_id)

    return JudgingAggregation(
        case_count=len(records),
        judged_count=counts[JUDGING_STATUS_JUDGED],
        excluded_ineligible_count=counts[JUDGING_STATUS_EXCLUDED_INELIGIBLE],
        excluded_not_applicable_count=counts[JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE],
        judging_failed_partial_count=counts[JUDGING_STATUS_FAILED_PARTIAL],
        judging_failed_total_count=counts[JUDGING_STATUS_FAILED_TOTAL],
        judged_case_ids=tuple(judged_ids),
        excluded_case_ids=tuple(excluded_ids),
        failed_case_ids=tuple(failed_ids),
    )


def _parse_judge_scores(raw: Mapping[str, Any], *, slot: str) -> JudgeCriterionScores:
    if not isinstance(raw, Mapping):
        raise QaCitationMetricError(f"{slot} judge scores must be an object, got {type(raw).__name__}.")
    status = raw.get("evaluation_status")
    if status is not None and status != "evaluated":
        raise QaCitationMetricError(
            f"{slot} judge evaluation_status must be 'evaluated' to contribute scores, "
            f"got {status!r}. Missing judges are rejected, not replaced."
        )
    parsed: dict[str, int] = {}
    for criterion in QA_CRITERIA:
        if criterion not in raw:
            raise QaCitationMetricError(
                f"{slot} judge is missing {criterion} score. Both judges must be preserved."
            )
        value = raw[criterion]
        if isinstance(value, bool) or not isinstance(value, int):
            raise QaCitationMetricError(
                f"{slot} judge {criterion} must be an integer in "
                f"[{QA_SCORE_MIN}, {QA_SCORE_MAX}], got {value!r}."
            )
        if value < QA_SCORE_MIN or value > QA_SCORE_MAX:
            raise QaCitationMetricError(
                f"{slot} judge {criterion}={value} is outside [{QA_SCORE_MIN}, {QA_SCORE_MAX}]."
            )
        parsed[criterion] = value
    return JudgeCriterionScores(**parsed)


def _validate_validity_map(
    unique_displayed: Sequence[str],
    citation_validity_by_id: Mapping[str, str],
) -> None:
    missing = [citation_id for citation_id in unique_displayed if citation_id not in citation_validity_by_id]
    if missing:
        raise QaCitationMetricError(
            f"citation_validity_by_id is missing displayed id(s) {missing}. "
            "Invalid IDs must be annotated (unresolved/wrong_document), never dropped."
        )
    for citation_id in unique_displayed:
        status = citation_validity_by_id[citation_id]
        if status not in CITATION_VALIDITY_STATUSES:
            raise QaCitationMetricError(
                f"Displayed citation {citation_id!r} has unsupported validity {status!r}; "
                f"expected one of {sorted(CITATION_VALIDITY_STATUSES)!r}."
            )
