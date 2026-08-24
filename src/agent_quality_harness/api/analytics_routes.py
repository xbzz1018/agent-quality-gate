from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select

from agent_quality_harness.domain.enums import MeasurementStatus, RunStatus
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalRun,
    EvaluationTarget,
    GateResult,
    UsageMeasurement,
)

from .dependencies import SessionDependency, current_organization_id
from .schemas import CaseResultRead, GateResultRead, Page

router = APIRouter(tags=["analytics"])


class DashboardSummary(BaseModel):
    target_count: int
    active_target_count: int
    run_count: int
    completed_run_count: int
    failed_run_count: int
    latest_gate_decisions: list[dict[str, Any]]
    failure_categories: list[dict[str, Any]]
    run_trend: list[dict[str, Any]]


class UsageSummary(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    reasoning_tokens: int | None
    embedding_tokens: int | None
    vision_tokens: int | None
    judge_tokens: int | None
    model_cost: Decimal | None
    external_tool_cost: Decimal | None
    unknown_measurement_ratio: float
    unknown_cost_ratio: float
    groups: list[dict[str, Any]]


@router.get("/dashboard/summary", response_model=DashboardSummary)
def dashboard_summary(request: Request, session: SessionDependency):
    organization_id = current_organization_id(request)
    target_count = int(
        session.scalar(
            select(func.count())
            .select_from(EvaluationTarget)
            .where(EvaluationTarget.organization_id == organization_id)
        )
        or 0
    )
    active_target_count = int(
        session.scalar(
            select(func.count())
            .select_from(EvaluationTarget)
            .where(
                EvaluationTarget.organization_id == organization_id,
                EvaluationTarget.enabled.is_(True),
            )
        )
        or 0
    )
    runs = list(
        session.scalars(
            select(EvalRun)
            .where(EvalRun.organization_id == organization_id)
            .order_by(EvalRun.id.desc())
        )
    )
    recent_gates = list(
        session.execute(
            select(GateResult, EvalRun.created_at)
            .join(EvalRun, EvalRun.id == GateResult.run_id)
            .where(EvalRun.organization_id == organization_id)
            .order_by(GateResult.evaluated_at.desc())
            .limit(8)
        )
    )
    failures = Counter(
        session.scalars(
            select(CaseResult.failure_type)
            .join(EvalRun, EvalRun.id == CaseResult.run_id)
            .where(
                EvalRun.organization_id == organization_id,
                CaseResult.failure_type.is_not(None),
            )
        )
    )
    trend_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for run in runs:
        day = run.created_at.astimezone(UTC).date().isoformat()
        trend_counts[day][run.status.value] += 1
    return DashboardSummary(
        target_count=target_count,
        active_target_count=active_target_count,
        run_count=len(runs),
        completed_run_count=sum(run.status is RunStatus.COMPLETED for run in runs),
        failed_run_count=sum(run.status is RunStatus.FAILED for run in runs),
        latest_gate_decisions=[
            {
                "run_id": gate.run_id,
                "decision": gate.decision.value,
                "evaluated_at": gate.evaluated_at.isoformat(),
                "run_created_at": created_at.isoformat(),
            }
            for gate, created_at in recent_gates
        ],
        failure_categories=[
            {"failure_type": key, "count": value} for key, value in failures.most_common(8)
        ],
        run_trend=[
            {"date": day, "total": sum(counts.values()), **dict(counts)}
            for day, counts in sorted(trend_counts.items())[-14:]
        ],
    )


@router.get("/usage/summary", response_model=UsageSummary)
def usage_summary(
    request: Request,
    session: SessionDependency,
    target_id: int | None = None,
    version_id: int | None = None,
    model: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    group_by: str = Query(default="target", pattern="^(day|target|version|model)$"),
):
    organization_id = current_organization_id(request)
    statement = (
        select(UsageMeasurement, EvalRun, AgentVersion, EvaluationTarget)
        .join(CaseResult, CaseResult.id == UsageMeasurement.case_result_id)
        .join(EvalRun, EvalRun.id == CaseResult.run_id)
        .join(AgentVersion, AgentVersion.id == EvalRun.candidate_version_id)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(EvalRun.organization_id == organization_id)
    )
    if target_id is not None:
        statement = statement.where(EvaluationTarget.id == target_id)
    if version_id is not None:
        statement = statement.where(AgentVersion.id == version_id)
    if model:
        statement = statement.where(AgentVersion.model == model)
    if created_from:
        statement = statement.where(EvalRun.created_at >= created_from)
    if created_to:
        statement = statement.where(EvalRun.created_at <= created_to)
    rows = list(session.execute(statement))
    token_fields = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "embedding_tokens",
        "vision_tokens",
        "judge_tokens",
    )
    totals = {
        field: _sum_nullable([getattr(usage, field) for usage, *_ in rows])
        for field in token_fields
    }
    model_cost = _sum_nullable([usage.model_cost for usage, *_ in rows])
    external_tool_cost = _sum_nullable([usage.external_tool_cost for usage, *_ in rows])
    grouped: dict[str, list[UsageMeasurement]] = defaultdict(list)
    for usage, run, version, target in rows:
        key = {
            "day": run.created_at.date().isoformat(),
            "target": target.name,
            "version": version.version,
            "model": version.model or "UNKNOWN",
        }[group_by]
        grouped[key].append(usage)
    groups = []
    for key, measurements in sorted(grouped.items()):
        groups.append(
            {
                "key": key,
                "input_tokens": _sum_nullable([item.input_tokens for item in measurements]),
                "output_tokens": _sum_nullable([item.output_tokens for item in measurements]),
                "model_cost": _json_decimal(
                    _sum_nullable([item.model_cost for item in measurements])
                ),
                "external_tool_cost": _json_decimal(
                    _sum_nullable([item.external_tool_cost for item in measurements])
                ),
                "unknown_ratio": _ratio_unknown(measurements, "measurement_status"),
            }
        )
    return UsageSummary(
        **totals,
        model_cost=model_cost,
        external_tool_cost=external_tool_cost,
        unknown_measurement_ratio=_ratio_unknown(
            [usage for usage, *_ in rows], "measurement_status"
        ),
        unknown_cost_ratio=_ratio_unknown([usage for usage, *_ in rows], "cost_status"),
        groups=groups,
    )


@router.get("/results/search", response_model=Page[CaseResultRead])
def result_search(
    request: Request,
    session: SessionDependency,
    failure_only: bool = False,
    trace_id: str | None = None,
    run_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [EvalRun.organization_id == current_organization_id(request)]
    if failure_only:
        filters.append(CaseResult.failure_type.is_not(None))
    if trace_id:
        filters.append(CaseResult.trace_id == trace_id)
    if run_id:
        filters.append(CaseResult.run_id == run_id)
    base = select(CaseResult).join(EvalRun, EvalRun.id == CaseResult.run_id).where(*filters)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(CaseResult)
            .join(EvalRun, EvalRun.id == CaseResult.run_id)
            .where(*filters)
        )
        or 0
    )
    rows = list(
        session.scalars(
            base.order_by(CaseResult.id.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    )
    jaeger = request.app.state.settings.jaeger_base_url.rstrip("/")
    items = [_case_result(session, row, jaeger) for row in rows]
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/gate-audits", response_model=Page[GateResultRead])
def gate_audits(
    request: Request,
    session: SessionDependency,
    decision: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    filters = [EvalRun.organization_id == current_organization_id(request)]
    if decision:
        filters.append(GateResult.decision == decision)
    total = int(
        session.scalar(
            select(func.count())
            .select_from(GateResult)
            .join(EvalRun, EvalRun.id == GateResult.run_id)
            .where(*filters)
        )
        or 0
    )
    items = list(
        session.scalars(
            select(GateResult)
            .join(EvalRun, EvalRun.id == GateResult.run_id)
            .where(*filters)
            .order_by(GateResult.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=items, total=total, page=page, page_size=page_size)


def _case_result(session, row: CaseResult, jaeger_base_url: str) -> dict[str, Any]:
    usage = session.scalar(
        select(UsageMeasurement).where(UsageMeasurement.case_result_id == row.id)
    )
    return {
        "id": row.id,
        "run_id": row.run_id,
        "case_id": row.case_id,
        "version_role": row.version_role,
        "attempt": row.attempt,
        "output": row.output,
        "final_action": row.final_action,
        "trace_id": row.trace_id,
        "trace_url": None if row.trace_id is None else f"{jaeger_base_url}/trace/{row.trace_id}",
        "scores": row.scores,
        "failure_type": row.failure_type,
        "latency_ms": row.latency_ms,
        "usage": usage,
    }


def _sum_nullable(values):
    known = [value for value in values if value is not None]
    return None if not known else sum(known)


def _ratio_unknown(measurements, field: str) -> float:
    if not measurements:
        return 0.0
    count = sum(getattr(item, field) is MeasurementStatus.UNKNOWN for item in measurements)
    return round(count / len(measurements), 4)


def _json_decimal(value):
    return None if value is None else str(value)
