"""Durable human answer-quality overlay for Admin Overview RAG cards.

The live student-chatbot scores live in
``backend/benchmarks/evaluation/human_answer_quality_overview.json``.
They are re-applied onto every completed evaluation run so clicking
Run Evaluation cannot blank the Overview cards. This is not RAGAS and
does not treat ``rag_eval_dataset.json`` as labeled.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models.db_models import EvaluationComponent, EvaluationResult, EvaluationRun

HUMAN_RAG_OVERVIEW_PATH = (
    Path(__file__).resolve().parents[3] / "benchmarks" / "evaluation" / "human_answer_quality_overview.json"
)
COMPONENT_NAME = "answer_generation_llm"
METRIC_NAMES = (
    "answer_correctness",
    "faithfulness",
    "answer_relevancy",
    "citation_set_precision",
)


def load_human_rag_overview(path: Path | None = None) -> dict[str, Any] | None:
    target = path or HUMAN_RAG_OVERVIEW_PATH
    if not target.is_file():
        return None
    payload = json.loads(target.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        return None
    if not all(name in metrics and metrics[name].get("value") is not None for name in METRIC_NAMES):
        return None
    return payload


def overlay_case_breakdown(payload: dict[str, Any] | None = None) -> list[dict[str, Any]] | None:
    """Per-question human scores already stored in the overlay file.

    Returns None when the overlay has no ``cases`` list. Never invents a
    question or a score.
    """
    data = payload if payload is not None else load_human_rag_overview()
    if not data:
        return None
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        return None
    return [case for case in cases if isinstance(case, dict)]


def apply_human_rag_overview_to_run(session: Session, run: EvaluationRun) -> bool:
    payload = load_human_rag_overview()
    if payload is None or run is None:
        return False

    case_count = int(payload.get("student_visible_case_count") or 0)
    skipped = len(payload.get("role_gated_excluded") or [])
    note = (
        "Human-scored live student chatbot screenshots "
        f"({payload.get('run_id')}); not RAGAS and not rag_eval_dataset.json. "
        "Re-applied after each evaluation run so Overview cards are not wiped."
    )
    component = (
        session.query(EvaluationComponent)
        .filter_by(run_id=run.id, component=COMPONENT_NAME)
        .one_or_none()
    )
    if component is None:
        component = EvaluationComponent(
            run_id=run.id,
            component=COMPONENT_NAME,
            status="evaluated",
            reason=None,
            note=note,
            model_name=(settings.groq_model or "").strip() or "human_live_student_chat",
            shares_model_with=None,
            allow_llm_fallback=None,
            case_count=case_count,
            skipped_unlabeled_count=skipped,
        )
        session.add(component)
        session.flush()
    else:
        component.status = "evaluated"
        component.reason = None
        component.note = note
        component.case_count = case_count
        component.skipped_unlabeled_count = skipped

    existing = {
        row.metric_name: row
        for row in session.query(EvaluationResult).filter_by(component_id=component.id).all()
    }
    for name in METRIC_NAMES:
        metric = payload["metrics"][name]
        extra = {
            "judge_source": "human_verified",
            "formula": metric.get("formula"),
            "contributing_cases": metric.get("contributing_cases"),
            "live_run_id": payload.get("run_id"),
            "not_ragas": True,
            "durable_overview_overlay": True,
        }
        if metric.get("note"):
            extra["note"] = metric["note"]
        if name in existing:
            existing[name].metric_value = float(metric["value"])
            existing[name].extra_json = json.dumps(extra)
        else:
            session.add(
                EvaluationResult(
                    run_id=run.id,
                    component_id=component.id,
                    metric_name=name,
                    metric_value=float(metric["value"]),
                    extra_json=json.dumps(extra),
                )
            )

    cases = overlay_case_breakdown(payload)
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

    if run.config_json:
        try:
            config = json.loads(run.config_json)
        except json.JSONDecodeError:
            config = {}
        config["human_answer_quality_overview"] = payload.get("run_id")
        run.config_json = json.dumps(config)
    return True
