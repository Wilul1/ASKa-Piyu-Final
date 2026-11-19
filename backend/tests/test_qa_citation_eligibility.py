"""Stage 3.2B Phase 1 eligibility-filter tests.

Pure-function logic; no mocking needed. One test loads the real, preserved
failed run (qac_capture_20261109T095436Z_892ed650) read-only and confirms
the file is untouched before and after.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.services.evaluation.qa_citation_eligibility import (
    EXCLUSION_EMPTY_ANSWER,
    EXCLUSION_FALLBACK_NOT_GENUINE,
    EXCLUSION_FIELD_MISSING,
    EXCLUSION_NO_RESULT,
    EXCLUSION_REFUSAL_NOT_QA_SCORED,
    QaCitationEligibilityError,
    classify_eligibility,
    load_captures_jsonl,
    summarize_captures_file,
    summarize_eligibility,
)

# The preserved failed run (qac_capture_20261109T095436Z_892ed650) was
# captured BEFORE is_genuine_model_output/fallback_used existed as
# top-level capture-record fields -- those were added to
# qa_citation_capture.py by a later recovery fix. Its 36 records therefore
# fail closed on EXCLUSION_FIELD_MISSING (the authoritative fields are
# absent), not EXCLUSION_FALLBACK_NOT_GENUINE. This is the correct,
# intentional behavior: the filter does not fall back to inferring
# eligibility from the older fallback_reason field for legacy-schema data.

BACKEND_DIR = Path(__file__).resolve().parents[1]
FAILED_RUN_DIR = (
    BACKEND_DIR
    / "benchmarks"
    / "evaluation"
    / "qa_citation_runs"
    / "qac_capture_20261109T095436Z_892ed650"
)
FAILED_CAPTURES_PATH = FAILED_RUN_DIR / "captures.jsonl"
FAILED_SUMMARY_PATH = FAILED_RUN_DIR / "summary.json"
EXPECTED_CAPTURES_SHA256 = (
    "82ad34bb9278922ef0ca102a5fb938329f21050bed87b222cf3dfae7262502fe"
)
EXPECTED_SUMMARY_SHA256 = (
    "33991d53086a089e09ac99fe50e8c2cbd577ef650acb55af6c003c53abf97b7a"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _base_record(**overrides) -> dict:
    record = {
        "case_id": "qac_001_example",
        "execution_status": "ok",
        "is_genuine_model_output": True,
        "fallback_used": False,
        "generated_answer": "The fee is P75.00/page.",
    }
    record.update(overrides)
    return record


def test_fully_eligible_record():
    verdict = classify_eligibility(_base_record())
    assert verdict.eligible is True
    assert verdict.exclusion_reason is None


def test_fallback_not_genuine_matches_the_actual_incident_shape():
    record = _base_record(
        is_genuine_model_output=False,
        fallback_used=True,
        execution_status="ok",
        generated_answer="Extractive fallback text, not a real answer.",
    )
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_FALLBACK_NOT_GENUINE


def test_missing_is_genuine_model_output_fails_closed():
    record = _base_record()
    del record["is_genuine_model_output"]
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_FIELD_MISSING


def test_missing_fallback_used_fails_closed():
    record = _base_record()
    del record["fallback_used"]
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_FIELD_MISSING


def test_none_is_genuine_model_output_means_no_result_to_judge():
    record = _base_record(
        is_genuine_model_output=None,
        fallback_used=False,
        execution_status="error",
        generated_answer=None,
    )
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_NO_RESULT


def test_oos_or_refusal_excluded_even_if_other_fields_look_fine():
    record = _base_record(
        execution_status="oos_or_refusal",
        is_genuine_model_output=True,
        fallback_used=False,
        generated_answer="I can't help with that out-of-scope request.",
    )
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_REFUSAL_NOT_QA_SCORED


def test_empty_answer_fails_closed_even_when_marked_genuine():
    record = _base_record(generated_answer="   ")
    verdict = classify_eligibility(record)
    assert verdict.eligible is False
    assert verdict.exclusion_reason == EXCLUSION_EMPTY_ANSWER

    record2 = _base_record(generated_answer=None)
    verdict2 = classify_eligibility(record2)
    assert verdict2.eligible is False
    assert verdict2.exclusion_reason == EXCLUSION_EMPTY_ANSWER


def test_summary_counts_and_per_case_reasons_are_exact_and_nothing_is_dropped():
    records = [
        _base_record(case_id="c1"),
        _base_record(
            case_id="c2",
            is_genuine_model_output=False,
            fallback_used=True,
            generated_answer="fallback text",
        ),
        _base_record(case_id="c3", execution_status="oos_or_refusal"),
        {**_base_record(case_id="c4")},
    ]
    del records[3]["fallback_used"]

    summary = summarize_eligibility(records)

    assert summary.total_count == 4
    assert summary.eligible_count == 1
    assert summary.excluded_count == 3
    assert summary.exclusion_counts_by_reason == {
        EXCLUSION_FALLBACK_NOT_GENUINE: 1,
        EXCLUSION_REFUSAL_NOT_QA_SCORED: 1,
        EXCLUSION_FIELD_MISSING: 1,
    }
    case_ids = {verdict.case_id for verdict in summary.verdicts}
    assert case_ids == {"c1", "c2", "c3", "c4"}

    by_case = {verdict.case_id: verdict for verdict in summary.verdicts}
    assert by_case["c1"].eligible is True
    assert by_case["c2"].exclusion_reason == EXCLUSION_FALLBACK_NOT_GENUINE
    assert by_case["c3"].exclusion_reason == EXCLUSION_REFUSAL_NOT_QA_SCORED
    assert by_case["c4"].exclusion_reason == EXCLUSION_FIELD_MISSING


def test_duplicate_case_id_raises_rather_than_silently_merging():
    records = [_base_record(case_id="dup"), _base_record(case_id="dup")]
    with pytest.raises(QaCitationEligibilityError):
        summarize_eligibility(records)


@pytest.mark.skipif(
    not FAILED_CAPTURES_PATH.exists(),
    reason="Preserved failed run not present in this environment.",
)
def test_real_failed_run_is_zero_eligible_and_file_is_untouched():
    hash_before_captures = _sha256(FAILED_CAPTURES_PATH)
    hash_before_summary = _sha256(FAILED_SUMMARY_PATH)
    assert hash_before_captures == EXPECTED_CAPTURES_SHA256
    assert hash_before_summary == EXPECTED_SUMMARY_SHA256

    summary = summarize_captures_file(FAILED_CAPTURES_PATH)

    assert summary.total_count == 36
    assert summary.eligible_count == 0
    assert summary.excluded_count == 36
    assert summary.exclusion_counts_by_reason == {EXCLUSION_FIELD_MISSING: 36}
    assert len(summary.verdicts) == 36
    assert all(not verdict.eligible for verdict in summary.verdicts)
    assert all(
        verdict.exclusion_reason == EXCLUSION_FIELD_MISSING
        for verdict in summary.verdicts
    )

    hash_after_captures = _sha256(FAILED_CAPTURES_PATH)
    hash_after_summary = _sha256(FAILED_SUMMARY_PATH)
    assert hash_after_captures == hash_before_captures == EXPECTED_CAPTURES_SHA256
    assert hash_after_summary == hash_before_summary == EXPECTED_SUMMARY_SHA256


@pytest.mark.skipif(
    not FAILED_CAPTURES_PATH.exists(),
    reason="Preserved failed run not present in this environment.",
)
def test_load_captures_jsonl_reads_all_36_records_without_error():
    records = load_captures_jsonl(FAILED_CAPTURES_PATH)
    assert len(records) == 36
    assert {record["case_id"] for record in records} and all(
        record.get("case_id") for record in records
    )
