"""add bounded multi-agent scenario runtime

Revision ID: 7c1e2f3a4b5c
Revises: 0d8f9a1b2c3d
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "7c1e2f3a4b5c"
down_revision: str | None = "0d8f9a1b2c3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_evaluation_targets_kind_protocol", "evaluation_targets", type_="check")
    op.drop_constraint("target_kind", "evaluation_targets", type_="check")
    op.drop_constraint("target_protocol", "evaluation_targets", type_="check")
    op.alter_column(
        "evaluation_targets",
        "target_kind",
        existing_type=sa.String(length=5),
        type_=sa.String(length=8),
    )
    op.alter_column(
        "evaluation_targets",
        "protocol",
        existing_type=sa.String(length=5),
        type_=sa.String(length=8),
    )
    op.create_check_constraint(
        "target_kind",
        "evaluation_targets",
        "target_kind IN ('agent', 'tool', 'scenario')",
    )
    op.create_check_constraint(
        "target_protocol",
        "evaluation_targets",
        "protocol IN ('http', 'sse', 'ag_ui', 'a2a', 'mcp', 'scenario')",
    )
    op.create_check_constraint(
        "ck_evaluation_targets_kind_protocol",
        "evaluation_targets",
        "(target_kind = 'agent' AND protocol IN ('http', 'sse', 'ag_ui', 'a2a')) "
        "OR (target_kind = 'tool' AND protocol = 'mcp') "
        "OR (target_kind = 'scenario' AND protocol = 'scenario')",
    )
    op.create_table(
        "scenario_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("scenario_version_id", sa.BigInteger(), nullable=False),
        sa.Column("gate_result_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "mode",
            sa.Enum("shadow", "pilot", name="scenario_mode", native_enum=False),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("input_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("input_sha256", sa.String(length=64), nullable=False),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("limits", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "cancel_requested",
                "cancelled",
                "completed",
                "failed",
                name="scenario_run_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("trace_id", sa.String(length=32), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=30), nullable=False),
        sa.Column("actor_id", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["scenario_version_id"], ["agent_versions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["gate_result_id"], ["gate_results.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "idempotency_key", name="uq_scenario_runs_org_idempotency"
        ),
    )
    op.create_index("ix_scenario_runs_organization_id", "scenario_runs", ["organization_id"])
    op.create_index(
        "ix_scenario_runs_scenario_version_id",
        "scenario_runs",
        ["scenario_version_id"],
    )
    op.create_index("ix_scenario_runs_gate_result_id", "scenario_runs", ["gate_result_id"])
    op.create_index("ix_scenario_runs_trace_id", "scenario_runs", ["trace_id"])
    op.create_index("ix_scenario_runs_status_created", "scenario_runs", ["status", "created_at"])
    op.create_table(
        "scenario_node_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("scenario_run_id", sa.BigInteger(), nullable=False),
        sa.Column("node_id", sa.String(length=100), nullable=False),
        sa.Column("target_version_id", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("invocation_id", sa.String(length=200), nullable=True),
        sa.Column("input_sha256", sa.String(length=64), nullable=True),
        sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_scenario_node_runs_status",
        ),
        sa.ForeignKeyConstraint(["scenario_run_id"], ["scenario_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_version_id"], ["agent_versions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_run_id", "node_id", "attempt", name="uq_scenario_node_runs_attempt"
        ),
    )
    op.create_index(
        "ix_scenario_node_runs_scenario_run_id",
        "scenario_node_runs",
        ["scenario_run_id"],
    )
    op.create_index(
        "ix_scenario_node_runs_target_version_id",
        "scenario_node_runs",
        ["target_version_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scenario_node_runs_target_version_id", table_name="scenario_node_runs")
    op.drop_index("ix_scenario_node_runs_scenario_run_id", table_name="scenario_node_runs")
    op.drop_table("scenario_node_runs")
    op.drop_index("ix_scenario_runs_status_created", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_trace_id", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_gate_result_id", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_scenario_version_id", table_name="scenario_runs")
    op.drop_index("ix_scenario_runs_organization_id", table_name="scenario_runs")
    op.drop_table("scenario_runs")
    op.drop_constraint("ck_evaluation_targets_kind_protocol", "evaluation_targets", type_="check")
    op.drop_constraint("target_kind", "evaluation_targets", type_="check")
    op.drop_constraint("target_protocol", "evaluation_targets", type_="check")
    op.alter_column(
        "evaluation_targets",
        "target_kind",
        existing_type=sa.String(length=8),
        type_=sa.String(length=5),
    )
    op.alter_column(
        "evaluation_targets",
        "protocol",
        existing_type=sa.String(length=8),
        type_=sa.String(length=5),
    )
    op.create_check_constraint(
        "target_kind", "evaluation_targets", "target_kind IN ('agent', 'tool')"
    )
    op.create_check_constraint(
        "target_protocol",
        "evaluation_targets",
        "protocol IN ('http', 'sse', 'ag_ui', 'a2a', 'mcp')",
    )
    op.create_check_constraint(
        "ck_evaluation_targets_kind_protocol",
        "evaluation_targets",
        "(target_kind = 'agent' AND protocol IN ('http', 'sse', 'ag_ui', 'a2a')) "
        "OR (target_kind = 'tool' AND protocol = 'mcp')",
    )
