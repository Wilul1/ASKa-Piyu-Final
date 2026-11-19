"""Stage 3.2B Phase 5 Part A: citation claim-level judging.

Extracts factual claims from a genuinely-generated chatbot answer, marks
which claims require a citation, assesses each citation-required claim's
``claim_support`` (``supported`` / ``unsupported`` / ``not_assessable``),
and records which of the case's own ``displayed_citation_ids`` back each
claim -- never any ID the judge invents. Resolves each displayed citation
ID against the locked 691-chunk extract (reusing
``qa_citation_dataset.load_locked_extract_index`` -- no new corpus-reading
code) to produce ``citation_validity_by_id``, then calls the existing
``qa_citation_metrics.compute_citation_metrics`` directly; its math is not
reimplemented here.

This module makes no real HTTP/LLM call anywhere -- the same injectable
``response_fn`` pattern as ``qa_citation_judge_prompt.JudgeAdapter`` /
``qa_citation_insufficient_evidence.InsufficientEvidenceJudgeAdapter`` is
used, exercised only by test doubles in this phase.

Design decisions this module settles (both left open by the approved
Stage 3.2B design, neither ducked)
--------------------------------------------------------------------------
1. **Separate orchestration, separate judge pair from the QA rubric.**
   Citation-claim judging is its own two-judge call, not folded into the
   same response as QA scoring. This keeps the two rubrics' failure
   domains independent -- a malformed QA response does not also void a
   perfectly good claim extraction, and vice versa -- which is the same
   reasoning Phase 4 already used to keep the insufficient-evidence
   rubric a separate call from the QA rubric rather than one combined
   judge response carrying both.
2. **Both judges' claim extractions are preserved and scored
   independently; neither is treated as "the" authoritative claim set.**
   ``compute_citation_metrics`` takes one claim list, so when both judge
   slots evaluate successfully, this module calls it *twice* -- once
   against the primary judge's claims, once against the secondary's --
   and keeps both ``CitationMetrics`` results on the case outcome. This
   mirrors the dual-AI QA rubric's own rule (never collapse two judges
   into one before reporting both) and avoids an unreliable free-text
   merge of two independently-extracted claim lists, which would risk
   silently inventing a claim neither judge actually produced. Run-level
   aggregation (Part B) then treats each (case, evaluated judge slot)
   pair as its own data point when summing counts -- see
   ``qa_citation_run_report.py`` for the reasoning on why counts are
   summed before fractions are computed, not fractions averaged.

Both judge slots failing or exactly one succeeding follow the same
combination rule as every other Stage 3.2B rubric: ``judging_failed_total``
/ ``judging_failed_partial``, no automatic retries, a single surviving
judge's result is preserved for diagnostics only and never presented as
the case's citation outcome.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from app.services.evaluation.qa_citation_dataset import (
    QaCitationCase,
    QaCitationDataset,
    load_locked_extract_index,
)
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
from app.services.evaluation.qa_citation_judging import JudgeCallError, JudgeTimeoutError
from app.services.evaluation.qa_citation_metrics import (
    CITATION_VALIDITY_UNRESOLVED,
    CITATION_VALIDITY_VALID,
    CLAIM_STATUSES,
    CLAIM_STATUS_SUPPORTED,
    JUDGE_EXECUTION_STATUS_ERROR,
    JUDGE_EXECUTION_STATUS_EVALUATED,
    JUDGE_EXECUTION_STATUS_MALFORMED,
    JUDGE_EXECUTION_STATUS_TIMEOUT,
    JUDGING_STATUS_EXCLUDED_INELIGIBLE,
    JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE,
    JUDGING_STATUS_FAILED_PARTIAL,
    JUDGING_STATUS_FAILED_TOTAL,
    JUDGING_STATUS_JUDGED,
    CitationMetrics,
    ClaimMetricInput,
    QaCitationMetricError,
    compute_citation_metrics,
    unique_preserve_order,
)

CITATION_CLAIM_PROMPT_VERSION = "qa_citation_claim_judge_v1"

CITATION_CLAIM_PROMPT_TEMPLATE = """You are an independent evaluator extracting and judging the factual claims in one chatbot answer from the ASKa-Piyu student support assistant. Work strictly from the materials given below. Do not use outside knowledge about Laguna State Polytechnic University.

QUESTION:
{question}

CHATBOT ANSWER:
{generated_answer}

RETRIEVED EVIDENCE (everything the chatbot actually retrieved):
{retrieved_context}

DISPLAYED CITATION IDS (the ONLY ids you may ever write in supporting_displayed_ids; never invent an id that is not in this exact list, and never substitute a retrieved-evidence id that is not also in this list):
{displayed_citation_ids}

Extract every distinct factual claim the CHATBOT ANSWER makes. For each claim:
1. requires_citation: true if the claim is a specific factual assertion that should be backed by evidence (a fee amount, a procedure step, a name, a deadline, a policy rule). false for greetings, questions back to the student, generic disclaimers, or statements that assert nothing factual.
2. If requires_citation is true, assess claim_support using only RETRIEVED EVIDENCE and DISPLAYED CITATION IDS above:
   - "supported": at least one id in DISPLAYED CITATION IDS actually backs this exact claim.
   - "unsupported": no id in DISPLAYED CITATION IDS backs this claim, even if RETRIEVED EVIDENCE elsewhere might.
   - "not_assessable": you cannot determine support from the materials given (state this rather than guessing).
   If requires_citation is false, claim_support must be null.
3. supporting_displayed_ids: for a "supported" claim, the DISPLAYED CITATION IDS (only from the exact list above) that back it -- must be non-empty. For "unsupported" or "not_assessable" claims, this must be an empty list. For claims where requires_citation is false, omit this field or leave it empty.

Respond with ONLY a single JSON object, no other text before or after it, in exactly this shape:
{{
  "evaluation_status": "evaluated",
  "claims": [
    {{
      "claim_id": "c1",
      "text": "<the claim, in your own words or a short quote>",
      "requires_citation": true,
      "claim_support": "supported",
      "supporting_displayed_ids": ["<id from DISPLAYED CITATION IDS above>"]
    }}
  ]
}}

claims may be an empty list if the answer makes no factual claims at all. Never invent a claim_id, a citation id, or a claim the answer does not actually make."""


def citation_claim_prompt_sha256() -> str:
    """SHA-256 of this rubric's prompt template, same method as the other two
    Stage 3.2B prompts (``hashlib.sha256(text.encode("utf-8")).hexdigest()``)."""
    return hashlib.sha256(CITATION_CLAIM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()


def build_citation_claim_prompt(
    *,
    question: str,
    generated_answer: str | None,
    retrieved_context: str | None,
    displayed_citation_ids: Sequence[str] | None,
) -> str:
    ids = list(displayed_citation_ids or [])
    return CITATION_CLAIM_PROMPT_TEMPLATE.format(
        question=question or "",
        generated_answer=generated_answer or "",
        retrieved_context=retrieved_context or "(no retrieved evidence recorded)",
        displayed_citation_ids=json.dumps(ids, ensure_ascii=False) if ids else "[] (empty)",
    )


@dataclass(frozen=True)
class ParsedClaim:
    """One validated claim from one judge's response."""

    claim_id: str
    text: str
    requires_citation: bool
    claim_support: str | None
    supporting_displayed_ids: tuple[str, ...]


@dataclass(frozen=True)
class CitationClaimJudgeResponse:
    """One judge's fully validated claim extraction for one case."""

    claims: tuple[ParsedClaim, ...]
    raw: dict[str, Any]


def _validate_claim(
    raw_claim: Any, *, index: int, slot: str, displayed_ids: frozenset[str]
) -> ParsedClaim:
    loc = f"{slot} judge claims[{index}]"
    if not isinstance(raw_claim, Mapping):
        raise QaCitationMetricError(f"{loc} must be an object.")

    claim_id = raw_claim.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise QaCitationMetricError(f"{loc}: claim_id must be a non-empty string.")

    text = raw_claim.get("text")
    if not isinstance(text, str) or not text.strip():
        raise QaCitationMetricError(f"{loc} (claim_id={claim_id!r}): text must be a non-empty string.")

    requires_citation = raw_claim.get("requires_citation")
    if not isinstance(requires_citation, bool):
        raise QaCitationMetricError(
            f"{loc} (claim_id={claim_id!r}): requires_citation must be a boolean, "
            f"got {requires_citation!r}."
        )

    claim_support = raw_claim.get("claim_support")
    supporting_raw = raw_claim.get("supporting_displayed_ids")

    if not requires_citation:
        if claim_support is not None:
            raise QaCitationMetricError(
                f"{loc} (claim_id={claim_id!r}): claim_support must be null when "
                "requires_citation is false."
            )
        if supporting_raw not in (None, []):
            raise QaCitationMetricError(
                f"{loc} (claim_id={claim_id!r}): supporting_displayed_ids must be empty "
                "or omitted when requires_citation is false."
            )
        return ParsedClaim(
            claim_id=claim_id,
            text=text,
            requires_citation=False,
            claim_support=None,
            supporting_displayed_ids=(),
        )

    if claim_support not in CLAIM_STATUSES:
        raise QaCitationMetricError(
            f"{loc} (claim_id={claim_id!r}): claim_support must be one of "
            f"{sorted(CLAIM_STATUSES)!r} when requires_citation is true, got {claim_support!r}."
        )

    if not isinstance(supporting_raw, (list, tuple)):
        raise QaCitationMetricError(
            f"{loc} (claim_id={claim_id!r}): supporting_displayed_ids must be a list "
            "when requires_citation is true (it may be empty for unsupported/"
            f"not_assessable), got {type(supporting_raw).__name__}."
        )
    supporting_ids: list[str] = []
    for position, item in enumerate(supporting_raw):
        if not isinstance(item, str) or not item.strip():
            raise QaCitationMetricError(
                f"{loc} (claim_id={claim_id!r}): supporting_displayed_ids[{position}] "
                "must be a non-empty string."
            )
        if item not in displayed_ids:
            raise QaCitationMetricError(
                f"{loc} (claim_id={claim_id!r}): supporting_displayed_ids references "
                f"{item!r}, which is not in this case's displayed_citation_ids. "
                "Citations are never invented."
            )
        supporting_ids.append(item)

    if claim_support == CLAIM_STATUS_SUPPORTED and not supporting_ids:
        raise QaCitationMetricError(
            f"{loc} (claim_id={claim_id!r}): a supported claim must list at least one "
            "supporting_displayed_ids entry."
        )
    if claim_support != CLAIM_STATUS_SUPPORTED and supporting_ids:
        raise QaCitationMetricError(
            f"{loc} (claim_id={claim_id!r}): only a supported claim may list "
            f"supporting_displayed_ids; claim_support={claim_support!r} must have none."
        )

    return ParsedClaim(
        claim_id=claim_id,
        text=text,
        requires_citation=True,
        claim_support=claim_support,
        supporting_displayed_ids=tuple(supporting_ids),
    )


def validate_citation_claim_response(
    raw: str | Mapping[str, Any],
    *,
    slot: str,
    displayed_citation_ids: Sequence[str],
) -> CitationClaimJudgeResponse:
    """Full Phase 5 validation: JSON structure, ``evaluation_status``, and every
    claim's shape -- including that ``supporting_displayed_ids`` only ever
    references this case's actual ``displayed_citation_ids``. Raises
    QaCitationMetricError naming the exact problem on any failure. Never
    silently defaults, drops, or invents a claim or a citation id.
    """
    parsed = parse_judge_response_json(raw)

    status = parsed.get("evaluation_status")
    if status != "evaluated":
        raise QaCitationMetricError(
            f"{slot} judge evaluation_status must be 'evaluated', got {status!r}. "
            "Missing judges are rejected, not replaced."
        )

    raw_claims = parsed.get("claims")
    if not isinstance(raw_claims, list):
        raise QaCitationMetricError(f"{slot} judge response is missing a 'claims' list.")

    displayed_ids_set = frozenset(str(value) for value in displayed_citation_ids)
    claims: list[ParsedClaim] = []
    seen_claim_ids: set[str] = set()
    for index, raw_claim in enumerate(raw_claims):
        claim = _validate_claim(
            raw_claim, index=index, slot=slot, displayed_ids=displayed_ids_set
        )
        if claim.claim_id in seen_claim_ids:
            raise QaCitationMetricError(
                f"{slot} judge response has duplicate claim_id {claim.claim_id!r}. "
                "Claims are not silently merged."
            )
        seen_claim_ids.add(claim.claim_id)
        claims.append(claim)

    return CitationClaimJudgeResponse(claims=tuple(claims), raw=dict(parsed))


def build_citation_claim_judge_call_payload(
    raw: str | Mapping[str, Any],
    *,
    slot: str,
    displayed_citation_ids: Sequence[str],
) -> dict[str, Any]:
    """What a ``CitationClaimJudgeAdapter`` returns from one call.

    On success: ``evaluation_status: "evaluated"`` plus every validated claim
    as a plain dict (so this is JSON-round-trippable, matching the other two
    rubrics' adapter payload shape). On ANY validation failure: ``evaluation_
    status: "invalid_response"`` and no claims -- the orchestration below
    checks this status directly, the same pattern Phase 4 established for a
    rubric with no existing Phase 2 function to route malformed responses
    through.
    """
    try:
        payload = validate_citation_claim_response(
            raw, slot=slot, displayed_citation_ids=displayed_citation_ids
        )
    except QaCitationMetricError as exc:
        return {"evaluation_status": "invalid_response", "validation_error": str(exc)}

    return {
        "evaluation_status": "evaluated",
        "claims": [
            {
                "claim_id": claim.claim_id,
                "text": claim.text,
                "requires_citation": claim.requires_citation,
                "claim_support": claim.claim_support,
                "supporting_displayed_ids": list(claim.supporting_displayed_ids),
            }
            for claim in payload.claims
        ],
    }


def resolve_citation_validity(
    *,
    displayed_citation_ids: Sequence[str],
) -> dict[str, str]:
    """Resolve each unique displayed citation id against the locked 691-chunk
    extract (``qa_citation_dataset.load_locked_extract_index`` -- the same
    cached, pure lookup Stage 2 already built; no new corpus-reading code).
    This is the ONLY source of document/chunk identity this function
    consults.

    "valid": the id's exact ``document_id::chunk_index`` compound key exists
      in the locked extract.
    "unresolved": the id is malformed (doesn't parse, or doesn't match any
      key), or well-formed but does not exist in the locked extract --
      nonexistent document, nonexistent chunk index within an otherwise-real
      document, or any other non-existence case. A plain dict lookup
      already covers all of these: a malformed or nonexistent string simply
      is not a key, with no special-casing needed.

    Stage 3.6 fix -- read before changing this function again
    --------------------------------------------------------------------
    A prior version of this function ALSO cross-checked the capture
    record's own ``source_metadata.document_id`` against the locked
    extract's ``document_id`` for the same chunk, treating a mismatch as a
    third status, "wrong_document". That comparison was a confirmed
    defect, not a real citation-integrity signal: ``source_metadata.
    document_id`` is populated by production code from the application's
    own Document-table UUID (a presentation-layer identifier, e.g. used to
    build a "view original document" link) -- a completely different
    namespace from the document_id embedded in a Chroma chunk_id, which is
    assigned at ingestion time. Confirmed empirically against the Stage
    3.4 capture's real data: 64/64 displayed citations with source_
    metadata had a ``source_metadata.document_id`` that differed from
    their own chunk-embedded document_id (0/64 agreed), while the extract's
    own ``ExtractChunkRecord.document_id`` field is -- by construction,
    see ``load_locked_extract_index`` -- always parsed FROM the chunk_id
    itself, never an independently-sourced value. There is therefore no
    genuinely separate "wrong document" signal derivable from the locked
    extract alone: comparing it to ``source_metadata`` was comparing two
    unrelated UUID namespaces, which is why the old check spuriously
    flagged 100% of real, correctly-cited chunks as invalid. Do not
    reintroduce a ``source_metadata``-based comparison here; if a genuine
    document-mislabeling check is ever wanted, it needs a canonical,
    same-namespace source for both sides of the comparison, which does not
    currently exist.
    """
    extract_index = load_locked_extract_index()
    validity: dict[str, str] = {}
    for citation_id in unique_preserve_order([str(value) for value in displayed_citation_ids]):
        record = extract_index.by_chunk_id.get(citation_id)
        validity[citation_id] = (
            CITATION_VALIDITY_VALID if record is not None else CITATION_VALIDITY_UNRESOLVED
        )
    return validity


ResponseFn = Callable[[str], "str | Mapping[str, Any]"]


class CitationClaimJudgeAdapter:
    """Injectable adapter for citation-claim judging, mirroring
    ``qa_citation_judge_prompt.JudgeAdapter`` and
    ``qa_citation_insufficient_evidence.InsufficientEvidenceJudgeAdapter``
    exactly in shape (same constructor pattern, same
    ``identity``/``model_identity`` surface so ``build_judge_pair`` works
    unmodified on any of the three rubrics' adapters). No real HTTP/LLM call
    exists anywhere in this class -- ``response_fn`` is caller-supplied.
    """

    def __init__(
        self,
        *,
        model: str,
        provider: str,
        dataset: QaCitationDataset,
        response_fn: ResponseFn,
        slot_name: str = "judge",
        prompt_version: str = CITATION_CLAIM_PROMPT_VERSION,
    ) -> None:
        self.identity = JudgeIdentity(model=model, provider=provider)
        self._cases_by_id: dict[str, QaCitationCase] = {
            case.case_id: case for case in dataset.cases
        }
        self._response_fn = response_fn
        self.slot_name = slot_name
        self.prompt_version = prompt_version
        self.prompt_sha256 = citation_claim_prompt_sha256()

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
        displayed_citation_ids = list(record.get("displayed_citation_ids") or [])
        prompt = build_citation_claim_prompt(
            question=case.question,
            generated_answer=record.get("generated_answer"),
            retrieved_context=record.get("retrieved_context"),
            displayed_citation_ids=displayed_citation_ids,
        )
        raw = self._response_fn(prompt)  # may raise; propagates to orchestration unchanged
        payload = build_citation_claim_judge_call_payload(
            raw, slot=self.slot_name, displayed_citation_ids=displayed_citation_ids
        )
        payload["_judge_model"] = self.identity.model
        payload["_judge_provider"] = self.identity.provider
        payload["_judge_prompt_version"] = self.prompt_version
        payload["_judge_prompt_sha256"] = self.prompt_sha256
        return payload


# Re-exported so callers only need this module for the citation-claim path;
# identical function, not reimplemented.
build_citation_claim_judge_pair = build_judge_pair


JudgeCallFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]


@dataclass(frozen=True)
class CitationClaimJudgeSlotOutcome:
    """One judge slot's result for one case's citation-claim judging."""

    judge_execution_status: str
    raw_response: Mapping[str, Any] | None
    parsed: CitationClaimJudgeResponse | None = None
    citation_metrics: CitationMetrics | None = None
    error_detail: str | None = None

    @property
    def evaluated(self) -> bool:
        return self.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED


@dataclass(frozen=True)
class CitationClaimOutcome:
    """The full, per-case Phase 5 Part A result. Exactly one of these is
    produced per input capture record -- whether excluded, partially/totally
    failed, or judged. When judged, BOTH judges' independently-extracted
    claims and independently-computed ``CitationMetrics`` are preserved --
    neither is discarded in favor of the other."""

    case_id: str
    final_status: str
    eligibility_verdict: EligibilityVerdict
    citation_validity_by_id: dict[str, str]
    primary_judge: CitationClaimJudgeSlotOutcome | None
    secondary_judge: CitationClaimJudgeSlotOutcome | None


class QaCitationClaimJudgingError(ValueError):
    """Malformed orchestration input (not a judge-call failure)."""


def _claim_metric_inputs(claims: Sequence[ParsedClaim]) -> tuple[ClaimMetricInput, ...]:
    return tuple(
        ClaimMetricInput(
            claim_id=claim.claim_id,
            requires_citation=claim.requires_citation,
            claim_support=claim.claim_support,
            supporting_displayed_ids=claim.supporting_displayed_ids,
        )
        for claim in claims
    )


def _call_citation_claim_judge_slot(
    record: Mapping[str, Any],
    judge_fn: JudgeCallFn,
    *,
    slot: str,
    displayed_citation_ids: Sequence[str],
    citation_validity_by_id: Mapping[str, str],
) -> CitationClaimJudgeSlotOutcome:
    try:
        response = judge_fn(record)
    except JudgeTimeoutError as exc:
        return CitationClaimJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_TIMEOUT,
            raw_response=None,
            error_detail=str(exc) or "judge call timed out",
        )
    except JudgeCallError as exc:
        return CitationClaimJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or "judge call failed",
        )
    except Exception as exc:  # pragma: no cover - defensive safety net, mirrors Phase 2/4
        return CitationClaimJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_ERROR,
            raw_response=None,
            error_detail=str(exc) or f"unexpected {type(exc).__name__}",
        )

    try:
        parsed = validate_citation_claim_response(
            response, slot=slot, displayed_citation_ids=displayed_citation_ids
        )
    except QaCitationMetricError as exc:
        raw_for_record = response if isinstance(response, Mapping) else None
        return CitationClaimJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_MALFORMED,
            raw_response=raw_for_record,
            error_detail=str(exc),
        )

    try:
        metrics = compute_citation_metrics(
            displayed_citation_ids=displayed_citation_ids,
            claims=_claim_metric_inputs(parsed.claims),
            citation_validity_by_id=citation_validity_by_id,
        )
    except QaCitationMetricError as exc:
        # A validated-per-claim response can still fail compute_citation_
        # metrics' own cross-claim invariants (e.g. a duplicate claim_id
        # this module's own check also catches, defensively reused here as
        # the authoritative math). Treated the same as any other malformed
        # response -- never silently scored with partial/invented data.
        return CitationClaimJudgeSlotOutcome(
            judge_execution_status=JUDGE_EXECUTION_STATUS_MALFORMED,
            raw_response=response if isinstance(response, Mapping) else None,
            parsed=parsed,
            error_detail=str(exc),
        )

    return CitationClaimJudgeSlotOutcome(
        judge_execution_status=JUDGE_EXECUTION_STATUS_EVALUATED,
        raw_response=response,
        parsed=parsed,
        citation_metrics=metrics,
    )


def judge_citation_claims_case(
    record: Mapping[str, Any],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> CitationClaimOutcome:
    """Run Phase 1 eligibility first; only call judges for an eligible
    record. Mirrors every other Stage 3.2B rubric's combination rule:
    both evaluated -> ``judged`` (both judges' CitationMetrics preserved,
    neither discarded); exactly one evaluated -> ``judging_failed_partial``
    (no citation outcome is reported for the case); neither -> ``judging_
    failed_total``. No automatic retries.

    Generic over any eligible record -- it does not itself check dataset
    ``case_type``. Like Phase 2 (QA) and Phase 4 (insufficient-evidence),
    which records get routed here versus to the insufficient-evidence
    rubric is the top-level run orchestrator's decision (Part B), not this
    module's.
    """
    verdict = classify_eligibility(record)

    if not verdict.eligible:
        final_status = (
            JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
            if verdict.exclusion_reason == EXCLUSION_REFUSAL_NOT_QA_SCORED
            else JUDGING_STATUS_EXCLUDED_INELIGIBLE
        )
        return CitationClaimOutcome(
            case_id=verdict.case_id,
            final_status=final_status,
            eligibility_verdict=verdict,
            citation_validity_by_id={},
            primary_judge=None,
            secondary_judge=None,
        )

    displayed_citation_ids = list(record.get("displayed_citation_ids") or [])
    citation_validity_by_id = resolve_citation_validity(
        displayed_citation_ids=displayed_citation_ids
    )

    primary_outcome = _call_citation_claim_judge_slot(
        record,
        primary_judge,
        slot="primary",
        displayed_citation_ids=displayed_citation_ids,
        citation_validity_by_id=citation_validity_by_id,
    )
    secondary_outcome = _call_citation_claim_judge_slot(
        record,
        secondary_judge,
        slot="secondary",
        displayed_citation_ids=displayed_citation_ids,
        citation_validity_by_id=citation_validity_by_id,
    )

    if primary_outcome.evaluated and secondary_outcome.evaluated:
        final_status = JUDGING_STATUS_JUDGED
    elif primary_outcome.evaluated or secondary_outcome.evaluated:
        final_status = JUDGING_STATUS_FAILED_PARTIAL
    else:
        final_status = JUDGING_STATUS_FAILED_TOTAL

    return CitationClaimOutcome(
        case_id=verdict.case_id,
        final_status=final_status,
        eligibility_verdict=verdict,
        citation_validity_by_id=citation_validity_by_id,
        primary_judge=primary_outcome,
        secondary_judge=secondary_outcome,
    )


def judge_citation_claims_cases(
    records: Sequence[Mapping[str, Any]],
    *,
    primary_judge: JudgeCallFn,
    secondary_judge: JudgeCallFn,
) -> list[CitationClaimOutcome]:
    """Run ``judge_citation_claims_case`` over every record. One output per
    input; no case is dropped. Duplicate case_ids raise rather than
    overwrite."""
    outcomes: list[CitationClaimOutcome] = []
    seen_case_ids: set[str] = set()
    for record in records:
        outcome = judge_citation_claims_case(
            record, primary_judge=primary_judge, secondary_judge=secondary_judge
        )
        if outcome.case_id in seen_case_ids:
            raise QaCitationClaimJudgingError(
                f"Duplicate case_id {outcome.case_id!r} in citation-claim judging input."
            )
        seen_case_ids.add(outcome.case_id)
        outcomes.append(outcome)
    return outcomes
