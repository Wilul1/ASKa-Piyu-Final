"""Stage 3.2B Phase 5 Part A tests: citation claim-level judging.

All judge "calls" here are local Python fakes (strings/dicts/exceptions).
No real HTTP/LLM call is made anywhere in this file. Citation-id
resolution reads the real, locked, read-only extract artifact via
``load_locked_extract_index`` (the same cached function Stage 2 already
uses) -- this does not touch any capture run or the dataset file.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from app.services.evaluation.qa_citation_claim_judging import (
    CITATION_CLAIM_PROMPT_TEMPLATE,
    CITATION_CLAIM_PROMPT_VERSION,
    CitationClaimJudgeAdapter,
    QaCitationClaimJudgingError,
    build_citation_claim_judge_call_payload,
    build_citation_claim_judge_pair,
    build_citation_claim_prompt,
    citation_claim_prompt_sha256,
    judge_citation_claims_case,
    judge_citation_claims_cases,
    resolve_citation_validity,
    validate_citation_claim_response,
)
from app.services.evaluation.qa_citation_dataset import (
    CorpusSnapshot,
    QaCitationCase,
    QaCitationDataset,
    load_locked_extract_index,
)
from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_FALLBACK_NOT_GENUINE,
    EXCLUSION_FIELD_MISSING,
)
from app.services.evaluation.qa_citation_judge_prompt import DuplicateJudgeModelError
from app.services.evaluation.qa_citation_judging import JudgeCallError, JudgeTimeoutError
from app.services.evaluation.qa_citation_metrics import (
    CITATION_VALIDITY_UNRESOLVED,
    CITATION_VALIDITY_VALID,
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

_EXTRACT = load_locked_extract_index()
_REAL_IDS = list(_EXTRACT.by_chunk_id.keys())
REAL_ID_1 = _REAL_IDS[0]
REAL_ID_2 = _REAL_IDS[1]
REAL_ID_1_DOCUMENT = _EXTRACT.by_chunk_id[REAL_ID_1].document_id
FAKE_ID = "not-a-real-document-id::0"


def _case(case_id: str = "qac_001_answerable") -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question="How much does a second copy of my diploma cost?",
        category="Fees",
        difficulty="easy",
        case_type="labeled_student_support",
        labeling_status="labeled",
        reference_answer="P100.00 for a second copy of the diploma.",
        supporting_document_ids=(REAL_ID_1_DOCUMENT,),
        supporting_chunk_ids=(REAL_ID_1,),
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
        source_path="<memory>",
    )


def _eligible_record(
    case_id: str = "qac_001_answerable",
    *,
    displayed_citation_ids: list[str] | None = None,
    source_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ids = displayed_citation_ids if displayed_citation_ids is not None else [REAL_ID_1]
    return {
        "case_id": case_id,
        "execution_status": "ok",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "generated_answer": "A second copy of your diploma costs P100.00.",
        "retrieved_context": f"[{REAL_ID_1}] Second copy of diploma: P100.00.",
        "displayed_citation_ids": ids,
        "source_metadata": source_metadata if source_metadata is not None else [],
    }


def _valid_response(claim_id: str = "c1") -> dict[str, Any]:
    return {
        "evaluation_status": "evaluated",
        "claims": [
            {
                "claim_id": claim_id,
                "text": "A second copy of the diploma costs P100.00.",
                "requires_citation": True,
                "claim_support": "supported",
                "supporting_displayed_ids": [REAL_ID_1],
            }
        ],
    }


# --- prompt -----------------------------------------------------------------


def test_prompt_includes_question_answer_evidence_and_citation_ids():
    text = build_citation_claim_prompt(
        question="How much does a second copy of my diploma cost?",
        generated_answer="It costs P100.00.",
        retrieved_context=f"[{REAL_ID_1}] Second copy of diploma: P100.00.",
        displayed_citation_ids=[REAL_ID_1],
    )
    assert "How much does a second copy of my diploma cost?" in text
    assert "It costs P100.00." in text
    assert REAL_ID_1 in text
    assert "never invent an id" in text.lower()


def test_prompt_version_and_hash_are_stable():
    assert CITATION_CLAIM_PROMPT_VERSION == "qa_citation_claim_judge_v1"
    assert citation_claim_prompt_sha256() == citation_claim_prompt_sha256()
    import hashlib

    assert citation_claim_prompt_sha256() == hashlib.sha256(
        CITATION_CLAIM_PROMPT_TEMPLATE.encode("utf-8")
    ).hexdigest()


# --- citation validity resolution -------------------------------------------


def test_resolve_citation_validity_valid_and_unresolved():
    validity = resolve_citation_validity(displayed_citation_ids=[REAL_ID_1, FAKE_ID])
    assert validity[REAL_ID_1] == CITATION_VALIDITY_VALID
    assert validity[FAKE_ID] == CITATION_VALIDITY_UNRESOLVED


def test_resolve_citation_validity_no_longer_accepts_source_metadata():
    """Stage 3.6: source_metadata is not a parameter of this function at
    all anymore -- passing it must fail loudly (a TypeError), not be
    silently ignored, so a caller can never think this cross-check still
    happens."""
    with pytest.raises(TypeError):
        resolve_citation_validity(  # type: ignore[call-arg]
            displayed_citation_ids=[REAL_ID_1],
            source_metadata=[{"citation_id": REAL_ID_1, "document_id": "irrelevant"}],
        )


def test_resolve_citation_validity_real_chunk_with_mismatched_metadata_document_is_valid():
    """Stage 3.6 regression test for the confirmed defect: a real, existing
    chunk_id must resolve as valid regardless of what document_id a
    capture record's source_metadata happens to claim for it -- that field
    is a different (application Document-table) UUID namespace and must
    never be consulted by this function. Before the fix, this exact
    scenario (which is what every real Stage 3.4 citation actually looked
    like) was misclassified as CITATION_VALIDITY_WRONG_DOCUMENT."""
    validity = resolve_citation_validity(displayed_citation_ids=[REAL_ID_1])
    assert validity[REAL_ID_1] == CITATION_VALIDITY_VALID


def test_resolve_citation_validity_nonexistent_document_uuid_is_unresolved():
    fake_but_well_formed = "00000000-0000-0000-0000-000000000000::0"
    validity = resolve_citation_validity(displayed_citation_ids=[fake_but_well_formed])
    assert validity[fake_but_well_formed] == CITATION_VALIDITY_UNRESOLVED


def test_resolve_citation_validity_nonexistent_chunk_index_for_real_document_is_unresolved():
    # A real document_id, but a chunk index that certainly doesn't exist
    # for it (this document has far fewer than 999999 chunks).
    bogus_index_id = f"{REAL_ID_1_DOCUMENT}::999999"
    assert bogus_index_id not in _EXTRACT.by_chunk_id  # sanity: genuinely nonexistent
    validity = resolve_citation_validity(displayed_citation_ids=[bogus_index_id])
    assert validity[bogus_index_id] == CITATION_VALIDITY_UNRESOLVED


@pytest.mark.parametrize(
    "malformed_id",
    [
        "no-separator-at-all",
        "",
        "::0",
        "trailing-colon::",
        f"{REAL_ID_1_DOCUMENT}::not-an-integer",
    ],
)
def test_resolve_citation_validity_malformed_ids_are_unresolved_not_crashes(malformed_id):
    validity = resolve_citation_validity(displayed_citation_ids=[malformed_id])
    assert validity[malformed_id] == CITATION_VALIDITY_UNRESOLVED


def test_resolve_citation_validity_deduplicates_repeated_ids():
    validity = resolve_citation_validity(
        displayed_citation_ids=[REAL_ID_1, REAL_ID_1, FAKE_ID, REAL_ID_1, FAKE_ID]
    )
    # One entry per unique id, following the same unique_preserve_order
    # dedup rule used everywhere else in this rubric -- not one entry per
    # occurrence.
    assert set(validity.keys()) == {REAL_ID_1, FAKE_ID}
    assert len(validity) == 2
    assert validity[REAL_ID_1] == CITATION_VALIDITY_VALID
    assert validity[FAKE_ID] == CITATION_VALIDITY_UNRESOLVED


def test_resolve_citation_validity_multiple_real_ids_all_valid():
    validity = resolve_citation_validity(displayed_citation_ids=[REAL_ID_1, REAL_ID_2])
    assert validity[REAL_ID_1] == CITATION_VALIDITY_VALID
    assert validity[REAL_ID_2] == CITATION_VALIDITY_VALID


# --- response validation ------------------------------------------------


def test_validate_response_accepts_well_formed_claims():
    response = validate_citation_claim_response(
        _valid_response(), slot="primary", displayed_citation_ids=[REAL_ID_1]
    )
    assert len(response.claims) == 1
    claim = response.claims[0]
    assert claim.requires_citation is True
    assert claim.claim_support == "supported"
    assert claim.supporting_displayed_ids == (REAL_ID_1,)


def test_validate_response_allows_empty_claims_list():
    response = validate_citation_claim_response(
        {"evaluation_status": "evaluated", "claims": []},
        slot="primary",
        displayed_citation_ids=[REAL_ID_1],
    )
    assert response.claims == ()


def test_validate_response_rejects_invalid_json_string():
    with pytest.raises(QaCitationMetricError):
        validate_citation_claim_response(
            "not json{{{", slot="primary", displayed_citation_ids=[REAL_ID_1]
        )


def test_validate_response_rejects_missing_claims_key():
    with pytest.raises(QaCitationMetricError):
        validate_citation_claim_response(
            {"evaluation_status": "evaluated"}, slot="primary", displayed_citation_ids=[REAL_ID_1]
        )


def test_validate_response_rejects_invented_citation_id():
    bad = _valid_response()
    bad["claims"][0]["supporting_displayed_ids"] = [FAKE_ID]
    with pytest.raises(QaCitationMetricError, match="not in this case"):
        validate_citation_claim_response(bad, slot="primary", displayed_citation_ids=[REAL_ID_1])


def test_validate_response_rejects_unsupported_claim_with_supporting_ids():
    bad = _valid_response()
    bad["claims"][0]["claim_support"] = "unsupported"
    # supporting_displayed_ids still non-empty -- inconsistent with "unsupported"
    with pytest.raises(QaCitationMetricError):
        validate_citation_claim_response(bad, slot="primary", displayed_citation_ids=[REAL_ID_1])


def test_validate_response_rejects_supported_claim_with_no_supporting_ids():
    bad = _valid_response()
    bad["claims"][0]["supporting_displayed_ids"] = []
    with pytest.raises(QaCitationMetricError):
        validate_citation_claim_response(bad, slot="primary", displayed_citation_ids=[REAL_ID_1])


def test_validate_response_rejects_duplicate_claim_ids():
    response = _valid_response()
    response["claims"].append(dict(response["claims"][0]))
    with pytest.raises(QaCitationMetricError, match="duplicate claim_id"):
        validate_citation_claim_response(
            response, slot="primary", displayed_citation_ids=[REAL_ID_1]
        )


def test_validate_response_rejects_claim_support_when_citation_not_required():
    bad = {
        "evaluation_status": "evaluated",
        "claims": [
            {
                "claim_id": "c1",
                "text": "Thank you for your question.",
                "requires_citation": False,
                "claim_support": "supported",
            }
        ],
    }
    with pytest.raises(QaCitationMetricError):
        validate_citation_claim_response(bad, slot="primary", displayed_citation_ids=[REAL_ID_1])


def test_non_citation_required_claim_needs_no_support():
    ok = {
        "evaluation_status": "evaluated",
        "claims": [
            {
                "claim_id": "c1",
                "text": "Thank you for your question.",
                "requires_citation": False,
                "claim_support": None,
            }
        ],
    }
    response = validate_citation_claim_response(
        ok, slot="primary", displayed_citation_ids=[REAL_ID_1]
    )
    assert response.claims[0].requires_citation is False
    assert response.claims[0].claim_support is None


def test_build_judge_call_payload_marks_invalid_response_on_failure():
    payload = build_citation_claim_judge_call_payload(
        "not json", slot="primary", displayed_citation_ids=[REAL_ID_1]
    )
    assert payload["evaluation_status"] == "invalid_response"
    assert "validation_error" in payload


# --- adapter ------------------------------------------------------------


def test_adapter_builds_prompt_and_delegates_to_response_fn():
    dataset = _dataset((_case(),))
    captured: dict[str, Any] = {}

    def fake_response_fn(prompt: str) -> dict[str, Any]:
        captured["prompt"] = prompt
        return _valid_response()

    adapter = CitationClaimJudgeAdapter(
        model="model-a", provider="provider-a", dataset=dataset, response_fn=fake_response_fn
    )
    record = _eligible_record()
    payload = adapter(record)
    assert "How much does a second copy" in captured["prompt"]
    assert payload["evaluation_status"] == "evaluated"
    assert payload["_judge_model"] == "model-a"
    assert payload["_judge_provider"] == "provider-a"
    assert payload["_judge_prompt_version"] == CITATION_CLAIM_PROMPT_VERSION


def test_adapter_raises_on_unknown_case_id():
    dataset = _dataset((_case(),))
    adapter = CitationClaimJudgeAdapter(
        model="model-a", provider="provider-a", dataset=dataset,
        response_fn=lambda prompt: _valid_response(),
    )
    with pytest.raises(Exception):
        adapter({"case_id": "does-not-exist", "displayed_citation_ids": []})


def test_build_citation_claim_judge_pair_rejects_identical_models():
    dataset = _dataset((_case(),))
    primary = CitationClaimJudgeAdapter(
        model="same-model", provider="provider-a", dataset=dataset,
        response_fn=lambda prompt: _valid_response(),
    )
    secondary = CitationClaimJudgeAdapter(
        model="same-model", provider="provider-b", dataset=dataset,
        response_fn=lambda prompt: _valid_response(),
    )
    with pytest.raises(DuplicateJudgeModelError):
        build_citation_claim_judge_pair(primary=primary, secondary=secondary)


# --- orchestration: eligibility gating -----------------------------------


def test_ineligible_fallback_record_excluded_before_any_judge_call():
    record = {
        "case_id": "qac_033_wifi_password",
        "execution_status": "ok",
        "is_genuine_model_output": False,
        "fallback_used": True,
        "generated_answer": "Acts of Cybercrime...",
        "retrieved_context": "...",
        "displayed_citation_ids": [],
        "source_metadata": [],
    }
    called = {"primary": False, "secondary": False}

    def primary(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        called["primary"] = True
        return _valid_response()

    def secondary(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        called["secondary"] = True
        return _valid_response()

    outcome = judge_citation_claims_case(record, primary_judge=primary, secondary_judge=secondary)
    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.eligibility_verdict.exclusion_reason == EXCLUSION_FALLBACK_NOT_GENUINE
    assert called == {"primary": False, "secondary": False}


def test_missing_eligibility_fields_excluded_before_any_judge_call():
    record = {"case_id": "qac_x", "execution_status": "ok", "generated_answer": "answer"}
    called = {"primary": False}

    def primary(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        called["primary"] = True
        return _valid_response()

    outcome = judge_citation_claims_case(record, primary_judge=primary, secondary_judge=primary)
    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_INELIGIBLE
    assert outcome.eligibility_verdict.exclusion_reason == EXCLUSION_FIELD_MISSING
    assert called == {"primary": False}


def test_refusal_record_excluded_as_not_applicable():
    record = {
        "case_id": "qac_oos",
        "execution_status": "oos_or_refusal",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "generated_answer": "I can't help with that.",
    }
    outcome = judge_citation_claims_case(
        record, primary_judge=lambda r: _valid_response(), secondary_judge=lambda r: _valid_response()
    )
    assert outcome.final_status == JUDGING_STATUS_EXCLUDED_NOT_APPLICABLE


# --- orchestration: success / partial / total failure ----------------------


def test_both_judges_succeed_preserves_both_citation_metrics_independently():
    record = _eligible_record()
    outcome = judge_citation_claims_case(
        record,
        primary_judge=lambda r: _valid_response("c1"),
        secondary_judge=lambda r: _valid_response("c1"),
    )
    assert outcome.final_status == JUDGING_STATUS_JUDGED
    assert outcome.primary_judge.evaluated
    assert outcome.secondary_judge.evaluated
    assert outcome.primary_judge.citation_metrics is not None
    assert outcome.secondary_judge.citation_metrics is not None
    # hand-computed: one citation-required claim, supported, one displayed id
    assert outcome.primary_judge.citation_metrics.citation_precision.numerator == 1
    assert outcome.primary_judge.citation_metrics.citation_precision.denominator == 1
    assert outcome.primary_judge.citation_metrics.citation_precision.value == 1.0
    assert outcome.primary_judge.citation_metrics.claim_support_rate.value == 1.0


def test_one_judge_fails_via_timeout_yields_partial_failure():
    record = _eligible_record()

    def timing_out(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        raise JudgeTimeoutError("slow provider")

    outcome = judge_citation_claims_case(
        record, primary_judge=lambda r: _valid_response(), secondary_judge=timing_out
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.primary_judge.evaluated
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT
    # the surviving judge's citation metrics exist for diagnostics but the
    # case-level outcome is not "judged" -- confirm callers can tell.
    assert outcome.primary_judge.citation_metrics is not None


def test_one_judge_fails_via_malformed_response_yields_partial_failure():
    record = _eligible_record()

    def malformed(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"evaluation_status": "evaluated"}  # missing "claims"

    outcome = judge_citation_claims_case(
        record, primary_judge=lambda r: _valid_response(), secondary_judge=malformed
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_PARTIAL
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_MALFORMED


def test_both_judges_fail_yields_total_failure():
    record = _eligible_record()

    def erroring(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        raise JudgeCallError("401 Unauthorized")

    def timing_out(_record: Mapping[str, Any]) -> Mapping[str, Any]:
        raise JudgeTimeoutError("slow")

    outcome = judge_citation_claims_case(
        record, primary_judge=erroring, secondary_judge=timing_out
    )
    assert outcome.final_status == JUDGING_STATUS_FAILED_TOTAL
    assert outcome.primary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_ERROR
    assert outcome.secondary_judge.judge_execution_status == JUDGE_EXECUTION_STATUS_TIMEOUT


def test_identical_judge_models_raise_before_any_judging():
    dataset = _dataset((_case(),))
    primary = CitationClaimJudgeAdapter(
        model="dup-model", provider="p1", dataset=dataset, response_fn=lambda p: _valid_response()
    )
    secondary = CitationClaimJudgeAdapter(
        model="dup-model", provider="p2", dataset=dataset, response_fn=lambda p: _valid_response()
    )
    with pytest.raises(DuplicateJudgeModelError):
        build_citation_claim_judge_pair(primary=primary, secondary=secondary)


# --- batch runner ---------------------------------------------------------


def test_batch_runner_produces_one_outcome_per_record_and_rejects_duplicates():
    records = [_eligible_record("qac_1"), _eligible_record("qac_2")]
    outcomes = judge_citation_claims_cases(
        records,
        primary_judge=lambda r: _valid_response(),
        secondary_judge=lambda r: _valid_response(),
    )
    assert len(outcomes) == 2
    assert {o.case_id for o in outcomes} == {"qac_1", "qac_2"}

    with pytest.raises(QaCitationClaimJudgingError):
        judge_citation_claims_cases(
            [_eligible_record("dup"), _eligible_record("dup")],
            primary_judge=lambda r: _valid_response(),
            secondary_judge=lambda r: _valid_response(),
        )
