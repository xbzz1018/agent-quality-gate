import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from agent_quality_harness.adapters.base import AgentRunEvent, AgentRunResult, TokenUsage
from agent_quality_harness.administration import bootstrap_platform_admin
from agent_quality_harness.core.config import Settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.enums import RunStatus
from agent_quality_harness.domain.models import (
    AgentVersion,
    CaseResult,
    EvalDataset,
    EvalRun,
    EvaluationTarget,
    GatePolicy,
    GateResult,
    PricingSnapshot,
    RunEvent,
    UsageMeasurement,
    User,
)
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.main import create_app
from agent_quality_harness.queue import RedisRunQueue, RedisRunWorker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AQH_RUN_INTEGRATION") != "1",
        reason="set AQH_RUN_INTEGRATION=1 with project services running",
    ),
]


class EchoAdapter:
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        text = input_data["prompt"]
        if context["target_version"] == "candidate" and context["case_id"] == "case-2":
            text = "candidate regression"
        return AgentRunResult(
            run_id=f"fake-{context['case_id']}",
            final_action="answer",
            output={"text": text, "version": context["target_version"]},
            usage=TokenUsage(input_tokens=3, output_tokens=2),
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        if False:
            yield AgentRunEvent("unused")

    async def cancel(self, run_id: str) -> bool:
        return True


async def test_real_postgres_redis_and_inspect_worker(tmp_path: Path) -> None:
    suffix = uuid4().hex[:10]
    settings = Settings(
        database_url="postgresql+psycopg://agent_quality:agent_quality@localhost:5432/agent_quality",
        redis_url="redis://localhost:6379/0",
        redis_queue_key=f"aqh:test:{suffix}",
        otel_enabled=False,
        jwt_secret=f"integration-secret-long-enough-{suffix}",
    )
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    app = create_app(settings, database=database, run_queue=queue)
    transport = httpx.ASGITransport(app=app)
    created: dict[str, int] = {}
    auth_headers: dict[str, str] = {}
    username = f"integration-{suffix}"
    password = "Integration!Password123"
    with database.session() as session:
        admin = bootstrap_platform_admin(
            session,
            username=username,
            password=password,
            display_name="Integration Admin",
            email=None,
        )
        created["user"] = admin.id
        created["organization"] = admin.id
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            readiness = await client.get("/api/v1/health/ready")
            assert readiness.status_code == 200

            login = await client.post(
                "/api/v1/auth/login",
                json={"username": username, "password": password},
            )
            assert login.status_code == 200, login.text
            organization_id = login.json()["organizations"][0]["id"]
            created["organization"] = organization_id
            client.headers.update(
                {
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "X-Organization-ID": str(organization_id),
                }
            )
            auth_headers = dict(client.headers)

            target = await client.post(
                "/api/v1/targets",
                json={
                    "name": f"integration-{suffix}",
                    "target_kind": "agent",
                    "protocol": "http",
                    "endpoint": "http://fake/invoke",
                },
            )
            assert target.status_code == 201, target.text
            created["target"] = target.json()["id"]

            version_ids: list[int] = []
            for version in ("baseline", "candidate"):
                response = await client.post(
                    f"/api/v1/targets/{created['target']}/versions",
                    json={"version": version},
                )
                assert response.status_code == 201, response.text
                version_ids.append(response.json()["id"])

            listed_versions = await client.get(f"/api/v1/targets/{created['target']}/versions")
            assert listed_versions.status_code == 200
            assert {item["id"] for item in listed_versions.json()} == set(version_ids)

            policy = await client.post(
                "/api/v1/gate-policies",
                json={"name": f"integration-{suffix}", "version": "v1"},
            )
            assert policy.status_code == 201, policy.text
            created["policy"] = policy.json()["id"]

            pricing = await client.post(
                "/api/v1/pricing-snapshots",
                json={
                    "provider": "fake",
                    "model": f"integration-{suffix}",
                    "version": "v1",
                    "effective_at": "2026-08-22T00:00:00Z",
                    "prices": {
                        "input_tokens": "1",
                        "output_tokens": "1",
                        "cache_read_tokens": "1",
                        "cache_write_tokens": "1",
                        "reasoning_tokens": "1",
                        "embedding_tokens": "1",
                        "vision_tokens": "1",
                        "judge_tokens": "1",
                    },
                    "source": "integration fixture",
                },
            )
            assert pricing.status_code == 201, pricing.text
            created["pricing"] = pricing.json()["id"]

            dataset = await client.post(
                "/api/v1/datasets/import",
                json={
                    "name": f"integration-{suffix}",
                    "version": "v1",
                    "cases": [
                        {
                            "id": "case-1",
                            "input": {"prompt": "alpha"},
                            "expected": {
                                "final_action": "answer",
                                "output": {
                                    "assertions": [
                                        {
                                            "id": "text",
                                            "path": "text",
                                            "operator": "equals",
                                            "value": "alpha",
                                        }
                                    ]
                                },
                            },
                        },
                        {
                            "id": "case-2",
                            "input": {"prompt": "beta"},
                            "expected": {
                                "final_action": "answer",
                                "output": {
                                    "assertions": [
                                        {
                                            "id": "text",
                                            "path": "text",
                                            "operator": "equals",
                                            "value": "beta",
                                        }
                                    ]
                                },
                            },
                        },
                    ],
                },
            )
            assert dataset.status_code == 201, dataset.text
            created["dataset"] = dataset.json()["id"]

            other_target = await client.post(
                "/api/v1/targets",
                json={
                    "name": f"other-{suffix}",
                    "target_kind": "agent",
                    "protocol": "http",
                    "endpoint": "http://fake/invoke",
                },
            )
            created["other_target"] = other_target.json()["id"]
            other_version = await client.post(
                f"/api/v1/targets/{created['other_target']}/versions",
                json={"version": "candidate"},
            )
            cross_target = await client.post(
                "/api/v1/eval-runs",
                json={
                    "dataset_id": created["dataset"],
                    "baseline_version_id": version_ids[0],
                    "candidate_version_id": other_version.json()["id"],
                },
            )
            assert cross_target.status_code == 422

            pending_target = await client.post(
                "/api/v1/targets",
                json={
                    "name": f"pending-{suffix}",
                    "target_kind": "agent",
                    "protocol": "a2a",
                    "endpoint": "http://pending/invoke",
                },
            )
            created["pending_target"] = pending_target.json()["id"]
            pending_version = await client.post(
                f"/api/v1/targets/{created['pending_target']}/versions",
                json={"version": "v1"},
            )
            pending_run = await client.post(
                "/api/v1/eval-runs",
                json={
                    "dataset_id": created["dataset"],
                    "candidate_version_id": pending_version.json()["id"],
                },
            )
            assert pending_run.status_code == 422
            assert "Adapter pending" in pending_run.text

            run = await client.post(
                "/api/v1/eval-runs",
                json={
                    "dataset_id": created["dataset"],
                    "baseline_version_id": version_ids[0],
                    "candidate_version_id": version_ids[1],
                    "gate_policy_id": created["policy"],
                    "pricing_snapshot_id": created["pricing"],
                },
            )
            assert run.status_code == 202, run.text
            created["run"] = run.json()["id"]

        executor = InspectRunExecutor(
            database,
            InspectHarness(max_samples=2, log_dir=tmp_path / "inspect"),
            adapter_factory=lambda _: EchoAdapter(),
        )
        worker = RedisRunWorker(queue, executor.execute, claim_timeout_seconds=1)
        assert await worker.process_once() is True

        with database.session() as session:
            stored_run = session.get(EvalRun, created["run"])
            assert stored_run is not None
            assert stored_run.status is RunStatus.COMPLETED
            assert stored_run.completed_case_count == 2
            assert stored_run.started_at is not None
            assert stored_run.finished_at is not None
            assert stored_run.started_at >= stored_run.created_at
            assert stored_run.finished_at >= stored_run.started_at
            results = list(
                session.scalars(select(CaseResult).where(CaseResult.run_id == stored_run.id))
            )
            assert len(results) == 4
            assert all(row.trace_id is not None for row in results)
            assert sum(row.scores["passed"] is True for row in results) == 3
            usage_rows = list(
                session.scalars(
                    select(UsageMeasurement).where(
                        UsageMeasurement.case_result_id.in_([row.id for row in results])
                    )
                )
            )
            assert len(usage_rows) == 4
            assert all(row.input_tokens == 3 for row in usage_rows)
            gate = session.scalar(select(GateResult).where(GateResult.run_id == stored_run.id))
            assert gate is not None
            assert gate.decision.value == "block"
            events = list(session.scalars(select(RunEvent).where(RunEvent.run_id == stored_run.id)))
            assert any(event.event_type == "gate.evaluated" for event in events)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=auth_headers,
        ) as client:
            comparison = await client.get(f"/api/v1/eval-runs/{created['run']}/comparison")
            assert comparison.status_code == 200
            assert comparison.json()["candidate"]["success_rate"] == 0.5
            gate_response = await client.get(f"/api/v1/eval-runs/{created['run']}/gate")
            assert gate_response.json()["decision"] == "block"
            event_response = await client.get(f"/api/v1/eval-runs/{created['run']}/events")
            assert any(item["event_type"] == "gate.evaluated" for item in event_response.json())
            replay = await client.post(f"/api/v1/eval-runs/{created['run']}/replay", json={})
            assert replay.status_code == 202, replay.text
            created["replay"] = replay.json()["id"]
            assert replay.json()["expected_case_count"] == 1

        assert await worker.process_once() is True
        with database.session() as session:
            replay_run = session.get(EvalRun, created["replay"])
            assert replay_run is not None
            assert replay_run.status is RunStatus.COMPLETED
            assert replay_run.replay_of_run_id == created["run"]
            assert replay_run.manifest["replay"]["case_ids"] == ["case-2"]
            replay_results = list(
                session.scalars(select(CaseResult).where(CaseResult.run_id == created["replay"]))
            )
            assert len(replay_results) == 2

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers=auth_headers,
        ) as client:
            queued = await client.post(
                "/api/v1/eval-runs",
                json={
                    "dataset_id": created["dataset"],
                    "candidate_version_id": version_ids[1],
                },
            )
            created["cancelled"] = queued.json()["id"]
            cancelled = await client.post(f"/api/v1/eval-runs/{created['cancelled']}/cancel")
            assert cancelled.json()["status"] == "cancelled"
        assert await worker.process_once() is True
        with database.session() as session:
            cancelled_run = session.get(EvalRun, created["cancelled"])
            assert cancelled_run is not None
            assert cancelled_run.status is RunStatus.CANCELLED
            assert not list(
                session.scalars(select(CaseResult).where(CaseResult.run_id == created["cancelled"]))
            )
    finally:
        await queue.client.delete(queue.queue_key, queue.processing_key)
        if created.get("run") is not None:
            with database.session() as session:
                run_ids = [created["run"]]
                if created.get("replay") is not None:
                    run_ids.append(created["replay"])
                if created.get("cancelled") is not None:
                    run_ids.append(created["cancelled"])
                result_ids = list(
                    session.scalars(select(CaseResult.id).where(CaseResult.run_id.in_(run_ids)))
                )
                if result_ids:
                    session.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
                    session.execute(delete(GateResult).where(GateResult.run_id.in_(run_ids)))
                    session.execute(
                        delete(UsageMeasurement).where(
                            UsageMeasurement.case_result_id.in_(result_ids)
                        )
                    )
                session.execute(delete(CaseResult).where(CaseResult.run_id.in_(run_ids)))
                session.execute(delete(EvalRun).where(EvalRun.id.in_(run_ids)))
                session.execute(delete(EvalDataset).where(EvalDataset.id == created.get("dataset")))
                session.execute(
                    delete(AgentVersion).where(
                        AgentVersion.target_id.in_(
                            [
                                created.get("target"),
                                created.get("other_target"),
                                created.get("pending_target"),
                            ]
                        )
                    )
                )
                session.execute(
                    delete(EvaluationTarget).where(
                        EvaluationTarget.id.in_(
                            [
                                created.get("target"),
                                created.get("other_target"),
                                created.get("pending_target"),
                            ]
                        )
                    )
                )
                session.execute(delete(GatePolicy).where(GatePolicy.id == created.get("policy")))
                session.execute(
                    delete(PricingSnapshot).where(PricingSnapshot.id == created.get("pricing"))
                )
                session.commit()
        if created.get("user") is not None:
            with database.session() as session:
                user = session.get(User, created["user"])
                if user is not None:
                    session.delete(user)
                    session.commit()
        await queue.close()
        database.close()
