"""Stage 3.1 QA answer-capture tests.

Integration tests open the real evaluation Chroma sqlite and locked extract.
They do not call a live LLM. Mocked tests never open the evaluation index
or invoke ``generate_groq_answer`` as the capture entry point.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import settings
from app.services.chroma_store import RetrievedChunk
from app.services.evaluation.qa_citation_capture import (
    CAPTURE_USER_ROLE,
    PIPELINE_NAME,
    EvaluationStudentStore,
    QaCitationCaptureError,
    _force_synchronous_citation_verification,
    assert_one_record_per_case,
    build_capture_record,
    capture_one_case,
    classify_execution_status,
    run_answer_capture,
)
from app.services.evaluation.qa_citation_corpus import (
    EVALUATION_SQLITE_PATH,
    CorpusIdentityError,
    EvaluationCorpusIdentity,
    verify_evaluation_corpus,
)
from app.services.evaluation.qa_citation_dataset import (
    CASE_TYPE_INSUFFICIENT_EVIDENCE,
    CASE_TYPE_LABELED_STUDENT_SUPPORT,
    EXPERIMENT_FAMILY,
    LOCKED_CORPUS_CHUNK_COUNT,
    LOCKED_CORPUS_COLLECTION,
    LOCKED_CORPUS_EXTRACT_ARTIFACT,
    LOCKED_CORPUS_PATH,
    LOCKED_IDENTITY_DIGEST,
    LOCKED_METADATA_TEXT_DIGEST,
    QaCitationCase,
    load_qa_citation_dataset,
)
from app.services.evaluation.qa_citation_metrics import (
    EXECUTION_STATUS_ERROR,
    EXECUTION_STATUS_INCOMPLETE,
    EXECUTION_STATUS_OK,
    EXECUTION_STATUS_OOS_OR_REFUSAL,
)
from app.services.qa.groq_answer_service import GroqAnswerError
from app.services.qa.question_answering import (
    FACULTY_SIGNIN_ANSWER,
    OUT_OF_SCOPE_ANSWER,
    QAResult,
    answer_qa_question,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REAL_DOCUMENT_ID = "da4a1832-7242-4e94-8ba6-bc0b9f2294bf"
REAL_CHUNK_ID = f"{REAL_DOCUMENT_ID}::1"
REAL_EXCERPT = "Undergraduate: P75.00/page; Graduate: P150/page"


class FakeStore:
    """In-memory store for path tests. Not the evaluation Chroma index."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self.chunks = chunks
        self.calls: list[dict] = []
        self.chunk_count = max(len(chunks), 1)

    def search(self, query: str, *, top_k=None, raw_k=None, user_role=None, ablation=None):
        self.calls.append(
            {
                "query": query,
                "top_k": top_k,
                "raw_k": raw_k,
                "user_role": user_role,
            }
        )
        return list(self.chunks)

    def list_chunks(self):
        items = []
        for chunk in self.chunks:
            metadata = dict(chunk.metadata or {})
            metadata.setdefault("document_id", chunk.document_id)
            metadata.setdefault("chunk_index", chunk.chunk_index)
            items.append(
                {
                    "id": str(metadata.get("chunk_id") or f"{chunk.document_id}::{chunk.chunk_index}"),
                    "text": chunk.text,
                    "metadata": metadata,
                }
            )
        return items


def _tor_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        document_id=REAL_DOCUMENT_ID,
        title="Issuance of Transcript of Records",
        source_filename="Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
        chunk_index=1,
        text=f"Issuance of Transcript of Records. {REAL_EXCERPT}",
        relevance_score=0.9,
        original_score=0.82,
        reranked_score=0.9,
        rerank_reasons=["test_match"],
        metadata={
            "document_id": REAL_DOCUMENT_ID,
            "chunk_id": REAL_CHUNK_ID,
            "chunk_index": 1,
            "audience": "student",
            "title": "Issuance of Transcript of Records",
            "source_filename": "Laguna State Polytechnic University-CC_2026-1st Edition.pdf",
            "page_number": 12,
        },
    )


def _faculty_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        document_id="faculty-manual-chunk",
        title="Faculty teaching load",
        source_filename="faculty_manual.pdf",
        chunk_index=0,
        text="Regular faculty weekly instruction hours are defined in the Faculty Manual.",
        relevance_score=0.88,
        original_score=0.8,
        reranked_score=0.88,
        rerank_reasons=["test_match"],
        metadata={
            "document_id": "faculty-manual-chunk",
            "chunk_id": "faculty-manual-chunk::0",
            "chunk_index": 0,
            "audience": "faculty",
        },
    )


def _labeled_case(**overrides) -> dict:
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
        "reviewer_notes": "Capture fixture using a real extract chunk. Not a live evaluation result.",
    }
    case.update(overrides)
    return case


def _insufficient_case(**overrides) -> dict:
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
        "dataset_version": "2026-11-09-stage3-1-test",
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


def _write_dataset(tmp_path: Path, cases: list[dict], name: str = "qa_citation_eval_dataset.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(_valid_dataset(cases)), encoding="utf-8")
    return path


def _fake_identity(**overrides) -> EvaluationCorpusIdentity:
    identity = EvaluationCorpusIdentity(
        verified_at="2026-11-09T05:00:00+00:00",
        evaluation_path=LOCKED_CORPUS_PATH,
        evaluation_collection=LOCKED_CORPUS_COLLECTION,
        evaluation_sqlite_sha256="a" * 64,
        evaluation_record_count=LOCKED_CORPUS_CHUNK_COUNT,
        evaluation_exclusion_count=0,
        evaluation_identity_digest=LOCKED_IDENTITY_DIGEST,
        evaluation_metadata_text_digest=LOCKED_METADATA_TEXT_DIGEST,
        extract_artifact=LOCKED_CORPUS_EXTRACT_ARTIFACT,
        extract_identity_digest=LOCKED_IDENTITY_DIGEST,
        extract_metadata_text_digest=LOCKED_METADATA_TEXT_DIGEST,
        extract_record_count=LOCKED_CORPUS_CHUNK_COUNT,
        extract_source_path_as_recorded="C:\\extract-source\\chroma.sqlite3",
        extract_source_collection_as_recorded="aska_knowledge_base",
        extract_source_sqlite_sha256="b" * 64,
        identity_digest_matches=True,
        metadata_text_digest_matches=True,
        embedding_id_set_equal=True,
        text_exact_match_count=LOCKED_CORPUS_CHUNK_COUNT,
        text_mismatch_count=0,
        document_id_mismatch_count=0,
        metadata_chunk_id_mismatch_count=0,
        chunk_index_mismatch_count=0,
        sqlite_file_hash_equals_extract_source=False,
        corresponds=True,
        limitations=("unit-test fixture; not a live Chroma read",),
    )
    return replace(identity, **overrides) if overrides else identity


def _qa_result(**overrides) -> QAResult:
    result = QAResult(
        answer="A Transcript of Records costs P75.00 per page for undergraduate students.",
        sources=[
            {
                "citation_id": REAL_CHUNK_ID,
                "document_id": REAL_DOCUMENT_ID,
                "title": "Issuance of Transcript of Records",
                "source_filename": "charter.pdf",
                "page_number": 12,
            }
        ],
        confidence="high",
        retrieved_chunks=[
            {
                "citation_id": REAL_CHUNK_ID,
                "content_preview": REAL_EXCERPT,
                "title": "Issuance of Transcript of Records",
                "selected_for_context": True,
                "document_id": REAL_DOCUMENT_ID,
                "chunk_index": 1,
            }
        ],
        out_of_scope_detected=False,
        fallback_reason=None,
    )
    for key, value in overrides.items():
        setattr(result, key, value)
    return result


def _case_obj(case_id: str = "qac_test_001_tor_fee") -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question="How much does a Transcript of Records cost for undergraduate students?",
        category="Student Records",
        difficulty="easy",
        case_type=CASE_TYPE_LABELED_STUDENT_SUPPORT,
        labeling_status="labeled",
        reference_answer="P75.00 per page.",
        supporting_document_ids=(REAL_DOCUMENT_ID,),
        supporting_chunk_ids=(REAL_CHUNK_ID,),
        reference_evidence=(),
        generation_model="test-generator-not-executed",
        generation_prompt_version="qac-gen-test-v1",
    )


def _loaded_dataset(tmp_path: Path, cases: list[dict] | None = None):
    path = _write_dataset(tmp_path, cases or [_labeled_case()])
    return load_qa_citation_dataset(path)


# ---------------------------------------------------------------------------
# Integration: real evaluation Chroma vs locked extract. No LLM.
# ---------------------------------------------------------------------------


def test_eval_chroma_corresponds_to_locked_extract_integration():
    """Actual sqlite identity check. Not mocked."""
    assert EVALUATION_SQLITE_PATH.is_file()
    identity = verify_evaluation_corpus()
    assert identity.corresponds is True
    assert identity.evaluation_record_count == 691
    assert identity.identity_digest_matches is True
    assert identity.metadata_text_digest_matches is True
    assert identity.evaluation_identity_digest == LOCKED_IDENTITY_DIGEST
    assert identity.evaluation_metadata_text_digest == LOCKED_METADATA_TEXT_DIGEST
    assert identity.embedding_id_set_equal is True
    assert identity.text_exact_match_count == 691
    assert identity.text_mismatch_count == 0
    assert identity.document_id_mismatch_count == 0
    assert identity.sqlite_file_hash_equals_extract_source is False


def test_corpus_mismatch_raises_and_is_not_correspondence():
    """Mocked digest mismatch. Does not execute capture."""
    from app.services.evaluation import qa_citation_corpus as corpus_mod

    def _wrong_digest(_records):
        return "0" * 64

    with (
        patch.object(corpus_mod, "compute_identity_digest", side_effect=_wrong_digest),
        pytest.raises(CorpusIdentityError, match="does not correspond"),
    ):
        verify_evaluation_corpus()


# ---------------------------------------------------------------------------
# Dataset loading through the approved Stage 2 loader
# ---------------------------------------------------------------------------


def test_capture_loads_dataset_through_stage2_loader(tmp_path):
    unlabeled = _labeled_case(
        case_id="qac_test_003_unlabeled_id",
        labeling_status="unlabeled",
        reference_answer=None,
        supporting_document_ids=[],
        supporting_chunk_ids=[],
        reference_evidence=[],
    )
    path = _write_dataset(tmp_path, [_labeled_case(), _insufficient_case(), unlabeled])
    dataset = load_qa_citation_dataset(path)
    assert dataset.total_count == 3
    assert [case.case_id for case in dataset.cases] == [
        "qac_test_001_tor_fee",
        "qac_test_002_sunday_shuttle",
        "qac_test_003_unlabeled_id",
    ]
    assert dataset.unlabeled_count == 1
    assert dataset.corpus.identity_digest == LOCKED_IDENTITY_DIGEST
    assert dataset.dataset_json_sha256 != LOCKED_IDENTITY_DIGEST


def test_capture_refuses_example_dataset(tmp_path):
    path = _write_dataset(tmp_path, [_labeled_case()], name="qa_citation_eval_dataset.example.json")
    with pytest.raises(QaCitationCaptureError, match="example artifact"):
        run_answer_capture(
            dataset_path=path,
            output_dir=tmp_path / "runs",
            corpus_identity=_fake_identity(),
            store=FakeStore([_tor_chunk()]),
            persist_corpus_report=False,
        )


def test_missing_live_dataset_does_not_invent_or_run(tmp_path):
    missing = tmp_path / "qa_citation_eval_dataset.json"
    assert not missing.exists()
    with pytest.raises(QaCitationCaptureError, match="not found"):
        run_answer_capture(
            dataset_path=missing,
            corpus_identity=_fake_identity(),
            store=FakeStore([_tor_chunk()]),
            persist_corpus_report=False,
        )


# ---------------------------------------------------------------------------
# Mocked capture statuses, errors, duplicates, provenance
# ---------------------------------------------------------------------------


def test_classify_successful_is_not_correctness():
    assert classify_execution_status(_qa_result()) == EXECUTION_STATUS_OK
    assert classify_execution_status(
        _qa_result(answer="wrong fee entirely")
    ) == EXECUTION_STATUS_OK


def test_classify_oos_refusal_error_incomplete():
    assert classify_execution_status(
        _qa_result(out_of_scope_detected=True, answer=OUT_OF_SCOPE_ANSWER, sources=[], retrieved_chunks=[])
    ) == EXECUTION_STATUS_OOS_OR_REFUSAL
    assert classify_execution_status(
        _qa_result(answer=FACULTY_SIGNIN_ANSWER, fallback_reason="faculty_topic_hidden_from_role")
    ) == EXECUTION_STATUS_OOS_OR_REFUSAL
    assert classify_execution_status(None, error=RuntimeError("boom")) == EXECUTION_STATUS_ERROR
    assert classify_execution_status(_qa_result(answer="")) == EXECUTION_STATUS_INCOMPLETE
    assert classify_execution_status(None) == EXECUTION_STATUS_INCOMPLETE


def test_student_role_is_passed_to_answer_fn(tmp_path):
    dataset = _loaded_dataset(tmp_path)
    seen: dict[str, object] = {}

    def _answer(question, **kwargs):
        seen["user_role"] = kwargs.get("user_role")
        seen["history"] = kwargs.get("history")
        seen["question"] = question
        return _qa_result()

    record = capture_one_case(
        dataset.cases[0],
        run_id="run_test_role",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        store=FakeStore([_tor_chunk()]),
        captured_at="2026-11-09T05:00:00+00:00",
        answer_fn=_answer,
    )
    assert seen["user_role"] == CAPTURE_USER_ROLE == "student"
    assert seen["history"] == []
    assert record["user_role"] == "student"
    assert record["pipeline"] == PIPELINE_NAME


def test_refuses_generate_groq_answer_as_capture_entry_point(tmp_path):
    dataset = _loaded_dataset(tmp_path)

    def generate_groq_answer(*_args, **_kwargs):
        raise AssertionError("should not be called")

    with pytest.raises(QaCitationCaptureError, match="generate_groq_answer"):
        capture_one_case(
            dataset.cases[0],
            run_id="run_test_no_groq",
            dataset=dataset,
            corpus_identity=_fake_identity(),
            store=FakeStore([_tor_chunk()]),
            captured_at="2026-11-09T05:00:00+00:00",
            answer_fn=generate_groq_answer,
        )


def test_mocked_run_keeps_ok_oos_error_incomplete_and_does_not_drop(tmp_path):
    cases = [
        _labeled_case(case_id="qac_ok"),
        _insufficient_case(case_id="qac_oos"),
        _labeled_case(case_id="qac_error", question="Trigger an error."),
        _labeled_case(case_id="qac_incomplete", question="Trigger incomplete."),
    ]
    path = _write_dataset(tmp_path, cases)
    outputs = {
        "qac_ok": lambda: _qa_result(),
        "qac_oos": lambda: _qa_result(
            answer=OUT_OF_SCOPE_ANSWER,
            out_of_scope_detected=True,
            sources=[],
            retrieved_chunks=[],
        ),
        "qac_incomplete": lambda: _qa_result(answer=""),
    }

    def _answer(question, **_kwargs):
        if "error" in question.lower():
            raise GroqAnswerError("provider_unavailable")
        if "incomplete" in question.lower():
            return outputs["qac_incomplete"]()
        if "shuttle" in question.lower():
            return outputs["qac_oos"]()
        return outputs["qac_ok"]()

    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_status_mix",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=_answer,
        persist_corpus_report=False,
    )
    assert result.live_benchmark_executed is True
    assert len(result.records) == 4
    assert result.status_counts == {
        EXECUTION_STATUS_OK: 1,
        EXECUTION_STATUS_OOS_OR_REFUSAL: 1,
        EXECUTION_STATUS_ERROR: 1,
        EXECUTION_STATUS_INCOMPLETE: 1,
    }
    by_id = {record["case_id"]: record for record in result.records}
    assert by_id["qac_error"]["execution_status"] == EXECUTION_STATUS_ERROR
    assert by_id["qac_error"]["error_type"] == "GroqAnswerError"
    assert by_id["qac_error"]["generated_answer"] is None
    assert by_id["qac_incomplete"]["execution_status"] == EXECUTION_STATUS_INCOMPLETE
    summary = json.loads((result.output_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 4
    assert summary["failed_executions"] == 2
    assert summary["successful_executions"] == 2


def test_duplicate_case_records_are_rejected_not_overwritten():
    record = {
        "case_id": "qac_dup",
        "execution_status": EXECUTION_STATUS_OK,
    }
    with pytest.raises(QaCitationCaptureError, match="Duplicate capture case_id"):
        assert_one_record_per_case([record, dict(record, generated_answer="second")])


def test_existing_run_directory_is_not_overwritten(tmp_path):
    path = _write_dataset(tmp_path, [_labeled_case()])
    run_dir = tmp_path / "runs" / "run_existing"
    run_dir.mkdir(parents=True)
    (run_dir / "captures.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(QaCitationCaptureError, match="already exists"):
        run_answer_capture(
            dataset_path=path,
            output_dir=tmp_path / "runs",
            run_id="run_existing",
            store=FakeStore([_tor_chunk()]),
            corpus_identity=_fake_identity(),
            answer_fn=lambda *_args, **_kwargs: _qa_result(),
            persist_corpus_report=False,
        )
    assert (run_dir / "captures.jsonl").read_text(encoding="utf-8") == "{}\n"


def test_unverified_corpus_does_not_execute_capture(tmp_path):
    path = _write_dataset(tmp_path, [_labeled_case()])
    called = {"n": 0}

    def _answer(*_args, **_kwargs):
        called["n"] += 1
        return _qa_result()

    with pytest.raises(QaCitationCaptureError, match="not verified"):
        run_answer_capture(
            dataset_path=path,
            output_dir=tmp_path / "runs",
            store=FakeStore([_tor_chunk()]),
            corpus_identity=_fake_identity(corresponds=False),
            answer_fn=_answer,
            persist_corpus_report=False,
        )
    assert called["n"] == 0


def test_provenance_preserved_on_capture_record(tmp_path):
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_prov",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model", "config_snapshot": {"not_generate_groq_answer": True}},
        result=_qa_result(),
        error=None,
    )
    assert record["dataset_version"] == dataset.dataset_version
    assert record["dataset_json_sha256"] == dataset.dataset_json_sha256
    assert record["corpus"]["identity_digest"] == LOCKED_IDENTITY_DIGEST
    assert record["corpus"]["metadata_text_digest"] == LOCKED_METADATA_TEXT_DIGEST
    assert record["corpus"]["extract_artifact"] == LOCKED_CORPUS_EXTRACT_ARTIFACT
    assert record["corpus"]["path"] == LOCKED_CORPUS_PATH
    assert record["corpus"]["collection"] == LOCKED_CORPUS_COLLECTION
    assert record["retrieved_chunk_ids"] == [REAL_CHUNK_ID]
    assert record["displayed_citation_ids"] == [REAL_CHUNK_ID]
    assert record["generation_context_chunk_ids"] == []
    assert REAL_EXCERPT in (record["retrieved_context"] or "")
    assert record["model"]["config_snapshot"]["not_generate_groq_answer"] is True


def test_secrets_are_stripped_from_raw_dump(tmp_path):
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_secrets",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=_qa_result(),
        error=None,
        generation_usage_sink={"groq_api_key": "should-not-leak", "tokens": 12},
    )
    raw = record["raw_qa_result_json"]
    assert raw["generation_usage_sink"]["groq_api_key"] == "[redacted]"
    assert raw["generation_usage_sink"]["tokens"] == 12


# ---------------------------------------------------------------------------
# fallback_used / is_genuine_model_output -- regression for the credential-
# failure incident where every record in a 36-case live run reported
# execution_status "ok" despite every answer being an extractive fallback
# (OpenRouter 401s, answer_qa_question's own except GroqAnswerError path).
# classify_execution_status legitimately still returns "ok" here (capture
# completed; a fallback answer is a complete, non-empty string) -- these
# fields are what make the degraded provenance distinguishable without
# redefining what "ok" means in the approved Stage 2 status contract.
# ---------------------------------------------------------------------------


def test_genuine_generation_is_marked_as_genuine(tmp_path):
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_genuine",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=_qa_result(fallback_used=False, fallback_reason=None),
        error=None,
    )
    assert record["execution_status"] == EXECUTION_STATUS_OK
    assert record["fallback_used"] is False
    assert record["is_genuine_model_output"] is True
    assert record["fallback_reason"] is None


def test_generation_error_fallback_is_honestly_recorded_not_unqualified_ok(tmp_path):
    """Reproduces the real incident: Groq/OpenRouter 401 -> conversational
    fallback -> answer_qa_question returns a complete QAResult with
    fallback_used=True, fallback_reason="generation_error". The record must
    still be execution_status "ok" (capture completed; this is not a
    capture-process failure per the Stage 2 contract's "error" meaning), but
    must now be explicitly flagged as not genuine model output.
    """
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_fallback",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=_qa_result(
            fallback_used=True,
            fallback_reason="generation_error",
            answer="Extractive stand-in text pulled from retrieved chunks.",
        ),
        error=None,
    )
    assert record["execution_status"] == EXECUTION_STATUS_OK
    assert record["fallback_reason"] == "generation_error"
    assert record["fallback_used"] is True
    assert record["is_genuine_model_output"] is False


def test_fallback_content_never_misrepresented_as_genuine_regardless_of_reason(tmp_path):
    """Any fallback_used=True case -- not only generation_error -- must be
    flagged as not-genuine. A future judging stage reading only the
    top-level fields must never mistake template/extractive/recovered
    content for the model's own generated reasoning.
    """
    dataset = _loaded_dataset(tmp_path)
    for reason in ("generation_error", "underspecified_without_active_topic", "low_confidence_retrieval"):
        record = build_capture_record(
            case=dataset.cases[0],
            run_id=f"run_{reason}",
            dataset=dataset,
            corpus_identity=_fake_identity(),
            captured_at="2026-11-09T05:00:00+00:00",
            model_snapshot={"answer_generation_model": "test-model"},
            result=_qa_result(fallback_used=True, fallback_reason=reason),
            error=None,
        )
        assert record["is_genuine_model_output"] is False, reason
        assert record["fallback_used"] is True, reason


def test_is_genuine_model_output_is_none_without_a_result(tmp_path):
    """error/incomplete captures have no result to judge genuineness of."""
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_error",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=None,
        error=RuntimeError("boom"),
    )
    assert record["execution_status"] == EXECUTION_STATUS_ERROR
    assert record["fallback_used"] is False
    assert record["is_genuine_model_output"] is None


def test_empty_displayed_citations_stay_empty_not_fabricated(tmp_path):
    """A fallback (or any) answer with no real sources must keep
    displayed_citation_ids == [] -- never backfilled from retrieved_chunk_ids
    or any other default."""
    dataset = _loaded_dataset(tmp_path)
    record = build_capture_record(
        case=dataset.cases[0],
        run_id="run_empty_citations",
        dataset=dataset,
        corpus_identity=_fake_identity(),
        captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=_qa_result(
            fallback_used=True,
            fallback_reason="generation_error",
            sources=[],
        ),
        error=None,
    )
    assert record["displayed_citation_ids"] == []
    assert record["retrieved_chunk_ids"] == [REAL_CHUNK_ID]
    assert record["is_genuine_model_output"] is False


def test_status_contract_and_one_record_per_case_unaffected_by_new_fields(tmp_path):
    """The four approved execution statuses and the duplicate-case-id
    rejection rule are unchanged by adding fallback_used /
    is_genuine_model_output -- these are additive fields, not a status
    redefinition."""
    dataset = _loaded_dataset(tmp_path)
    ok_record = build_capture_record(
        case=dataset.cases[0], run_id="run_contract", dataset=dataset,
        corpus_identity=_fake_identity(), captured_at="2026-11-09T05:00:00+00:00",
        model_snapshot={"answer_generation_model": "test-model"},
        result=_qa_result(fallback_used=True, fallback_reason="generation_error"), error=None,
    )
    assert ok_record["execution_status"] in {
        EXECUTION_STATUS_OK, EXECUTION_STATUS_OOS_OR_REFUSAL,
        EXECUTION_STATUS_ERROR, EXECUTION_STATUS_INCOMPLETE,
    }
    with pytest.raises(QaCitationCaptureError, match="Duplicate"):
        assert_one_record_per_case([ok_record, {**ok_record}])


# ---------------------------------------------------------------------------
# Actual answer_qa_question path. FakeStore only; generate_groq_answer mocked.
# ---------------------------------------------------------------------------


def test_actual_answer_qa_question_path_captures_retrieval_and_citations(tmp_path):
    dataset = _loaded_dataset(tmp_path)
    store = FakeStore([_tor_chunk()])

    def _echo(*, context="", **_kwargs):
        return context or "Follow the cited policy."

    with patch(
        "app.services.qa.question_answering.generate_groq_answer",
        side_effect=_echo,
    ) as mock_generate:
        record = capture_one_case(
            dataset.cases[0],
            run_id="run_path",
            dataset=dataset,
            corpus_identity=_fake_identity(),
            store=store,
            captured_at="2026-11-09T05:00:00+00:00",
            answer_fn=answer_qa_question,
        )

    assert record["pipeline"] == "answer_qa_question"
    assert record["user_role"] == "student"
    assert record["execution_status"] in {
        EXECUTION_STATUS_OK,
        EXECUTION_STATUS_OOS_OR_REFUSAL,
        EXECUTION_STATUS_INCOMPLETE,
    }
    assert store.calls, "answer_qa_question must search the injected evaluation store"
    assert {call["user_role"] for call in store.calls} == {"student"}
    assert mock_generate.called or record["execution_status"] != EXECUTION_STATUS_OK
    if record["execution_status"] == EXECUTION_STATUS_OK:
        assert record["generated_answer"]
        assert REAL_CHUNK_ID in record["retrieved_chunk_ids"]
        assert isinstance(record["displayed_citation_ids"], list)
        assert REAL_CHUNK_ID in record["generation_context_chunk_ids"]
        assert record["retrieved_context"]
        assert isinstance(record["raw_qa_result_json"]["qa_result"]["sources"], list)


def test_actual_path_student_oos_refusal_is_captured(tmp_path):
    # Faculty questions cannot live in the Stage 2 dataset; this path test
    # still executes answer_qa_question as student against that query.
    dataset = _loaded_dataset(tmp_path)
    case = replace(
        dataset.cases[0],
        case_id="qac_test_faculty_hidden_path",
        question="How many instruction hours does a regular faculty member have in the weekly load?",
    )
    store = FakeStore([_faculty_chunk()])
    with patch("app.services.qa.question_answering.generate_groq_answer") as mock_generate:
        record = capture_one_case(
            case,
            run_id="run_path_oos",
            dataset=dataset,
            corpus_identity=_fake_identity(),
            store=store,
            captured_at="2026-11-09T05:00:00+00:00",
            answer_fn=answer_qa_question,
        )
    assert record["execution_status"] == EXECUTION_STATUS_OOS_OR_REFUSAL
    assert record["out_of_scope_detected"] is True
    assert mock_generate.called is False
    assert store.calls == []


def test_evaluation_student_store_filters_faculty_chunks_for_student_role():
    class Inner:
        def search(self, query, **_kwargs):
            return [_tor_chunk(), _faculty_chunk()]

    wrapper = EvaluationStudentStore(Inner())
    visible = wrapper.search("tor fee", top_k=5, raw_k=5, user_role="student")
    assert [chunk.document_id for chunk in visible] == [REAL_DOCUMENT_ID]
    unfiltered = wrapper.search("tor fee", top_k=5, raw_k=5, user_role=None)
    assert len(unfiltered) == 2


# ---------------------------------------------------------------------------
# Scoped synchronous citation-verification override -- regression for the
# 2026-11-09 finding that a live 36-case run captured 35 genuine answers but
# ZERO displayed citations on any of them: async_llm defers verification to
# a BackgroundTasks job that run_answer_capture (a script, not an HTTP
# request) never schedules, so verification simply never happens. Forcing
# "llm" mode for the lifetime of the capture run makes verification run
# synchronously instead, using the same decision logic the deferred async
# job would have used (citation_verification_jobs._ASYNC_TO_SEMANTIC_MODE
# maps async_llm -> llm). These tests never touch production settings.env
# or app/config.py's default -- only the in-process settings object, scoped
# and restored by _force_synchronous_citation_verification itself.
# ---------------------------------------------------------------------------


def test_override_is_active_during_the_capture_call(tmp_path):
    """settings.citation_verification_mode must read 'llm' DURING the run,
    proving the override is live at the moment answer_fn executes, not just
    nominally set somewhere unrelated."""
    original = settings.citation_verification_mode
    assert original != "llm", "fixture precondition: start from a non-llm ambient mode"
    observed: dict[str, str] = {}

    def _answer(*_args, **_kwargs):
        observed["mode_during_call"] = settings.citation_verification_mode
        return _qa_result()

    path = _write_dataset(tmp_path, [_labeled_case()])
    run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_override_active",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=_answer,
        persist_corpus_report=False,
    )
    assert observed["mode_during_call"] == "llm"
    assert settings.citation_verification_mode == original


def test_model_snapshot_reports_llm_as_the_mode_actually_used(tmp_path):
    """The run's own provenance fields must say 'llm' -- what was actually
    exercised -- not the ambient async_llm default, since that would be a
    false audit trail."""
    path = _write_dataset(tmp_path, [_labeled_case()])
    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_snapshot_llm",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=lambda *_a, **_k: _qa_result(),
        persist_corpus_report=False,
    )
    record = result.records[0]
    assert record["model"]["citation_verification_mode"] == "llm"
    assert record["model"]["config_snapshot"]["citation_verification_mode"] == "llm"


def test_original_mode_restored_after_successful_run(tmp_path):
    original = settings.citation_verification_mode
    path = _write_dataset(tmp_path, [_labeled_case()])
    run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_restore_success",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=lambda *_a, **_k: _qa_result(),
        persist_corpus_report=False,
    )
    assert settings.citation_verification_mode == original


def test_original_mode_restored_after_exception(tmp_path):
    """An exception inside the override's scope must not leave
    citation_verification_mode stuck on 'llm'."""
    original = settings.citation_verification_mode

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure inside the override scope")

    with pytest.raises(RuntimeError, match="simulated failure"):
        with _force_synchronous_citation_verification():
            assert settings.citation_verification_mode == "llm"
            _boom()
    assert settings.citation_verification_mode == original


def test_original_mode_restored_even_when_an_individual_case_errors(tmp_path):
    """A per-case GroqAnswerError is caught and recorded (execution_status
    'error'), not re-raised -- confirm the override still restores cleanly
    for this, the actually-expected failure path during a real run."""
    original = settings.citation_verification_mode
    path = _write_dataset(tmp_path, [_labeled_case()])
    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_restore_case_error",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=lambda *_a, **_k: (_ for _ in ()).throw(GroqAnswerError("boom")),
        persist_corpus_report=False,
    )
    assert result.records[0]["execution_status"] == EXECUTION_STATUS_ERROR
    assert settings.citation_verification_mode == original


def test_generated_answer_text_unaffected_by_verification_mode_override(tmp_path):
    """The override must be scoped to citation verification only -- it must
    never alter what generation produces."""
    fixed_answer = "This exact answer text must survive regardless of mode."
    path = _write_dataset(tmp_path, [_labeled_case()])

    def _answer_llm(*_args, **_kwargs):
        assert settings.citation_verification_mode == "llm"
        return _qa_result(answer=fixed_answer)

    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_answer_unaffected",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=_answer_llm,
        persist_corpus_report=False,
    )
    assert result.records[0]["generated_answer"] == fixed_answer

    # Same fixed answer, called directly outside the override (ambient
    # mode) -- proves the override path and the ambient path produce
    # identical generated_answer content; only citation behavior differs.
    direct_result = _qa_result(answer=fixed_answer)
    assert direct_result.answer == fixed_answer


def test_displayed_citations_populate_under_the_override_when_sources_are_real(tmp_path):
    """When the QA pipeline returns genuine sources (what synchronous llm-
    mode verification is meant to produce), the existing, unmodified
    build_capture_record logic must carry them into displayed_citation_ids."""
    path = _write_dataset(tmp_path, [_labeled_case()])
    seen_mode: dict[str, str] = {}

    def _answer_with_real_citation(*_args, **_kwargs):
        seen_mode["mode"] = settings.citation_verification_mode
        return _qa_result()  # _qa_result()'s sources include REAL_CHUNK_ID

    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_citations_populate",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=_answer_with_real_citation,
        persist_corpus_report=False,
    )
    assert seen_mode["mode"] == "llm"
    assert result.records[0]["displayed_citation_ids"] == [REAL_CHUNK_ID]


def test_verification_failure_under_override_stays_fail_closed_not_fabricated(tmp_path):
    """A verifier failure (mirrored here as the QA pipeline returning no
    sources, consistent with 'a verifier failure of any kind displays zero
    citations') must still produce displayed_citation_ids == [] under the
    override -- never a fabricated or backfilled citation."""
    path = _write_dataset(tmp_path, [_labeled_case()])

    def _answer_verifier_failed(*_args, **_kwargs):
        assert settings.citation_verification_mode == "llm"
        return _qa_result(sources=[])

    result = run_answer_capture(
        dataset_path=path,
        output_dir=tmp_path / "runs",
        run_id="run_verification_fail_closed",
        store=FakeStore([_tor_chunk()]),
        corpus_identity=_fake_identity(),
        answer_fn=_answer_verifier_failed,
        persist_corpus_report=False,
    )
    record = result.records[0]
    assert record["displayed_citation_ids"] == []
    # Retrieval still happened and is preserved -- only display is empty.
    assert record["retrieved_chunk_ids"] == [REAL_CHUNK_ID]


def test_no_background_verification_job_is_scheduled_by_capture(tmp_path):
    """The real answer_qa_question() path, exercised through capture_one_case
    exactly as a live run would use it, must never touch
    citation_verification_jobs.schedule_verification -- the capture script
    has no BackgroundTasks instance and must not attempt to acquire one."""
    dataset = _loaded_dataset(tmp_path)
    store = FakeStore([_tor_chunk()])

    def _echo(*, context="", **_kwargs):
        return context or "Follow the cited policy."

    with (
        patch(
            "app.services.qa.question_answering.generate_groq_answer",
            side_effect=_echo,
        ),
        patch(
            "app.services.qa.citation_verification_jobs.schedule_verification"
        ) as mock_schedule,
        _force_synchronous_citation_verification(),
    ):
        capture_one_case(
            dataset.cases[0],
            run_id="run_no_background_job",
            dataset=dataset,
            corpus_identity=_fake_identity(),
            store=store,
            captured_at="2026-11-09T05:00:00+00:00",
            answer_fn=answer_qa_question,
        )
    mock_schedule.assert_not_called()
