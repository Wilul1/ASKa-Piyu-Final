"""Add Model Evaluation System tables (evaluation_runs, evaluation_components,
evaluation_results, evaluation_confusion_matrices, evaluation_case_results).

Revision ID: 20261104_0015
Revises: 20261014_0014
Create Date: 2026-11-04

Purely additive: five new tables, no existing table touched. Local-only
feature -- these tables store the output of
app.services.evaluation.evaluation_service.run_evaluation (which itself
never writes to ChromaDB or changes chatbot/retrieval behavior). See
app/models/db_models.py's EvaluationRun/EvaluationComponent/
EvaluationResult/EvaluationConfusionMatrix/EvaluationCaseResult for the
exact column-for-column mapping this mirrors.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "20261104_0015"
down_revision: Union[str, None] = "20261014_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = inspect(bind)

    if not existing.has_table("evaluation_runs"):
        op.create_table(
            "evaluation_runs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
            sa.Column("triggered_by_user_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=True),
            sa.Column("config_json", sa.Text(), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('running', 'completed', 'failed')",
                name="ck_evaluation_runs_status",
            ),
        )
        op.create_index("ix_evaluation_runs_status", "evaluation_runs", ["status"])

    if not existing.has_table("evaluation_components"):
        op.create_table(
            "evaluation_components",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("evaluation_runs.id"), nullable=False),
            sa.Column("component", sa.String(length=80), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("model_name", sa.String(length=255), nullable=False),
            sa.Column("shares_model_with", sa.String(length=80), nullable=True),
            sa.Column("allow_llm_fallback", sa.Boolean(), nullable=True),
            sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_unlabeled_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.CheckConstraint(
                "status IN ('evaluated', 'not_evaluable', 'failed')",
                name="ck_evaluation_components_status",
            ),
            sa.UniqueConstraint("run_id", "component", name="uq_evaluation_components_run_component"),
        )
        op.create_index("ix_evaluation_components_run_id", "evaluation_components", ["run_id"])

    if not existing.has_table("evaluation_results"):
        op.create_table(
            "evaluation_results",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("evaluation_runs.id"), nullable=False),
            sa.Column(
                "component_id", sa.String(length=36), sa.ForeignKey("evaluation_components.id"), nullable=False
            ),
            sa.Column("metric_name", sa.String(length=80), nullable=False),
            sa.Column("metric_value", sa.Float(), nullable=True),
            sa.Column("extra_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_evaluation_results_run_id", "evaluation_results", ["run_id"])
        op.create_index("ix_evaluation_results_component_id", "evaluation_results", ["component_id"])

    if not existing.has_table("evaluation_confusion_matrices"):
        op.create_table(
            "evaluation_confusion_matrices",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("evaluation_runs.id"), nullable=False),
            sa.Column(
                "component_id", sa.String(length=36), sa.ForeignKey("evaluation_components.id"), nullable=False
            ),
            sa.Column("labels_json", sa.Text(), nullable=False),
            sa.Column("matrix_json", sa.Text(), nullable=False),
            sa.Column("case_count", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("component_id", name="uq_evaluation_confusion_matrices_component_id"),
        )
        op.create_index("ix_evaluation_confusion_matrices_run_id", "evaluation_confusion_matrices", ["run_id"])
        op.create_index(
            "ix_evaluation_confusion_matrices_component_id", "evaluation_confusion_matrices", ["component_id"]
        )

    if not existing.has_table("evaluation_case_results"):
        op.create_table(
            "evaluation_case_results",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("run_id", sa.String(length=36), sa.ForeignKey("evaluation_runs.id"), nullable=False),
            sa.Column(
                "component_id", sa.String(length=36), sa.ForeignKey("evaluation_components.id"), nullable=False
            ),
            sa.Column("case_id", sa.String(length=120), nullable=False),
            sa.Column("predicted", sa.Text(), nullable=True),
            sa.Column("expected", sa.Text(), nullable=True),
            sa.Column("correct", sa.Boolean(), nullable=True),
            sa.Column("latency_ms", sa.Float(), nullable=True),
            sa.Column("raw_response_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_evaluation_case_results_run_id", "evaluation_case_results", ["run_id"])
        op.create_index("ix_evaluation_case_results_component_id", "evaluation_case_results", ["component_id"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = inspect(bind)
    # Drop in dependency order (children before evaluation_components/evaluation_runs).
    for table in (
        "evaluation_case_results",
        "evaluation_confusion_matrices",
        "evaluation_results",
        "evaluation_components",
        "evaluation_runs",
    ):
        if existing.has_table(table):
            op.drop_table(table)
