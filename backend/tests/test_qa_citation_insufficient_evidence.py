"""Stage 3.2B Phase 4 tests: the separate insufficient-evidence rubric.

All judge "calls" here are local Python fakes (strings/dicts/exceptions).
No real HTTP/LLM call is made anywhere in this file.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.services.evaluation.qa_citation_dataset import (
    CorpusSnapshot,
    QaCitationCase,
    QaCitationDataset,
)
from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_FALLBACK_NOT_GENUINE,
    EXCLUSION_FIELD_MISSING,
)
from app.services.evaluation.qa_citation_insufficient_evidence import (
    INSUFFICIENT_EVIDENCE_PROMPT_TEMPLATE,
    INSUFFICIENT_EVIDENCE_PROMPT_VERSION,
    InsufficientEvidenceJudgeAdapter,
    QaCitationInsufficientEvidenceError,
    build_insufficient_evidence_judge_call_payload,
    build_insufficient_evidence_prompt,
    build_insufficient_evidence_judge_pair,
    insufficient_evidence_prompt_sha256,
    judge_insufficient_evidence_case,
    judge_insufficient_evidence_cases,
    summarize_insufficient_evidence_outcomes,
    validate_insufficient_evidence_response,
)
from app.services.evaluation.qa_citation_judge_prompt import DuplicateJudgeModelError
from app.services.evaluation.qa_citation_judging import JudgeCallError, JudgeTimeoutError
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


def _case(case_id: str = "qac_033_wifi_password") -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question="What is the LSPU student Wi-Fi password?",
        category="IT Services",
        difficulty="insufficient_evidence",
        case_type="insufficient_evidence",
        labeling_status="labeled",
        reference_answer=None,
        supporting_document_ids=(),
        supporting_chunk_ids=(),
        reference_evidence=(),
        generation_model="n/a",
        generation_prompt_version="n/a",
    )


def _dataset(cases: tuple[QaCitationCase, ...]) -> QaCitationDataset:
    corpus = CorpusSnapshot(
        path="backend/data/chroma_evaluation",
        collection="aska_evaluation",
        expected_chunk_count=691,
        extract_artifact="backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json",
        identity_digest="fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b",
        metadata_text_digest="7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7",
        source_path_as_recorded="backend/data/chroma/chroma.sqlite3",
        source_collection_as_recorded="aska_knowledge_base",
    )
    return QaCitationDataset(
        dataset_version="test-fixture-v1",
        experiment_family="qa_citation_v1",
        annotation_method="ai_assisted_grounded_generation",
        judge_source_for_later_scoring="ai_evaluator",
        corpus=corpus,
        generation_model="n/a",
        generation_prompt_version="n/a",
        labeled_cases=cases,
        unlabeled_cases=(),
        unlabeled_count=0,
        total_count=len(cases),
        cases=cases,
        dataset_json_sha256="0" * 64,
        source_path="fixture.json",
    )


def _base_record(**overrides) -> dict:
    record = {
        "case_id": "qac_033_wifi_password",
        "execution_status": "ok",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "case_type": "insufficient_evidence",
        "generated_answer": "I don't have that specific information in the knowledge base.",
        "retrieved_context": "(no directly relevant passages were retrieved)",
        "displayed_citation_ids": [],
    }
    record.update(overrides)
    return record


def _dimension(
    *, result: bool, explanation: str = "Because of the evidence.", excerpt: str = "excerpt", ref: str = "ref"
) -> dict[str, Any]:
    return {
        "result": result,
        "explanation": explanation,
        "answer_excerpts": [excerpt],
        "evidence_refs": [ref],
    }


def _good_response(
    *, correctly_declined: bool = True, unsupported_claim_detected: bool = False, **overrides
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "evaluation_status": "evaluated",
        "correctly_declined": _dimension(result=correctly_declined),
        "unsupported_claim_detected": _dimension(result=unsupported_claim_detected),
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
# Prompt construction
# ---------------------------------------------------------------------------


def test_prompt_mentions_not_assuming_empty_citations_means_unsupported():
    prompt = build_insufficient_evidence_prompt(
        question="q",
        generated_answer="a",
        retrieved_context="evidence text",
        displayed_citation_ids=[],
    )
    assert "does NOT by itself mean the answer is unsupported" in prompt
    assert "evidence text" in prompt


def test_prompt_sha256_is_stable_and_matches_template():
    import hashlib

    expected = hashlib.sha256(INSUFFICIENT_EVIDENCE_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
    assert insufficient_evidence_prompt_sha256() == expected
    assert INSUFFICIENT_EVIDENCE_PROMPT_VERSION  # non-empty version string


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------


def test_valid_response_parses_both_dimensions_independently():
    payload = validate_insufficient_evidence_response(
        _good_response(correctly_declined=True, unsupported_claim_detected=True), slot="primary"
    )
    # Independent dimensions: both True is a valid, expected combination
    # (declined, but still slipped in an unsupported claim).
    assert payload.correctly_declined.result is True
    assert payload.unsupported_claim_detected.result is True
    assert payload.correctly_declined.explanation
    assert payload.correctly_declined.answer_excerpts
    assert payload.correctly_declined.evidence_refs


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update({"evaluation_status": "not_evaluated"}),
        lambda r: r["correctly_declined"].pop("result"),
        lambda r: r["correctly_declined"].update({"result": "true"}),  # string, not bool
        lambda r: r["correctly_declined"].update({"result": 1}),  # int, not bool
        lambda r: r["correctly_declined"].pop("explanation"),
        lambda r: r["correctly_declined"].update({"explanation": "   "}),
        lambda r: r["correctly_declined"].pop("answer_excerpts"),
        lambda r: r["correctly_declined"].update({"answer_excerpts": []}),
        lambda r: r["correctly_declined"].pop("evidence_refs"),
        lambda r: r["correctly_declined"].update({"evidence_refs": []}),
        lambda r: r.pop("unsupported_claim_detected"),
        lambda r: r["unsupported_claim_detected"].pop("evidence_refs"),
    ],
)
def test_malformed_or_missing_fields_raise(mutate):
    response = _good_response()
    mutate(response)
    with pytest.raises(QaCitationMetricError):
        validate_insufficient_evidence_response(response, slot="primary")


def test_invalid_json_string_raises():
    with pytest.raises(QaCitationMetricError):
        validate_insufficient_evidence_response("{not json", slot="primary")


def test_build_judge_call_payload_success_and_failure():
    ok = build_insufficient_evidence_judge_call_payload(_good_response(), slot="primary")
    assert ok["evaluation_status"] == "evaluated"
    assert ok["correctly_declined"]["result"] is True

    bad = dict(_good_response())
    del bad["correctly_declined"]
    invalid = build_insufficient_evidence_judge_call_payload(bad, slot="primary")
    assert invalid["evaluation_status"] == "invalid_response"
    assert "validation_error" in invalid


# ---------------------------------------------------------------------------
# Orchestration: success
# ---------------------------------------------------------------------------


def test_correct_refusal_both_judges_agree():
    response = _good_response(correctly_declined=True, unsupported_claim_detected=False)
    outcome = judge_insufficient_evidence_case(
        _base_record(),
        primary_judge=_fixed_judge(response),
        secondary_judge=_fixed_judge(response),
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.result is not None
    assert outcome.result.correctly_declined_agreement is True
    assert outcome.result.unsupported_claim_detected_agreement is True
    assert outcome.result.primary.correctly_declined.result is True
    assert outcome.result.primary.unsupported_claim_detected.result is False


def test_unsupported_claim_despite_refusal_language_both_true_is_allowed():
    """Independent dimensions: declined AND still made an unsupported claim."""
    response = _good_response(correctly_declined=True, unsupported_claim_detected=True)
    outcome = judge_insufficient_evidence_case(
        _base_record(
            generated_answer=(
                "I don't have that information, but it is typically a simple default password."
            )
        ),
        primary_judge=_fixed_judge(response),
        secondary_judge=_fixed_judge(response),
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.result.primary.correctly_declined.result is True
    assert outcome.result.primary.unsupported_claim_detected.result is True


def test_confident_unsupported_answer():
    response = _good_response(correctly_declined=False, unsupported_claim_detected=True)
    outcome = judge_insufficient_evidence_case(
        _base_record(generated_answer="The Wi-Fi password is LSPU2024!"),
        primary_judge=_fixed_judge(response),
        secondary_judge=_fixed_judge(response),
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.result.primary.correctly_declined.result is False
    assert outcome.result.primary.unsupported_claim_detected.result is True


def test_disagreement_reported_per_dimension():
    primary_response = _good_response(correctly_declined=True, unsupported_claim_detected=False)
    secondary_response = _good_response(correctly_declined=False, unsupported_claim_detected=True)

    outcome = judge_insufficient_evidence_case(
        _base_record(),
        primary_judge=_fixed_judge(primary_response),
        secondary_judge=_fixed_judge(secondary_response),
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.result.correctly_declined_agreement is False
    assert outcome.result.unsupported_claim_detected_agreement is False
    # Both judges' individual verdicts are preserved, not collapsed.
    assert outcome.result.primary.correctly_declined.result is True
    assert outcome.result.secondary.correctly_declined.result is False


# ---------------------------------------------------------------------------
# Eligibility exclusions
# ---------------------------------------------------------------------------


def test_empty_answer_excluded_before_any_judge_call():
    calls: list[str] = []

    def _tracking_judge(_record):
        calls.append("called")
        return _good_response()

    record = _base_record(generated_answer="   ")
    outcome = judge_insufficient_evidence_case(
        record, primary_judge=_tracking_judge, secondary_judge=_tracking_judge
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.result is None
    assert calls == []


def test_ineligible_fallback_record_shaped_like_qac_033_never_calls_a_judge():
    """Regression test: this is the real shape of the actual failed capture
    run's qac_033_wifi_password record (fallback_reason=generation_error,
    is_genuine_model_output=False), which must never reach a judge."""
    calls: list[str] = []

    def _tracking_judge(_record):
        calls.append("called")
        return _good_response()

    record = _base_record(
        is_genuine_model_output=False,
        fallback_used=True,
        generated_answer=(
            "Cyber bullying or bullying Suspension Suspension Expulsion: done "
            "through the use of technology..."
        ),
    )

    outcome = judge_insufficient_evidence_case(
        record, primary_judge=_tracking_judge, secondary_judge=_tracking_judge
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.eligibility_verdict.exclusion_reason == EXCLUSION_FALLBACK_NOT_GENUINE
    assert outcome.result is None
    assert calls == []


def test_missing_eligibility_fields_fail_closed():
    record = _base_record()
    del record["fallback_used"]

    outcome = judge_insufficient_evidence_case(
        record,
        primary_judge=_fixed_judge(_good_response()),
        secondary_judge=_fixed_judge(_good_response()),
    )

    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.eligibility_verdict.exclusion_reason == EXCLUSION_FIELD_MISSING


def test_refusal_execution_status_excluded_not_applicable():
    record = _base_record(execution_status="oos_or_refusal")
    outcome = judge_insufficient_evidence_case(
        record,
        primary_judge=_fixed_judge(_good_response()),
        secondary_judge=_fixed_judge(_good_response()),
    )
    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Judge failures
# ---------------------------------------------------------------------------


def test_one_judge_timeout_is_partial_failure_no_combined_result():
    outcome = judge_insufficient_evidence_case(
        _base_record(),
        primary_judge=_fixed_judge(_good_response()),
        secondary_judge=_raising_judge(JudgeTimeoutError("slow provider")),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT
    assert outcome.result is None  # never promote a single judge to a final result


def test_one_judge_malformed_is_partial_failure():
    malformed = dict(_good_response())
    del malformed["unsupported_claim_detected"]

    outcome = judge_insufficient_evidence_case(
        _base_record(),
        primary_judge=_fixed_judge(malformed),
        secondary_judge=_fixed_judge(_good_response()),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED
    assert outcome.result is None


def test_both_judges_fail_two_distinct_modes_is_total_failure():
    outcome = judge_insufficient_evidence_case(
        _base_record(),
        primary_judge=_raising_judge(JudgeCallError("401 Unauthorized")),
        secondary_judge=_raising_judge(JudgeTimeoutError("no response")),
    )

    assert outcome.final_status == JUDGING_STATUS_FAILED_TOTAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT
    assert outcome.result is None


# ---------------------------------------------------------------------------
# Distinct judge model identity enforcement (reused from Phase 3, unmodified)
# ---------------------------------------------------------------------------


def test_distinct_judge_identities_enforced_via_phase3_build_judge_pair():
    dataset = _dataset((_case(),))

    def _responder(_prompt: str) -> dict:
        return _good_response()

    primary = InsufficientEvidenceJudgeAdapter(
        model="same-model", provider="provider-x", dataset=dataset, response_fn=_responder
    )
    secondary = InsufficientEvidenceJudgeAdapter(
        model="same-model", provider="provider-y", dataset=dataset, response_fn=_responder
    )

    with pytest.raises(DuplicateJudgeModelError):
        build_insufficient_evidence_judge_pair(primary=primary, secondary=secondary)


def test_distinct_models_same_provider_allowed():
    dataset = _dataset((_case(),))

    def _responder(_prompt: str) -> dict:
        return _good_response()

    primary = InsufficientEvidenceJudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=_responder
    )
    secondary = InsufficientEvidenceJudgeAdapter(
        model="model-b", provider="provider-x", dataset=dataset, response_fn=_responder
    )

    build_insufficient_evidence_judge_pair(primary=primary, secondary=secondary)  # no raise


def test_adapter_end_to_end_builds_prompt_and_judges(monkeypatch):
    dataset = _dataset((_case(),))
    seen_prompts: list[str] = []

    def _responder(prompt: str) -> dict:
        seen_prompts.append(prompt)
        return _good_response(correctly_declined=True, unsupported_claim_detected=False)

    primary = InsufficientEvidenceJudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=_responder, slot_name="primary"
    )
    secondary = InsufficientEvidenceJudgeAdapter(
        model="model-b", provider="provider-y", dataset=dataset, response_fn=_responder, slot_name="secondary"
    )

    outcome = judge_insufficient_evidence_case(
        _base_record(), primary_judge=primary, secondary_judge=secondary
    )

    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert len(seen_prompts) == 2
    assert "Wi-Fi password" in seen_prompts[0]


# ---------------------------------------------------------------------------
# Full batch + aggregation
# ---------------------------------------------------------------------------


def test_full_batch_aggregate_counts_and_no_case_dropped():
    records = [
        _base_record(case_id="c_judged"),
        _base_record(
            case_id="c_ineligible", is_genuine_model_output=False, fallback_used=True,
            generated_answer="fallback text",
        ),
        _base_record(case_id="c_refusal", execution_status="oos_or_refusal"),
        _base_record(case_id="c_partial"),
        _base_record(case_id="c_total"),
        _base_record(case_id="c_disagree"),
    ]

    def primary_judge(record: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = record["case_id"]
        if case_id == "c_total":
            raise JudgeTimeoutError("timed out")
        if case_id == "c_disagree":
            return _good_response(correctly_declined=True, unsupported_claim_detected=False)
        return _good_response(correctly_declined=True, unsupported_claim_detected=False)

    def secondary_judge(record: Mapping[str, Any]) -> Mapping[str, Any]:
        case_id = record["case_id"]
        if case_id == "c_partial":
            raise JudgeCallError("auth failed")
        if case_id == "c_total":
            raise JudgeCallError("auth failed")
        if case_id == "c_disagree":
            return _good_response(correctly_declined=False, unsupported_claim_detected=True)
        return _good_response(correctly_declined=True, unsupported_claim_detected=False)

    outcomes = judge_insufficient_evidence_cases(
        records, primary_judge=primary_judge, secondary_judge=secondary_judge
    )

    assert len(outcomes) == 6  # one output per input, nothing dropped
    by_case = {outcome.case_id: outcome for outcome in outcomes}
    assert by_case["c_judged"].final_status == JUDGING_STATUS_JUDGED
    assert by_case["c_ineligible"].final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert by_case["c_refusal"].final_status == JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE
    assert by_case["c_partial"].final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert by_case["c_total"].final_status == JUDGING_STATUS_FAILED_TOTAL
    assert by_case["c_disagree"].final_status == JUDGING_STATUS_JUDGED
    assert by_case["c_disagree"].result.correctly_declined_agreement is False

    aggregation = summarize_insufficient_evidence_outcomes(outcomes)
    assert aggregation.total_count == 6
    assert aggregation.excluded_count == 2  # c_ineligible (fallback) + c_refusal (not applicable)
    assert aggregation.eligible_count == 4
    assert aggregation.exclusion_counts_by_reason == {
        EXCLUSION_FALLBACK_NOT_GENUINE: 1,
        "refusal_not_qa_scored": 1,
    }
    assert aggregation.judged_count == 2  # c_judged, c_disagree
    assert aggregation.judging_failed_partial_count == 1
    assert aggregation.judging_failed_total_count == 1
    assert aggregation.correctly_declined_agreement_count == 1  # c_judged
    assert aggregation.correctly_declined_disagreement_count == 1  # c_disagree
    assert aggregation.unsupported_claim_detected_agreement_count == 1
    assert aggregation.unsupported_claim_detected_disagreement_count == 1


def test_duplicate_case_id_raises_rather_than_silently_merging():
    records = [_base_record(case_id="dup"), _base_record(case_id="dup")]
    with pytest.raises(QaCitationInsufficientEvidenceError):
        judge_insufficient_evidence_cases(
            records,
            primary_judge=_fixed_judge(_good_response()),
            secondary_judge=_fixed_judge(_good_response()),
        )
