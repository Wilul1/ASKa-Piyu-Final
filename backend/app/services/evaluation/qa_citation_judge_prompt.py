"""Stage 3.2B Phase 3: dual-AI judge prompt construction, structured response
parsing/validation, and an injectable judge-call adapter.

This module makes no real HTTP/LLM call anywhere. ``JudgeAdapter`` delegates
the actual model call to a caller-supplied ``response_fn`` -- a fake in
tests, a real provider client in a future phase. It implements Phase 2's
``JudgeCallFn`` contract (``qa_citation_judging.py``) exactly, so it plugs
into the existing, unmodified orchestration without any change there.

Reconciling Phase 3's richer validation with Phase 2's existing malformed-
response detection
-------------------------------------------------------------------------
Phase 2's ``_call_judge_slot`` classifies a judge outcome as
``judge_malformed_response`` only by calling ``qa_citation_metrics.
_parse_judge_scores`` on whatever a judge callable returns, and that
function only checks ``evaluation_status`` and the four 0-4 integer scores
-- it has no concept of explanations or faithfulness evidence references.
Rather than modify Phase 2 or ``_parse_judge_scores`` to add those checks
(which would be a Phase 1/2 behavior change made without first reporting
it, which this phase avoids), ``build_judge_call_payload`` below performs
the full validation itself and, on ANY failure -- invalid JSON, a missing
or out-of-range score, a missing explanation, or missing/empty faithfulness
evidence references -- returns ``{"evaluation_status": "invalid_response",
"validation_error": "..."}`` instead of raising. ``_parse_judge_scores``
sees a non-``"evaluated"`` status and raises immediately
(``"must be 'evaluated' to contribute scores"``), which Phase 2 already
catches and classifies as ``judge_malformed_response``. This reuses the
existing classification mechanism exactly rather than introducing a
parallel one, at the cost of withholding the scores entirely when the
response fails the richer checks -- which is correct: a response that
fails to explain itself or point to evidence should not have its numeric
scores trusted either.

Faithfulness evidence requirement
----------------------------------
``faithfulness_evidence_refs`` is a HARD requirement (non-empty) for every
judged case. Rationale: by the time a judge is called at all, Stage 3.2B
Phase 1's eligibility filter has already excluded ineligible/fallback
records and Phase 2's orchestration never calls a judge on a refusal
(``excluded_not_applicable`` cases never reach this module). Every case
Phase 3 actually judges is therefore a genuine answer that should have
retrieved evidence behind it; a faithfulness score with zero evidence refs
has no audit trail and cannot be distinguished from a fabricated judgment.
This mirrors this codebase's existing pattern of never silently accepting
an absence of evidence (for example ``not_assessable`` claim status exists
specifically so "cannot determine" is stated explicitly rather than
defaulted around).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.services.evaluation.qa_citation_dataset import QaCitationCase, QaCitationDataset
from app.services.evaluation.qa_citation_metrics import (
    QA_CRITERIA,
    JudgeCriterionScores,
    QaCitationMetricError,
    _parse_judge_scores,  # reused, not duplicated
)

JUDGE_PROMPT_VERSION = "qa_citation_judge_v1"

JUDGE_PROMPT_TEMPLATE = """You are an independent evaluator scoring one chatbot answer from the ASKa-Piyu student support assistant against four dimensions. Score strictly from the materials given below. Do not use outside knowledge about Laguna State Polytechnic University.

QUESTION:
{question}

CHATBOT ANSWER TO SCORE:
{generated_answer}

RETRIEVED EVIDENCE (this is what the chatbot actually retrieved and cited; use this, and ONLY this, to judge Faithfulness):
{retrieved_context}

GOLD REFERENCE ANSWER (for Correctness and Completeness ONLY -- do NOT use this as the evidence basis for Faithfulness; Faithfulness must be judged only against RETRIEVED EVIDENCE above, never against similarity to this reference):
{reference_answer}

Score each dimension on an integer scale from 0 to 4 (0 = worst, 4 = best):
- correctness: Does the answer state facts that match the gold reference answer?
- completeness: Does the answer cover everything the gold reference answer covers?
- relevance: Does the answer actually address the question asked?
- faithfulness: Is every factual claim in the answer actually supported by the RETRIEVED EVIDENCE above (not the gold reference, not outside knowledge)? A claim that is not present in the retrieved evidence is unfaithful even if it happens to be true.

Respond with ONLY a single JSON object, no other text before or after it, in exactly this shape:
{{
  "evaluation_status": "evaluated",
  "correctness": <int 0-4>,
  "completeness": <int 0-4>,
  "relevance": <int 0-4>,
  "faithfulness": <int 0-4>,
  "explanation": {{
    "correctness": "<one or two sentences>",
    "completeness": "<one or two sentences>",
    "relevance": "<one or two sentences>",
    "faithfulness": "<one or two sentences>"
  }},
  "faithfulness_evidence_refs": ["<citation id or short quote from RETRIEVED EVIDENCE that your faithfulness score relied on>", "..."]
}}

faithfulness_evidence_refs must be non-empty and must point to specific parts of RETRIEVED EVIDENCE above, never to the gold reference answer and never to outside knowledge."""


def judge_prompt_sha256() -> str:
    """SHA-256 of the judge prompt template, mirroring how the chatbot's own
    system prompt is hashed (``qa_citation_capture.chatbot_prompt_identity``:
    ``hashlib.sha256(text.encode("utf-8")).hexdigest()``)."""
    return hashlib.sha256(JUDGE_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def build_judge_prompt(
    *,
    question: str,
    generated_answer: str | None,
    retrieved_context: str | None,
    reference_answer: str | None,
) -> str:
    return JUDGE_PROMPT_TEMPLATE.format(
        question=question or "",
        generated_answer=generated_answer or "",
        retrieved_context=retrieved_context or "(no retrieved evidence recorded)",
        reference_answer=(
            reference_answer
            or "(no gold reference answer -- this case should not have reached ordinary QA judging)"
        ),
    )


class QaCitationJudgePromptError(ValueError):
    """Judge-prompt/adapter configuration problem (not a judge-response failure)."""


class DuplicateJudgeModelError(QaCitationJudgePromptError):
    """Raised when both judge slots would use the same underlying model.

    A single model used twice cannot provide genuine dual-AI independence.
    Raised at construction time of a judge pair, never silently allowed.
    """


@dataclass(frozen=True)
class JudgeResponsePayload:
    """One judge's fully validated response: scores, explanations, evidence."""

    scores: JudgeCriterionScores
    explanations: dict[str, str]
    faithfulness_evidence_refs: tuple[str, ...]
    raw: dict[str, Any]


def parse_judge_response_json(raw: str | Mapping[str, Any]) -> Mapping[str, Any]:
    """Parse a judge's raw output (text or already-parsed mapping) into a dict.

    Raises QaCitationMetricError on invalid JSON or a non-object JSON value.
    """
    if isinstance(raw, Mapping):
        return raw
    if not isinstance(raw, str):
        raise QaCitationMetricError(
            f"Judge response must be a JSON string or a mapping, got {type(raw).__name__}."
        )
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QaCitationMetricError(f"Judge response is not valid JSON: {exc}") from exc
    if not isinstance(parsed, Mapping):
        raise QaCitationMetricError(
            f"Judge response JSON must decode to an object, got {type(parsed).__name__}."
        )
    return parsed


def validate_judge_response(
    raw: str | Mapping[str, Any], *, slot: str
) -> JudgeResponsePayload:
    """Full Phase 3 validation: JSON structure, the four 0-4 integer scores
    (via the existing, reused ``_parse_judge_scores``), per-dimension
    explanations, and non-empty faithfulness evidence references.

    Raises QaCitationMetricError naming the exact problem on any failure.
    Never silently defaults or drops a required field.
    """
    parsed = parse_judge_response_json(raw)
    scores = _parse_judge_scores(parsed, slot=slot)

    explanation = parsed.get("explanation")
    if not isinstance(explanation, Mapping):
        raise QaCitationMetricError(
            f"{slot} judge response is missing the required 'explanation' object."
        )
    missing_or_empty = [
        criterion
        for criterion in QA_CRITERIA
        if not isinstance(explanation.get(criterion), str)
        or not explanation.get(criterion, "").strip()
    ]
    if missing_or_empty:
        raise QaCitationMetricError(
            f"{slot} judge response is missing a non-empty explanation for: "
            f"{missing_or_empty}."
        )

    evidence_refs = parsed.get("faithfulness_evidence_refs")
    if (
        not isinstance(evidence_refs, (list, tuple))
        or not evidence_refs
        or not all(isinstance(ref, str) and ref.strip() for ref in evidence_refs)
    ):
        raise QaCitationMetricError(
            f"{slot} judge response is missing non-empty 'faithfulness_evidence_refs'. "
            "Faithfulness must be assessed against retrieved evidence, not asserted "
            "without a reference."
        )

    return JudgeResponsePayload(
        scores=scores,
        explanations={criterion: explanation[criterion] for criterion in QA_CRITERIA},
        faithfulness_evidence_refs=tuple(evidence_refs),
        raw=dict(parsed),
    )


def build_judge_call_payload(
    raw: str | Mapping[str, Any], *, slot: str
) -> dict[str, Any]:
    """What a ``JudgeAdapter`` returns from one call, satisfying Phase 2's
    ``JudgeCallFn`` contract.

    On success: the full validated payload (scores + evaluation_status, plus
    explanations/evidence refs preserved for diagnostics -- Phase 2's
    ``_parse_judge_scores`` only reads the score/evaluation_status keys and
    ignores the rest, so this is safe to pass straight through).

    On ANY validation failure (invalid JSON, bad/missing score, missing
    explanation, missing evidence refs): an ``evaluation_status`` other than
    ``"evaluated"`` and no score keys. Phase 2's existing
    ``_parse_judge_scores`` call raises on that immediately and Phase 2
    classifies the outcome as ``judge_malformed_response`` -- the existing
    mechanism, not a new parallel one.
    """
    try:
        payload = validate_judge_response(raw, slot=slot)
    except QaCitationMetricError as exc:
        return {"evaluation_status": "invalid_response", "validation_error": str(exc)}

    result: dict[str, Any] = dict(payload.scores.as_dict())
    result["evaluation_status"] = "evaluated"
    result["explanation"] = dict(payload.explanations)
    result["faithfulness_evidence_refs"] = list(payload.faithfulness_evidence_refs)
    return result


@dataclass(frozen=True)
class JudgeIdentity:
    model: str
    provider: str

    @property
    def identity_key(self) -> str:
        return f"{self.provider}:{self.model}"


ResponseFn = Callable[[str], "str | Mapping[str, Any]"]


class JudgeAdapter:
    """Injectable adapter implementing Phase 2's ``JudgeCallFn`` contract.

    Builds the Stage 3.2B judge prompt from a capture record plus the
    matching dataset case (looked up by ``case_id``), delegates the actual
    model call to ``response_fn``, and validates/parses the result via
    ``build_judge_call_payload``. No real HTTP/LLM call exists anywhere in
    this class -- ``response_fn`` is supplied by the caller: a fake/fixture
    in tests this phase, a real provider client in a future phase. Any
    exception ``response_fn`` raises (including
    ``qa_citation_judging.JudgeTimeoutError``/``JudgeCallError``) propagates
    unchanged to Phase 2's orchestration, which already classifies it.
    """

    def __init__(
        self,
        *,
        model: str,
        provider: str,
        dataset: QaCitationDataset,
        response_fn: ResponseFn,
        slot_name: str = "judge",
        prompt_version: str = JUDGE_PROMPT_VERSION,
    ) -> None:
        self.identity = JudgeIdentity(model=model, provider=provider)
        self._cases_by_id: dict[str, QaCitationCase] = {
            case.case_id: case for case in dataset.cases
        }
        self._response_fn = response_fn
        self.slot_name = slot_name
        self.prompt_version = prompt_version
        self.prompt_sha256 = judge_prompt_sha256()

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
        prompt = build_judge_prompt(
            question=case.question,
            generated_answer=record.get("generated_answer"),
            retrieved_context=record.get("retrieved_context"),
            reference_answer=case.reference_answer,
        )
        raw = self._response_fn(prompt)  # may raise; propagates to Phase 2 unchanged
        payload = build_judge_call_payload(raw, slot=self.slot_name)
        payload["_judge_model"] = self.identity.model
        payload["_judge_provider"] = self.identity.provider
        payload["_judge_prompt_version"] = self.prompt_version
        payload["_judge_prompt_sha256"] = self.prompt_sha256
        return payload


def build_judge_pair(
    *, primary: JudgeAdapter, secondary: JudgeAdapter
) -> tuple[JudgeAdapter, JudgeAdapter]:
    """Construction-time check: the two judge slots must use distinct
    underlying models. Raises DuplicateJudgeModelError, never silently
    proceeds and never just logs a warning.

    Distinct providers are preferred but not enforced here (per the
    approved Stage 3.2B authorization: "Two distinct underlying judge
    models are required; different providers are preferred").
    """
    if primary.identity.model == secondary.identity.model:
        raise DuplicateJudgeModelError(
            "Both judge slots are configured with the same underlying model "
            f"({primary.identity.model!r}); dual-AI judging requires two "
            "distinct models. Refusing to proceed rather than silently "
            "misrepresenting independence."
        )
    return primary, secondary
