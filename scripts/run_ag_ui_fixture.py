from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import func, select

from agent_quality_harness.api.schemas import (
    DatasetImport,
    EvalRunCreate,
    TargetCreate,
    VersionCreate,
)
from agent_quality_harness.core.config import get_settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.enums import RunStatus, TargetProtocol
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    Organization,
    UsageMeasurement,
)
from agent_quality_harness.queue import RedisRunQueue
from agent_quality_harness.services import (
    create_eval_run,
    create_target,
    create_version,
    import_dataset,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "datasets" / "demo-fixture-ag-ui-v1.json"
TARGET_NAME = "Demo Fixture AG-UI Target"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic AG-UI Compose fixture")
    parser.add_argument("--endpoint", default="http://fake-ag-ui:8050/ag-ui")
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    result = asyncio.run(run(endpoint=args.endpoint, timeout_seconds=args.timeout))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


async def run(*, endpoint: str, timeout_seconds: float) -> dict[str, Any]:
    settings = get_settings()
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    try:
        with database.session() as session:
            organization = session.scalar(
                select(Organization).where(Organization.slug == "default")
            )
            if organization is None:
                raise LookupError(
                    "default organization not found; bootstrap an administrator first"
                )
            target = session.scalar(
                select(EvaluationTarget).where(
                    EvaluationTarget.organization_id == organization.id,
                    EvaluationTarget.name == TARGET_NAME,
                )
            )
            if target is None:
                target = create_target(
                    session,
                    TargetCreate(
                        name=TARGET_NAME,
                        protocol=TargetProtocol.AG_UI,
                        endpoint=endpoint,
                        timeout_seconds=30,
                        capabilities={
                            "contract_profile": "ag_ui_v1",
                            "profile_version": "0.1.19",
                            "demo_fixture": True,
                            "include_state_output": True,
                            "cancel_endpoint": (
                                "http://fake-ag-ui:8050/ag-ui/cancel/{run_id}"
                            ),
                        },
                    ),
                    organization.id,
                )
            elif target.endpoint != endpoint:
                raise ValueError(f"existing AG-UI fixture endpoint differs: {target.endpoint}")
            version = session.scalar(
                select(AgentVersion).where(
                    AgentVersion.target_id == target.id,
                    AgentVersion.version == "fixture-0.1.19",
                )
            )
            if version is None:
                version = create_version(
                    session,
                    target.id,
                    VersionCreate(
                        version="fixture-0.1.19",
                        metadata={"demo_fixture": True, "protocol_version": "0.1.19"},
                    ),
                    organization.id,
                )
            dataset = session.scalar(
                select(EvalDataset).where(
                    EvalDataset.organization_id == organization.id,
                    EvalDataset.name == "agent-quality-harness-demo-ag-ui",
                    EvalDataset.version == "v1",
                )
            )
            if dataset is None:
                payload = DatasetImport.model_validate_json(
                    DATASET_PATH.read_text(encoding="utf-8")
                )
                dataset, _ = import_dataset(session, payload, organization.id)
            eval_run = create_eval_run(
                session,
                EvalRunCreate(
                    dataset_id=dataset.id,
                    candidate_version_id=version.id,
                    config={"demo_fixture": True, "protocol": "ag-ui"},
                ),
                organization.id,
            )
            run_id = eval_run.id
        await queue.enqueue(run_id)
        deadline = monotonic() + timeout_seconds
        status = RunStatus.QUEUED
        while monotonic() < deadline:
            await asyncio.sleep(0.5)
            with database.session() as session:
                row = session.get(EvalRun, run_id)
                if row is None:
                    raise LookupError("AG-UI EvalRun disappeared")
                status = row.status
                if status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
                    break
        with database.session() as session:
            run_row = session.get(EvalRun, run_id)
            result_ids = list(
                session.scalars(select(CaseResult.id).where(CaseResult.run_id == run_id))
            )
            passed = int(
                session.scalar(
                    select(func.count(CaseResult.id)).where(
                        CaseResult.run_id == run_id,
                        CaseResult.scores["passed"].as_boolean().is_(True),
                    )
                )
                or 0
            )
            unknown_usage = int(
                session.scalar(
                    select(func.count(UsageMeasurement.id)).where(
                        UsageMeasurement.case_result_id.in_(result_ids),
                        UsageMeasurement.input_tokens.is_(None),
                        UsageMeasurement.output_tokens.is_(None),
                    )
                )
                or 0
            )
            trace_ids = list(
                session.scalars(
                    select(CaseResult.trace_id).where(CaseResult.run_id == run_id)
                )
            )
            return {
                "run_id": run_id,
                "status": status.value,
                "failure_reason": None if run_row is None else run_row.failure_reason,
                "result_count": len(result_ids),
                "passed_count": passed,
                "unknown_usage_count": unknown_usage,
                "trace_ids": trace_ids,
            }
    finally:
        await queue.close()
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
