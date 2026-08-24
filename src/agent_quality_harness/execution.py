from __future__ import annotations

import asyncio
import re
import socket
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select

from agent_quality_harness.adapter_factory import TargetSpec, create_agent_adapter
from agent_quality_harness.adapters import AgentAdapter
from agent_quality_harness.core.database import Database
from agent_quality_harness.core.telemetry import get_tracer
from agent_quality_harness.domain.enums import RunStatus, VersionRole
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalCase,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    GateResult,
    PricingSnapshot,
    RunEvent,
    UsageMeasurement,
)
from agent_quality_harness.evaluation import HarnessCase, HarnessResult, InspectHarness
from agent_quality_harness.gates import aggregate_metrics, evaluate_gate
from agent_quality_harness.pricing import calculate_model_cost
from agent_quality_harness.services import verify_dataset_integrity


@dataclass(frozen=True, slots=True)
class VersionExecution:
    role: VersionRole
    version_id: int
    version: str
    target_name: str
    target: TargetSpec


@dataclass(frozen=True, slots=True)
class RunExecution:
    run_id: int
    dataset_id: int
    cases: tuple[HarnessCase, ...]
    case_ids: dict[str, int]
    versions: tuple[VersionExecution, ...]
    pricing_snapshot_id: int | None
    prices: dict[str, Any] | None
    gate_policy_id: int | None
    gate_thresholds: dict[str, Any] | None


class InspectRunExecutor:
    def __init__(
        self,
        database: Database,
        harness: InspectHarness,
        adapter_factory: Callable[[TargetSpec], AgentAdapter] = create_agent_adapter,
        *,
        lease_seconds: int = 60,
        heartbeat_seconds: float = 10,
        worker_id: str | None = None,
    ) -> None:
        self.database = database
        self.harness = harness
        self.adapter_factory = adapter_factory
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = max(0.01, heartbeat_seconds)
        self.worker_id = worker_id or f"{socket.gethostname()}-{uuid4().hex[:8]}"

    async def execute(self, run_id: int) -> None:
        try:
            execution = self._claim(run_id)
            if execution is None:
                return
            captures: list[tuple[VersionRole, HarnessResult]] = []
            tracer = get_tracer()
            cancelled = False
            with tracer.start_as_current_span(
                "eval.run",
                attributes={"aqh.run.id": run_id, "aqh.dataset.id": execution.dataset_id},
            ):
                for version in execution.versions:
                    adapter = self.adapter_factory(version.target)
                    for start in range(0, len(execution.cases), self.harness.max_samples):
                        if self._cancel_requested(run_id):
                            cancelled = True
                            break
                        batch = execution.cases[start : start + self.harness.max_samples]
                        version_captures: list[HarnessResult] = []
                        task = self.harness.build_task(
                            batch,
                            adapter,
                            target_name=version.target_name,
                            target_version=version.version,
                            target_id=version.target.id,
                            version_id=version.version_id,
                            protocol=version.target.protocol.value,
                            capture=version_captures,
                        )
                        logs = await self._run_with_heartbeat(run_id, self.harness.run_async(task))
                        if len(logs) != 1 or logs[0].status != "success":
                            raise RuntimeError(f"Inspect AI failed for {version.role.value}")
                        expected_ids = {case.id for case in batch}
                        captured_ids = {item.case_id for item in version_captures}
                        if len(version_captures) != len(batch) or captured_ids != expected_ids:
                            raise RuntimeError(
                                f"Inspect capture count mismatch for {version.role.value}: "
                                f"expected {len(batch)}, got {len(version_captures)}"
                            )
                        captures.extend((version.role, item) for item in version_captures)
                        if not self._heartbeat(run_id):
                            raise RuntimeError("worker lease ownership lost")
                    if cancelled:
                        break
            self._persist(execution, captures, cancelled=cancelled)
        except Exception as exc:
            self._mark_failed(run_id, exc)

    def is_recoverable(self, run_id: int) -> bool:
        now = datetime.now(UTC)
        with self.database.session() as session:
            run = session.get(EvalRun, run_id)
            if run is None or run.status in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
            }:
                return False
            return run.status is RunStatus.QUEUED or (
                run.lease_expires_at is None or run.lease_expires_at <= now
            )

    def _claim(self, run_id: int) -> RunExecution | None:
        now = datetime.now(UTC)
        with self.database.session() as session:
            run = session.scalar(
                select(EvalRun).where(EvalRun.id == run_id).with_for_update(skip_locked=True)
            )
            if run is None or run.status in {
                RunStatus.COMPLETED,
                RunStatus.CANCELLED,
                RunStatus.FAILED,
            }:
                return None
            if run.status is RunStatus.CANCEL_REQUESTED:
                run.status = RunStatus.CANCELLED
                run.finished_at = max(now, run.started_at or run.created_at)
                self._add_event(session, run.id, "run.cancelled", "worker", {})
                session.commit()
                return None
            if (
                run.status is RunStatus.RUNNING
                and run.lease_expires_at
                and run.lease_expires_at > now
            ):
                return None
            dataset = session.get(EvalDataset, run.dataset_id)
            if dataset is None:
                raise LookupError(f"dataset not found: {run.dataset_id}")
            all_rows = list(
                session.scalars(
                    select(EvalCase)
                    .where(EvalCase.dataset_id == run.dataset_id)
                    .order_by(EvalCase.ordinal)
                )
            )
            verify_dataset_integrity(dataset, all_rows)
            selected_ids = run.config.get("selected_case_ids")
            rows = (
                [row for row in all_rows if row.external_id in set(selected_ids)]
                if selected_ids is not None
                else all_rows
            )
            if len(rows) != run.expected_case_count:
                raise ValueError(
                    f"dataset case count changed: expected {run.expected_case_count}, "
                    f"got {len(rows)}"
                )
            versions = self._load_versions(session, run)
            if not versions or versions[-1].role is not VersionRole.CANDIDATE:
                raise ValueError("candidate version snapshot is incomplete")
            pricing = (
                None
                if run.pricing_snapshot_id is None
                else session.get(PricingSnapshot, run.pricing_snapshot_id)
            )
            policy = (
                None if run.gate_policy_id is None else session.get(GatePolicy, run.gate_policy_id)
            )
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or max(now, run.created_at)
            run.worker_id = self.worker_id
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            run.attempt += 1
            self._add_event(
                session,
                run.id,
                "run.started",
                "worker",
                {"worker_id": self.worker_id, "attempt": run.attempt},
            )
            session.commit()
            cases = tuple(
                HarnessCase(
                    id=row.external_id,
                    input_data=dict(row.input_data),
                    expected=dict(row.expected),
                    tags=tuple(row.tags),
                )
                for row in rows
            )
            return RunExecution(
                run_id=run.id,
                dataset_id=run.dataset_id,
                cases=cases,
                case_ids={row.external_id: row.id for row in rows},
                versions=tuple(versions),
                pricing_snapshot_id=None if pricing is None else pricing.id,
                prices=None if pricing is None else dict(pricing.prices),
                gate_policy_id=None if policy is None else policy.id,
                gate_thresholds=None if policy is None else dict(policy.thresholds),
            )

    def _load_versions(self, session, run: EvalRun) -> list[VersionExecution]:
        versions: list[VersionExecution] = []
        for role, version_id in (
            (VersionRole.BASELINE, run.baseline_version_id),
            (VersionRole.CANDIDATE, run.candidate_version_id),
        ):
            if version_id is None:
                continue
            version = session.get(AgentVersion, version_id)
            if version is None:
                raise LookupError(f"version not found: {version_id}")
            target = session.get(EvaluationTarget, version.target_id)
            if target is None:
                raise LookupError(f"target not found: {version.target_id}")
            versions.append(
                VersionExecution(
                    role=role,
                    version_id=version.id,
                    version=version.version,
                    target_name=target.name,
                    target=TargetSpec(
                        id=target.id,
                        protocol=target.protocol,
                        endpoint=target.endpoint,
                        auth_ref=target.auth_ref,
                        timeout_seconds=target.timeout_seconds,
                        capabilities=dict(target.capabilities),
                    ),
                )
            )
        return versions

    def _persist(
        self,
        execution: RunExecution,
        captures: list[tuple[VersionRole, HarnessResult]],
        *,
        cancelled: bool,
    ) -> None:
        expected_total = len(execution.cases) * len(execution.versions)
        if not cancelled and len(captures) != expected_total:
            raise RuntimeError(
                f"result count mismatch: expected {expected_total}, got {len(captures)}"
            )
        with self.database.session() as session:
            run = session.get(EvalRun, execution.run_id)
            if run is None:
                raise LookupError(f"run not found: {execution.run_id}")
            candidate_cases: set[str] = set()
            metric_rows: dict[VersionRole, list[dict[str, Any]]] = {
                VersionRole.BASELINE: [],
                VersionRole.CANDIDATE: [],
            }
            for role, captured in captures:
                result = captured.result
                score_data = captured.scores.as_dict()
                case_result = CaseResult(
                    run_id=run.id,
                    case_id=execution.case_ids[captured.case_id],
                    version_role=role,
                    output=dict(result.output),
                    final_action=result.final_action,
                    trace_id=captured.trace_id,
                    scores=score_data,
                    failure_type=None if score_data["passed"] else "assertion_failure",
                    latency_ms=captured.latency_ms,
                )
                session.add(case_result)
                session.flush()
                cost = calculate_model_cost(result.usage, execution.prices)
                model_cost = cost.model_cost
                cost_status = cost.status
                if execution.prices is None and result.model_cost is not None:
                    model_cost = result.model_cost
                    cost_status = result.usage.status
                usage = result.usage
                session.add(
                    UsageMeasurement(
                        case_result_id=case_result.id,
                        pricing_snapshot_id=execution.pricing_snapshot_id,
                        measurement_status=usage.status,
                        cost_status=cost_status,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        cache_read_tokens=usage.cache_read_tokens,
                        cache_write_tokens=usage.cache_write_tokens,
                        reasoning_tokens=usage.reasoning_tokens,
                        embedding_tokens=usage.embedding_tokens,
                        vision_tokens=usage.vision_tokens,
                        judge_tokens=usage.judge_tokens,
                        model_cost=model_cost,
                        external_tool_cost=result.external_tool_cost,
                        cost_components=cost.components,
                        raw_usage=dict(usage.raw),
                    )
                )
                for event in result.events:
                    self._add_event(
                        session,
                        run.id,
                        event.event_type,
                        "agent",
                        dict(event.data),
                        case_result_id=case_result.id,
                        occurred_at=event.occurred_at,
                    )
                self._add_event(
                    session,
                    run.id,
                    "scorer.completed",
                    "scorer",
                    score_data,
                    case_result_id=case_result.id,
                )
                metric_rows[role].append(
                    {
                        "scores": score_data,
                        "latency_ms": captured.latency_ms,
                        "model_cost": model_cost,
                        "external_tool_cost": result.external_tool_cost,
                    }
                )
                if role is VersionRole.CANDIDATE:
                    candidate_cases.add(captured.case_id)
            run.completed_case_count = len(candidate_cases)
            run.status = RunStatus.CANCELLED if cancelled else RunStatus.COMPLETED
            run.finished_at = max(datetime.now(UTC), run.started_at or run.created_at)
            run.lease_expires_at = None
            self._add_event(
                session,
                run.id,
                "run.cancelled" if cancelled else "run.completed",
                "worker",
                {"completed_case_count": run.completed_case_count},
            )
            if not cancelled and execution.gate_policy_id is not None and run.baseline_version_id:
                baseline = aggregate_metrics(metric_rows[VersionRole.BASELINE])
                candidate = aggregate_metrics(metric_rows[VersionRole.CANDIDATE])
                gate = evaluate_gate(baseline, candidate, execution.gate_thresholds)
                session.add(
                    GateResult(
                        run_id=run.id,
                        policy_id=execution.gate_policy_id,
                        decision=gate.decision,
                        reasons=list(gate.reasons),
                        metric_deltas={
                            "baseline": baseline,
                            "candidate": candidate,
                            "deltas": gate.metric_deltas,
                        },
                    )
                )
                self._add_event(
                    session,
                    run.id,
                    "gate.evaluated",
                    "gate",
                    {
                        "decision": gate.decision.value,
                        "reasons": list(gate.reasons),
                    },
                )
            session.commit()

    def _cancel_requested(self, run_id: int) -> bool:
        with self.database.session() as session:
            status = session.scalar(select(EvalRun.status).where(EvalRun.id == run_id))
            return status is RunStatus.CANCEL_REQUESTED

    async def _run_with_heartbeat(self, run_id: int, work: Awaitable[Any]) -> Any:
        task = asyncio.ensure_future(work)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=self.heartbeat_seconds)
                if task in done:
                    return task.result()
                owned = await asyncio.to_thread(self._heartbeat, run_id)
                if not owned:
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    raise RuntimeError("worker lease ownership lost")
        except BaseException:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    def _heartbeat(self, run_id: int) -> bool:
        now = datetime.now(UTC)
        with self.database.session() as session:
            run = session.get(EvalRun, run_id)
            if (
                run is None
                or run.worker_id != self.worker_id
                or run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED, RunStatus.FAILED}
            ):
                return False
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            session.commit()
            return True

    def _mark_failed(self, run_id: int, exc: Exception) -> None:
        with self.database.session() as session:
            run = session.get(EvalRun, run_id)
            if run is None or run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}:
                return
            run.status = RunStatus.FAILED
            run.failure_reason = f"{type(exc).__name__}: {exc}"[:1000]
            run.finished_at = max(datetime.now(UTC), run.started_at or run.created_at)
            run.lease_expires_at = None
            self._add_event(
                session,
                run.id,
                "run.failed",
                "worker",
                {"reason": run.failure_reason},
            )
            session.commit()

    @staticmethod
    def _add_event(
        session,
        run_id: int,
        event_type: str,
        source: str,
        payload: Mapping[str, Any],
        *,
        case_result_id: int | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        session.add(
            RunEvent(
                run_id=run_id,
                case_result_id=case_result_id,
                event_type=event_type,
                source=source,
                payload=_redact(payload),
                redacted=True,
                occurred_at=occurred_at or datetime.now(UTC),
            )
        )


_SENSITIVE_KEY = re.compile(
    r"authorization|api[_-]?key|token|secret|password|cookie|reasoning|prompt|content",
    re.IGNORECASE,
)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str) and len(value) > 500:
        return f"{value[:500]}...[TRUNCATED]"
    return value
