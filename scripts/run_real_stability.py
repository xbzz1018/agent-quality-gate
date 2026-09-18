from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import func, select

from agent_quality_harness.api.schemas import EvalRunCreate, VersionCreate
from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.enums import RunStatus
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalRun,
    GatePolicy,
    GateResult,
    UsageMeasurement,
)
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.gates import DEFAULT_THRESHOLDS
from agent_quality_harness.services import create_eval_run, create_version


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run a current-snapshot stability Gate from a completed characterization"
    )
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--max-samples", type=int, default=1)
    args = parser.parse_args()
    result = asyncio.run(run(args.source_run_id, args.max_samples))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verified"] else 1


async def run(source_run_id: int, max_samples: int) -> dict:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        with database.session() as session:
            source = session.get(EvalRun, source_run_id)
            if source is None or source.status is not RunStatus.COMPLETED:
                raise ValueError("source characterization must be completed")
            source_result_count = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(CaseResult.run_id == source.id)
                )
                or 0
            )
            source_error_count = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(
                        CaseResult.run_id == source.id,
                        CaseResult.failure_type.in_(("target_error", "target_timeout")),
                    )
                )
                or 0
            )
            if source_result_count != source.expected_case_count or source_error_count:
                raise ValueError(
                    "source characterization contains incomplete or failed target results"
                )
            candidate = session.get(AgentVersion, source.candidate_version_id)
            if candidate is None:
                raise LookupError("source candidate version not found")
            baseline_name = f"recorded-baseline-run-{source.id}"
            baseline = session.scalar(
                select(AgentVersion).where(
                    AgentVersion.target_id == candidate.target_id,
                    AgentVersion.version == baseline_name,
                )
            )
            if baseline is None:
                baseline = create_version(
                    session,
                    candidate.target_id,
                    VersionCreate(
                        version=baseline_name,
                        model=candidate.model,
                        prompt_version=candidate.prompt_version,
                        metadata={
                            "recorded_baseline": {
                                "run_id": source.id,
                                "version_role": "candidate",
                                "source_version_id": candidate.id,
                            },
                            "stability_baseline": True,
                        },
                    ),
                    source.organization_id,
                )
            policy_name = f"Stability Gate Run {source.id}"
            policy = session.scalar(
                select(GatePolicy).where(
                    GatePolicy.organization_id == source.organization_id,
                    GatePolicy.name == policy_name,
                    GatePolicy.version == "1",
                )
            )
            if policy is None:
                policy = GatePolicy(
                    organization_id=source.organization_id,
                    name=policy_name,
                    version="1",
                    thresholds=DEFAULT_THRESHOLDS,
                    controls={},
                    active=False,
                )
                session.add(policy)
                session.commit()
                session.refresh(policy)
            stability = create_eval_run(
                session,
                EvalRunCreate(
                    dataset_id=source.dataset_id,
                    baseline_version_id=baseline.id,
                    candidate_version_id=candidate.id,
                    gate_policy_id=policy.id,
                    config={
                        "mode": "current_snapshot_stability",
                        "recorded_baseline_run_id": source.id,
                    },
                ),
                source.organization_id,
            )
            run_id = stability.id
        executor = InspectRunExecutor(
            database,
            InspectHarness(
                max_samples=max_samples,
                log_dir=settings.inspect_log_dir / f"stability-{run_id}",
            ),
            lease_seconds=settings.worker_lease_seconds,
            heartbeat_seconds=settings.worker_heartbeat_seconds,
        )
        await executor.execute(run_id)
        with database.session() as session:
            run_row = session.get(EvalRun, run_id)
            gate = session.scalar(select(GateResult).where(GateResult.run_id == run_id))
            result_count = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(CaseResult.run_id == run_id)
                )
                or 0
            )
            unknown_costs = int(
                session.scalar(
                    select(func.count(UsageMeasurement.id))
                    .join(CaseResult, CaseResult.id == UsageMeasurement.case_result_id)
                    .where(
                        CaseResult.run_id == run_id,
                        UsageMeasurement.model_cost.is_(None),
                    )
                )
                or 0
            )
            target_error_count = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(
                        CaseResult.run_id == run_id,
                        CaseResult.failure_type.in_(("target_error", "target_timeout")),
                    )
                )
                or 0
            )
            assertion_failure_count = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(
                        CaseResult.run_id == run_id,
                        CaseResult.failure_type == "assertion_failure",
                    )
                )
                or 0
            )
            expected_result_count = 0 if run_row is None else run_row.expected_case_count * 2
            return {
                "run_id": run_id,
                "source_run_id": source_run_id,
                "status": run_row.status.value if run_row else "missing",
                "case_count": 0 if run_row is None else run_row.completed_case_count,
                "result_count": result_count,
                "assertion_failure_count": assertion_failure_count,
                "target_error_count": target_error_count,
                "verified": (
                    run_row is not None
                    and run_row.status is RunStatus.COMPLETED
                    and result_count == expected_result_count
                    and target_error_count == 0
                ),
                "gate": None if gate is None else gate.decision.value,
                "cost_status": "unknown" if unknown_costs else "known",
                "unknown_cost_results": unknown_costs,
                "failure_reason": None if run_row is None else run_row.failure_reason,
            }
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
