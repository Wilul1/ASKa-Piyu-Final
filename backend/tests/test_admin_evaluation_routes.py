"""API-level tests for /admin/evaluation/* against the real aska_piyu_test
database (see conftest.py). Admin auth is overridden via FastAPI's own
``app.dependency_overrides`` (simulating an authenticated admin), not via
a real admin key, since this file tests routing/persistence wiring, not
the auth dependency itself (that is covered by test_security_hardening.py).
``persistence.process_evaluation_run_job`` is always mocked when calling
POST /run -- TestClient executes FastAPI BackgroundTasks synchronously
within the request, so leaving it real would make a real Groq/Chroma call.
"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db_session, get_session_factory
from app.main import app
from app.models.db_models import (
    EvaluationCaseResult,
    EvaluationComponent,
    EvaluationConfusionMatrix,
    EvaluationResult,
    EvaluationRun,
)
from app.routes.admin.evaluation import require_admin_only_key
from app.services.evaluation import persistence
from app.services.evaluation.classification_metrics import ClassificationMetrics, ClassMetrics
from app.services.evaluation.confusion_matrix import ConfusionMatrix
from app.services.evaluation.evaluation_service import (
    CaseResultRecord,
    ComponentEvaluationResult,
    ComponentModelInfo,
    EvaluationRunResult,
)


def _sample_result() -> EvaluationRunResult:
    classification = ComponentEvaluationResult(
        component="classify_question", status="evaluated", reason=None,
        model_info=ComponentModelInfo(component="classify_question", model_name="rule+similarity", allow_llm_fallback=False),
        case_count=1, skipped_unlabeled_count=0,
        classification_metrics=ClassificationMetrics(
            case_count=1, labels=("Enrollment",), accuracy=1.0,
            macro_precision=1.0, macro_recall=1.0, macro_f1=1.0,
            weighted_precision=1.0, weighted_recall=1.0, weighted_f1=1.0,
            per_class=(ClassMetrics(label="Enrollment", true_positives=1, true_negatives=0, false_positives=0, false_negatives=0, support=1, precision=1.0, recall=1.0, f1=1.0),),
        ),
        confusion_matrix=ConfusionMatrix(labels=("Enrollment",), matrix=((1,),), case_count=1),
        case_results=(CaseResultRecord(case_id="1", predicted="Enrollment", expected="Enrollment", correct=True),),
    )
    not_evaluable = ComponentEvaluationResult(
        component="embedding_retrieval", status="not_evaluable", reason="no labeled cases",
        model_info=ComponentModelInfo(component="embedding_retrieval", model_name="sentence-transformers: intfloat/multilingual-e5-small"),
        case_count=0, skipped_unlabeled_count=0,
    )
    return EvaluationRunResult(
        components=(classification, not_evaluable),
        dataset_versions={"classification": "cv1", "retrieval": "rv1", "rag": "gv1"},
        dataset_sha256={"classification": "a" * 64, "retrieval": "b" * 64, "rag": "c" * 64},
    )


@pytest.fixture
def client_and_session():
    session = get_session_factory()()
    created_run_ids: list[str] = []

    def _override_session():
        yield session

    app.dependency_overrides[get_db_session] = _override_session
    # None mirrors require_admin_only_key's own real contract for API-key
    # auth (no user row to attribute to) -- a fabricated user id string
    # would violate evaluation_runs.triggered_by_user_id's real FK to users.id.
    app.dependency_overrides[require_admin_only_key] = lambda: None
    client = TestClient(app)
    try:
        yield client, session, created_run_ids
    finally:
        for run_id in created_run_ids:
            session.query(EvaluationCaseResult).filter_by(run_id=run_id).delete()
            session.query(EvaluationConfusionMatrix).filter_by(run_id=run_id).delete()
            session.query(EvaluationResult).filter_by(run_id=run_id).delete()
            session.query(EvaluationComponent).filter_by(run_id=run_id).delete()
            session.query(EvaluationRun).filter_by(id=run_id).delete()
        session.commit()
        app.dependency_overrides.pop(get_db_session, None)
        app.dependency_overrides.pop(require_admin_only_key, None)
        session.close()


def test_run_endpoint_requires_admin_auth():
    client = TestClient(app)
    resp = client.post("/admin/evaluation/run")
    assert resp.status_code in (401, 503)


def test_run_endpoint_creates_running_run_and_schedules_job(client_and_session, monkeypatch):
    client, session, created = client_and_session
    scheduled: list[str] = []
    async def _fake_spawn(run_id):
        scheduled.append(run_id)

    monkeypatch.setattr(persistence, "spawn_evaluation_run_job", _fake_spawn)

    resp = client.post("/admin/evaluation/run")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    created.append(body["run_id"])
    deadline = time.time() + 2
    while scheduled != [body["run_id"]] and time.time() < deadline:
        time.sleep(0.01)
    assert scheduled == [body["run_id"]]


def test_models_endpoint_lists_known_components(client_and_session):
    client, _session, _created = client_and_session
    resp = client.get("/admin/evaluation/models")
    assert resp.status_code == 200
    components = {m["component"] for m in resp.json()["models"]}
    assert components == {
        "embedding_retrieval", "reranker", "classify_chunk", "classify_question",
        "answer_generation_llm", "citation_verifier_llm",
    }


def test_summary_endpoint_reports_explicit_empty_state(client_and_session):
    client, session, _created = client_and_session
    # Guarantee a clean slate for this specific assertion regardless of
    # what other test files may have left behind in aska_piyu_test.
    session.query(EvaluationCaseResult).delete()
    session.query(EvaluationConfusionMatrix).delete()
    session.query(EvaluationResult).delete()
    session.query(EvaluationComponent).delete()
    session.query(EvaluationRun).delete()
    session.commit()

    resp = client.get("/admin/evaluation/summary")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latest_run"] is None
    assert body["components"] == []


def test_history_endpoint_pagination(client_and_session):
    client, session, created = client_and_session
    for _ in range(3):
        run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
        created.append(run.id)

    resp = client.get("/admin/evaluation/history", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["runs"]) == 2
    assert body["total"] >= 3
    assert body["limit"] == 2 and body["offset"] == 0


def test_get_run_detail_not_found_returns_404(client_and_session):
    client, _session, _created = client_and_session
    resp = client.get("/admin/evaluation/does-not-exist")
    assert resp.status_code == 404


def test_get_run_detail_returns_components_metrics_and_config(client_and_session, monkeypatch):
    client, session, created = client_and_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    resp = client.get(f"/admin/evaluation/{run.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["config"]["dataset_versions"] == {"classification": "cv1", "retrieval": "rv1", "rag": "gv1"}
    by_name = {c["component"]: c for c in body["components"]}
    assert by_name["classify_question"]["has_confusion_matrix"] is True
    assert by_name["embedding_retrieval"]["status"] == "not_evaluable"
    metric_values = {m["metric_name"]: m["metric_value"] for m in by_name["classify_question"]["metrics"]}
    assert metric_values["accuracy"] == 1.0


def test_confusion_matrix_endpoint_round_trip_and_404(client_and_session, monkeypatch):
    client, session, created = client_and_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    resp = client.get(f"/admin/evaluation/{run.id}/confusion-matrix", params={"component": "classify_question"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["labels"] == ["Enrollment"]
    assert body["matrix"] == [[1]]

    missing = client.get(f"/admin/evaluation/{run.id}/confusion-matrix", params={"component": "embedding_retrieval"})
    assert missing.status_code == 404


def test_case_results_endpoint_pagination_and_404(client_and_session, monkeypatch):
    client, session, created = client_and_session
    run = persistence.start_evaluation_run(session, triggered_by_user_id=None)
    created.append(run.id)
    session.close()
    monkeypatch.setattr(persistence, "run_evaluation", lambda **kwargs: _sample_result())
    persistence.process_evaluation_run_job(run.id)

    fresh = get_session_factory()()
    try:
        component = fresh.query(EvaluationComponent).filter_by(run_id=run.id, component="classify_question").one()
    finally:
        fresh.close()

    resp = client.get(f"/admin/evaluation/{run.id}/components/{component.id}/cases", params={"limit": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["case_results"][0]["case_id"] == "1"

    wrong_run = client.get(f"/admin/evaluation/not-this-run/components/{component.id}/cases")
    assert wrong_run.status_code == 404
