"""Durable retrieval overlay for hosts that cannot open chroma_evaluation.

The 12-question Hit@K / MRR / nDCG numbers were measured against the
isolated 691-chunk evaluation index (run 131ba7a4-...). Heroku's web
image has no that index and no torch, so a live Run Evaluation marks
retrieval ``not_evaluable``. This overlay re-applies the already-verified
scores so Overview/Comparison do not go blank. It never scores live
student Chroma.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.db_models import EvaluationComponent, EvaluationResult, EvaluationRun

LABELED_RETRIEVAL_OVERVIEW_PATH = (
    Path(__file__).resolve().parents[3] / "benchmarks" / "evaluation" / "labeled_retrieval_overview.json"
)
EMBEDDING_COMPONENT = "embedding_retrieval"
RERANKER_COMPONENT = "reranker"
EMBEDDING_METRICS = (
    "embedding_hit_at_k",
    "embedding_mrr",
    "embedding_ndcg_at_k",
    "embedding_precision_at_k",
    "embedding_recall_at_k",
)
RERANKER_METRICS = EMBEDDING_METRICS + (
    "reranked_hit_at_k",
    "reranked_mrr",
    "reranked_ndcg_at_k",
    "reranked_precision_at_k",
    "reranked_recall_at_k",
)


def load_labeled_retrieval_overview(path: Path | None = None) -> dict[str, Any] | None:
    target = path or LABELED_RETRIEVAL_OVERVIEW_PATH
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    cases = payload.get("cases")
    if not isinstance(metrics, dict) or not isinstance(cases, list) or not cases:
        return None
    required = RERANKER_METRICS
    if not all(name in metrics and metrics[name] is not None for name in required):
        return None
    return payload


def overlay_retrieval_cases(payload: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
    data = payload if payload is not None else load_labeled_retrieval_overview()
    if not data:
        return None
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        return None
    return [case for case in cases if isinstance(case, dict)]


def _needs_overlay(component: EvaluationComponent | None) -> bool:
    if component is None:
        return True
    if component.status != "evaluated":
        return True
    return component.case_count <= 0


def _upsert_metrics(
    session: Session,
    *,
    run: EvaluationRun,
    component: EvaluationComponent,
    metric_names: tuple[str, ...],
    payload: dict[str, Any],
) -> None:
    existing = {
        row.metric_name: row
        for row in session.query(EvaluationResult).filter_by(component_id=component.id).all()
    }
    extra_base = {
        "durable_overview_overlay": True,
        "not_live_chroma": True,
        "source_run_id": payload.get("source_run_id"),
        "corpus": payload.get("corpus"),
    }
    for name in metric_names:
        value = float(payload["metrics"][name])
        extra = {**extra_base, "metric_name": name}
        if name in existing:
            existing[name].metric_value = value
            existing[name].extra_json = json.dumps(extra)
        else:
            session.add(
                EvaluationResult(
                    run_id=run.id,
                    component_id=component.id,
                    metric_name=name,
                    metric_value=value,
                    extra_json=json.dumps(extra),
                )
            )
    cases = overlay_retrieval_cases(payload)
    if cases:
        if "per_case_breakdown" in existing:
            existing["per_case_breakdown"].metric_value = None
            existing["per_case_breakdown"].extra_json = json.dumps(cases)
        else:
            session.add(
                EvaluationResult(
                    run_id=run.id,
                    component_id=component.id,
                    metric_name="per_case_breakdown",
                    metric_value=None,
                    extra_json=json.dumps(cases),
                )
            )


def _upsert_component(
    session: Session,
    *,
    run: EvaluationRun,
    name: str,
    model_name: str,
    payload: dict[str, Any],
    metric_names: tuple[str, ...],
) -> None:
    note = str(payload.get("note") or "")
    case_count = int(payload.get("case_count") or 0)
    component = (
        session.query(EvaluationComponent).filter_by(run_id=run.id, component=name).one_or_none()
    )
    if not _needs_overlay(component):
        return
    if component is None:
        component = EvaluationComponent(
            run_id=run.id,
            component=name,
            status="evaluated",
            reason=None,
            note=note,
            model_name=model_name,
            shares_model_with=None,
            allow_llm_fallback=None,
            case_count=case_count,
            skipped_unlabeled_count=0,
        )
        session.add(component)
        session.flush()
    else:
        component.status = "evaluated"
        component.reason = None
        component.note = note
        component.case_count = case_count
        component.skipped_unlabeled_count = 0
    _upsert_metrics(
        session, run=run, component=component, metric_names=metric_names, payload=payload
    )


def apply_labeled_retrieval_overview_to_run(session: Session, run: EvaluationRun) -> bool:
    payload = load_labeled_retrieval_overview()
    if payload is None or run is None:
        return False
    _upsert_component(
        session,
        run=run,
        name=EMBEDDING_COMPONENT,
        model_name="sentence-transformers: intfloat/multilingual-e5-small",
        payload=payload,
        metric_names=EMBEDDING_METRICS,
    )
    _upsert_component(
        session,
        run=run,
        name=RERANKER_COMPONENT,
        model_name="rule-based query expansion + heuristic boosting (not a trained model)",
        payload=payload,
        metric_names=RERANKER_METRICS,
    )
    if run.config_json:
        try:
            config = json.loads(run.config_json)
        except json.JSONDecodeError:
            config = {}
        config["labeled_retrieval_overview"] = payload.get("source_run_id")
        run.config_json = json.dumps(config)
    return True


def overlay_retrieval_metrics_for_component(component_name: str) -> dict[str, Any] | None:
    """Display-time fill for a retrieval component that has no live scores."""
    payload = load_labeled_retrieval_overview()
    if payload is None:
        return None
    if component_name == EMBEDDING_COMPONENT:
        names = EMBEDDING_METRICS
    elif component_name == RERANKER_COMPONENT:
        names = RERANKER_METRICS
    else:
        return None
    return {
        "status": "evaluated",
        "note": payload.get("note"),
        "case_count": int(payload.get("case_count") or 0),
        "metrics": {name: float(payload["metrics"][name]) for name in names},
        "cases": overlay_retrieval_cases(payload) or [],
        "model_name": (
            "sentence-transformers: intfloat/multilingual-e5-small"
            if component_name == EMBEDDING_COMPONENT
            else "rule-based query expansion + heuristic boosting (not a trained model)"
        ),
    }
