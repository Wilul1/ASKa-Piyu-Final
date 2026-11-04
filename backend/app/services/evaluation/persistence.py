"""Persistence for the Model Evaluation System: maps
``evaluation_service.EvaluationRunResult`` onto the ``evaluation_runs``/
``evaluation_components``/``evaluation_results``/
``evaluation_confusion_matrices``/``evaluation_case_results`` tables.

This is the ONLY place in the evaluation system that touches a database.
It never connects to Heroku/production Postgres (it uses whatever
``app.db.session.get_session_factory`` is configured for -- local dev in
this phase) and never touches ChromaDB at all (that stays
``evaluation_service``'s read-only Chroma access).

Idempotency: ``process_evaluation_run_job`` is safe to invoke more than
once for the same ``run_id`` -- it checks the run's current status and
whether any component rows already exist for it before doing any real
work, and is a no-op otherwise (see its docstring).

Privacy: every JSON blob persisted here goes through
``_strip_secret_like_keys`` first, which recursively drops any dict key
whose name looks like a credential (api key / token / secret /
authorization / password) -- defense in depth, since none of
``evaluation_service``'s own output fields currently carry such a key.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_session_factory
from app.models.db_models import (
    EvaluationCaseResult,
    EvaluationComponent,
    EvaluationConfusionMatrix,
    EvaluationResult,
    EvaluationRun,
)
from app.services.embeddings import current_embedding_model_label
from app.services.evaluation.evaluation_service import (
    DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE,
    DEFAULT_RETRIEVAL_K,
    ComponentEvaluationResult,
    EvaluationRunResult,
    run_evaluation,
)
from app.services.evaluation.human_rag_overview import apply_human_rag_overview_to_run

logger = logging.getLogger(__name__)

_SECRET_KEY_RE = re.compile(r"(api[_-]?key|token|secret|authoriz|password)", re.I)
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _strip_secret_like_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_secret_like_keys(val)
            for key, val in value.items()
            if not _SECRET_KEY_RE.search(str(key))
        }
    if isinstance(value, list):
        return [_strip_secret_like_keys(item) for item in value]
    return value


def _safe_json_dumps(value: Any) -> str:
    return json.dumps(_strip_secret_like_keys(value))


def _current_git_commit() -> str | None:
    """Best-effort app commit identifier for reproducibility. Never
    raises -- a missing git binary or a non-repo deployment (e.g. the
    Heroku slug, which this feature never runs against anyway) just
    yields ``None``."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:  # noqa: BLE001 -- best-effort only
        return None
    if result.returncode != 0:
        return None
    commit = result.stdout.strip()
    return commit or None


def build_run_config(*, retrieval_k: int, retrieval_candidate_pool_size: int) -> dict[str, Any]:
    """Reproducibility snapshot captured at run start -- model ids,
    embedding model, retrieval settings, citation-verification mode, and
    the app commit, if available. Dataset versions/hashes are merged in
    once the run completes (see ``_persist_result``), since they are only
    known after the datasets are actually loaded."""
    return {
        "retrieval_k": retrieval_k,
        "retrieval_candidate_pool_size": retrieval_candidate_pool_size,
        "groq_model": settings.groq_model,
        "citation_verifier_model": settings.citation_verifier_model,
        "citation_verification_mode": settings.citation_verification_mode,
        "embedding_model_label": current_embedding_model_label(),
        "embedding_backend": settings.embedding_backend,
        "app_commit": _current_git_commit(),
    }


def start_evaluation_run(
    session: Session,
    *,
    triggered_by_user_id: str | None,
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
    retrieval_candidate_pool_size: int = DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE,
) -> EvaluationRun:
    """Creates the run row (status="running") synchronously, quickly --
    the actual evaluation work happens afterward in a background task
    (see ``process_evaluation_run_job``), mirroring
    ``digital_ingestion.start_extraction_job``'s own job-creation shape.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=2)
    stale = (
        session.query(EvaluationRun)
        .filter(EvaluationRun.status == "running", EvaluationRun.started_at < cutoff)
        .all()
    )
    for old in stale:
        old.status = "failed"
        old.error_message = "Superseded: this run did not finish (worker restart or Chroma crash)."
        old.completed_at = datetime.now(timezone.utc)
    run = EvaluationRun(
        status="running",
        triggered_by_user_id=triggered_by_user_id,
        config_json=_safe_json_dumps(
            build_run_config(retrieval_k=retrieval_k, retrieval_candidate_pool_size=retrieval_candidate_pool_size)
        ),
        started_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.commit()
    return run


_METRIC_FLOAT_FIELDS = (
    # (attribute path on ComponentEvaluationResult, metric_name prefix, field names)
    (
        "classification_metrics",
        "",
        ("accuracy", "macro_precision", "macro_recall", "macro_f1", "weighted_precision", "weighted_recall", "weighted_f1"),
    ),
    ("retrieval_metrics_embedding_only", "embedding_", ("hit_at_k", "mrr", "precision_at_k", "recall_at_k", "ndcg_at_k")),
    ("retrieval_metrics_reranked", "reranked_", ("hit_at_k", "mrr", "precision_at_k", "recall_at_k", "ndcg_at_k")),
    (
        "rag_metrics",
        "",
        (
            "faithfulness", "answer_relevancy", "context_precision", "context_recall",
            "answer_correctness", "citation_set_precision", "citation_set_recall", "claim_support_rate",
        ),
    ),
    (
        "performance_metrics",
        "",
        (
            "avg_latency_ms", "median_latency_ms", "p95_latency_ms", "success_rate", "failure_rate",
            "first_call_in_run_avg_latency_ms", "warm_avg_latency_ms", "avg_prompt_tokens", "avg_completion_tokens",
        ),
    ),
)

_METRIC_COUNT_FIELDS = (
    ("classification_metrics", "", ("case_count",)),
    ("rag_metrics", "", ("llm_judge_case_count", "human_verified_case_count")),
    (
        "performance_metrics", "",
        ("call_count", "first_call_in_run_count", "warm_call_count", "total_prompt_tokens", "total_completion_tokens"),
    ),
)


def _flatten_metrics(component_result: ComponentEvaluationResult) -> list[tuple[str, float | None, Any]]:
    """Every (metric_name, metric_value, extra) row for one component's
    metrics dataclasses. ``metric_value`` stays ``None`` exactly where
    the source dataclass field is ``None`` -- never coerced to 0.0."""
    rows: list[tuple[str, float | None, Any]] = []
    for attr, prefix, fields in _METRIC_FLOAT_FIELDS:
        metrics_obj = getattr(component_result, attr, None)
        if metrics_obj is None:
            continue
        for field_name in fields:
            rows.append((f"{prefix}{field_name}", getattr(metrics_obj, field_name), None))
    for attr, prefix, fields in _METRIC_COUNT_FIELDS:
        metrics_obj = getattr(component_result, attr, None)
        if metrics_obj is None:
            continue
        for field_name in fields:
            rows.append((f"{prefix}{field_name}", float(getattr(metrics_obj, field_name)), None))

    if component_result.classification_metrics is not None:
        rows.append(
            ("per_class_breakdown", None, [dataclasses.asdict(c) for c in component_result.classification_metrics.per_class])
        )
    if component_result.rag_metrics is not None:
        rows.append(
            ("metric_contributing_counts", None, dict(component_result.rag_metrics.metric_contributing_counts))
        )
    return rows


def _persist_component(session: Session, *, run: EvaluationRun, component_result: ComponentEvaluationResult) -> None:
    component_row = EvaluationComponent(
        run_id=run.id,
        component=component_result.component,
        status=component_result.status,
        reason=component_result.reason,
        note=component_result.note,
        model_name=component_result.model_info.model_name,
        shares_model_with=component_result.model_info.shares_model_with,
        allow_llm_fallback=component_result.model_info.allow_llm_fallback,
        case_count=component_result.case_count,
        skipped_unlabeled_count=component_result.skipped_unlabeled_count,
    )
    session.add(component_row)
    session.flush()  # assigns component_row.id for the child rows below

    for metric_name, metric_value, extra in _flatten_metrics(component_result):
        session.add(
            EvaluationResult(
                run_id=run.id,
                component_id=component_row.id,
                metric_name=metric_name,
                metric_value=metric_value,
                extra_json=_safe_json_dumps(extra) if extra is not None else None,
            )
        )

    if component_result.confusion_matrix is not None:
        matrix = component_result.confusion_matrix
        session.add(
            EvaluationConfusionMatrix(
                run_id=run.id,
                component_id=component_row.id,
                labels_json=_safe_json_dumps(list(matrix.labels)),
                matrix_json=_safe_json_dumps([list(row) for row in matrix.matrix]),
                case_count=matrix.case_count,
            )
        )

    for case in component_result.case_results:
        session.add(
            EvaluationCaseResult(
                run_id=run.id,
                component_id=component_row.id,
                case_id=case.case_id,
                predicted=case.predicted,
                expected=case.expected,
                correct=case.correct,
                latency_ms=case.latency_ms,
            )
        )


def _persist_result(
    session: Session,
    *,
    run: EvaluationRun,
    result: EvaluationRunResult,
    retrieval_k: int,
    retrieval_candidate_pool_size: int,
) -> None:
    final_config = {
        **build_run_config(retrieval_k=retrieval_k, retrieval_candidate_pool_size=retrieval_candidate_pool_size),
        "dataset_versions": result.dataset_versions,
        "dataset_sha256": result.dataset_sha256,
    }
    run.config_json = _safe_json_dumps(final_config)
    for component_result in result.components:
        _persist_component(session, run=run, component_result=component_result)
    apply_human_rag_overview_to_run(session, run)


def _evaluation_python() -> Path:
    """Venv interpreter for the eval subprocess -- never the uvicorn reloader."""
    backend_root = Path(__file__).resolve().parents[3]
    windows = backend_root / "venv" / "Scripts" / "python.exe"
    unix = backend_root / "venv" / "bin" / "python"
    if windows.exists():
        return windows
    if unix.exists():
        return unix
    return Path(sys.executable)


async def spawn_evaluation_run_job(run_id: str) -> None:
    """Start evaluation in a separate process so login and GET /run stay responsive.

    In-process Chroma on Windows (uvicorn --reload or Starlette threadpool)
    previously hung or crashed with STATUS_ACCESS_VIOLATION. ``run_job``
    loads the isolated chroma_evaluation index, not live student Chroma.
    """
    backend_root = Path(__file__).resolve().parents[3]
    env = os.environ.copy()
    env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    subprocess.Popen(
        [str(_evaluation_python()), "-m", "app.services.evaluation.run_job", run_id],
        cwd=str(backend_root),
        env=env,
    )
    logger.info("spawn_evaluation_run_job: launched subprocess for run_id=%s", run_id)


def process_evaluation_run_job(
    run_id: str,
    *,
    retrieval_k: int = DEFAULT_RETRIEVAL_K,
    retrieval_candidate_pool_size: int = DEFAULT_RETRIEVAL_CANDIDATE_POOL_SIZE,
) -> None:
    """Background-task entry point (``background_tasks.add_task`` target).

    Idempotent: safe to invoke more than once for the same ``run_id``.
    - If the run is not found, or its status is no longer "running"
      (already "completed"/"failed"), this is a no-op.
    - If component rows already exist for this run_id (a previous
      invocation already did the real work, e.g. a retried background
      task), this is also a no-op -- it never re-runs evaluation or
      duplicates persisted rows.

    The real evaluation work (``run_evaluation``, which may make real
    Groq calls) happens with NO database transaction open; persistence
    is a single short transaction afterward, committed once the run is
    fully persisted and marked "completed" -- so a reader never observes
    a "completed" run with missing components, and a DB failure during
    persistence marks the run "failed" rather than leaving it stuck
    "running" or falsely "completed".
    """
    if not _claim_running_evaluation_job(run_id):
        return

    logger.info("process_evaluation_run_job: run_id=%s claimed; starting run_evaluation", run_id)
    try:
        result = run_evaluation(
            retrieval_k=retrieval_k, retrieval_candidate_pool_size=retrieval_candidate_pool_size
        )
    except Exception as exc:  # noqa: BLE001 -- a run must end "failed", never stuck "running"
        _mark_run_failed(run_id, f"{type(exc).__name__}: {exc}"[:2000])
        logger.exception("process_evaluation_run_job: run_id=%s failed during evaluation.", run_id)
        return

    session = get_session_factory()()
    try:
        run = session.get(EvaluationRun, run_id)
        if run is None or run.status != "running":
            return
        try:
            _persist_result(
                session, run=run, result=result,
                retrieval_k=retrieval_k, retrieval_candidate_pool_size=retrieval_candidate_pool_size,
            )
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
        except Exception as exc:  # noqa: BLE001 -- never mark "completed" when persistence itself failed
            session.rollback()
            run = session.get(EvaluationRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error_message = f"persistence failed: {type(exc).__name__}: {exc}"[:2000]
                run.completed_at = datetime.now(timezone.utc)
                session.commit()
            logger.exception("process_evaluation_run_job: run_id=%s failed during persistence.", run_id)
    finally:
        session.close()


def _claim_running_evaluation_job(run_id: str) -> bool:
    """Return True if this worker should run evaluation for ``run_id``.

    Commits and closes the inspection session before returning True so
    ``run_evaluation`` (Chroma / Groq) never holds an idle DB transaction.
    Polling GET /admin/evaluation/{run_id} was timing out at 60s when the
    previous implementation left that transaction open for the whole job.
    """
    session = get_session_factory()()
    try:
        run = session.get(EvaluationRun, run_id)
        if run is None:
            logger.warning("process_evaluation_run_job: run_id=%s not found; nothing to do.", run_id)
            return False
        if run.status != "running":
            logger.info(
                "process_evaluation_run_job: run_id=%s already status=%s; skipping (idempotent no-op).",
                run_id, run.status,
            )
            return False
        already_persisted = session.query(EvaluationComponent).filter_by(run_id=run_id).count()
        if already_persisted > 0:
            logger.info(
                "process_evaluation_run_job: run_id=%s already has %d persisted component(s); "
                "skipping duplicate processing.",
                run_id, already_persisted,
            )
            return False
        session.commit()
        return True
    finally:
        session.close()


def _mark_run_failed(run_id: str, error_message: str) -> None:
    session = get_session_factory()()
    try:
        run = session.get(EvaluationRun, run_id)
        if run is None or run.status != "running":
            return
        run.status = "failed"
        run.error_message = error_message
        run.completed_at = datetime.now(timezone.utc)
        session.commit()
    finally:
        session.close()


# --- read helpers (pagination-aware) ------------------------------------------


def list_runs(session: Session, *, limit: int = 20, offset: int = 0) -> tuple[list[EvaluationRun], int]:
    total = session.query(EvaluationRun).count()
    rows = (
        session.query(EvaluationRun)
        .order_by(EvaluationRun.started_at.desc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return rows, total


def get_run_with_components(session: Session, run_id: str) -> EvaluationRun | None:
    return session.get(EvaluationRun, run_id)


def get_latest_run(session: Session) -> EvaluationRun | None:
    return session.query(EvaluationRun).order_by(EvaluationRun.started_at.desc()).first()


def list_case_results(
    session: Session, *, component_id: str, limit: int = 50, offset: int = 0
) -> tuple[list[EvaluationCaseResult], int]:
    total = session.query(EvaluationCaseResult).filter_by(component_id=component_id).count()
    rows = (
        session.query(EvaluationCaseResult)
        .filter_by(component_id=component_id)
        .order_by(EvaluationCaseResult.created_at.asc())
        .limit(limit)
        .offset(offset)
        .all()
    )
    return rows, total


def get_confusion_matrix(session: Session, *, run_id: str, component: str) -> EvaluationConfusionMatrix | None:
    return (
        session.query(EvaluationConfusionMatrix)
        .join(EvaluationComponent, EvaluationConfusionMatrix.component_id == EvaluationComponent.id)
        .filter(EvaluationConfusionMatrix.run_id == run_id, EvaluationComponent.component == component)
        .one_or_none()
    )
