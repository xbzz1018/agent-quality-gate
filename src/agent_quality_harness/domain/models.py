from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .enums import (
    GateDecision,
    MeasurementStatus,
    RunStatus,
    TargetKind,
    TargetProtocol,
    VersionRole,
)

JSON_VALUE = JSON().with_variant(JSONB(), "postgresql")


def enum_column(enum_type: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_type,
        name=name,
        native_enum=False,
        create_constraint=True,
        validate_strings=True,
        values_callable=lambda values: [item.value for item in values],
    )


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class EvaluationTarget(TimestampMixin, Base):
    __tablename__ = "evaluation_targets"
    __table_args__ = (
        CheckConstraint(
            "(target_kind = 'agent' AND protocol IN ('http', 'sse', 'ag_ui', 'a2a')) "
            "OR (target_kind = 'tool' AND protocol = 'mcp')",
            name="ck_evaluation_targets_kind_protocol",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    target_kind: Mapped[TargetKind] = mapped_column(
        enum_column(TargetKind, "target_kind"), nullable=False
    )
    protocol: Mapped[TargetProtocol] = mapped_column(
        enum_column(TargetProtocol, "target_protocol"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    auth_ref: Mapped[str | None] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    versions: Mapped[list["AgentVersion"]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class AgentVersion(TimestampMixin, Base):
    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("target_id", "version", name="uq_agent_versions_target_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("evaluation_targets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    version: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    tool_schema_hash: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)

    target: Mapped[EvaluationTarget] = relationship(back_populates="versions")


class EvalDataset(TimestampMixin, Base):
    __tablename__ = "eval_datasets"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_eval_datasets_name_version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    split: Mapped[str] = mapped_column(Text, default="test", nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cases: Mapped[list["EvalCase"]] = relationship(
        back_populates="dataset", cascade="all, delete-orphan", order_by="EvalCase.ordinal"
    )


class EvalCase(TimestampMixin, Base):
    __tablename__ = "eval_cases"
    __table_args__ = (
        UniqueConstraint("dataset_id", "external_id", name="uq_eval_cases_dataset_external"),
        UniqueConstraint("dataset_id", "sha256", name="uq_eval_cases_dataset_hash"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON_VALUE, default=list, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    dataset: Mapped[EvalDataset] = relationship(back_populates="cases")


class EvalRun(TimestampMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint(
            "completed_case_count >= 0 AND expected_case_count >= completed_case_count",
            name="ck_eval_runs_case_counts",
        ),
        Index("ix_eval_runs_status_created", "status", "created_at"),
        Index(
            "ix_eval_runs_active_created",
            "created_at",
            postgresql_where=text("status IN ('queued', 'running', 'cancel_requested')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    dataset_id: Mapped[int] = mapped_column(
        ForeignKey("eval_datasets.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    baseline_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), index=True
    )
    candidate_version_id: Mapped[int] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    replay_of_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="SET NULL"), index=True
    )
    gate_policy_id: Mapped[int | None] = mapped_column(
        ForeignKey("gate_policies.id", ondelete="RESTRICT"), index=True
    )
    pricing_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("pricing_snapshots.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[RunStatus] = mapped_column(
        enum_column(RunStatus, "run_status"), default=RunStatus.QUEUED, nullable=False
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    manifest: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    benchmark_mode: Mapped[bool] = mapped_column(default=False, nullable=False)
    expected_case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class CaseResult(TimestampMixin, Base):
    __tablename__ = "case_results"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "case_id", "version_role", "attempt", name="uq_case_results_attempt"
        ),
        Index("ix_case_results_run_role", "run_id", "version_role"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), index=True, nullable=False
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("eval_cases.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    version_role: Mapped[VersionRole] = mapped_column(
        enum_column(VersionRole, "version_role"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE)
    final_action: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(String(32), index=True)
    scores: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    failure_type: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)


class GatePolicy(TimestampMixin, Base):
    __tablename__ = "gate_policies"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_gate_policies_name_version"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    active: Mapped[bool] = mapped_column(default=True, nullable=False)


class GateResult(Base):
    __tablename__ = "gate_results"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    policy_id: Mapped[int] = mapped_column(
        ForeignKey("gate_policies.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    decision: Mapped[GateDecision] = mapped_column(
        enum_column(GateDecision, "gate_decision"), nullable=False
    )
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSON_VALUE, default=list, nullable=False)
    metric_deltas: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PricingSnapshot(TimestampMixin, Base):
    __tablename__ = "pricing_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "provider", "model", "version", name="uq_pricing_snapshots_provider_model_version"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    prices: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)


class UsageMeasurement(TimestampMixin, Base):
    __tablename__ = "usage_measurements"
    __table_args__ = (
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0", name="ck_usage_input_tokens"),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_usage_output_tokens"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    case_result_id: Mapped[int] = mapped_column(
        ForeignKey("case_results.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    pricing_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("pricing_snapshots.id", ondelete="RESTRICT"), index=True
    )
    measurement_status: Mapped[MeasurementStatus] = mapped_column(
        enum_column(MeasurementStatus, "measurement_status"), nullable=False
    )
    cost_status: Mapped[MeasurementStatus] = mapped_column(
        enum_column(MeasurementStatus, "cost_status"), nullable=False
    )
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_write_tokens: Mapped[int | None] = mapped_column(BigInteger)
    reasoning_tokens: Mapped[int | None] = mapped_column(BigInteger)
    embedding_tokens: Mapped[int | None] = mapped_column(BigInteger)
    vision_tokens: Mapped[int | None] = mapped_column(BigInteger)
    judge_tokens: Mapped[int | None] = mapped_column(BigInteger)
    model_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    external_tool_cost: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    cost_components: Mapped[dict[str, Any]] = mapped_column(
        JSON_VALUE, default=dict, nullable=False
    )
    raw_usage: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (Index("ix_run_events_run_id_id", "run_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    case_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_results.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE, default=dict, nullable=False)
    redacted: Mapped[bool] = mapped_column(default=True, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
