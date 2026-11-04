"""Admin routes for the Model Evaluation System.

Admin-only (``require_admin_only_key``, the same strict admin-only
dependency ``admin_rebuild_knowledge_base`` uses) -- no public access, no
office-role access. Running an evaluation makes real Groq calls and
reads Chroma; it never writes to ChromaDB or touches production
PostgreSQL (see ``app.services.evaluation.evaluation_service``/
``persistence`` for those guarantees).
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db_session, get_session_factory
from app.models.db_models import EvaluationComponent, EvaluationResult
from app.models.schemas import (
    ErrorResponse,
    EvaluationCaseResultListResponse,
    EvaluationCaseResultSchema,
    EvaluationComponentSchema,
    EvaluationConfusionMatrixResponse,
    EvaluationMetricSchema,
    EvaluationModelInfoSchema,
    EvaluationModelsResponse,
    EvaluationRunDetailSchema,
    EvaluationRunListResponse,
    EvaluationRunSummarySchema,
    EvaluationSummaryResponse,
    StartEvaluationRunResponse,
)
from app.routes.admin.knowledge_base import require_admin_only_key
from app.services.evaluation import persistence
from app.services.evaluation.evaluation_service import model_inventory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/evaluation", tags=["Admin — Model Evaluation"])


def _run_summary(run) -> EvaluationRunSummarySchema:
    return EvaluationRunSummarySchema(
        run_id=run.id,
        status=run.status,
        triggered_by_user_id=run.triggered_by_user_id,
        started_at=run.started_at.isoformat(),
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
        error_message=run.error_message,
    )


def _component_schema(session: Session, component_row: EvaluationComponent) -> EvaluationComponentSchema:
    results = session.query(EvaluationResult).filter_by(component_id=component_row.id).all()
    metrics = [
        EvaluationMetricSchema(
            metric_name=r.metric_name,
            metric_value=r.metric_value,
            extra=json.loads(r.extra_json) if r.extra_json else None,
        )
        for r in results
    ]
    return EvaluationComponentSchema(
        component_id=component_row.id,
        component=component_row.component,
        status=component_row.status,
        reason=component_row.reason,
        note=component_row.note,
        model_name=component_row.model_name,
        shares_model_with=component_row.shares_model_with,
        allow_llm_fallback=component_row.allow_llm_fallback,
        case_count=component_row.case_count,
        skipped_unlabeled_count=component_row.skipped_unlabeled_count,
        has_confusion_matrix=component_row.confusion_matrix is not None,
        metrics=metrics,
    )


@router.post(
    "/run",
    response_model=StartEvaluationRunResponse,
    summary="[Admin] Start a new model evaluation run",
)
async def admin_start_evaluation_run(
    background_tasks: BackgroundTasks,
    triggered_by_user_id: str | None = Depends(require_admin_only_key),
) -> StartEvaluationRunResponse:
    """Creates the run row synchronously (status="running") and schedules
    the real evaluation + persistence as a background task -- mirrors
    ``POST /admin/knowledge-base/extract``'s own job-creation shape, so
    this request returns immediately regardless of how long the real
    Groq/retrieval calls take."""

    def _create_run():
        session = get_session_factory()()
        try:
            return persistence.start_evaluation_run(
                session, triggered_by_user_id=triggered_by_user_id
            )
        finally:
            session.close()

    run = await asyncio.to_thread(_create_run)
    background_tasks.add_task(persistence.spawn_evaluation_run_job, run.id)
    return StartEvaluationRunResponse(run_id=run.id, status=run.status)


@router.get(
    "/models",
    response_model=EvaluationModelsResponse,
    summary="[Admin] List the AI components this evaluation system covers",
)
async def admin_evaluation_models(
    _: None = Depends(require_admin_only_key),
) -> EvaluationModelsResponse:
    return EvaluationModelsResponse(
        models=[
            EvaluationModelInfoSchema(
                component=m.component,
                model_name=m.model_name,
                shares_model_with=m.shares_model_with,
                allow_llm_fallback=m.allow_llm_fallback,
            )
            for m in model_inventory()
        ]
    )


@router.get(
    "/summary",
    response_model=EvaluationSummaryResponse,
    summary="[Admin] Latest evaluation run's status and per-component results",
)
async def admin_evaluation_summary(
    _: None = Depends(require_admin_only_key),
    session: Session = Depends(get_db_session),
) -> EvaluationSummaryResponse:
    latest = persistence.get_latest_run(session)
    if latest is None:
        # No evaluation has ever been run -- an explicit empty state, never fabricated data.
        return EvaluationSummaryResponse(latest_run=None, components=[])
    return EvaluationSummaryResponse(
        latest_run=_run_summary(latest),
        components=[_component_schema(session, c) for c in latest.components],
    )


@router.get(
    "/history",
    response_model=EvaluationRunListResponse,
    summary="[Admin] Paginated evaluation run history",
)
async def admin_evaluation_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_admin_only_key),
    session: Session = Depends(get_db_session),
) -> EvaluationRunListResponse:
    runs, total = persistence.list_runs(session, limit=limit, offset=offset)
    return EvaluationRunListResponse(
        runs=[_run_summary(r) for r in runs], total=total, limit=limit, offset=offset
    )


@router.get(
    "/{run_id}",
    response_model=EvaluationRunDetailSchema,
    responses={404: {"model": ErrorResponse}},
    summary="[Admin] Full detail for one evaluation run",
)
async def admin_get_evaluation_run(
    run_id: str,
    _: None = Depends(require_admin_only_key),
    session: Session = Depends(get_db_session),
) -> EvaluationRunDetailSchema:
    """Component-level metrics only -- never the full case-level result
    list (see the dedicated, paginated cases endpoint below) so this
    response stays bounded regardless of dataset size."""
    run = persistence.get_run_with_components(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    config = json.loads(run.config_json) if run.config_json else {}
    return EvaluationRunDetailSchema(
        **_run_summary(run).model_dump(),
        config=config,
        components=[_component_schema(session, c) for c in run.components],
    )


@router.get(
    "/{run_id}/confusion-matrix",
    response_model=EvaluationConfusionMatrixResponse,
    responses={404: {"model": ErrorResponse}},
    summary="[Admin] Confusion matrix for one classification component in one run",
)
async def admin_get_confusion_matrix(
    run_id: str,
    component: str = Query(..., description="Component name, e.g. classify_question"),
    _: None = Depends(require_admin_only_key),
    session: Session = Depends(get_db_session),
) -> EvaluationConfusionMatrixResponse:
    matrix = persistence.get_confusion_matrix(session, run_id=run_id, component=component)
    if matrix is None:
        raise HTTPException(
            status_code=404,
            detail=f"No confusion matrix for component={component!r} in run {run_id!r}.",
        )
    return EvaluationConfusionMatrixResponse(
        component=component,
        labels=json.loads(matrix.labels_json),
        matrix=json.loads(matrix.matrix_json),
        case_count=matrix.case_count,
    )


@router.get(
    "/{run_id}/components/{component_id}/cases",
    response_model=EvaluationCaseResultListResponse,
    responses={404: {"model": ErrorResponse}},
    summary="[Admin] Paginated per-case raw predictions for one component",
)
async def admin_get_component_case_results(
    run_id: str,
    component_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: None = Depends(require_admin_only_key),
    session: Session = Depends(get_db_session),
) -> EvaluationCaseResultListResponse:
    component_row = session.get(EvaluationComponent, component_id)
    if component_row is None or component_row.run_id != run_id:
        raise HTTPException(status_code=404, detail="Component not found for this run.")
    rows, total = persistence.list_case_results(session, component_id=component_id, limit=limit, offset=offset)
    return EvaluationCaseResultListResponse(
        component=component_row.component,
        case_results=[
            EvaluationCaseResultSchema(
                case_id=r.case_id, predicted=r.predicted, expected=r.expected,
                correct=r.correct, latency_ms=r.latency_ms,
            )
            for r in rows
        ],
        total=total, limit=limit, offset=offset,
    )
