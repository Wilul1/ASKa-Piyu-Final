"""Stage 3.2B Phase 4: the separate insufficient-evidence evaluation rubric.

``labeled_student_support`` cases get the ordinary four-dimension QA rubric
(``qa_citation_judge_prompt.py`` / ``qa_citation_judging.py``). A dataset
case with ``case_type == "insufficient_evidence"`` has ``reference_answer``
is ``None`` by Stage 2 contract -- there is nothing to score Correctness or
Completeness against, and forcing one onto the 0-4 QA scale would be
meaningless. This module scores that population on two independent binary
dimensions instead:

* ``correctly_declined`` -- did the chatbot appropriately acknowledge the
  knowledge base does not support an answer?
* ``unsupported_claim_detected`` -- did the chatbot assert something not
  supported by the available evidence?

These are independent, not mutually exclusive: a chatbot can decline *and*
still slip in an unsupported claim ("I don't have that information, but
typically..."), which is exactly why both are tracked separately rather than
collapsed into one pass/fail outcome.

This module makes no real HTTP/LLM call anywhere -- the same injectable
``response_fn`` pattern as ``qa_citation_judge_prompt.JudgeAdapter`` is
used, and it is exercised only by test doubles in this phase. It reuses,
without modifying:

* Phase 1's ``classify_eligibility`` -- a genuinely-generated, non-fallback
  answer is required before this rubric is judged too; an
  insufficient-evidence case's dataset ``case_type`` does not change the
  eligibility rule.
* Phase 2's ``JudgeTimeoutError``/``JudgeCallError`` exception types and its
  excluded/failed status vocabulary (``JUDGING_STATUS_*`` from
  ``qa_citation_metrics``), so a Stage 3.2B report can tell at a glance that
  "judged" / "excluded_ineligible" / "judging_failed_partial" mean the same
  thing in both rubrics' outputs.
* Phase 3's ``build_judge_pair``/``DuplicateJudgeModelError`` for judge
  model-identity enforcement -- unchanged, not reimplemented here.

It does NOT reuse ``aggregate_dual_ai_qa_scores`` (that produces a 0-4 mean,
which this rubric must never produce) and does NOT reuse
``_parse_judge_scores`` (a different, int-scored response shape). A
dedicated response validator and a dedicated aggregation function live here
instead, operating on this rubric's own boolean+evidence response shape.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.services.evaluation.qa_citation_dataset import QaCitationCase, QaCitationDataset
from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_REFUSAL_NOT_QA_SCORED,
    EligibilityVerdict,
    classify_eligibility,
)
from app.services.evaluation.qa_citation_judge_prompt import (
    DuplicateJudgeModelError,  # re-exported for callers; unchanged, not redefined
    JudgeIdentity,
    QaCitationJudgePromptError,
    build_judge_pair,
    parse_judge_response_json,
)
from app.services.evaluation.qa_citation_judging import (
    JudgeCallError,
    JudgeTimeoutError,
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
    QaCitationMetricError,
)

INSUFFICIENT_EVIDENCE_PROMPT_VERSION = "qa_citation_insufficient_evidence_judge_v1"

INSUFFICIENT_EVIDENCE_DIMENSIONS = ("correctly_declined", "unsupported_claim_detected")

INSUFFICIENT_EVIDENCE_PROMPT_TEMPLATE = """You are an independent evaluator judging one chatbot answer from the ASKa-Piyu student support assistant on a question the available knowledge base cannot fully answer. Judge strictly from the materials given below. Do not use outside knowledge about Laguna State Polytechnic University.

QUESTION:
{question}

CHATBOT ANSWER TO JUDGE:
{generated_answer}

RETRIEVED EVIDENCE (everything the chatbot actually retrieved; this is the full available evidence):
{retrieved_context}

DISPLAYED CITATION IDS (what the chatbot actually showed the student as sources for this answer; this list may be empty):
{displayed_citation_ids}

An empty or short DISPLAYED CITATION IDS list does NOT by itself mean the answer is unsupported -- you must read RETRIEVED EVIDENCE and judge whether the answer's actual claims are backed by it, not just count citations.

Judge two independent binary dimensions. They are not mutually exclusive: an answer can correctly decline to answer AND still contain an unsupported claim (for example "I don't have that information, but it is typically...").

1. correctly_declined: did the chatbot appropriately acknowledge that the available knowledge base does not support a confident answer to this question (rather than inventing one)?
2. unsupported_claim_detected: did the chatbot assert any specific fact that RETRIEVED EVIDENCE above does not actually support?

Respond with ONLY a single JSON object, no other text before or after it, in exactly this shape:
{{
  "evaluation_status": "evaluated",
  "correctly_declined": {{
    "result": <true or false>,
    "explanation": "<one or two sentences>",
    "answer_excerpts": ["<short quote from CHATBOT ANSWER that supports this judgment>", "..."],
    "evidence_refs": ["<citation id or short quote from RETRIEVED EVIDENCE that supports this judgment>", "..."]
  }},
  "unsupported_claim_detected": {{
    "result": <true or false>,
    "explanation": "<one or two sentences>",
    "answer_excerpts": ["<short quote from CHATBOT ANSWER containing the claim(s) you assessed>", "..."],
    "evidence_refs": ["<citation id or short quote from RETRIEVED EVIDENCE that either supports or contradicts the claim(s), or notes none exists>", "..."]
  }}
}}

answer_excerpts and evidence_refs must each be non-empty for both dimensions, even when result is false -- point to what you actually checked, never leave your judgment unexplained or unsourced. Never invent a citation id or quote that does not appear in RETRIEVED EVIDENCE above."""


def insufficient_evidence_prompt_sha256() -> str:
    """SHA-256 of this rubric's prompt template, same method as the QA judge
    prompt's ``judge_prompt_sha256`` (``hashlib.sha256(text.encode("utf-8"))
    .hexdigest()``)."""
    return hashlib.sha256(INSUFFICIENT_EVIDENCE_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def build_insufficient_evidence_prompt(
    *,
    question: str,
    generated_answer: str | None,
    retrieved_context: str | None,
    displayed_citation_ids: Sequence[str] | None,
) -> str:
    ids = list(displayed_citation_ids or [])
    return INSUFFICIENT_EVIDENCE_PROMPT_TEMPLATE.format(
        question=question or "",
        generated_answer=generated_answer or "",
        retrieved_context=retrieved_context or "(no retrieved evidence recorded)",
        displayed_citation_ids=json.dumps(ids, ensure_ascii=False) if ids else "[] (empty)",
    )


@dataclass(frozen=True)
class InsufficientEvidenceDimensionResult:
    """One judge's verdict for one of the two binary dimensions."""

    result: bool
    explanation: str
    answer_excerpts: tuple[str, ...]
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class InsufficientEvidenceJudgeResponse:
    """One judge's fully validated response for both dimensions."""

    correctly_declined: InsufficientEvidenceDimensionResult
    unsupported_claim_detected: InsufficientEvidenceDimensionResult
    raw: dict[str, Any]


def _validate_dimension(
    parsed: Mapping[str, Any], *, dimension: str, slot: str
) -> InsufficientEvidenceDimensionResult:
    block = parsed.get(dimension)
    if not isinstance(block, Mapping):
        raise QaCitationMetricError(
            f"{slot} judge response is missing the required {dimension!r} object."
        )

    result = block.get("result")
    if not isinstance(result, bool):
        raise QaCitationMetricError(
            f"{slot} judge {dimension}.result must be a boolean, got {result!r}."
        )

    explanation = block.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        raise QaCitationMetricError(
            f"{slot} judge response is missing a non-empty {dimension}.explanation."
        )

    def _non_empty_string_list(field: str) -> tuple[str, ...]:
        value = block.get(field)
        if (
            not isinstance(value, (list, tuple))
            or not value
            or not all(isinstance(item, str) and item.strip() for item in value)
        ):
            raise QaCitationMetricError(
                f"{slot} judge response is missing non-empty {dimension}.{field}. "
                "A boolean result must point to what was actually checked, "
                "never left unexplained or unsourced."
            )
        return tuple(value)

    answer_excerpts = _non_empty_string_list("answer_excerpts")
    evidence_refs = _non_empty_string_list("evidence_refs")

    return InsufficientEvidenceDimensionResult(
        result=result,
        explanation=explanation,
        answer_excerpts=answer_excerpts,
        evidence_refs=evidence_refs,
    )


def validate_insufficient_evidence_response(
    raw: str | Mapping[str, Any], *, slot: str
) -> InsufficientEvidenceJudgeResponse:
    """Full Phase 4 validation: JSON structure, ``evaluation_status``, and
    both dimensions' boolean result + explanation + excerpts + evidence
    refs. Raises QaCitationMetricError naming the exact problem on any
    failure. Never silently defaults or drops a required field.
    """
    parsed = parse_judge_response_json(raw)

    status = parsed.get("evaluation_status")
    if status != "evaluated":
        raise QaCitationMetricError(
            f"{slot} judge evaluation_status must be 'evaluated', got {status!r}. "
            "Missing judges are rejected, not replaced."
        )

    correctly_declined = _validate_dimension(parsed, dimension="correctly_declined", slot=slot)
    unsupported_claim_detected = _validate_dimension(
        parsed, dimension="unsupported_claim_detected", slot=slot
    )

    return InsufficientEvidenceJudgeResponse(
        correctly_declined=correctly_declined,
        unsupported_claim_detected=unsupported_claim_detected,
        raw=dict(parsed),
    )


def build_insufficient_evidence_judge_call_payload(
    raw: str | Mapping[str, Any], *, slot: str
) -> dict[str, Any]:
    """What an insufficient-evidence judge adapter returns from one call.

    On success: ``evaluation_status: "evaluated"`` plus both validated
    dimension results. On ANY validation failure: ``evaluation_status:
    "invalid_response"`` and no result fields -- the orchestration below
    checks this status directly (this rubric has its own validator, so
    unlike the QA rubric there is no existing Phase 2 function to route
    through; the check is explicit here instead).
    """
    try:
        payload = validate_insufficient_evidence_response(raw, slot=slot)
    except QaCitationMetricError as exc:
        return {"evaluation_status": "invalid_response", "validation_error": str(exc)}

    return {
        "evaluation_status": "evaluated",
        "correctly_declined": {
            "result": payload.correctly_declined.result,
            "explanation": payload.correctly_declined.explanation,
            "answer_excerpts": list(payload.correctly_declined.answer_excerpts),
            "evidence_refs": list(payload.correctly_declined.evidence_refs),
        },
        "unsupported_claim_detected": {
            "result": payload.unsupported_claim_detected.result,
            "explanation": payload.unsupported_claim_detected.explanation,
            "answer_excerpts": list(payload.unsupported_claim_detected.answer_excerpts),
            "evidence_refs": list(payload.unsupported_claim_detected.evidence_refs),
        },
    }


class InsufficientEvidenceJudgeAdapter:
    """Injectable adapter for this rubric, mirroring
    ``qa_citation_judge_prompt.JudgeAdapter`` exactly in shape (same
    constructor pattern, same ``model_identity``/``identity`` surface so
    ``build_judge_pair`` works unmodified on either rubric's adapters), but
    building the insufficient-evidence prompt and validating this rubric's
    response shape instead. No real HTTP/LLM call exists anywhere in this
    class -- ``response_fn`` is caller-supplied.
    """

    def __init__(
        self,
        *,
        model: str,
        provider: str,
        dataset: QaCitationDataset,
        response_fn: Callable[[str], "str | Mapping[str, Any]"],
        slot_name: str = "judge",
        prompt_version: str = INSUFFICIENT_EVIDENCE_PROMPT_VERSION,
    ) -> None:
        self.identity = JudgeIdentity(model=model, provider=provider)
        self._cases_by_id: dict[str, QaCitationCase] = {
            case.case_id: case for case in dataset.cases
        }
        self._response_fn = response_fn
        self.slot_name = slot_name
        self.prompt_version = prompt_version
        self.prompt_sha256 = insufficient_evidence_prompt_sha256()

    @property
    def model_identity(self) -> str:
        return self.identity.identity_key

    def __call__(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = str(record.get("case_id") or "")
        case = self._cases_by_id.get(case_id)
        if case is None:
            raise QaCitationJudgePromptError(
                f"No dataset case found for case_id {case_id!r}; cannot build a judge prompt."
            )
        prompt = build_insufficient_evidence_prompt(
            question=case.question,
            generated_answer=record.get("generated_answer"),
            retrieved_context=record.get("retrieved_context"),
            displayed_citation_ids=record.get("displayed_citation_ids"),
        )
        raw = self._response_fn(prompt)  # may raise; propagates to orchestration unchanged
        payload = build_insufficient_evidence_judge_call_payload(raw, slot=self.slot_name)
        payload["_judge_model"] = self.identity.model
        payload["_judge_provider"] = self.identity.provider
        payload["_judge_prompt_version"] = self.prompt_version
        payload["_judge_prompt_sha256"] = self.prompt_sha256
        return payload


# Re-exported so callers only need this module for the insufficient-evidence
# path; identical function, not reimplemented.
build_insufficient_evidence_judge_pair = build_judge_pair


JudgeCallFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class InsufficientEvidenceJudgeSlotOutcome:
    """One judge slot's result for one insufficient-evidence case."""

    judge_execution_status: str
    raw_response: Mapping[str, Any] | None
    parsed: InsufficientEvidenceJudgeResponse | None = None
    error_detail: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED


@dataclass(frozen=True)
class InsufficientEvidenceResult:
    """Both judges' preserved, independent verdicts plus per-dimension
    agreement. Never collapses two booleans into one value."""

    primary: InsufficientEvidenceJudgeResponse
    secondary: InsufficientEvidenceJudgeResponse
    correctly_declined_agreement: bool
    unsupported_claim_detected_agreement: bool


@dataclass(frozen=True)
class InsufficientEvidenceOutcome:
    """The full, per-case Phase 4 judging result. Exactly one of these is
    produced per input capture record -- whether excluded, partially/totally
    failed, or judged."""

    case_id: str
    final_status: str
    eligibility_verdict: EligibilityVerdict
    primary_judge: InsufficientEvidenceJudgeSlotOutcome | None
    secondary_judge: InsufficientEvidenceJudgeSlotOutcome | None
    result: InsufficientEvidenceResult | None


class QaCitationInsufficientEvidenceError(ValueError):
    """Malformed orchestration input (not a judge-call failure)."""


def _call_insufficient_evidence_judge_slot(
    record: Mapping[str, Any],
    judge_fn: JudgeCallFn,
    *,
    slot: str,
) -> InsufficientEvidenceJudgeSlotOutcome:
    try:
        response = judge_fn(record)
    except JudgeTimeoutError as exc:
        return InsufficientEvidenceJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_TIMEOUT,
            raw_response=None,
            error_detail=str(exc) or "judge call timed out",
        )
    except JudgeCallError as exc:
        return InsufficientEvidenceJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or "judge call failed",
        )
    except Exception as exc:  # pragma: no cover - defensive safety net, mirrors Phase 2
        return InsufficientEvidenceJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or f"unexpected {type(exc).__name__}",
        )

    try:
        parsed = validate_insufficient_evidence_response(response, slot=slot)
    except QaCitationMetricError as exc:
        raw_for_record = response if isinstance(response, Mapping) else None
        return InsufficientEvidenceJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_MALFORMED,
            raw_response=raw_for_record,
            error_detail=str(exc),
        )

    return InsufficientEvidenceJudgeSlotOutcome(
        judge_execution_status=JUDGE_EXECUTION_STATUS_EVALUATED,
        raw_response=response,
        parsed=parsed,
    )


def judge_insufficient_evidence_case(
    record: Mapping[str, Any],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> InsufficientEvidenceOutcome:
    """Run Phase 1 eligibility first; only call judges for an eligible
    record. Mirrors Phase 2's ``judge_eligible_case`` combination rule
    exactly, but never calls ``aggregate_dual_ai_qa_scores`` and never
    collapses this rubric's two independent booleans into one value.
    """
    verdict = classify_eligibility(record)

    if not verdict.eligible:
        final_status = (
            JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
            if verdict.exclusion_reason == EXCLUSION_REFUSAL_NOT_QA_SCORED
            else JUDGING_STATUS_EXCLUDED_INELIGIBLE
        )
        return InsufficientEvidenceOutcome(
            case_id=verdict.case_id,
            final_status=final_status,
            eligibility_verdict=verdict,
            primary_judge=None,
            secondary_judge=None,
            result=None,
        )

    primary_outcome = _call_insufficient_evidence_judge_slot(record, primary_judge, slot="primary")
    secondary_outcome = _call_insufficient_evidence_judge_slot(
        record, secondary_judge, slot="secondary"
    )

    if primary_outcome.evaluated and secondary_outcome.evaluated:
        assert primary_outcome.parsed is not None and secondary_outcome.parsed is not None
        result = InsufficientEvidenceResult(
            primary=primary_outcome.parsed,
            secondary=secondary_outcome.parsed,
            correctly_declined_agreement=(
                primary_outcome.parsed.correctly_declined.result
                == secondary_outcome.parsed.correctly_declined.result
            ),
            unsupported_claim_detected_agreement=(
                primary_outcome.parsed.unsupported_claim_detected.result
                == secondary_outcome.parsed.unsupported_claim_detected.result
            ),
        )
        final_status = JUDGING_STATUS_JUDGED
    elif primary_outcome.evaluated or secondary_outcome.evaluated:
        # Exactly one slot succeeded. No InsufficientEvidenceResult is
        # produced here -- a single judge's verdict must never stand in as
        # the case's outcome, mirroring Phase 2's QA-rubric rule exactly.
        result = None
        final_status = JUDGING_STATUS_FAILED_PARTIAL
    else:
        result = None
        final_status = JUDGING_STATUS_FAILED_TOTAL

    return InsufficientEvidenceOutcome(
        case_id=verdict.case_id,
        final_status=final_status,
        eligibility_verdict=verdict,
        primary_judge=primary_outcome,
        secondary_judge=secondary_outcome,
        result=result,
    )


def judge_insufficient_evidence_cases(
    records: Sequence[Mapping[str, Any]],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> list[InsufficientEvidenceOutcome]:
    """Run ``judge_insufficient_evidence_case`` over every record. One
    output per input; no case is dropped. Duplicate case_ids raise rather
    than overwrite."""
    outcomes: list[InsufficientEvidenceOutcome] = []
    seen_case_ids: set[str] = set()
    for record in records:
        outcome = judge_insufficient_evidence_case(
            record, primary_judge=primary_judge, secondary_judge=secondary_judge
        )
        if outcome.case_id in seen_case_ids:
            raise QaCitationInsufficientEvidenceError(
                f"Duplicate case_id {outcome.case_id!r} in insufficient-evidence judging input."
            )
        seen_case_ids.add(outcome.case_id)
        outcomes.append(outcome)
    return outcomes


@dataclass(frozen=True)
class InsufficientEvidenceAggregation:
    """Separate from ``JudgingAggregation`` (the ordinary-QA rubric's
    aggregation shape) -- this rubric's outcome set is a different
    population and must never be merged into the same summary."""

    total_count: int
    eligible_count: int
    excluded_count: int
    exclusion_counts_by_reason: dict[str, int]
    judged_count: int
    judging_failed_partial_count: int
    judging_failed_total_count: int
    correctly_declined_agreement_count: int
    correctly_declined_disagreement_count: int
    unsupported_claim_detected_agreement_count: int
    unsupported_claim_detected_disagreement_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "total_count": self.total_count,
            "eligible_count": self.eligible_count,
            "excluded_count": self.excluded_count,
            "exclusion_counts_by_reason": dict(self.exclusion_counts_by_reason),
            "judged_count": self.judged_count,
            "judging_failed_partial_count": self.judging_failed_partial_count,
            "judging_failed_total_count": self.judging_failed_total_count,
            "correctly_declined_agreement_count": self.correctly_declined_agreement_count,
            "correctly_declined_disagreement_count": self.correctly_declined_disagreement_count,
            "unsupported_claim_detected_agreement_count": (
                self.unsupported_claim_detected_agreement_count
            ),
            "unsupported_claim_detected_disagreement_count": (
                self.unsupported_claim_detected_disagreement_count
            ),
        }


def summarize_insufficient_evidence_outcomes(
    outcomes: Sequence[InsufficientEvidenceOutcome],
) -> InsufficientEvidenceAggregation:
    """Aggregate a batch of InsufficientEvidenceOutcome. Kept entirely
    separate from ordinary QA score reporting -- a different population,
    a different rubric, a different summary shape."""
    total_count = len(outcomes)
    excluded_counts_by_reason: dict[str, int] = {}
    excluded_count = 0
    judged_count = 0
    partial_count = 0
    total_fail_count = 0
    cd_agree = cd_disagree = 0
    ucd_agree = ucd_disagree = 0

    for outcome in outcomes:
        if outcome.final_status in (
            JUDGING_STATUS_EXCLUDED_INELIGIBLE,
            JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE,
        ):
            excluded_count += 1
            reason = outcome.eligibility_verdict.exclusion_reason or ""
            excluded_counts_by_reason[reason] = excluded_counts_by_reason.get(reason, 0) + 1
        elif outcome.final_status == JUDGING_STATUS_JUDGED:
            judged_count += 1
            assert outcome.result is not None
            if outcome.result.correctly_declined_agreement:
                cd_agree += 1
            else:
                cd_disagree += 1
            if outcome.result.unsupported_claim_detected_agreement:
                ucd_agree += 1
            else:
                ucd_disagree += 1
        elif outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL:
            partial_count += 1
        elif outcome.final_status == JUDGING_STATUS_FAILED_TOTAL:
            total_fail_count += 1
        else:  # pragma: no cover - defensive
            raise QaCitationInsufficientEvidenceError(
                f"Unknown final_status {outcome.final_status!r} for case {outcome.case_id!r}."
            )

    eligible_count = total_count - excluded_count
    return InsufficientEvidenceAggregation(
        total_count=total_count,
        eligible_count=eligible_count,
        excluded_count=excluded_count,
        exclusion_counts_by_reason=excluded_counts_by_reason,
        judged_count=judged_count,
        judging_failed_partial_count=partial_count,
        judging_failed_total_count=total_fail_count,
        correctly_declined_agreement_count=cd_agree,
        correctly_declined_disagreement_count=cd_disagree,
        unsupported_claim_detected_agreement_count=ucd_agree,
        unsupported_claim_detected_disagreement_count=ucd_disagree,
    )
