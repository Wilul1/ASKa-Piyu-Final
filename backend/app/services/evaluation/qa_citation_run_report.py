"""Stage 3.2B Phase 5 Part B: full run aggregation and reporting.

Ties together Phase 2 (ordinary QA judging), Phase 4 (insufficient-evidence
judging), and Phase 5 Part A (citation-claim judging) for one whole capture
run -- not a single case -- into two auditable flat files:

* ``judgments.jsonl`` -- one row per case, every rubric that applied to it,
  both judges' raw responses preserved, exclusion reasons preserved.
* ``judging_summary.json`` -- the full aggregate report, with every
  reproducibility field the approved design required (dataset version +
  hash, capture run id + file hash, corpus identity digests, judge
  identities + prompt versions/hashes for all three rubrics, run timestamp,
  this module's own report-format version).

No real AI judge call happens here -- the six judge callables this module
takes are caller-supplied (fakes in this phase's tests, real adapters in a
future live run). No live judging run is executed by this phase.

Routing: which records go to which rubric
------------------------------------------
Mirrors the existing split precedent exactly: Phase 2's ``judge_eligible_
case`` and Phase 4's ``judge_insufficient_evidence_case`` do not themselves
inspect dataset ``case_type`` -- the caller decides. This module is that
caller. It partitions capture records by the matching dataset case's
``case_type``: ``labeled_student_support`` records go to both the QA
rubric (Phase 2) and the citation-claim rubric (Phase 5A); ``insufficient_
evidence`` records go only to the insufficient-evidence rubric (Phase 4).
Eligibility is identical either way -- ``qa_citation_eligibility.
classify_eligibility`` is a pure function of the capture record alone, so
an answerable record's eligibility verdict is the same whether it is being
routed to QA judging or citation-claim judging.

Run-level citation aggregation: counts summed before fractions, both
judges counted as independent data points
--------------------------------------------------------------------------
Phase 5A deliberately preserves BOTH judges' independently-extracted claims
and independently-computed ``CitationMetrics`` for every judged case,
rather than merging two free-text claim lists into one "authoritative"
set. Run-level aggregation here therefore treats each (case, evaluated
judge slot) pair as its own data point: for every judged citation-claim
case, BOTH the primary and the secondary judge's ``CitationMetrics``
numerators/denominators are added into the run-level sums, and only then
are the five run-level fractions computed via
``FractionMetric.from_counts``. This is almost certainly correct for
these metrics (each is explicitly defined as a count ratio, not an
average of ratios) and is the same reasoning that makes summing-then-
dividing correct for any rate metric with varying per-item denominators:
averaging each case's fraction *value* would weight a case with one
citation the same as a case with ten, which is wrong.

Run-level QA aggregation: per-case dual-AI means, then averaged across
judged cases
--------------------------------------------------------------------------
Each judged case already has a per-case dual-AI mean from
``aggregate_dual_ai_qa_scores`` (the already-reported ``reported_*``
values). The run-level dimension mean is the arithmetic mean of those
per-case values across every ``judged`` case -- a mean of means, which is
appropriate here because every case contributes exactly one already-
combined (not count-weighted) score per dimension, unlike the citation
metrics above, which have genuinely different per-case denominators.
Distributions, by contrast, are built from each judge's individual raw
0-4 integer score (both judges, every judged case) rather than from the
rounded reported means, since means can land on a half-integer that does
not fit a discrete 0-4 bucket.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from app.services.evaluation.qa_citation_capture import DEFAULT_RUNS_DIR
from app.services.evaluation.qa_citation_claim_judging import (
    CitationClaimOutcome,
    judge_citation_claims_cases,
)
from app.services.evaluation.qa_citation_dataset import (
    CASE_TYPE_INSUFFICIENT_EVIDENCE,
    CASE_TYPE_LABELED_STUDENT_SUPPORT,
    QaCitationDataset,
)
from app.services.evaluation.qa_citation_eligibility import (
    EligibilitySummary,
    load_captures_jsonl,
    summarize_eligibility,
)
from app.services.evaluation.qa_citation_insufficient_evidence import (
    InsufficientEvidenceAggregation,
    InsufficientEvidenceOutcome,
    judge_insufficient_evidence_cases,
    summarize_insufficient_evidence_outcomes,
)
from app.services.evaluation.qa_citation_judging import JudgingOutcome, judge_eligible_cases
from app.services.evaluation.qa_citation_metrics import (
    JUDGING_STATUS_FAILED_PARTIAL,
    JUDGING_STATUS_FAILED_TOTAL,
    JUDGING_STATUS_JUDGED,
    QA_CRITERIA,
    FractionMetric,
)

JUDGING_REPORT_VERSION = "stage_3_2b_phase5_v1"
CATEGORY_MIN_SAMPLE_SIZE = 5

JudgeCallFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]

_CITATION_METRIC_NAMES = (
    "citation_precision",
    "citation_completeness",
    "claim_support_rate",
    "unsupported_claim_rate",
    "citation_validity",
)


class QaCitationRunReportError(ValueError):
    """Malformed run-report input or a run-level invariant was violated."""


@dataclass(frozen=True)
class RubricJudgeIdentities:
    """Plain metadata about which two judges were used for one rubric.

    Decoupled from the actual callables -- the caller already built the
    judge pair (and already had ``build_judge_pair``/equivalent enforce
    distinct underlying models at construction time, in Phase 3/4/5A); this
    is only the metadata to preserve in ``judging_summary.json``, mirroring
    how ``qa_citation_capture.model_config_snapshot`` is also plain
    metadata decoupled from execution.
    """

    primary_model: str
    primary_provider: str
    secondary_model: str
    secondary_provider: str
    prompt_version: str
    prompt_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "primary_model": self.primary_model,
            "primary_provider": self.primary_provider,
            "secondary_model": self.secondary_model,
            "secondary_provider": self.secondary_provider,
            "prompt_version": self.prompt_version,
            "prompt_sha256": self.prompt_sha256,
        }


@dataclass(frozen=True)
class JudgingRunResult:
    run_id: str
    output_dir: Path
    capture_run_id: str
    capture_file_sha256: str
    dataset_version: str
    dataset_json_sha256: str
    summary: dict[str, Any]
    judgment_rows: tuple[dict[str, Any], ...]
    qa_outcomes: tuple[JudgingOutcome, ...]
    citation_outcomes: tuple[CitationClaimOutcome, ...]
    insufficient_evidence_outcomes: tuple[InsufficientEvidenceOutcome, ...]


def new_judging_run_id(*, judged_at: datetime | None = None) -> str:
    stamp = (judged_at or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"qacj_judging_{stamp}_{uuid.uuid4().hex[:8]}"


def _safe_asdict(value: Any) -> Any:
    return None if value is None else asdict(value)


def _case_lookup(dataset: QaCitationDataset) -> dict[str, Any]:
    return {case.case_id: case for case in dataset.cases}


def _partition_records_by_case_type(
    capture_records: Sequence[Mapping[str, Any]], dataset: QaCitationDataset
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split capture records into (answerable, insufficient_evidence) by the
    matching dataset case's case_type. Raises if a capture record has no
    matching dataset case, or if the input has duplicate case_ids."""
    cases_by_id = _case_lookup(dataset)
    seen: set[str] = set()
    answerable: list[Mapping[str, Any]] = []
    insufficient_evidence: list[Mapping[str, Any]] = []
    for record in capture_records:
        case_id = str(record.get("case_id") or "")
        if not case_id:
            raise QaCitationRunReportError("Capture record is missing case_id.")
        if case_id in seen:
            raise QaCitationRunReportError(
                f"Duplicate case_id {case_id!r} in judging-run input. "
                "One capture record per case is expected."
            )
        seen.add(case_id)
        case = cases_by_id.get(case_id)
        if case is None:
            raise QaCitationRunReportError(
                f"Capture record case_id {case_id!r} has no matching case in the "
                "supplied dataset. Cannot route it to a rubric."
            )
        if case.case_type == CASE_TYPE_LABELED_STUDENT_SUPPORT:
            answerable.append(record)
        elif case.case_type == CASE_TYPE_INSUFFICIENT_EVIDENCE:
            insufficient_evidence.append(record)
        else:  # pragma: no cover - defensive; CASE_TYPES is a closed set
            raise QaCitationRunReportError(
                f"Case {case_id!r} has unsupported case_type {case.case_type!r}."
            )
    return answerable, insufficient_evidence


# ---------------------------------------------------------------------------
# QA (answerable-case) aggregation
# ---------------------------------------------------------------------------


def _qa_judged(outcomes: Sequence[JudgingOutcome]) -> list[JudgingOutcome]:
    return [o for o in outcomes if o.final_status == JUDGING_STATUS_JUDGED]


def _qa_dimension_means(judged: Sequence[JudgingOutcome]) -> dict[str, float | None]:
    dims = QA_CRITERIA + ("overall",)
    if not judged:
        return {dim: None for dim in dims}
    means: dict[str, float] = {}
    for dim in dims:
        attr = f"reported_{dim}"
        means[dim] = sum(getattr(o.qa_result, attr) for o in judged) / len(judged)
    return means


def _qa_dimension_distributions(judged: Sequence[JudgingOutcome]) -> dict[str, dict[str, int]]:
    """Counts of each judge's raw 0-4 integer score (both judges, every
    judged case) -- not the rounded reported mean, which can be a
    half-integer and does not fit a discrete 0-4 bucket."""
    dist: dict[str, dict[str, int]] = {dim: {str(i): 0 for i in range(5)} for dim in QA_CRITERIA}
    for outcome in judged:
        result = outcome.qa_result
        assert result is not None
        for dim in QA_CRITERIA:
            dist[dim][str(getattr(result.primary, dim))] += 1
            dist[dim][str(getattr(result.secondary, dim))] += 1
    return dist


def _qa_disagreement(judged: Sequence[JudgingOutcome]) -> tuple[FractionMetric, dict[str, int]]:
    disagreement_count = sum(1 for o in judged if o.qa_result.disagreement)
    rate = FractionMetric.from_counts(disagreement_count, len(judged))
    by_criterion = {
        dim: sum(1 for o in judged if o.qa_result.disagreement_by_criterion[dim])
        for dim in QA_CRITERIA
    }
    return rate, by_criterion


def _qa_by_category(
    judged: Sequence[JudgingOutcome], *, category_by_case_id: Mapping[str, str]
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[JudgingOutcome]] = {}
    for outcome in judged:
        category = category_by_case_id.get(outcome.case_id, "unknown")
        grouped.setdefault(category, []).append(outcome)
    return {
        category: {
            "judged_count": len(group),
            "dimension_means": _qa_dimension_means(group),
        }
        for category, group in grouped.items()
        if len(group) >= CATEGORY_MIN_SAMPLE_SIZE
    }


def _build_qa_aggregation(
    outcomes: Sequence[JudgingOutcome],
    *,
    eligibility: EligibilitySummary,
    category_by_case_id: Mapping[str, str],
) -> dict[str, Any]:
    judged = _qa_judged(outcomes)
    partial = sum(1 for o in outcomes if o.final_status == JUDGING_STATUS_FAILED_PARTIAL)
    total_fail = sum(1 for o in outcomes if o.final_status == JUDGING_STATUS_FAILED_TOTAL)
    disagreement_rate, disagreement_by_criterion = _qa_disagreement(judged)
    return {
        "eligible_count": eligibility.eligible_count,
        "excluded_count": eligibility.excluded_count,
        "excluded_counts_by_reason": dict(eligibility.exclusion_counts_by_reason),
        "judged_count": len(judged),
        "judging_failed_partial_count": partial,
        "judging_failed_total_count": total_fail,
        "dimension_means": _qa_dimension_means(judged),
        "dimension_distributions": _qa_dimension_distributions(judged),
        "judge_disagreement_rate": {
            "numerator": disagreement_rate.numerator,
            "denominator": disagreement_rate.denominator,
            "value": disagreement_rate.value,
        },
        "disagreement_by_criterion_counts": disagreement_by_criterion,
        "category_min_sample_size": CATEGORY_MIN_SAMPLE_SIZE,
        "by_category": _qa_by_category(judged, category_by_case_id=category_by_case_id),
    }


# ---------------------------------------------------------------------------
# Citation-claim aggregation
# ---------------------------------------------------------------------------


def _citation_judged(outcomes: Sequence[CitationClaimOutcome]) -> list[CitationClaimOutcome]:
    return [o for o in outcomes if o.final_status == JUDGING_STATUS_JUDGED]


def _build_citation_aggregation(
    outcomes: Sequence[CitationClaimOutcome],
    *,
    eligibility: EligibilitySummary,
) -> dict[str, Any]:
    judged = _citation_judged(outcomes)
    partial = sum(1 for o in outcomes if o.final_status == JUDGING_STATUS_FAILED_PARTIAL)
    total_fail = sum(1 for o in outcomes if o.final_status == JUDGING_STATUS_FAILED_TOTAL)

    sums: dict[str, list[int]] = {name: [0, 0] for name in _CITATION_METRIC_NAMES}
    data_points = 0
    for outcome in judged:
        for slot_outcome in (outcome.primary_judge, outcome.secondary_judge):
            assert slot_outcome is not None and slot_outcome.citation_metrics is not None
            metrics = slot_outcome.citation_metrics
            data_points += 1
            for name in _CITATION_METRIC_NAMES:
                fraction: FractionMetric = getattr(metrics, name)
                sums[name][0] += fraction.numerator
                sums[name][1] += fraction.denominator

    aggregated = {
        name: FractionMetric.from_counts(numerator, denominator)
        for name, (numerator, denominator) in sums.items()
    }
    return {
        "eligible_count": eligibility.eligible_count,
        "excluded_count": eligibility.excluded_count,
        "excluded_counts_by_reason": dict(eligibility.exclusion_counts_by_reason),
        "judged_case_count": len(judged),
        "judge_data_points_aggregated": data_points,
        "judging_failed_partial_count": partial,
        "judging_failed_total_count": total_fail,
        **{
            name: {
                "numerator": fraction.numerator,
                "denominator": fraction.denominator,
                "value": fraction.value,
            }
            for name, fraction in aggregated.items()
        },
    }


# ---------------------------------------------------------------------------
# judgments.jsonl row construction
# ---------------------------------------------------------------------------


def _build_judgment_row(
    *,
    case_id: str,
    case_type: str,
    qa_outcome: JudgingOutcome | None,
    citation_outcome: CitationClaimOutcome | None,
    ie_outcome: InsufficientEvidenceOutcome | None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"case_id": case_id, "case_type": case_type}
    if qa_outcome is not None:
        row["qa"] = {
            "final_status": qa_outcome.final_status,
            "eligibility": qa_outcome.eligibility_verdict.as_dict(),
            "primary_judge": _safe_asdict(qa_outcome.primary_judge),
            "secondary_judge": _safe_asdict(qa_outcome.secondary_judge),
            "result": _safe_asdict(qa_outcome.qa_result),
        }
    if citation_outcome is not None:
        row["citation"] = {
            "final_status": citation_outcome.final_status,
            "eligibility": citation_outcome.eligibility_verdict.as_dict(),
            "citation_validity_by_id": dict(citation_outcome.citation_validity_by_id),
            "primary_judge": _safe_asdict(citation_outcome.primary_judge),
            "secondary_judge": _safe_asdict(citation_outcome.secondary_judge),
        }
    if ie_outcome is not None:
        row["insufficient_evidence"] = {
            "final_status": ie_outcome.final_status,
            "eligibility": ie_outcome.eligibility_verdict.as_dict(),
            "primary_judge": _safe_asdict(ie_outcome.primary_judge),
            "secondary_judge": _safe_asdict(ie_outcome.secondary_judge),
            "result": _safe_asdict(ie_outcome.result),
        }
    return row


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def run_qa_citation_judging(
    *,
    dataset: QaCitationDataset,
    capture_records: Sequence[Mapping[str, Any]],
    qa_primary_judge: JudgeCallFn,
    qa_secondary_judge: JudgeCallFn,
    insufficient_evidence_primary_judge: JudgeCallFn,
    insufficient_evidence_secondary_judge: JudgeCallFn,
    citation_primary_judge: JudgeCallFn,
    citation_secondary_judge: JudgeCallFn,
    qa_judge_identities: RubricJudgeIdentities,
    insufficient_evidence_judge_identities: RubricJudgeIdentities,
    citation_judge_identities: RubricJudgeIdentities,
    capture_run_id: str,
    capture_file_sha256: str,
    output_dir: str | Path | None = None,
    run_id: str | None = None,
    judged_at: datetime | None = None,
) -> JudgingRunResult:
    """Judge every case in ``capture_records`` under whichever rubric(s)
    apply, aggregate, and write a new, never-overwritten judging run
    directory. No real judge call happens inside this function -- every
    ``*_judge`` parameter is caller-supplied (a fake in tests, a real
    adapter's ``__call__`` in a future phase).

    Raises QaCitationRunReportError if ``capture_records`` has a duplicate
    or unmatched case_id (never silently dropped or guessed).
    """
    if not capture_records:
        raise QaCitationRunReportError(
            "No capture records supplied; refusing to write an empty judging run."
        )

    answerable_records, insufficient_evidence_records = _partition_records_by_case_type(
        capture_records, dataset
    )

    qa_outcomes = tuple(
        judge_eligible_cases(
            answerable_records,
            primary_judge=qa_primary_judge,
            secondary_judge=qa_secondary_judge,
        )
    )
    citation_outcomes = tuple(
        judge_citation_claims_cases(
            answerable_records,
            primary_judge=citation_primary_judge,
            secondary_judge=citation_secondary_judge,
        )
    )
    insufficient_evidence_outcomes = tuple(
        judge_insufficient_evidence_cases(
            insufficient_evidence_records,
            primary_judge=insufficient_evidence_primary_judge,
            secondary_judge=insufficient_evidence_secondary_judge,
        )
    )

    total_routed = (
        len(qa_outcomes) + len(insufficient_evidence_outcomes)
    )
    if total_routed != len(capture_records) or len(citation_outcomes) != len(answerable_records):
        raise QaCitationRunReportError(  # pragma: no cover - defensive
            "Judging dropped or duplicated cases: "
            f"capture_records={len(capture_records)}, qa_outcomes={len(qa_outcomes)}, "
            f"citation_outcomes={len(citation_outcomes)}, "
            f"insufficient_evidence_outcomes={len(insufficient_evidence_outcomes)}."
        )

    cases_by_id = _case_lookup(dataset)
    category_by_case_id = {case_id: case.category for case_id, case in cases_by_id.items()}

    qa_eligibility = summarize_eligibility(answerable_records)
    ie_eligibility = summarize_eligibility(insufficient_evidence_records)

    qa_aggregation = _build_qa_aggregation(
        qa_outcomes, eligibility=qa_eligibility, category_by_case_id=category_by_case_id
    )
    citation_aggregation = _build_citation_aggregation(citation_outcomes, eligibility=qa_eligibility)
    ie_aggregation: InsufficientEvidenceAggregation = summarize_insufficient_evidence_outcomes(
        insufficient_evidence_outcomes
    )

    fallback_counts = {"genuine": 0, "fallback": 0, "no_result": 0, "fields_missing": 0}
    for record in capture_records:
        if "is_genuine_model_output" not in record or "fallback_used" not in record:
            fallback_counts["fields_missing"] += 1
        elif record["is_genuine_model_output"] is None:
            fallback_counts["no_result"] += 1
        elif record["is_genuine_model_output"] is True:
            fallback_counts["genuine"] += 1
        else:
            fallback_counts["fallback"] += 1

    population_summary = {
        "answerable_total": len(answerable_records),
        "answerable_qa_judged": qa_aggregation["judged_count"],
        "answerable_qa_judging_failed_partial": qa_aggregation["judging_failed_partial_count"],
        "answerable_qa_judging_failed_total": qa_aggregation["judging_failed_total_count"],
        "answerable_citation_judged": citation_aggregation["judged_case_count"],
        "answerable_citation_judging_failed_partial": (
            citation_aggregation["judging_failed_partial_count"]
        ),
        "answerable_citation_judging_failed_total": (
            citation_aggregation["judging_failed_total_count"]
        ),
        "answerable_excluded": qa_eligibility.excluded_count,
        "insufficient_evidence_total": len(insufficient_evidence_records),
        "insufficient_evidence_judged": ie_aggregation.judged_count,
        "insufficient_evidence_judging_failed_partial": (
            ie_aggregation.judging_failed_partial_count
        ),
        "insufficient_evidence_judging_failed_total": ie_aggregation.judging_failed_total_count,
        "insufficient_evidence_excluded": ie_aggregation.excluded_count,
        "ineligible_excluded_by_reason": {
            **qa_eligibility.exclusion_counts_by_reason,
            **ie_eligibility.exclusion_counts_by_reason,
        },
        "fallback_vs_genuine_counts": fallback_counts,
    }

    qa_outcomes_by_id = {o.case_id: o for o in qa_outcomes}
    citation_outcomes_by_id = {o.case_id: o for o in citation_outcomes}
    ie_outcomes_by_id = {o.case_id: o for o in insufficient_evidence_outcomes}
    judgment_rows = tuple(
        _build_judgment_row(
            case_id=record_case_id,
            case_type=cases_by_id[record_case_id].case_type,
            qa_outcome=qa_outcomes_by_id.get(record_case_id),
            citation_outcome=citation_outcomes_by_id.get(record_case_id),
            ie_outcome=ie_outcomes_by_id.get(record_case_id),
        )
        for record_case_id in (str(r.get("case_id") or "") for r in capture_records)
    )

    corpus_dicts = [dict(r.get("corpus") or {}) for r in capture_records]
    corpus = corpus_dicts[0] if corpus_dicts else {}
    if any(c != corpus for c in corpus_dicts):
        raise QaCitationRunReportError(
            "Capture records in this run disagree on corpus identity; "
            "a judging run must be built from one capture run's records."
        )

    judged_dt = judged_at or datetime.now(timezone.utc)
    resolved_run_id = run_id or new_judging_run_id(judged_at=judged_dt)
    runs_root = Path(output_dir) if output_dir is not None else DEFAULT_RUNS_DIR
    run_dir = runs_root / resolved_run_id
    if run_dir.exists():
        raise QaCitationRunReportError(
            f"Judging run directory already exists: {run_dir}. "
            "Previous results are not overwritten. Use a new run_id."
        )

    summary: dict[str, Any] = {
        "judging_run_id": resolved_run_id,
        "report_version": JUDGING_REPORT_VERSION,
        "judged_at": judged_dt.isoformat(),
        "capture_run_id": capture_run_id,
        "capture_file_sha256": capture_file_sha256,
        "dataset_version": dataset.dataset_version,
        "dataset_json_sha256": dataset.dataset_json_sha256,
        "corpus": corpus,
        "judges": {
            "qa_rubric": qa_judge_identities.as_dict(),
            "insufficient_evidence_rubric": insufficient_evidence_judge_identities.as_dict(),
            "citation_claim_rubric": citation_judge_identities.as_dict(),
        },
        "population_summary": population_summary,
        "qa_aggregation": qa_aggregation,
        "citation_aggregation": citation_aggregation,
        "insufficient_evidence_aggregation": ie_aggregation.as_dict(),
    }

    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "judgments.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, default=str) + "\n" for row in judgment_rows),
        encoding="utf-8",
    )
    (run_dir / "judging_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    return JudgingRunResult(
        run_id=resolved_run_id,
        output_dir=run_dir,
        capture_run_id=capture_run_id,
        capture_file_sha256=capture_file_sha256,
        dataset_version=dataset.dataset_version,
        dataset_json_sha256=dataset.dataset_json_sha256,
        summary=summary,
        judgment_rows=judgment_rows,
        qa_outcomes=qa_outcomes,
        citation_outcomes=citation_outcomes,
        insufficient_evidence_outcomes=insufficient_evidence_outcomes,
    )


def run_qa_citation_judging_from_capture_run_dir(
    capture_run_dir: str | Path,
    *,
    dataset: QaCitationDataset,
    qa_primary_judge: JudgeCallFn,
    qa_secondary_judge: JudgeCallFn,
    insufficient_evidence_primary_judge: JudgeCallFn,
    insufficient_evidence_secondary_judge: JudgeCallFn,
    citation_primary_judge: JudgeCallFn,
    citation_secondary_judge: JudgeCallFn,
    qa_judge_identities: RubricJudgeIdentities,
    insufficient_evidence_judge_identities: RubricJudgeIdentities,
    citation_judge_identities: RubricJudgeIdentities,
    output_dir: str | Path | None = None,
    run_id: str | None = None,
    judged_at: datetime | None = None,
) -> JudgingRunResult:
    """Convenience wrapper: read an existing Stage 3.1 capture run's
    ``captures.jsonl`` and ``summary.json`` (read-only; never modifies
    them), derive ``capture_run_id``/``capture_file_sha256``, then call
    ``run_qa_citation_judging``."""
    capture_dir = Path(capture_run_dir)
    captures_path = capture_dir / "captures.jsonl"
    summary_path = capture_dir / "summary.json"
    if not captures_path.is_file() or not summary_path.is_file():
        raise QaCitationRunReportError(
            f"Capture run directory {capture_dir} is missing captures.jsonl or summary.json."
        )
    capture_records = load_captures_jsonl(captures_path)
    capture_file_sha256 = hashlib.sha256(captures_path.read_bytes()).hexdigest()
    capture_summary = json.loads(summary_path.read_text(encoding="utf-8"))
    capture_run_id = str(capture_summary.get("run_id") or "")
    if not capture_run_id:
        raise QaCitationRunReportError(f"{summary_path} is missing run_id.")

    return run_qa_citation_judging(
        dataset=dataset,
        capture_records=capture_records,
        qa_primary_judge=qa_primary_judge,
        qa_secondary_judge=qa_secondary_judge,
        insufficient_evidence_primary_judge=insufficient_evidence_primary_judge,
        insufficient_evidence_secondary_judge=insufficient_evidence_secondary_judge,
        citation_primary_judge=citation_primary_judge,
        citation_secondary_judge=citation_secondary_judge,
        qa_judge_identities=qa_judge_identities,
        insufficient_evidence_judge_identities=insufficient_evidence_judge_identities,
        citation_judge_identities=citation_judge_identities,
        capture_run_id=capture_run_id,
        capture_file_sha256=capture_file_sha256,
        output_dir=output_dir,
        run_id=run_id,
        judged_at=judged_at,
    )
