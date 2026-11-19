"""Stage 3.2B Phase 5 Part B tests: full run aggregation and reporting.

All judge "calls" here are local Python fakes. No real HTTP/LLM call is
made anywhere in this file, and no live judging run is executed. Citation
ids are real, locked-extract chunk ids (read-only lookup), never from any
capture run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.services.evaluation.qa_citation_dataset import (
    CorpusSnapshot,
    QaCitationCase,
    QaCitationDataset,
    load_locked_extract_index,
)
from app.services.evaluation.qa_citation_run_report import (
    JUDGING_REPORT_VERSION,
    QaCitationRunReportError,
    RubricJudgeIdentities,
    run_qa_citation_judging,
    run_qa_citation_judging_from_capture_run_dir,
)

_EXTRACT = load_locked_extract_index()
_REAL_IDS = list(_EXTRACT.by_chunk_id.keys())
ID_A, ID_B, ID_C, ID_D = _REAL_IDS[0], _REAL_IDS[1], _REAL_IDS[2], _REAL_IDS[3]
DOC_A = _EXTRACT.by_chunk_id[ID_A].document_id
DOC_B = _EXTRACT.by_chunk_id[ID_B].document_id


def _identities(prefix: str) -> RubricJudgeIdentities:
    return RubricJudgeIdentities(
        primary_model=f"{prefix}-primary-model",
        primary_provider=f"{prefix}-provider-a",
        secondary_model=f"{prefix}-secondary-model",
        secondary_provider=f"{prefix}-provider-b",
        prompt_version=f"{prefix}_v1",
        prompt_sha256="0" * 64,
    )


def _answerable_case(case_id: str, *, category: str = "Fees", chunk_id: str = ID_A) -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question=f"Question for {case_id}?",
        category=category,
        difficulty="easy",
        case_type="labeled_student_support",
        labeling_status="labeled",
        reference_answer="The reference answer.",
        supporting_document_ids=(_EXTRACT.by_chunk_id[chunk_id].document_id,),
        supporting_chunk_ids=(chunk_id,),
        reference_evidence=(),
        generation_model="n/a",
        generation_prompt_version="n/a",
    )


def _insufficient_evidence_case(case_id: str, *, category: str = "IT Services") -> QaCitationCase:
    return QaCitationCase(
        case_id=case_id,
        question=f"Question for {case_id}?",
        category=category,
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
        dataset_json_sha256="a" * 64,
        source_path="<memory>",
    )


_CORPUS_DICT = {
    "path": "backend/data/chroma_evaluation",
    "collection": "aska_evaluation",
    "chunk_count": 691,
    "extract_artifact": "backend/benchmarks/results/chroma_record_extraction_20261104T104214Z.json",
    "identity_digest": "fcb324dad73c41684e771defec0a36937ddde014df858c3f020aaf914774c85b",
    "metadata_text_digest": "7cec45b38d017d17f4f7b39abf3dc2d52a4f6f832b179ea2b70c37c6086262d7",
    "evaluation_sqlite_sha256": "b" * 64,
    "corresponds_to_locked_extract": True,
}


def _record(
    case_id: str,
    *,
    genuine: bool = True,
    displayed_citation_ids: list[str] | None = None,
    execution_status: str = "ok",
) -> dict[str, Any]:
    ids = displayed_citation_ids if displayed_citation_ids is not None else [ID_A]
    return {
        "case_id": case_id,
        "execution_status": execution_status,
        "is_genuine_model_output": genuine if execution_status == "ok" else None,
        "fallback_used": (not genuine) if execution_status == "ok" else False,
        "generated_answer": f"Answer for {case_id}." if genuine else "fallback text",
        "retrieved_context": f"[{ID_A}] evidence text",
        "displayed_citation_ids": ids,
        "source_metadata": [],
        "corpus": dict(_CORPUS_DICT),
    }


def _qa_response(correctness=4, completeness=4, relevance=4, faithfulness=4) -> dict[str, Any]:
    return {
        "evaluation_status": "evaluated",
        "correctness": correctness,
        "completeness": completeness,
        "relevance": relevance,
        "faithfulness": faithfulness,
        "explanation": {k: "ok" for k in ("correctness", "completeness", "relevance", "faithfulness")},
        "faithfulness_evidence_refs": [ID_A],
    }


def _citation_response(claim_id: str = "c1", supporting: list[str] | None = None) -> dict[str, Any]:
    return {
        "evaluation_status": "evaluated",
        "claims": [
            {
                "claim_id": claim_id,
                "text": "A factual claim.",
                "requires_citation": True,
                "claim_support": "supported",
                "supporting_displayed_ids": supporting if supporting is not None else [ID_A],
            }
        ],
    }


def _ie_response(declined=True, unsupported=False) -> dict[str, Any]:
    return {
        "evaluation_status": "evaluated",
        "correctly_declined": {
            "result": declined,
            "explanation": "checked",
            "answer_excerpts": ["excerpt"],
            "evidence_refs": ["evidence"],
        },
        "unsupported_claim_detected": {
            "result": unsupported,
            "explanation": "checked",
            "answer_excerpts": ["excerpt"],
            "evidence_refs": ["evidence"],
        },
    }


def _always(response: Any):
    return lambda record: response


def test_full_run_aggregation_hand_computed(tmp_path: Path):
    cases = (
        _answerable_case("qac_1", category="Fees"),
        _answerable_case("qac_2", category="Fees"),
        _insufficient_evidence_case("ie_1"),
    )
    dataset = _dataset(cases)
    records = [
        _record("qac_1"),
        _record("qac_2"),
        _record("ie_1", displayed_citation_ids=[]),
    ]

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response(correctness=4)),
        qa_secondary_judge=_always(_qa_response(correctness=2)),
        insufficient_evidence_primary_judge=_always(_ie_response(declined=True, unsupported=False)),
        insufficient_evidence_secondary_judge=_always(_ie_response(declined=True, unsupported=False)),
        citation_primary_judge=_always(_citation_response("c1")),
        citation_secondary_judge=_always(_citation_response("c1")),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="qac_capture_test_run",
        capture_file_sha256="c" * 64,
        output_dir=tmp_path,
    )

    assert result.summary["report_version"] == JUDGING_REPORT_VERSION
    qa_agg = result.summary["qa_aggregation"]
    assert qa_agg["judged_count"] == 2
    # correctness mean per case: (4+2)/2 = 3.0 for both cases -> run mean 3.0
    assert qa_agg["dimension_means"]["correctness"] == pytest.approx(3.0)
    # completeness/relevance/faithfulness: both judges scored 4 -> mean 4.0
    assert qa_agg["dimension_means"]["completeness"] == pytest.approx(4.0)
    assert qa_agg["judge_disagreement_rate"]["numerator"] == 2  # both cases disagree on correctness
    assert qa_agg["judge_disagreement_rate"]["denominator"] == 2
    # correctness distribution: two cases, primary=4 x2, secondary=2 x2
    assert qa_agg["dimension_distributions"]["correctness"]["4"] == 2
    assert qa_agg["dimension_distributions"]["correctness"]["2"] == 2

    citation_agg = result.summary["citation_aggregation"]
    assert citation_agg["judged_case_count"] == 2
    assert citation_agg["judge_data_points_aggregated"] == 4  # 2 cases x 2 judges
    # each (case, judge) data point: 1 citation required, 1 supported, 1 displayed id
    assert citation_agg["citation_precision"]["numerator"] == 4
    assert citation_agg["citation_precision"]["denominator"] == 4
    assert citation_agg["citation_precision"]["value"] == pytest.approx(1.0)

    ie_agg = result.summary["insufficient_evidence_aggregation"]
    assert ie_agg["judged_count"] == 1
    assert ie_agg["correctly_declined_agreement_count"] == 1

    pop = result.summary["population_summary"]
    assert pop["answerable_total"] == 2
    assert pop["insufficient_evidence_total"] == 1
    assert pop["fallback_vs_genuine_counts"]["genuine"] == 3

    assert len(result.judgment_rows) == 3
    output_files = {p.name for p in result.output_dir.iterdir()}
    assert output_files == {"judgments.jsonl", "judging_summary.json"}
    written_summary = json.loads((result.output_dir / "judging_summary.json").read_text())
    assert written_summary["capture_run_id"] == "qac_capture_test_run"
    assert written_summary["capture_file_sha256"] == "c" * 64
    assert written_summary["dataset_version"] == "test-fixture-v1"
    assert written_summary["corpus"] == _CORPUS_DICT
    lines = (result.output_dir / "judgments.jsonl").read_text().strip().splitlines()
    assert len(lines) == 3


def test_empty_insufficient_evidence_population_does_not_crash(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1")]
    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="d" * 64,
        output_dir=tmp_path,
    )
    ie_agg = result.summary["insufficient_evidence_aggregation"]
    assert ie_agg["total_count"] == 0
    assert ie_agg["judged_count"] == 0
    pop = result.summary["population_summary"]
    assert pop["insufficient_evidence_total"] == 0


def test_duplicate_case_records_rejected(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1"), _record("qac_1")]
    with pytest.raises(QaCitationRunReportError, match="Duplicate"):
        run_qa_citation_judging(
            dataset=dataset,
            capture_records=records,
            qa_primary_judge=_always(_qa_response()),
            qa_secondary_judge=_always(_qa_response()),
            insufficient_evidence_primary_judge=_always(_ie_response()),
            insufficient_evidence_secondary_judge=_always(_ie_response()),
            citation_primary_judge=_always(_citation_response()),
            citation_secondary_judge=_always(_citation_response()),
            qa_judge_identities=_identities("qa"),
            insufficient_evidence_judge_identities=_identities("ie"),
            citation_judge_identities=_identities("cite"),
            capture_run_id="run",
            capture_file_sha256="e" * 64,
            output_dir=tmp_path,
        )


def test_unmatched_case_id_rejected(tmp_path: Path):
    dataset = _dataset((_answerable_case("qac_1"),))
    records = [_record("qac_not_in_dataset")]
    with pytest.raises(QaCitationRunReportError, match="no matching case"):
        run_qa_citation_judging(
            dataset=dataset,
            capture_records=records,
            qa_primary_judge=_always(_qa_response()),
            qa_secondary_judge=_always(_qa_response()),
            insufficient_evidence_primary_judge=_always(_ie_response()),
            insufficient_evidence_secondary_judge=_always(_ie_response()),
            citation_primary_judge=_always(_citation_response()),
            citation_secondary_judge=_always(_citation_response()),
            qa_judge_identities=_identities("qa"),
            insufficient_evidence_judge_identities=_identities("ie"),
            citation_judge_identities=_identities("cite"),
            capture_run_id="run",
            capture_file_sha256="f" * 64,
            output_dir=tmp_path,
        )


def test_missing_judge_results_mixed_with_success_bucketed_correctly(tmp_path: Path):
    cases = (_answerable_case("qac_ok"), _answerable_case("qac_partial"))
    dataset = _dataset(cases)
    records = [_record("qac_ok"), _record("qac_partial")]

    def qa_secondary(record: Mapping[str, Any]):
        if record["case_id"] == "qac_partial":
            raise RuntimeError("secondary judge down")
        return _qa_response()

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=qa_secondary,
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="0" * 64,
        output_dir=tmp_path,
    )
    qa_agg = result.summary["qa_aggregation"]
    assert qa_agg["judged_count"] == 1
    assert qa_agg["judging_failed_partial_count"] == 1
    # the partial failure must not contribute to the dimension means
    assert qa_agg["dimension_means"]["correctness"] == pytest.approx(4.0)


def test_partial_failures_excluded_from_score_aggregation_but_counted(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1")]

    def failing_secondary(record: Mapping[str, Any]):
        raise RuntimeError("down")

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=failing_secondary,
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="1" * 64,
        output_dir=tmp_path,
    )
    citation_agg = result.summary["citation_aggregation"]
    assert citation_agg["judged_case_count"] == 0
    assert citation_agg["judging_failed_partial_count"] == 1
    assert citation_agg["citation_precision"]["denominator"] == 0
    assert citation_agg["citation_precision"]["value"] is None


def test_invalid_citation_ids_stay_in_denominators(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    fake_id = "not-a-real-document::0"
    records = [_record("qac_1", displayed_citation_ids=[ID_A, fake_id])]

    def citation_response(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "evaluation_status": "evaluated",
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "claim backed by the real id",
                    "requires_citation": True,
                    "claim_support": "supported",
                    "supporting_displayed_ids": [ID_A],
                }
            ],
        }

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=citation_response,
        citation_secondary_judge=citation_response,
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="2" * 64,
        output_dir=tmp_path,
    )
    citation_agg = result.summary["citation_aggregation"]
    # 2 displayed ids (1 real + 1 fake) per judge x 2 judges = 4 in the
    # precision/validity denominator; only the real id is a precision hit
    # or counts as valid.
    assert citation_agg["citation_precision"]["denominator"] == 4
    assert citation_agg["citation_precision"]["numerator"] == 2
    assert citation_agg["citation_validity"]["numerator"] == 2
    assert citation_agg["citation_validity"]["denominator"] == 4


def test_whole_run_zero_denominator_citation_metrics_are_null(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1", displayed_citation_ids=[])]

    def no_claims(record: Mapping[str, Any]) -> dict[str, Any]:
        return {"evaluation_status": "evaluated", "claims": []}

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=no_claims,
        citation_secondary_judge=no_claims,
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="3" * 64,
        output_dir=tmp_path,
    )
    citation_agg = result.summary["citation_aggregation"]
    for name in (
        "citation_precision",
        "citation_completeness",
        "claim_support_rate",
        "unsupported_claim_rate",
        "citation_validity",
    ):
        assert citation_agg[name]["denominator"] == 0
        assert citation_agg[name]["value"] is None


def test_category_minimum_sample_size_gates_by_category_breakdown(tmp_path: Path):
    small_category_cases = [_answerable_case(f"small_{i}", category="Admissions") for i in range(4)]
    big_category_cases = [_answerable_case(f"big_{i}", category="Fees") for i in range(5)]
    cases = tuple(small_category_cases + big_category_cases)
    dataset = _dataset(cases)
    records = [_record(c.case_id) for c in cases]

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="4" * 64,
        output_dir=tmp_path,
    )
    by_category = result.summary["qa_aggregation"]["by_category"]
    assert "Fees" in by_category
    assert by_category["Fees"]["judged_count"] == 5
    assert "Admissions" not in by_category


def test_insufficient_evidence_results_never_leak_into_qa_or_citation_aggregation(tmp_path: Path):
    cases = (_answerable_case("qac_1"), _insufficient_evidence_case("ie_1"))
    dataset = _dataset(cases)
    records = [_record("qac_1"), _record("ie_1", displayed_citation_ids=[])]

    # If insufficient-evidence judges were ever called for the answerable
    # case, or QA/citation judges were ever called for the insufficient-
    # evidence case, this would raise and fail the test.
    def qa_judge_only_for_answerable(record: Mapping[str, Any]) -> dict[str, Any]:
        assert record["case_id"] == "qac_1"
        return _qa_response()

    def citation_judge_only_for_answerable(record: Mapping[str, Any]) -> dict[str, Any]:
        assert record["case_id"] == "qac_1"
        return _citation_response()

    def ie_judge_only_for_insufficient_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
        assert record["case_id"] == "ie_1"
        return _ie_response()

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=qa_judge_only_for_answerable,
        qa_secondary_judge=qa_judge_only_for_answerable,
        insufficient_evidence_primary_judge=ie_judge_only_for_insufficient_evidence,
        insufficient_evidence_secondary_judge=ie_judge_only_for_insufficient_evidence,
        citation_primary_judge=citation_judge_only_for_answerable,
        citation_secondary_judge=citation_judge_only_for_answerable,
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="5" * 64,
        output_dir=tmp_path,
    )
    assert result.summary["qa_aggregation"]["judged_count"] == 1
    assert result.summary["citation_aggregation"]["judged_case_count"] == 1
    assert result.summary["insufficient_evidence_aggregation"]["judged_count"] == 1
    # the insufficient-evidence case never appears in qa_outcomes/citation_outcomes
    assert {o.case_id for o in result.qa_outcomes} == {"qac_1"}
    assert {o.case_id for o in result.citation_outcomes} == {"qac_1"}
    assert {o.case_id for o in result.insufficient_evidence_outcomes} == {"ie_1"}


def test_run_metadata_and_hashes_match_real_source_values(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1")]

    result = run_qa_citation_judging(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="qac_capture_real_run_id",
        capture_file_sha256="deadbeef" * 8,
        output_dir=tmp_path,
    )
    assert result.summary["dataset_version"] == dataset.dataset_version
    assert result.summary["dataset_json_sha256"] == dataset.dataset_json_sha256
    assert result.summary["capture_run_id"] == "qac_capture_real_run_id"
    assert result.summary["capture_file_sha256"] == "deadbeef" * 8
    assert result.summary["judges"]["qa_rubric"] == _identities("qa").as_dict()
    assert result.summary["judges"]["citation_claim_rubric"] == _identities("cite").as_dict()


def test_second_run_with_same_run_id_does_not_overwrite(tmp_path: Path):
    cases = (_answerable_case("qac_1"),)
    dataset = _dataset(cases)
    records = [_record("qac_1")]
    kwargs = dict(
        dataset=dataset,
        capture_records=records,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        capture_run_id="run",
        capture_file_sha256="6" * 64,
        output_dir=tmp_path,
        run_id="fixed-run-id",
    )
    run_qa_citation_judging(**kwargs)
    with pytest.raises(QaCitationRunReportError, match="already exists"):
        run_qa_citation_judging(**kwargs)


def test_from_capture_run_dir_reads_real_capture_files_read_only(tmp_path: Path):
    capture_dir = tmp_path / "qac_capture_fixture_run"
    capture_dir.mkdir()
    records = [_record("qac_1")]
    captures_path = capture_dir / "captures.jsonl"
    captures_path.write_text(
        "".join(json.dumps(r) + "\n" for r in records), encoding="utf-8"
    )
    summary_path = capture_dir / "summary.json"
    summary_path.write_text(json.dumps({"run_id": "qac_capture_fixture_run"}), encoding="utf-8")
    before_captures = captures_path.read_bytes()
    before_summary = summary_path.read_bytes()

    dataset = _dataset((_answerable_case("qac_1"),))
    result = run_qa_citation_judging_from_capture_run_dir(
        capture_dir,
        dataset=dataset,
        qa_primary_judge=_always(_qa_response()),
        qa_secondary_judge=_always(_qa_response()),
        insufficient_evidence_primary_judge=_always(_ie_response()),
        insufficient_evidence_secondary_judge=_always(_ie_response()),
        citation_primary_judge=_always(_citation_response()),
        citation_secondary_judge=_always(_citation_response()),
        qa_judge_identities=_identities("qa"),
        insufficient_evidence_judge_identities=_identities("ie"),
        citation_judge_identities=_identities("cite"),
        output_dir=tmp_path / "judging_runs",
    )
    assert result.capture_run_id == "qac_capture_fixture_run"
    import hashlib

    assert result.capture_file_sha256 == hashlib.sha256(before_captures).hexdigest()
    # read-only: the capture files themselves are untouched
    assert captures_path.read_bytes() == before_captures
    assert summary_path.read_bytes() == before_summary
