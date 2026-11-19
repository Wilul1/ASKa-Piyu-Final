"""Stage 3.2B Phase 1: fail-closed answer eligibility for QA judging.

A capture record from Stage 3.1 (``qa_citation_capture.py``) reaching
``execution_status == "ok"`` does not, by itself, mean the record is
eligible for ordinary QA answer-quality judging. A fallback answer (for
example a generation-service auth failure that fell back to extractive
text) is also recorded as ``ok`` -- capture completed, not that a genuine
model answer was produced. This module adds the eligibility check that
must run before any future judging stage scores a record.

This module does not call a judge, does not score anything, and does not
modify capture records or run files. It only classifies.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.evaluation.qa_citation_metrics import EXECUTION_STATUS_OOS_OR_REFUSAL

ELIGIBILITY_OK = "eligible"
EXCLUSION_FIELD_MISSING = "eligibility_field_missing"
EXCLUSION_NO_RESULT = "no_result_to_judge"
EXCLUSION_FALLBACK_NOT_GENUINE = "fallback_not_genuine"
EXCLUSION_REFUSAL_NOT_QA_SCORED = "refusal_not_qa_scored"
EXCLUSION_EMPTY_ANSWER = "empty_answer"

EXCLUSION_REASONS = frozenset(
    {
        EXCLUSION_FIELD_MISSING,
        EXCLUSION_NO_RESULT,
        EXCLUSION_FALLBACK_NOT_GENUINE,
        EXCLUSION_REFUSAL_NOT_QA_SCORED,
        EXCLUSION_EMPTY_ANSWER,
    }
)

EXCLUSION_REASON_MEANINGS = {
    EXCLUSION_FIELD_MISSING: (
        "is_genuine_model_output or fallback_used is absent from the record "
        "(for example older/example data predating these fields)."
    ),
    EXCLUSION_NO_RESULT: (
        "is_genuine_model_output is None: the capture had no result to judge "
        "(error/incomplete execution_status)."
    ),
    EXCLUSION_FALLBACK_NOT_GENUINE: (
        "is_genuine_model_output is False: execution_status may still be ok, "
        "but the recorded answer is fallback content, not genuine model output."
    ),
    EXCLUSION_REFUSAL_NOT_QA_SCORED: (
        "execution_status is oos_or_refusal: a completed refusal, not routed "
        "to ordinary QA answer-quality judging."
    ),
    EXCLUSION_EMPTY_ANSWER: (
        "generated_answer is missing, empty, or whitespace-only despite "
        "is_genuine_model_output being True."
    ),
}


class QaCitationEligibilityError(ValueError):
    """Malformed eligibility input (not a judging failure; a usage error)."""


@dataclass(frozen=True)
class EligibilityVerdict:
    case_id: str
    eligible: bool
    exclusion_reason: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "eligible": self.eligible,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class EligibilitySummary:
    total_count: int
    eligible_count: int
    excluded_count: int
    exclusion_counts_by_reason: dict[str, int]
    verdicts: tuple[EligibilityVerdict, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "exclusion_counts_by_reason": dict(self.exclusion_counts_by_reason),
            "verdicts": [verdict.as_dict() for verdict in self.verdicts],
        }


def classify_eligibility(record: Mapping[str, Any]) -> EligibilityVerdict:
    """Fail-closed eligibility check for one Stage 3.1 capture record.

    Required for ordinary QA answer-quality judging::

        execution_status == "ok"
        and is_genuine_model_output is True
        and fallback_used is False
        and generated_answer is a non-empty, non-whitespace string

    Any missing eligibility field excludes the record rather than assuming
    it is eligible. ``execution_status == "ok"`` alone is never read as
    eligibility -- that is exactly the gap a fallback-masked generation
    failure exploited in run qac_capture_20261109T095436Z_892ed650.
    """
    case_id = str(record.get("case_id") or "")
    if not case_id:
        raise QaCitationEligibilityError("Capture record is missing case_id.")

    execution_status = record.get("execution_status")

    if execution_status == EXECUTION_STATUS_OOS_OR_REFUSAL:
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_REFUSAL_NOT_QA_SCORED,
        )

    if "is_genuine_model_output" not in record or "fallback_used" not in record:
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_FIELD_MISSING,
        )

    is_genuine_model_output = record["is_genuine_model_output"]
    fallback_used = record["fallback_used"]

    if is_genuine_model_output is None:
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_NO_RESULT,
        )

    if is_genuine_model_output is not True or fallback_used is not False:
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_FALLBACK_NOT_GENUINE,
        )

    generated_answer = record.get("generated_answer")
    if not isinstance(generated_answer, str) or not generated_answer.strip():
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_EMPTY_ANSWER,
        )

    if execution_status != "ok":
        # Defensive: genuine, non-empty output should only coexist with ok,
        # but fail closed rather than assume eligibility for an unexpected
        # status combination.
        return EligibilityVerdict(
            case_id=case_id,
            eligible=False,
            exclusion_reason=EXCLUSION_FIELD_MISSING,
        )

    return EligibilityVerdict(case_id=case_id, eligible=True, exclusion_reason=None)


def summarize_eligibility(records: Sequence[Mapping[str, Any]]) -> EligibilitySummary:
    """Classify every record. No case is dropped from the per-case verdict list."""
    verdicts: list[EligibilityVerdict] = []
    seen_case_ids: set[str] = set()
    counts_by_reason: dict[str, int] = {reason: 0 for reason in sorted(EXCLUSION_REASONS)}
    eligible_count = 0

    for record in records:
        verdict = classify_eligibility(record)
        if verdict.case_id in seen_case_ids:
            raise QaCitationEligibilityError(
                f"Duplicate case_id {verdict.case_id!r} in eligibility input."
            )
        seen_case_ids.add(verdict.case_id)
        verdicts.append(verdict)
        if verdict.eligible:
            eligible_count += 1
        else:
            reason = verdict.exclusion_reason or ""
            if reason not in counts_by_reason:
                counts_by_reason[reason] = 0
            counts_by_reason[reason] += 1

    total_count = len(verdicts)
    return EligibilitySummary(
        total_count=total_count,
        eligible_count=eligible_count,
        excluded_count=total_count - eligible_count,
        exclusion_counts_by_reason={
            reason: count for reason, count in counts_by_reason.items() if count
        },
        verdicts=tuple(verdicts),
    )


def load_captures_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read a Stage 3.1 ``captures.jsonl`` file. Read-only; never modifies it."""
    target = Path(path)
    records: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                records.append(json.loads(text))
            except json.JSONDecodeError as exc:
                raise QaCitationEligibilityError(
                    f"{target}:{line_number}: invalid JSON line."
                ) from exc
    return records


def summarize_captures_file(path: str | Path) -> EligibilitySummary:
    """Load a captures.jsonl file (read-only) and summarize its eligibility."""
    return summarize_eligibility(load_captures_jsonl(path))


def write_eligibility_report(
    summary: EligibilitySummary,
    *,
    output_path: str | Path,
    run_id: str,
    source_captures_path: str | Path,
) -> Path:
    """Write a new, separate eligibility report file.

    Never writes to or overwrites ``captures.jsonl``/``summary.json``.
    """
    target = Path(output_path)
    if target.exists():
        raise QaCitationEligibilityError(
            f"Eligibility report already exists: {target}. "
            "Previous reports are not overwritten."
        )
    payload = {
        "run_id": run_id,
        "source_captures_path": str(source_captures_path),
        "phase": "stage_3_2b_phase_1_eligibility",
        **summary.as_dict(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return target
