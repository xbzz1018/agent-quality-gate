from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import monotonic
from typing import Any

from sqlalchemy import select

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
    AgentVersionSkill,
    CaseResult,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    GateResult,
    Organization,
    SkillPackage,
    SkillScan,
    SkillVersion,
)
from agent_quality_harness.gates import DEFAULT_THRESHOLDS
from agent_quality_harness.queue import RedisRunQueue
from agent_quality_harness.services import (
    create_eval_run,
    create_target,
    create_version,
    import_dataset,
)
from agent_quality_harness.skills import (
    create_skill_scan,
    import_skill,
    replace_skill_bindings,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "datasets" / "demo-fixture-multi-skill-v1.json"
TARGET_NAME = "Demo Fixture Multi-Skill AG-UI Target"
POLICY_NAME = "Demo Fixture Multi-Skill Reliability Gate"


async def run(timeout_seconds: float = 120) -> dict[str, Any]:
    settings = get_settings()
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    try:
        with database.session() as session:
            organization = session.scalar(
                select(Organization).where(Organization.slug == "default")
            )
            if organization is None:
                raise LookupError("default organization not found")
            skills = [
                _ensure_skill(session, organization.id, "quality-lookup", "lookup-quality"),
                _ensure_skill(session, organization.id, "quality-summary", "summarize-quality"),
            ]
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
                        endpoint="http://fake-ag-ui:8050/ag-ui",
                        timeout_seconds=30,
                        capabilities={
                            "contract_profile": "ag_ui_v1",
                            "profile_version": "0.1.19",
                            "demo_fixture": True,
                            "include_state_output": True,
                        },
                    ),
                    organization.id,
                )
            versions = [
                _ensure_version(session, target.id, organization.id, "baseline-multi-v1"),
                _ensure_version(session, target.id, organization.id, "candidate-multi-v1"),
            ]
            for version in versions:
                existing = list(
                    session.scalars(
                        select(AgentVersionSkill).where(
                            AgentVersionSkill.agent_version_id == version.id
                        )
                    )
                )
                if not existing:
                    replace_skill_bindings(
                        session,
                        organization_id=organization.id,
                        agent_version_id=version.id,
                        skill_version_ids=[skill.id for skill, _ in skills],
                    )
                    session.commit()
            dataset = session.scalar(
                select(EvalDataset).where(
                    EvalDataset.organization_id == organization.id,
                    EvalDataset.name == "agent-quality-harness-demo-multi-skill",
                    EvalDataset.version == "v1",
                )
            )
            if dataset is None:
                raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
                identities = {
                    package.name: {
                        "name": package.name,
                        "version": skill.version,
                        "sha256": skill.sha256,
                    }
                    for skill, package in skills
                }
                for case in raw["cases"]:
                    name = case["expected"]["skills"]["required"][0]
                    case["input"]["forwarded_props"]["skill_events"] = _lifecycle(
                        identities[name], case["id"]
                    )
                dataset, _ = import_dataset(
                    session, DatasetImport.model_validate(raw), organization.id
                )
            policy = session.scalar(
                select(GatePolicy).where(
                    GatePolicy.organization_id == organization.id,
                    GatePolicy.name == POLICY_NAME,
                    GatePolicy.version == "v1",
                )
            )
            if policy is None:
                policy = GatePolicy(
                    organization_id=organization.id,
                    name=POLICY_NAME,
                    version="v1",
                    thresholds=DEFAULT_THRESHOLDS
                    | {"latency_growth_warn": 10.0, "cost_growth_warn": 10.0},
                    controls={
                        "skill": {
                            "enabled": True,
                            "require_telemetry": True,
                            "minimum_selection_accuracy": 1.0,
                            "block_unbound": True,
                            "block_lifecycle_errors": True,
                            "minimum_coverage_ratio": 1.0,
                            "redundant_call_growth_warn": 10.0,
                        },
                        "evidence": {
                            "enabled": True,
                            "minimum_coverage": 1.0,
                            "block_invalid_refs": True,
                            "block_unsupported_claims": True,
                        },
                    },
                    active=False,
                )
                session.add(policy)
                session.commit()
                session.refresh(policy)
            eval_run = create_eval_run(
                session,
                EvalRunCreate(
                    dataset_id=dataset.id,
                    baseline_version_id=versions[0].id,
                    candidate_version_id=versions[1].id,
                    gate_policy_id=policy.id,
                    config={"demo_fixture": True, "multi_skill": True},
                ),
                organization.id,
            )
            run_id = eval_run.id
        await queue.enqueue(run_id)
        deadline = monotonic() + timeout_seconds
        while monotonic() < deadline:
            await asyncio.sleep(0.5)
            with database.session() as session:
                row = session.get(EvalRun, run_id)
                if row is not None and row.status in {
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                }:
                    break
        with database.session() as session:
            row = session.get(EvalRun, run_id)
            gate = session.scalar(select(GateResult).where(GateResult.run_id == run_id))
            results = list(
                session.scalars(select(CaseResult).where(CaseResult.run_id == run_id))
            )
            return {
                "run_id": run_id,
                "status": None if row is None else row.status.value,
                "failure_reason": None if row is None else row.failure_reason,
                "result_count": len(results),
                "passed_count": sum(bool(item.scores.get("passed")) for item in results),
                "gate": None if gate is None else gate.decision.value,
                "gate_reasons": [] if gate is None else gate.reasons,
                "trace_ids": sorted({item.trace_id for item in results if item.trace_id}),
            }
    finally:
        await queue.close()
        database.close()


def _ensure_skill(
    session, organization_id: int, name: str, intent: str
) -> tuple[SkillVersion, SkillPackage]:
    package, version = import_skill(
        session,
        organization_id=organization_id,
        name=name,
        version="1.0.0",
        description=f"Deterministic {name} fixture",
        source_ref="demo-fixture",
        manifest={
            "schema": "aqh.skill-manifest/v1",
            "routing": {
                "intents": [intent],
                "positive_tests": [f"{name}-positive"],
                "negative_tests": [f"{name}-negative"],
            },
            "dependencies": [],
            "conflicts": [],
            "permissions": {},
        },
        files=[{"path": "SKILL.md", "content": f"Execute {name} deterministically."}],
    )
    latest_scan = session.scalar(
        select(SkillScan)
        .where(SkillScan.skill_version_id == version.id)
        .order_by(SkillScan.id.desc())
        .limit(1)
    )
    if latest_scan is None:
        create_skill_scan(session, version)
    session.commit()
    return version, package


def _ensure_version(
    session, target_id: int, organization_id: int, version_name: str
) -> AgentVersion:
    version = session.scalar(
        select(AgentVersion).where(
            AgentVersion.target_id == target_id,
            AgentVersion.version == version_name,
        )
    )
    if version is None:
        version = create_version(
            session,
            target_id,
            VersionCreate(version=version_name, metadata={"demo_fixture": True}),
            organization_id,
        )
    return version


def _lifecycle(identity: dict[str, str], invocation_id: str) -> list[dict[str, Any]]:
    return [
        {
            "schema": "aqh.skill-event/v1",
            "type": event_type,
            "invocation_id": invocation_id,
            "skill": identity,
            "reason_code": "fixture_route",
            "status": "success" if event_type == "skill.completed" else None,
        }
        for event_type in ("skill.selected", "skill.started", "skill.completed")
    ]


def main() -> int:
    result = asyncio.run(run())
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "completed" and result["gate"] == "ship" else 1


if __name__ == "__main__":
    raise SystemExit(main())
