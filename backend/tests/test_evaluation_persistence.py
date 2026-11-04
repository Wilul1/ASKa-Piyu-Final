"""Tests for app.services.evaluation.persistence against the real
aska_piyu_test Postgres database (conftest.py already enforces that this
test suite can only ever run against that database -- see its
_isolate_tests_on_aska_piyu_test fixture). evaluation_service.run_evaluation
is always mocked here: these tests verify ONLY the persistence/idempotency/
privacy layer, never a real Groq/Chroma call.
"""
from __future__ import annotations

import json

import pytest

from app.db.session import get_session_factory
from app.models.db_models import (
    EvaluationCaseResult,
    EvaluationComponent,
    EvaluationConfusionMatrix,
    EvaluationResult,
    EvaluationRun,
)
from app.services.evaluation import persistence
from app.services.evaluation.classification_metrics import ClassificationMetrics, ClassMetrics
from app.services.evaluation.confusion_matrix import ConfusionMatrix
from app.services.evaluation.evaluation_service import (
    CaseResultRecord,
    ComponentEvaluationResult,
    ComponentModelInfo,
    EvaluationRunResult,
)
from app.services.evaluation.performance_metrics import PerformanceMetrics


@pytest.fixture
def db_session():
    session = get_session_factory()()
    created_run_ids: list[str] = []
    try:
        yield session, created_run_ids
    finally:
        # Explicit cleanup (raw deletes in dependency order) -- persistence
        # functions commit internally, so a plain rollback would not undo them.
        for run_id in created_run_ids:
            session.query(EvaluationCaseResult).filter_by(run_id=run_id).delete()
            session.query(EvaluationConfusionMatrix).filter_by(run_id=run_id).delete()
            session.query(EvaluationResult).filter_by(run_id=run_id).delete()
            session.query(EvaluationComponent).filter_by(run_id=run_id).delete()
            session.query(EvaluationRun).filter_by(id=run_id).delete()
        session.commit()
        session.close()


def _sample_result() -> EvaluationRunResult:
    classification = ComponentEvaluationResult(
        component="classify_question",
        status="evaluated",
        reason=None,
        model_info=ComponentModelInfo(component="classify_question", model_name="rule+similarity", allow_llm_fallback=False),
        case_count=2,
        skipped_unlabeled_count=1,
        classification_metrics=ClassificationMetrics(
            case_count=2, labels=("Enrollment", "Library"), accuracy=1.0,
            macro_precision=1.0, macro_recall=1.0, macro_f1=1.0,
            weighted_precision=1.0, weighted_recall=1.0, weighted_f1=1.0,
            per_class=(
                ClassMetrics(label="Enrollment", true_positives=1, true_negatives=1, false_positives=0, false_negatives=0, support=1, precision=1.0, recall=1.0, f1=1.0),
                ClassMetrics(label="Library", true_positives=1, true_negatives=1, false_positives=0, false_negatives=0, support=1, precision=1.0, recall=1.0, f1=1.0),
            ),
        ),
        confusion_matrix=ConfusionMatrix(labels=("Enrollment", "Library"), matrix=((1, 0), (0, 1)), case_count=2),
        case_results=(
            CaseResultRecord(case_id="1", predicted="Enrollment", expected="Enrollment", correct=True),
            CaseResultRecord(case_id="2", predicted="Library", expected="Library", correct=True),
        ),
    )
    answer_llm = ComponentEvaluationResult(
        component="answer_generation_llm",
        status="evaluated",
        reason=None,
        model_info=ComponentModelInfo(component="answer_generation_llm", model_name="llama-3.3-70b-versatile"),
        case_count=1,
        skipped_unlabeled_count=0,
        performance_metrics=PerformanceMetrics(
            call_count=1, success_count=1, failure_count=0, success_rate=1.0, failure_rate=0.0,
            avg_latency_ms=120.0, median_latency_ms=120.0, p95_latency_ms=120.0,
            first_call_in_run_count=1, first_call_in_run_avg_latency_ms=120.0,
            warm_call_count=0, warm_avg_latency_ms=None,
            total_prompt_tokens=100, total_completion_tokens=20, avg_prompt_tokens=100.0, avg_completion_tokens=20.0,
        ),
        case_results=(CaseResultRecord(case_id="r1", predicted="An answer.", correct=True, latency_ms=120.0),),
    )
    not_evaluable = ComponentEvaluationResult(
        component="citation_verifier_llm",
        status="not_evaluable",
        reason="no gold_citation_ids",
        model_info=ComponentModelInfo(component="citation_verifier_llm", model_name="llama-3.3-70b-versatile", shares_model_with="answer_generation_llm"),
        case_count=1,
        skipped_unlabeled_count=0,
    )
    return EvaluationRunResult(
        components=(classification, answer_llm, not_evaluable),
        dataset_versions={"classification": "cv1", "retrieval": "rv1", "rag": "gv1"},
        dataset_sha256={"classification": "a" * 64, "retrieval": "b" * 64, "rag": "c" * 64},
    )


def test_start_evaluation_run_creates_running_row_with_config(db_session):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)

    assert run.status == "running"
    assert run.completed_at is None
    config = json.loads(run.config_json)
    assert config["groq_model"] == persistence.settings.groq_model
    assert "groq_api_key" not in config
    assert "dataset_versions" not in config  # not known yet at start


def test_process_evaluation_run_job_persists_everything_and_marks_completed(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()  # process_evaluation_run_job opens its own session

    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        persisted_run = fresh.get(EvaluationRun, run.id)
        assert persisted_run.status == "completed"
        assert persisted_run.completed_at is not None
        config = json.loads(persisted_run.config_json)
        assert config["dataset_versions"] == {"classification": "cv1", "retrieval": "rv1", "rag": "gv1"}

        components = fresh.query(EvaluationComponent).filter_by(run_id=run.id).all()
        assert len(components) == 3
        by_name = {c.component: c for c in components}
        assert by_name["citation_verifier_llm"].status == "not_evaluable"
        assert by_name["citation_verifier_llm"].shares_model_with == "answer_generation_llm"

        classify_component = by_name["classify_question"]
        results = fresh.query(EvaluationResult).filter_by(component_id=classify_component.id).all()
        metric_values = {r.metric_name: r.metric_value for r in results}
        assert metric_values["accuracy"] == 1.0

        matrix = fresh.query(EvaluationConfusionMatrix).filter_by(component_id=classify_component.id).one()
        assert json.loads(matrix.labels_json) == ["Enrollment", "Library"]

        case_rows = fresh.query(EvaluationCaseResult).filter_by(component_id=classify_component.id).all()
        assert len(case_rows) == 2
    finally:
        fresh.close()


def test_process_evaluation_run_job_is_idempotent_on_second_invocation(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()

    call_count = {"n": 0}

    def _fake_run_evaluation(**kwargs):
        call_count["n"] += 1
        return _sample_result()

    monkeypatch.setattr(persistence, "run_evaluation", _fake_run_evaluation)
    persistence.process_evaluation_run_job(run.id)
    persistence.process_evaluation_run_job(run.id)  # second invocation must be a no-op

    assert call_count["n"] == 1
    fresh = get_session_factory()()
    try:
        components = fresh.query(EvaluationComponent).filter_by(run_id=run.id).all()
        assert len(components) == 3  # not duplicated
    finally:
        fresh.close()


def test_process_evaluation_run_job_releases_db_session_during_evaluation(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()

    seen_running = []

    def _fake_eval(**kwargs):
        probe = get_session_factory()()
        try:
            persisted = probe.get(EvaluationRun, run.id)
            assert persisted is not None
            assert persisted.status == "running"
            seen_running.append(True)
        finally:
            probe.close()
        return _sample_result()

    monkeypatch.setattr(persistence, "run_evaluation", _fake_eval)
    persistence.process_evaluation_run_job(run.id)
    assert seen_running == [True]


def test_process_evaluation_run_job_marks_run_failed_when_evaluation_raises(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()

    def _raise(**kwargs):
        raise RuntimeError("synthetic evaluation failure")

    monkeypatch.setattr(persistence, "run_evaluation", _raise)
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        persisted_run = fresh.get(EvaluationRun, run.id)
        assert persisted_run.status == "failed"
        assert "synthetic evaluation failure" in persisted_run.error_message
        assert persisted_run.completed_at is not None
        assert fresh.query(EvaluationComponent).filter_by(run_id=run.id).count() == 0
    finally:
        fresh.close()


def test_process_evaluation_run_job_skips_unknown_run_id():
    persistence.process_evaluation_run_job("does-not-exist")  # must not raise


def test_strip_secret_like_keys_removes_credential_shaped_fields():
    tainted = {"groq_model": "llama", "api_key": "sk-secret", "nested": {"Authorization": "Bearer xyz", "ok": 1}}
    cleaned = persistence._strip_secret_like_keys(tainted)
    assert cleaned == {"groq_model": "llama", "nested": {"ok": 1}}


def test_list_runs_pagination(db_session):
    session, created = db_session
    run1 = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    run2 = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.extend([run1.id, run2.id])

    page1, total = persistence.list_runs(session, limit=1, offset=0)
    assert total >= 2
    assert len(page1) == 1


def test_list_case_results_pagination(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        component = fresh.query(EvaluationComponent).filter_by(run_id=run.id, component="classify_question").one()
        page, total = persistence.list_case_results(fresh, component_id=component.id, limit=1, offset=0)
        assert total == 2
        assert len(page) == 1
    finally:
        fresh.close()


def test_human_rag_overview_is_reapplied_after_empty_rag_run(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()

    empty_rag = ComponentEvaluationResult(
        component="answer_generation_llm",
        status="not_evaluable",
        reason="no labeled cases in rag_eval_dataset.json",
        model_info=ComponentModelInfo(component="answer_generation_llm", model_name="llama-3.3-70b-versatile"),
        case_count=0,
        skipped_unlabeled_count=0,
    )
    result = EvaluationRunResult(
        components=(empty_rag,),
        dataset_versions={"rag": "empty"},
        dataset_sha256={"rag": "d" * 64},
    )
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: result)
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        component = fresh.query(EvaluationComponent).filter_by(
            run_id=run.id, component="answer_generation_llm"
        ).one()
        assert component.status == "evaluated"
        assert component.case_count == 12
        values = {
            row.metric_name: row.metric_value
            for row in fresh.query(EvaluationResult).filter_by(component_id=component.id).all()
        }
        assert values["answer_correctness"] == pytest.approx(0.5833)
        assert values["faithfulness"] == pytest.approx(0.5417)
        assert values["answer_relevancy"] == pytest.approx(0.9167)
        assert values["citation_set_precision"] == pytest.approx(0.9)
        config = json.loads(fresh.get(EvaluationRun, run.id).config_json)
        assert config["human_answer_quality_overview"] == "aq_live_student_chat_20261105T023200Z"
    finally:
        fresh.close()


def test_get_confusion_matrix_returns_none_when_absent(db_session, monkeypatch):
    session, created = db_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        assert persistence.get_confusion_matrix(fresh, run_id=run.id, component="classify_question") is not None
        assert persistence.get_confusion_matrix(fresh, run_id=run.id, component="answer_generation_llm") is None
    finally:
        fresh.close()


