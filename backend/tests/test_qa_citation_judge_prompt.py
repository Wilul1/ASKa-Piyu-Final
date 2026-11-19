"""Stage 3.2B Phase 3 tests: judge prompt construction, structured response
parsing/validation, and the injectable judge-call adapter.

All judge "calls" here are local Python fakes (strings/dicts/exceptions).
No real HTTP/LLM call is made anywhere in this file.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import pytest

from app.services.evaluation.qa_citation_dataset import (
    CorpusSnapshot,
    QaCitationCase,
    QaCitationDataset,
)
from app.services.evaluation.qa_citation_judge_prompt import (
    JUDGE_PROMPT_TEMPLATE,
    JUDGE_PROMPT_VERSION,
    DuplicateJudgeModelError,
    JudgeAdapter,
    QaCitationJudgePromptError,
    build_judge_call_payload,
    build_judge_pair,
    build_judge_prompt,
    judge_prompt_sha256,
    validate_judge_response,
)
from app.services.evaluation.qa_citation_judging import (
    JudgeCallError,
    JudgeTimeoutError,
    judge_eligible_case,
)
from app.services.evaluation.qa_citation_metrics import (
    JUDGE_EXECUTION_STATUS_ERROR,
    JUDGE_EXECUTION_STATUS_EVALUATED,
    JUDGE_EXECUTION_STATUS_MALFORMED,
    JUDGE_EXECUTION_STATUS_TIMEOUT,
    JUDGING_STATUS_FAILED_PARTIAL,
    JUDGING_STATUS_FAILED_TOTAL,
    JUDGING_STATUS_JUDGED,
    QaCitationMetricError,
)


def _case(case_id: str = "qac_001_tor_fee", reference_answer: str | None = "P75/page.") -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question="How much is the TOR fee?",
        category="Fees",
        difficulty="easy",
        case_type="labeled_student_support",
        labeling_status="labeled",
        reference_answer=reference_answer,
        supporting_document_ids=("doc_1",),
        supporting_chunk_ids=("doc_1::0",),
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


def _good_response_dict(**overrides) -> dict[str, Any]:
    response = {
        "evaluation_status": "evaluated",
        "correctness": 3,
        "completeness": 2,
        "relevance": 4,
        "faithfulness": 3,
        "explanation": {
            "correctness": "Matches the fee.",
            "completeness": "Covers the main point.",
            "relevance": "Answers the question.",
            "faithfulness": "Backed by retrieved text.",
        },
        "faithfulness_evidence_refs": ["doc_1::0"],
    }
    response.update(overrides)
    return response


def _base_record(**overrides) -> dict:
    record = {
        "case_id": "qac_001_tor_fee",
        "execution_status": "ok",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "generated_answer": "The TOR fee is P75.00/page.",
        "retrieved_context": "Undergraduate TOR fee: P75.00/page.",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Prompt design and versioning
# ---------------------------------------------------------------------------


def test_prompt_includes_question_answer_evidence_and_labels_reference_as_not_faithfulness_basis():
    prompt = build_judge_prompt(
        question="How much is the TOR fee?",
        generated_answer="P75/page.",
        retrieved_context="Undergraduate: P75.00/page.",
        reference_answer="P75/page per the Charter.",
    )
    assert "How much is the TOR fee?" in prompt
    assert "P75/page." in prompt
    assert "Undergraduate: P75.00/page." in prompt
    assert "P75/page per the Charter." in prompt
    assert "do NOT use this as the evidence basis for Faithfulness" in prompt
    assert "ONLY a single JSON object" in prompt
    assert "faithfulness_evidence_refs" in prompt


def test_prompt_version_and_hash_are_stable_and_match_template():
    import hashlib

    assert JUDGE_PROMPT_VERSION == "qa_citation_judge_v1"
    expected = hashlib.sha256(JUDGE_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()
    assert judge_prompt_sha256() == expected
    # Stable across repeated calls.
    assert judge_prompt_sha256() == judge_prompt_sha256()


def test_prompt_handles_missing_reference_answer_without_crashing():
    prompt = build_judge_prompt(
        question="q", generated_answer="a", retrieved_context=None, reference_answer=None
    )
    assert "no gold reference answer" in prompt
    assert "no retrieved evidence recorded" in prompt


# ---------------------------------------------------------------------------
# Structured response validation -- validate_judge_response
# ---------------------------------------------------------------------------


def test_valid_response_parses_with_scores_explanations_and_evidence_refs_preserved():
    payload = validate_judge_response(_good_response_dict(), slot="primary")
    assert payload.scores.correctness == 3
    assert payload.scores.faithfulness == 3
    assert payload.explanations["faithfulness"] == "Backed by retrieved text."
    assert payload.faithfulness_evidence_refs == ("doc_1::0",)


def test_valid_response_also_accepts_a_json_string():
    text = json.dumps(_good_response_dict())
    payload = validate_judge_response(text, slot="primary")
    assert payload.scores.relevance == 4


def test_invalid_json_string_rejected():
    with pytest.raises(QaCitationMetricError, match="not valid JSON"):
        validate_judge_response("not json at all {{{", slot="primary")


def test_missing_dimension_rejected():
    bad = _good_response_dict()
    del bad["faithfulness"]
    with pytest.raises(QaCitationMetricError, match="faithfulness"):
        validate_judge_response(bad, slot="primary")


@pytest.mark.parametrize("value", [5, -1, 10])
def test_out_of_range_score_rejected(value):
    bad = _good_response_dict(correctness=value)
    with pytest.raises(QaCitationMetricError):
        validate_judge_response(bad, slot="primary")


@pytest.mark.parametrize("value", ["3", 3.5, True, False])
def test_incorrect_score_type_rejected(value):
    bad = _good_response_dict(correctness=value)
    with pytest.raises(QaCitationMetricError):
        validate_judge_response(bad, slot="primary")


def test_missing_explanation_object_rejected():
    bad = _good_response_dict()
    del bad["explanation"]
    with pytest.raises(QaCitationMetricError, match="explanation"):
        validate_judge_response(bad, slot="primary")


def test_missing_one_explanation_dimension_rejected():
    bad = _good_response_dict()
    del bad["explanation"]["faithfulness"]
    with pytest.raises(QaCitationMetricError, match="faithfulness"):
        validate_judge_response(bad, slot="primary")


def test_blank_explanation_text_rejected():
    bad = _good_response_dict()
    bad["explanation"]["relevance"] = "   "
    with pytest.raises(QaCitationMetricError):
        validate_judge_response(bad, slot="primary")


def test_missing_faithfulness_evidence_refs_rejected_hard_failure():
    bad = _good_response_dict()
    del bad["faithfulness_evidence_refs"]
    with pytest.raises(QaCitationMetricError, match="faithfulness_evidence_refs"):
        validate_judge_response(bad, slot="primary")


def test_empty_faithfulness_evidence_refs_list_rejected():
    bad = _good_response_dict(faithfulness_evidence_refs=[])
    with pytest.raises(QaCitationMetricError, match="faithfulness_evidence_refs"):
        validate_judge_response(bad, slot="primary")


# ---------------------------------------------------------------------------
# build_judge_call_payload -- routes failures into Phase 2's existing
# judge_malformed_response mechanism without a parallel one
# ---------------------------------------------------------------------------


def test_payload_success_sets_evaluated_and_preserves_everything():
    payload = build_judge_call_payload(_good_response_dict(), slot="primary")
    assert payload["evaluation_status"] == "evaluated"
    assert payload["correctness"] == 3
    assert payload["explanation"]["faithfulness"] == "Backed by retrieved text."
    assert payload["faithfulness_evidence_refs"] == ["doc_1::0"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("faithfulness"),
        lambda d: d.update(correctness=9),
        lambda d: d["explanation"].pop("faithfulness"),
        lambda d: d.update(faithfulness_evidence_refs=[]),
    ],
)
def test_payload_failure_sets_non_evaluated_status_so_existing_parser_raises(mutate):
    bad = _good_response_dict()
    mutate(bad)
    payload = build_judge_call_payload(bad, slot="primary")
    assert payload["evaluation_status"] != "evaluated"
    assert "correctness" not in payload  # scores withheld on failed validation
    # Confirm this routes through Phase 2's EXISTING malformed-detection
    # mechanism (qa_citation_metrics._parse_judge_scores), not a new one.
    from app.services.evaluation.qa_citation_metrics import _parse_judge_scores

    with pytest.raises(QaCitationMetricError):
        _parse_judge_scores(payload, slot="primary")


def test_payload_handles_invalid_json_string_the_same_way():
    payload = build_judge_call_payload("{{{not json", slot="primary")
    assert payload["evaluation_status"] == "invalid_response"
    assert "validation_error" in payload


# ---------------------------------------------------------------------------
# JudgeAdapter -- prompt building + identity + end-to-end via Phase 2
# ---------------------------------------------------------------------------


def test_adapter_builds_prompt_from_record_and_dataset_case_then_returns_valid_payload():
    dataset = _dataset((_case(),))
    seen_prompts: list[str] = []

    def fake_llm(prompt: str) -> str:
        seen_prompts.append(prompt)
        return json.dumps(_good_response_dict())

    adapter = JudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=fake_llm
    )
    result = adapter(_base_record())

    assert len(seen_prompts) == 1
    assert "How much is the TOR fee?" in seen_prompts[0]
    assert "The TOR fee is P75.00/page." in seen_prompts[0]
    assert result["evaluation_status"] == "evaluated"
    assert result["_judge_model"] == "model-a"
    assert result["_judge_provider"] == "provider-x"
    assert result["_judge_prompt_version"] == JUDGE_PROMPT_VERSION
    assert result["_judge_prompt_sha256"] == judge_prompt_sha256()


def test_adapter_raises_configuration_error_when_case_id_not_in_dataset():
    dataset = _dataset((_case(case_id="other_case"),))
    adapter = JudgeAdapter(
        model="model-a",
        provider="provider-x",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(_good_response_dict()),
    )
    with pytest.raises(QaCitationJudgePromptError):
        adapter(_base_record(case_id="missing_case"))


def test_provider_auth_failure_propagates_as_judge_call_error_through_phase_2():
    dataset = _dataset((_case(),))

    def auth_fails(_prompt: str) -> str:
        raise JudgeCallError("401 Unauthorized")

    adapter_primary = JudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=auth_fails
    )
    adapter_secondary = JudgeAdapter(
        model="model-b",
        provider="provider-y",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(_good_response_dict()),
    )

    outcome = judge_eligible_case(
        _base_record(), primary_judge=adapter_primary, secondary_judge=adapter_secondary
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED
    assert outcome.qa_result is None


def test_timeout_propagates_through_phase_2():
    dataset = _dataset((_case(),))

    def too_slow(_prompt: str) -> str:
        raise JudgeTimeoutError("provider did not respond in time")

    adapter_primary = JudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=too_slow
    )
    adapter_secondary = JudgeAdapter(
        model="model-b",
        provider="provider-y",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(_good_response_dict()),
    )

    outcome = judge_eligible_case(
        _base_record(), primary_judge=adapter_primary, secondary_judge=adapter_secondary
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT


def test_malformed_response_via_adapter_routes_to_malformed_through_phase_2():
    dataset = _dataset((_case(),))

    def missing_evidence(_prompt: str) -> str:
        bad = _good_response_dict()
        del bad["faithfulness_evidence_refs"]
        return json.dumps(bad)

    adapter_primary = JudgeAdapter(
        model="model-a", provider="provider-x", dataset=dataset, response_fn=missing_evidence
    )
    adapter_secondary = JudgeAdapter(
        model="model-b",
        provider="provider-y",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(_good_response_dict()),
    )

    outcome = judge_eligible_case(
        _base_record(), primary_judge=adapter_primary, secondary_judge=adapter_secondary
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_EVALUATED


def test_both_adapters_succeed_end_to_end_produces_judged_with_distinct_models():
    dataset = _dataset((_case(),))
    primary = JudgeAdapter(
        model="model-a",
        provider="provider-x",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(
            _good_response_dict(correctness=4, completeness=2, relevance=4, faithfulness=2)
        ),
    )
    secondary = JudgeAdapter(
        model="model-b",
        provider="provider-y",
        dataset=dataset,
        response_fn=lambda _p: json.dumps(
            _good_response_dict(correctness=2, completeness=4, relevance=4, faithfulness=4)
        ),
    )
    build_judge_pair(primary=primary, secondary=secondary)  # does not raise

    outcome = judge_eligible_case(_base_record(), primary_judge=primary, secondary_judge=secondary)
    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.qa_result.reported_correctness == 3.0
    assert outcome.qa_result.reported_faithfulness == 3.0


def test_total_failure_two_different_modes_end_to_end():
    dataset = _dataset((_case(),))

    def auth_fails(_prompt: str) -> str:
        raise JudgeCallError("401 Unauthorized")

    def bad_json(_prompt: str) -> str:
        return "not json"

    primary = JudgeAdapter(model="model-a", provider="provider-x", dataset=dataset, response_fn=auth_fails)
    secondary = JudgeAdapter(model="model-b", provider="provider-y", dataset=dataset, response_fn=bad_json)

    outcome = judge_eligible_case(_base_record(), primary_judge=primary, secondary_judge=secondary)
    assert outcome.final_status == JUDGING_STATUS_FAILED_TOTAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED
    assert outcome.qa_result is None


# ---------------------------------------------------------------------------
# Distinct judge model enforcement
# ---------------------------------------------------------------------------


def test_identical_judge_models_raise_at_construction_before_any_judging():
    dataset = _dataset((_case(),))
    same_fn = lambda _p: json.dumps(_good_response_dict())  # noqa: E731

    primary = JudgeAdapter(model="same-model", provider="provider-x", dataset=dataset, response_fn=same_fn)
    secondary = JudgeAdapter(model="same-model", provider="provider-y", dataset=dataset, response_fn=same_fn)

    with pytest.raises(DuplicateJudgeModelError):
        build_judge_pair(primary=primary, secondary=secondary)


def test_different_models_same_provider_is_allowed_provider_match_is_only_preferred_not_enforced():
    dataset = _dataset((_case(),))
    same_fn = lambda _p: json.dumps(_good_response_dict())  # noqa: E731

    primary = JudgeAdapter(model="model-a", provider="provider-x", dataset=dataset, response_fn=same_fn)
    secondary = JudgeAdapter(model="model-b", provider="provider-x", dataset=dataset, response_fn=same_fn)

    # Does not raise: distinct models satisfy the hard requirement even
    # though the provider happens to match on both sides.
    build_judge_pair(primary=primary, secondary=secondary)
