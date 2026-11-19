"""Export the latest completed evaluation run from local Postgres to JSON."""

from __future__ import annotations

import json
from pathlib import Path

from app.db.session import get_session_factory
from app.models.db_models import EvaluationCaseResult, EvaluationComponent, EvaluationResult
from app.services.evaluation.persistence import get_latest_run

OUT_DIR = Path(__file__).resolve().parent / "results_json"


def _parse_json(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def export() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = get_session_factory()()
    try:
        run = get_latest_run(session)
        if run is None:
            raise SystemExit("No evaluation run found.")
        components = (
            session.query(EvaluationComponent).filter_by(run_id=run.id).order_by(EvaluationComponent.component).all()
        )
        payload = {
            "run_id": run.id,
            "status": run.status,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "config": _parse_json(run.config_json),
            "components": [],
        }
        headline = {
            "run_id": run.id,
            "status": run.status,
            "retrieval": {},
            "classification": {},
            "question_answering": {},
        }
        for component in components:
            metrics = {
                row.metric_name: {
                    "value": row.metric_value,
                    "extra": _parse_json(row.extra_json),
                }
                for row in session.query(EvaluationResult)
                .filter_by(component_id=component.id)
                .order_by(EvaluationResult.metric_name)
            }
            cases = [
                {
                    "case_id": row.case_id,
                    "predicted": row.predicted,
                    "expected": row.expected,
                    "correct": row.correct,
                    "latency_ms": row.latency_ms,
                }
                for row in session.query(EvaluationCaseResult)
                .filter_by(component_id=component.id)
                .order_by(EvaluationCaseResult.created_at.asc())
            ]
            matrix = None
            if component.confusion_matrix is not None:
                matrix = {
                    "labels": _parse_json(component.confusion_matrix.labels_json),
                    "matrix": _parse_json(component.confusion_matrix.matrix_json),
                    "case_count": component.confusion_matrix.case_count,
                }
            item = {
                "component": component.component,
                "status": component.status,
                "model_name": component.model_name,
                "shares_model_with": component.shares_model_with,
                "allow_llm_fallback": component.allow_llm_fallback,
                "case_count": component.case_count,
                "skipped_unlabeled_count": component.skipped_unlabeled_count,
                "reason": component.reason,
                "note": component.note,
                "metrics": {name: row["value"] for name, row in metrics.items()},
                "metric_details": metrics,
                "confusion_matrix": matrix,
                "case_results": cases,
            }
            payload["components"].append(item)

            m = item["metrics"]
            if component.component == "reranker":
                headline["retrieval"] = {
                    "cases": component.case_count,
                    "embedding_only": {
                        "hit_at_k": m.get("embedding_hit_at_k"),
                        "mrr": m.get("embedding_mrr"),
                        "ndcg_at_k": m.get("embedding_ndcg_at_k"),
                        "precision_at_k": m.get("embedding_precision_at_k"),
                        "recall_at_k": m.get("embedding_recall_at_k"),
                    },
                    "reranked": {
                        "hit_at_k": m.get("reranked_hit_at_k"),
                        "mrr": m.get("reranked_mrr"),
                        "ndcg_at_k": m.get("reranked_ndcg_at_k"),
                        "precision_at_k": m.get("reranked_precision_at_k"),
                        "recall_at_k": m.get("reranked_recall_at_k"),
                    },
                }
            if component.component == "classify_question":
                headline["classification"]["questions"] = {
                    "accuracy": m.get("accuracy"),
                    "macro_f1": m.get("macro_f1"),
                    "cases": component.case_count,
                }
            if component.component == "classify_chunk(allow_llm=True)":
                headline["classification"]["chunks"] = {
                    "accuracy": m.get("accuracy"),
                    "macro_f1": m.get("macro_f1"),
                    "cases": component.case_count,
                }
            if component.component == "answer_generation_llm":
                headline["question_answering"] = {
                    "answer_correctness": m.get("answer_correctness"),
                    "faithfulness": m.get("faithfulness"),
                    "answer_relevancy": m.get("answer_relevancy"),
                    "citation_set_precision": m.get("citation_set_precision"),
                    "cases": component.case_count,
                    "skipped_role_gated": component.skipped_unlabeled_count,
                }

        full_path = OUT_DIR / f"evaluation_run_{run.id}.json"
        headline_path = OUT_DIR / "evaluation_results.json"
        full_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        headline_path.write_text(json.dumps(headline, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {headline_path}")
        print(f"Wrote {full_path}")
        return headline_path
    finally:
        session.close()


if __name__ == "__main__":
    export()
