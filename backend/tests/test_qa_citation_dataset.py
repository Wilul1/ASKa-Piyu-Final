"""Deterministic unit tests for the Stage 2 QA/citation dataset loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services.evaluation.qa_citation_dataset import (
    CASE_TYPE_INSUFFICIENT_EVIDENCE,
    CASE_TYPE_LABELED_STUDENT_SUPPORT,
    CORPUS_PROVENANCE,
    EXPERIMENT_FAMILY,
    LIVE_DIFFICULTIES,
    LOCKED_CORPUS_CHUNK_COUNT,
    LOCKED_CORPUS_COLLECTION,
    LOCKED_CORPUS_EXTRACT_ARTIFACT,
    LOCKED_CORPUS_PATH,
    LOCKED_IDENTITY_DIGEST,
    LOCKED_METADATA_TEXT_DIGEST,
    QaCitationDatasetError,
    faculty_scope_violations,
    load_locked_extract_index,
    load_qa_citation_dataset,
    parse_citation_id,
    validate_qa_citation_payload,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
EXAMPLE_DATASET = (
    BACKEND_DIR
    / "benchmarks"
    / "evaluation"
    / "qa_citation_contract"
    / "examples"
    / "qa_citation_eval_dataset.example.json"
)

# Real extract membership fixture (Charter TOR chunk). Not an evaluation gold set.
REAL_DOCUMENT_ID = "da4a1832-7242-4e94-8ba6-bc0b9f2294bf"
REAL_CHUNK_ID = f"{REAL_DOCUMENT_ID}::1"
REAL_EXCERPT = "Undergraduate: P75.00/page; Graduate: P150/page"

FAQ_DOCUMENT_ID = "faq:5efbafa2-cc06-420f-990b-81548cd5451e"
FAQ_CHUNK_ID = f"{FAQ_DOCUMENT_ID}::0"
FAQ_EXCERPT = "Brand New Article"

NONEXISTENT_DOCUMENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
NONEXISTENT_CHUNK_ID = f"{NONEXISTENT_DOCUMENT_ID}::0"


def _labeled_student_support_case(**overrides) -> dict:
    case = {
        "case_id": "qac_test_001_tor_fee",
        "question": "How much does a Transcript of Records cost for undergraduate students?",
        "category": "Student Records",
        "difficulty": "easy",
        "case_type": CASE_TYPE_LABELED_STUDENT_SUPPORT,
        "labeling_status": "labeled",
        "reference_answer": "A Transcript of Records costs P75.00 per page for undergraduate students.",
        "supporting_document_ids": [REAL_DOCUMENT_ID],
        "supporting_chunk_ids": [REAL_CHUNK_ID],
        "reference_evidence": [
            {
                "chunk_id": REAL_CHUNK_ID,
                "document_id": REAL_DOCUMENT_ID,
                "excerpt": REAL_EXCERPT,
            }
        ],
        "generation_model": "test-generator-not-executed",
        "generation_prompt_version": "qac-gen-test-v1",
        "reviewer_notes": "Loader fixture using a real extract chunk. Not a live evaluation result.",
    }
    case.update(overrides)
    return case


def _insufficient_evidence_case(**overrides) -> dict:
    case = {
        "case_id": "qac_test_002_sunday_shuttle",
        "question": "Does the campus shuttle run on Sundays for off-campus dorm students?",
        "category": "Student Services",
        "difficulty": "insufficient_evidence",
        "case_type": CASE_TYPE_INSUFFICIENT_EVIDENCE,
        "labeling_status": "labeled",
        "reference_answer": None,
        "supporting_document_ids": [],
        "supporting_chunk_ids": [],
        "reference_evidence": [],
        "generation_model": "test-generator-not-executed",
        "generation_prompt_version": "qac-gen-test-v1",
        "reviewer_notes": "In-scope student question; locked corpus has no shuttle schedule.",
    }
    case.update(overrides)
    return case


def _valid_dataset(cases: list[dict], **overrides) -> dict:
    payload = {
        "dataset_version": "2026-11-09-stage2-test",
        "experiment_family": EXPERIMENT_FAMILY,
        "annotation_method": "ai_assisted_grounded_generation",
        "judge_source_for_later_scoring": "ai_evaluator",
        "evaluation_ready": True,
        "corpus": {
            "path": LOCKED_CORPUS_PATH,
            "collection": LOCKED_CORPUS_COLLECTION,
            "expected_chunk_count": LOCKED_CORPUS_CHUNK_COUNT,
            "extract_artifact": LOCKED_CORPUS_EXTRACT_ARTIFACT,
            "identity_digest": LOCKED_IDENTITY_DIGEST,
            "metadata_text_digest": LOCKED_METADATA_TEXT_DIGEST,
        },
        "generation": {
            "model": "test-generator-not-executed",
            "prompt_version": "qac-gen-test-v1",
        },
        "cases": cases,
    }
    payload.update(overrides)
    return payload


def _write(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_locked_extract_digests_match_artifact():
    index = load_locked_extract_index()
    assert index.identity_digest == LOCKED_IDENTITY_DIGEST
    assert index.metadata_text_digest == LOCKED_METADATA_TEXT_DIGEST
    assert index.record_count == 691
    assert REAL_CHUNK_ID in index.by_chunk_id
    assert FAQ_CHUNK_ID in index.by_chunk_id
    assert index.source_collection_as_recorded == "aska_knowledge_base"
    assert "does not prove" in CORPUS_PROVENANCE["limitation"]


def test_valid_labeled_student_support_case_loads():
    payload = _valid_dataset([_labeled_student_support_case()])
    dataset = validate_qa_citation_payload(payload, source_path="memory://labeled")
    assert dataset.total_count == 1
    assert dataset.unlabeled_count == 0
    assert len(dataset.labeled_cases) == 1
    case = dataset.labeled_cases[0]
    assert case.case_id == "qac_test_001_tor_fee"
    assert case.case_type == CASE_TYPE_LABELED_STUDENT_SUPPORT
    assert case.reference_answer is not None
    assert case.supporting_chunk_ids == (REAL_CHUNK_ID,)
    assert REAL_EXCERPT in case.reference_evidence[0].excerpt
    assert dataset.corpus.expected_chunk_count == 691
    assert dataset.corpus.identity_digest == LOCKED_IDENTITY_DIGEST
    assert dataset.experiment_family == EXPERIMENT_FAMILY
    assert dataset.dataset_json_sha256 != dataset.corpus.identity_digest


def test_valid_insufficient_evidence_case_loads():
    payload = _valid_dataset([_insufficient_evidence_case()])
    dataset = validate_qa_citation_payload(payload, source_path="memory://insufficient")
    assert dataset.total_count == 1
    case = dataset.labeled_cases[0]
    assert case.case_type == CASE_TYPE_INSUFFICIENT_EVIDENCE
    assert case.reference_answer is None
    assert case.supporting_document_ids == ()
    assert case.reference_evidence == ()


def test_mixed_valid_cases_preserve_both_types(tmp_path):
    path = _write(
        tmp_path,
        "qa_citation_eval_dataset.json",
        _valid_dataset([_labeled_student_support_case(), _insufficient_evidence_case()]),
    )
    dataset = load_qa_citation_dataset(path)
    assert dataset.total_count == 2
    assert {case.case_type for case in dataset.labeled_cases} == {
        CASE_TYPE_LABELED_STUDENT_SUPPORT,
        CASE_TYPE_INSUFFICIENT_EVIDENCE,
    }
    assert dataset.dataset_json_sha256
    assert dataset.dataset_json_sha256 != LOCKED_IDENTITY_DIGEST


def test_reject_faculty_related_case():
    faculty_case = _labeled_student_support_case(
        case_id="qac_test_faculty_manual",
        question="Where can faculty members find the faculty manual teaching load?",
        category="Faculty Affairs",
    )
    payload = _valid_dataset([faculty_case])
    with pytest.raises(QaCitationDatasetError, match="faculty-related"):
        validate_qa_citation_payload(payload, source_path="memory://faculty")


def test_reject_faculty_category_even_if_question_looks_student():
    faculty_case = _labeled_student_support_case(
        case_id="qac_test_faculty_category",
        question="What is the deadline to submit a leave form?",
        category="Faculty Handbook",
    )
    payload = _valid_dataset([faculty_case])
    with pytest.raises(QaCitationDatasetError, match="faculty-related"):
        validate_qa_citation_payload(payload, source_path="memory://faculty-category")


def test_student_question_about_college_or_faculty_is_allowed():
    assert faculty_scope_violations(
        "Which college or faculty should I contact for enrollment?"
    ) == ()
    case = _labeled_student_support_case(
        case_id="qac_test_college_or_faculty",
        question="Which college or faculty should I contact for enrollment?",
        category="Student Records",
    )
    dataset = validate_qa_citation_payload(
        _valid_dataset([case]), source_path="memory://student-faculty-unit"
    )
    assert dataset.labeled_cases[0].case_id == "qac_test_college_or_faculty"


def test_reject_labeled_student_support_missing_evidence():
    case = _labeled_student_support_case(
        supporting_document_ids=[],
        supporting_chunk_ids=[],
        reference_evidence=[],
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="grounded reference evidence"):
        validate_qa_citation_payload(payload, source_path="memory://missing-evidence")


def test_reject_labeled_student_support_null_reference_answer():
    case = _labeled_student_support_case(reference_answer=None)
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="non-null grounded reference_answer"):
        validate_qa_citation_payload(payload, source_path="memory://null-answer")


def test_reject_insufficient_evidence_case_with_reference_answer():
    case = _insufficient_evidence_case(
        reference_answer="The shuttle runs at 08:00 on Sundays."
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="reference_answer=null"):
        validate_qa_citation_payload(payload, source_path="memory://insuf-answer")


def test_reject_insufficient_evidence_case_carrying_evidence():
    case = _insufficient_evidence_case(
        labeling_status="unlabeled",
        supporting_document_ids=[REAL_DOCUMENT_ID],
        supporting_chunk_ids=[REAL_CHUNK_ID],
        reference_evidence=[
            {
                "chunk_id": REAL_CHUNK_ID,
                "document_id": REAL_DOCUMENT_ID,
                "excerpt": REAL_EXCERPT,
            }
        ],
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="must not include supporting"):
        validate_qa_citation_payload(payload, source_path="memory://insuf-evidence")


def test_reject_duplicate_case_ids():
    payload = _valid_dataset(
        [
            _labeled_student_support_case(),
            _insufficient_evidence_case(case_id="qac_test_001_tor_fee"),
        ]
    )
    with pytest.raises(QaCitationDatasetError, match="duplicate case_id"):
        validate_qa_citation_payload(payload, source_path="memory://dup")


def test_reject_malformed_chunk_identifier():
    case = _labeled_student_support_case(supporting_chunk_ids=["not-a-chunk-id"])
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="malformed chunk identifier"):
        validate_qa_citation_payload(payload, source_path="memory://bad-chunk")


def test_reject_malformed_document_identifier():
    case = _labeled_student_support_case(supporting_document_ids=["bad id with spaces"])
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="malformed document identifier"):
        validate_qa_citation_payload(payload, source_path="memory://bad-doc")


def test_reject_chunk_id_that_does_not_match_document_id():
    case = _labeled_student_support_case(
        reference_evidence=[
            {
                "chunk_id": "other-document::0",
                "document_id": REAL_DOCUMENT_ID,
                "excerpt": REAL_EXCERPT,
            }
        ]
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="does not belong to document_id"):
        validate_qa_citation_payload(payload, source_path="memory://mismatched-ids")


def test_reject_example_only_payload():
    payload = _valid_dataset([_labeled_student_support_case()], example_only=True)
    with pytest.raises(QaCitationDatasetError, match="example artifact"):
        validate_qa_citation_payload(payload, source_path="memory://example-flag")


def test_reject_not_an_evaluation_result_payload():
    payload = _valid_dataset(
        [_labeled_student_support_case()], not_an_evaluation_result=True
    )
    with pytest.raises(QaCitationDatasetError, match="example artifact"):
        validate_qa_citation_payload(payload, source_path="memory://not-result")


def test_reject_example_filename_even_if_flags_absent(tmp_path):
    path = _write(
        tmp_path,
        "qa_citation_eval_dataset.example.json",
        _valid_dataset([_labeled_student_support_case()]),
    )
    with pytest.raises(QaCitationDatasetError, match="example artifact"):
        load_qa_citation_dataset(path)


def test_reject_stage1_contract_example_file_as_live_dataset():
    assert EXAMPLE_DATASET.is_file()
    with pytest.raises(QaCitationDatasetError, match="example artifact"):
        load_qa_citation_dataset(EXAMPLE_DATASET)


def test_reject_unsupported_experiment_family():
    payload = _valid_dataset([_labeled_student_support_case()], experiment_family="preserved")
    with pytest.raises(QaCitationDatasetError, match="experiment_family"):
        validate_qa_citation_payload(payload, source_path="memory://family")


def test_reject_out_of_scope_difficulty():
    case = _insufficient_evidence_case(
        case_id="qac_test_mars",
        question="What is the weather like on Mars this week?",
        difficulty="out_of_scope",
        case_type=CASE_TYPE_INSUFFICIENT_EVIDENCE,
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="out_of_scope|not allowed"):
        validate_qa_citation_payload(payload, source_path="memory://oos")


def test_schema_and_loader_live_difficulties_match():
    assert LIVE_DIFFICULTIES == {
        "easy",
        "medium",
        "hard",
        "conflict",
        "insufficient_evidence",
    }
    schema_path = (
        BACKEND_DIR
        / "benchmarks"
        / "evaluation"
        / "qa_citation_contract"
        / "qa_citation_records.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema_difficulties = set(schema["$defs"]["qa_case"]["properties"]["difficulty"]["enum"])
    assert schema_difficulties == LIVE_DIFFICULTIES
    corpus_required = set(schema["$defs"]["dataset_envelope"]["properties"]["corpus"]["required"])
    assert "identity_digest" in corpus_required
    assert "metadata_text_digest" in corpus_required


def test_reject_missing_case_id():
    case = _labeled_student_support_case(case_id="  ")
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="case_id"):
        validate_qa_citation_payload(payload, source_path="memory://blank-id")


def test_reject_missing_or_empty_question():
    case = _labeled_student_support_case(question="")
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="question"):
        validate_qa_citation_payload(payload, source_path="memory://empty-q")


def test_reject_wrong_corpus_chunk_count_without_coercion():
    payload = _valid_dataset([_labeled_student_support_case()])
    payload["corpus"] = dict(payload["corpus"], expected_chunk_count="691")
    with pytest.raises(QaCitationDatasetError, match="expected_chunk_count"):
        validate_qa_citation_payload(payload, source_path="memory://corpus-count")


def test_reject_wrong_corpus_path():
    payload = _valid_dataset([_labeled_student_support_case()])
    payload["corpus"] = dict(payload["corpus"], path="backend/data/chroma_production")
    with pytest.raises(QaCitationDatasetError, match="corpus.path"):
        validate_qa_citation_payload(payload, source_path="memory://corpus-path")


def test_require_corpus_identity_digests():
    payload = _valid_dataset([_insufficient_evidence_case()])
    dataset = validate_qa_citation_payload(payload, source_path="memory://digests")
    assert dataset.corpus.identity_digest == LOCKED_IDENTITY_DIGEST
    assert dataset.corpus.metadata_text_digest == LOCKED_METADATA_TEXT_DIGEST


def test_reject_missing_corpus_identity_digest():
    payload = _valid_dataset([_insufficient_evidence_case()])
    payload["corpus"] = {
        key: value
        for key, value in payload["corpus"].items()
        if key != "identity_digest"
    }
    with pytest.raises(QaCitationDatasetError, match="identity_digest is required"):
        validate_qa_citation_payload(payload, source_path="memory://missing-digest")


def test_reject_incorrect_corpus_identity_digest():
    payload = _valid_dataset([_insufficient_evidence_case()])
    payload["corpus"] = dict(
        payload["corpus"],
        identity_digest="0" * 64,
    )
    with pytest.raises(QaCitationDatasetError, match="does not match the locked extract"):
        validate_qa_citation_payload(payload, source_path="memory://wrong-digest")


def test_reject_malformed_corpus_identity_digest():
    payload = _valid_dataset([_insufficient_evidence_case()])
    payload["corpus"] = dict(payload["corpus"], identity_digest="NOT-A-DIGEST")
    with pytest.raises(QaCitationDatasetError, match="64-character lowercase hex"):
        validate_qa_citation_payload(payload, source_path="memory://malformed-digest")


def test_reject_optional_arbitrary_hash_field():
    payload = _valid_dataset([_insufficient_evidence_case()])
    payload["corpus"] = dict(payload["corpus"], hash="abc")
    with pytest.raises(QaCitationDatasetError, match="unsupported field"):
        validate_qa_citation_payload(payload, source_path="memory://optional-hash")


def test_real_extract_membership_for_supporting_chunk_ids():
    index = load_locked_extract_index()
    record = index.by_chunk_id[REAL_CHUNK_ID]
    assert record.document_id == REAL_DOCUMENT_ID
    assert record.chunk_index == 1
    assert REAL_EXCERPT in record.text
    dataset = validate_qa_citation_payload(
        _valid_dataset([_labeled_student_support_case()]),
        source_path="memory://membership",
    )
    assert dataset.labeled_cases[0].supporting_chunk_ids == (REAL_CHUNK_ID,)


def test_reject_syntactically_valid_but_nonexistent_chunk_id():
    case = _labeled_student_support_case(
        supporting_document_ids=[NONEXISTENT_DOCUMENT_ID],
        supporting_chunk_ids=[NONEXISTENT_CHUNK_ID],
        reference_evidence=[
            {
                "chunk_id": NONEXISTENT_CHUNK_ID,
                "document_id": NONEXISTENT_DOCUMENT_ID,
                "excerpt": "TEST-ONLY excerpt that is not in the extract",
            }
        ],
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="not in the locked extract"):
        validate_qa_citation_payload(payload, source_path="memory://nonexistent")


def test_reject_excerpt_that_is_not_in_extract_text():
    case = _labeled_student_support_case(
        reference_evidence=[
            {
                "chunk_id": REAL_CHUNK_ID,
                "document_id": REAL_DOCUMENT_ID,
                "excerpt": "this excerpt is not present in the locked extract record",
            }
        ]
    )
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="verbatim contiguous"):
        validate_qa_citation_payload(payload, source_path="memory://excerpt")


def test_real_faq_document_ids_are_accepted():
    assert parse_citation_id(FAQ_CHUNK_ID) == (FAQ_DOCUMENT_ID, 0)
    case = _labeled_student_support_case(
        case_id="qac_test_faq_identifier",
        question="Is there a published student-facing article titled Brand New Article?",
        supporting_document_ids=[FAQ_DOCUMENT_ID],
        supporting_chunk_ids=[FAQ_CHUNK_ID],
        reference_evidence=[
            {
                "chunk_id": FAQ_CHUNK_ID,
                "document_id": FAQ_DOCUMENT_ID,
                "excerpt": FAQ_EXCERPT,
            }
        ],
        reviewer_notes="Identifier membership fixture for faq: document IDs, not evaluation gold.",
    )
    dataset = validate_qa_citation_payload(
        _valid_dataset([case]), source_path="memory://faq-id"
    )
    assert dataset.labeled_cases[0].supporting_chunk_ids == (FAQ_CHUNK_ID,)


def test_malformed_final_separator_is_rejected():
    with pytest.raises(QaCitationDatasetError, match="final '::'"):
        parse_citation_id("faq:5efbafa2-cc06-420f-990b-81548cd5451e:0")
    with pytest.raises(QaCitationDatasetError, match="Malformed citation identifier"):
        parse_citation_id("faq:5efbafa2-cc06-420f-990b-81548cd5451e::")
    with pytest.raises(QaCitationDatasetError, match="Malformed citation identifier"):
        parse_citation_id("::0")
    case = _labeled_student_support_case(
        supporting_chunk_ids=["faq:5efbafa2-cc06-420f-990b-81548cd5451e:0"]
    )
    with pytest.raises(QaCitationDatasetError, match="malformed chunk identifier"):
        validate_qa_citation_payload(
            _valid_dataset([case]), source_path="memory://bad-separator"
        )


def test_reject_malformed_top_level_structure():
    with pytest.raises(QaCitationDatasetError, match="JSON object"):
        validate_qa_citation_payload(["not", "an", "object"], source_path="memory://list")


def test_reject_missing_cases_list():
    payload = _valid_dataset([])
    payload.pop("cases")
    with pytest.raises(QaCitationDatasetError, match="cases"):
        validate_qa_citation_payload(payload, source_path="memory://no-cases")


def test_reject_unknown_case_field_instead_of_dropping_it():
    case = _labeled_student_support_case(gold_citation_ids=["invented"])
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="unsupported field"):
        validate_qa_citation_payload(payload, source_path="memory://unknown-field")


def test_reject_non_student_audience():
    case = _labeled_student_support_case(audience="faculty")
    payload = _valid_dataset([case])
    with pytest.raises(QaCitationDatasetError, match="audience"):
        validate_qa_citation_payload(payload, source_path="memory://audience")


def test_file_load_round_trip_does_not_drop_invalid_by_skipping(tmp_path):
    path = _write(tmp_path, "qa_citation_eval_dataset.json", _valid_dataset([]))
    dataset = load_qa_citation_dataset(path)
    assert dataset.total_count == 0
    assert dataset.labeled_cases == ()
    assert dataset.corpus.identity_digest == LOCKED_IDENTITY_DIGEST


def test_live_qa_citation_eval_dataset_loads_through_stage2_loader():
    path = (
        BACKEND_DIR / "benchmarks" / "evaluation" / "qa_citation_eval_dataset.json"
    )
    dataset = load_qa_citation_dataset(path)
    assert dataset.total_count == len(dataset.cases) == 36
    assert dataset.experiment_family == EXPERIMENT_FAMILY
    assert dataset.corpus.identity_digest == LOCKED_IDENTITY_DIGEST
    assert dataset.corpus.metadata_text_digest == LOCKED_METADATA_TEXT_DIGEST
    assert dataset.dataset_json_sha256 != LOCKED_IDENTITY_DIGEST
    assert {case.case_type for case in dataset.cases} == {
        CASE_TYPE_LABELED_STUDENT_SUPPORT,
        CASE_TYPE_INSUFFICIENT_EVIDENCE,
    }
    insufficient = [
        case for case in dataset.cases if case.case_type == CASE_TYPE_INSUFFICIENT_EVIDENCE
    ]
    assert len(insufficient) == 4
    for case in insufficient:
        assert case.reference_answer is None
        assert case.supporting_chunk_ids == ()
        assert case.reference_evidence == ()
    for case in dataset.cases:
        assert not faculty_scope_violations(case.question)
        assert not faculty_scope_violations(case.category)
        assert not faculty_scope_violations(case.reviewer_notes or "")
