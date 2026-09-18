from __future__ import annotations

import asyncio
import hashlib
import json
import socket
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_quality_harness.adapters.scenario import (
    ScenarioCancelled,
    ScenarioExecution,
    execute_scenario,
)
from agent_quality_harness.api.schemas import ScenarioRunCreate
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import get_tracer
from agent_quality_harness.domain.enums import GateDecision, RunStatus, ScenarioMode, TargetKind
from agent_quality_harness.domain.models import (
    AgentVersion,
    EvalRun,
    EvaluationTarget,
    GateResult,
    PolicyEvaluation,
    ScenarioNodeRun,
    ScenarioRun,
)
from agent_quality_harness.scenarios import resolve_scenario_version
from agent_quality_harness.security import AuthContext


def create_scenario_run(
    session: Session,
    payload: ScenarioRunCreate,
    *,
    organization_id: int,
    context: AuthContext,
    idempotency_key: str,
) -> tuple[ScenarioRun, bool]:
    existing = session.scalar(
        select(ScenarioRun).where(
            ScenarioRun.organization_id == organization_id,
            ScenarioRun.idempotency_key == idempotency_key,
        )
    )
    input_data = dict(payload.input)
    input_sha256 = _sha256(input_data)
    if existing is not None:
        if (
            existing.scenario_version_id != payload.scenario_version_id
            or existing.mode is not payload.mode
            or existing.input_sha256 != input_sha256
        ):
            raise ValueError("idempotency key was already used with a different request")
        return existing, False
    version = session.scalar(
        select(AgentVersion)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id == payload.scenario_version_id,
            EvaluationTarget.organization_id == organization_id,
            EvaluationTarget.target_kind == TargetKind.SCENARIO,
            EvaluationTarget.enabled.is_(True),
        )
    )
    if version is None:
        raise LookupError("scenario version not found")
    plan, participants = resolve_scenario_version(session, version, organization_id)
    _validate_side_effects(payload.mode, participants)
    limits = payload.limits.model_dump(mode="json", exclude_none=True)
    gate_result = None
    if payload.mode is ScenarioMode.PILOT:
        if not limits:
            raise ValueError("pilot mode requires a token or cost budget")
        gate_result = _pilot_gate(session, version, organization_id, plan.sha256)
    row = ScenarioRun(
        organization_id=organization_id,
        scenario_version_id=version.id,
        gate_result_id=None if gate_result is None else gate_result.id,
        mode=payload.mode,
        idempotency_key=idempotency_key,
        input_data=input_data,
        input_sha256=input_sha256,
        limits=limits,
        usage={},
        status=RunStatus.QUEUED,
        actor_type=context.actor_type,
        actor_id=context.actor_id,
        attempt=0,
    )
    session.add(row)
    session.flush()
    session.commit()
    session.refresh(row)
    return row, True


def _pilot_gate(
    session: Session,
    version: AgentVersion,
    organization_id: int,
    scenario_sha256: str,
) -> GateResult:
    result = session.execute(
        select(GateResult, EvalRun, PolicyEvaluation)
        .join(EvalRun, EvalRun.id == GateResult.run_id)
        .outerjoin(PolicyEvaluation, PolicyEvaluation.id == GateResult.policy_evaluation_id)
        .where(
            EvalRun.organization_id == organization_id,
            EvalRun.candidate_version_id == version.id,
            EvalRun.status == RunStatus.COMPLETED,
            GateResult.decision == GateDecision.SHIP,
        )
        .order_by(GateResult.id.desc())
    ).first()
    if result is None:
        raise PermissionError("pilot requires a current SHIP Gate")
    gate, run, policy = result
    manifest_sha = dict(run.manifest.get("scenario") or {}).get("sha256")
    if manifest_sha != scenario_sha256:
        raise PermissionError("pilot Gate does not match the current scenario SHA")
    if policy is None or policy.decision != GateDecision.SHIP.value or policy.error is not None:
        raise PermissionError("pilot requires an explicit OPA SHIP decision")
    return gate


def _validate_side_effects(mode: ScenarioMode, participants: dict[int, Any]) -> None:
    allowed = {"none"} if mode is ScenarioMode.SHADOW else {"none", "idempotent"}
    for participant in participants.values():
        if participant.target_kind is not TargetKind.TOOL:
            continue
        side_effects = str(participant.capabilities.get("side_effects", "unknown"))
        if side_effects not in allowed:
            raise ValueError(f"{mode.value} mode rejects Tool side_effects={side_effects}")


class ScenarioRuntimeExecutor:
    def __init__(
        self,
        database: Database,
        *,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 10,
        worker_id: str | None = None,
    ) -> None:
        self.database = database
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = max(0.1, heartbeat_seconds)
        self.worker_id = worker_id or f"{socket.gethostname()}-scenario-{uuid4().hex[:8]}"

    async def execute(self, run_id: int) -> None:
        claimed = self._claim(run_id)
        if claimed is None:
            return
        run, plan, participants = claimed
        cancelled = asyncio.Event()
        try:
            tracer = get_tracer()
            with tracer.start_as_current_span(
                "scenario.run",
                attributes={
                    "aqh.scenario.run.id": run.id,
                    "aqh.scenario.version.id": run.scenario_version_id,
                    "aqh.scenario.mode": run.mode.value,
                },
            ) as span:
                task = asyncio.create_task(
                    execute_scenario(
                        plan,
                        participants,
                        run.input_data,
                        {
                            "scenario_run_id": str(run.id),
                            "organization_id": run.organization_id,
                            "mode": run.mode.value,
                        },
                        cancelled,
                    )
                )
                execution = await self._run_with_heartbeat(run.id, task, cancelled)
                span_context = span.get_span_context()
                trace_id = (
                    format(span_context.trace_id, "032x") if span_context.is_valid else None
                )
            self._persist_success(run.id, execution, trace_id)
        except ScenarioCancelled:
            self._mark_cancelled(run.id)
        except Exception as exc:
            self._mark_failed(run.id, exc)

    def is_recoverable(self, run_id: int) -> bool:
        now = datetime.now(UTC)
        with self.database.session() as session:
            row = session.get(ScenarioRun, run_id)
            if row is None or row.status in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
            }:
                return False
            return row.status is RunStatus.QUEUED or (
                row.lease_expires_at is None or row.lease_expires_at <= now
            )

    def _claim(self, run_id: int):
        now = datetime.now(UTC)
        with self.database.session() as session:
            row = session.scalar(
                select(ScenarioRun)
                .where(ScenarioRun.id == run_id)
                .with_for_update(skip_locked=True)
            )
            if row is None or row.status in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
            }:
                return None
            if row.status is RunStatus.CANCEL_REQUESTED:
                row.status = RunStatus.CANCELLED
                row.finished_at = now
                session.commit()
                return None
            if (
                row.status is RunStatus.RUNNING
                and row.lease_expires_at
                and row.lease_expires_at > now
            ):
                return None
            version = session.get(AgentVersion, row.scenario_version_id)
            if version is None:
                raise LookupError("scenario version not found")
            plan, participants = resolve_scenario_version(session, version, row.organization_id)
            row.status = RunStatus.RUNNING
            row.started_at = row.started_at or now
            row.worker_id = self.worker_id
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            row.attempt += 1
            session.commit()
            return row, plan, participants

    async def _run_with_heartbeat(self, run_id: int, task, cancelled: asyncio.Event):
        while True:
            done, _ = await asyncio.wait(
                {task}, timeout=self.heartbeat_seconds, return_when=asyncio.FIRST_COMPLETED
            )
            if task in done:
                return await task
            if not self._heartbeat(run_id):
                cancelled.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise ScenarioCancelled("scenario lease lost or cancellation requested")

    def _heartbeat(self, run_id: int) -> bool:
        now = datetime.now(UTC)
        with self.database.session() as session:
            row = session.get(ScenarioRun, run_id)
            if (
                row is None
                or row.worker_id != self.worker_id
                or row.status is RunStatus.CANCEL_REQUESTED
            ):
                return False
            row.heartbeat_at = now
            row.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            session.commit()
            return True

    def _persist_success(
        self, run_id: int, execution: ScenarioExecution, trace_id: str | None
    ) -> None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            row = session.get(ScenarioRun, run_id)
            if row is None:
                return
            usage = _usage_document(execution)
            budget_error = _budget_error(row, usage)
            session.add_all(
                ScenarioNodeRun(
                    scenario_run_id=row.id,
                    node_id=outcome.node_id,
                    target_version_id=outcome.target_version_id,
                    attempt=row.attempt,
                    status=outcome.status,
                    invocation_id=outcome.invocation_id,
                    output=outcome.output,
                    usage=_token_usage(outcome.usage),
                    latency_ms=outcome.latency_ms,
                    failure_reason=outcome.failure_reason,
                    started_at=row.started_at,
                    finished_at=now,
                )
                for outcome in execution.outcomes
            )
            row.output = execution.output
            row.usage = usage
            row.trace_id = trace_id
            row.status = RunStatus.FAILED if budget_error else RunStatus.COMPLETED
            row.failure_reason = budget_error
            row.finished_at = now
            row.lease_expires_at = None
            session.commit()

    def _mark_cancelled(self, run_id: int) -> None:
        with self.database.session() as session:
            row = session.get(ScenarioRun, run_id)
            if row is not None:
                row.status = RunStatus.CANCELLED
                row.finished_at = datetime.now(UTC)
                row.lease_expires_at = None
                session.commit()

    def _mark_failed(self, run_id: int, exc: Exception) -> None:
        with self.database.session() as session:
            row = session.get(ScenarioRun, run_id)
            if row is not None:
                row.status = RunStatus.FAILED
                row.failure_reason = type(exc).__name__
                row.finished_at = datetime.now(UTC)
                row.lease_expires_at = None
                session.commit()


def _usage_document(execution: ScenarioExecution) -> dict[str, Any]:
    return {
        **_token_usage(execution.usage),
        "model_cost": None if execution.model_cost is None else str(execution.model_cost),
        "external_tool_cost": (
            None
            if execution.external_tool_cost is None
            else str(execution.external_tool_cost)
        ),
    }


def _token_usage(usage) -> dict[str, Any]:
    return {
        name: getattr(usage, name)
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
            "embedding_tokens",
            "vision_tokens",
            "judge_tokens",
        )
    }


def _budget_error(row: ScenarioRun, usage: dict[str, Any]) -> str | None:
    max_tokens = row.limits.get("max_total_tokens")
    if max_tokens is not None:
        values = [usage.get("input_tokens"), usage.get("output_tokens")]
        if any(value is None for value in values):
            return "scenario token usage is UNKNOWN"
        if sum(int(value) for value in values) > int(max_tokens):
            return "scenario token budget exceeded"
    max_cost = row.limits.get("max_cost_usd")
    if max_cost is not None:
        values = [usage.get("model_cost"), usage.get("external_tool_cost")]
        if any(value is None for value in values):
            return "scenario cost is UNKNOWN"
        if sum(Decimal(value) for value in values) > Decimal(str(max_cost)):
            return "scenario cost budget exceeded"
    return None


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
