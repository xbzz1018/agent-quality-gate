import os
from collections.abc import Mapping
from uuid import uuid4

import httpx
import pytest

from agent_quality_harness.adapters.base import AgentRunResult, TokenUsage
from agent_quality_harness.administration import bootstrap_platform_admin, provision_organization
from agent_quality_harness.core.config import Settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.enums import RunStatus
from agent_quality_harness.domain.models import Organization, ScenarioRun, User
from agent_quality_harness.main import create_app
from agent_quality_harness.queue import RedisRunQueue, RedisRunWorker
from agent_quality_harness.scenario_runtime import ScenarioRuntimeExecutor

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AQH_RUN_INTEGRATION") != "1",
        reason="set AQH_RUN_INTEGRATION=1 with project services running",
    ),
]


class ScenarioEchoAdapter:
    async def invoke(self, input_data: Mapping, context: Mapping) -> AgentRunResult:
        return AgentRunResult(
            run_id=str(context["scenario_node_id"]),
            final_action="answer",
            output={"text": input_data["text"], "node": context["scenario_node_id"]},
            usage=TokenUsage(input_tokens=2, output_tokens=1),
        )

    async def cancel(self, run_id: str) -> bool:
        return True


@pytest.mark.asyncio
async def test_scenario_api_worker_idempotency_and_pilot_gate(monkeypatch) -> None:
    suffix = uuid4().hex[:10]
    settings = Settings(
        redis_url=os.getenv("AQH_INTEGRATION_REDIS_URL", "redis://localhost:56379/0"),
        redis_queue_key=f"aqh:scenario-eval:{suffix}",
        redis_scenario_queue_key=f"aqh:scenario-runtime:{suffix}",
        otel_enabled=False,
        jwt_secret=f"integration-secret-long-enough-{suffix}",
    )
    database = Database(settings.database_url)
    eval_queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    scenario_queue = RedisRunQueue(settings.redis_url, settings.redis_scenario_queue_key)
    app = create_app(
        settings,
        database=database,
        run_queue=eval_queue,
        scenario_queue=scenario_queue,
    )
    username = f"scenario-admin-{suffix}"
    password = "Integration!Password123"
    with database.session() as session:
        admin = bootstrap_platform_admin(
            session,
            username=username,
            password=password,
            display_name="Scenario Admin",
            email=None,
        )
        organization = provision_organization(
            session, slug=f"scenario-{suffix}", name="Scenario Integration"
        )
        session.commit()
        admin_id = admin.id
        organization_id = organization.id
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200
            client.headers.update(
                {
                    "Authorization": f"Bearer {login.json()['access_token']}",
                    "X-Organization-ID": str(organization_id),
                }
            )
            participant = await client.post(
                "/api/v1/targets",
                json={
                    "name": f"participant-{suffix}",
                    "target_kind": "agent",
                    "protocol": "http",
                    "endpoint": "http://fixture/invoke",
                    "capabilities": {"side_effects": "none"},
                },
            )
            assert participant.status_code == 201, participant.text
            participant_version = await client.post(
                f"/api/v1/targets/{participant.json()['id']}/versions",
                json={"version": "1"},
            )
            scenario = await client.post(
                "/api/v1/targets",
                json={
                    "name": f"scenario-{suffix}",
                    "target_kind": "scenario",
                    "protocol": "scenario",
                    "endpoint": "internal://scenario",
                },
            )
            assert scenario.status_code == 201, scenario.text
            graph = {
                "schema": "aqh.scenario/v1",
                "nodes": [
                    {
                        "id": "answer",
                        "target_version_id": participant_version.json()["id"],
                        "kind": "agent",
                        "depends_on": [],
                        "input_map": {"text": "$case.input.question"},
                    }
                ],
                "output": "$nodes.answer.output",
            }
            scenario_version = await client.post(
                f"/api/v1/targets/{scenario.json()['id']}/versions",
                json={"version": "1", "metadata": {"scenario": graph}},
            )
            assert scenario_version.status_code == 201, scenario_version.text
            version_id = scenario_version.json()["id"]
            validated = await client.post(f"/api/v1/scenario-versions/{version_id}/validate")
            assert validated.status_code == 200, validated.text
            assert validated.json()["node_count"] == 1
            headers = {"Idempotency-Key": f"shadow-{suffix}"}
            created = await client.post(
                "/api/v1/scenario-runs",
                headers=headers,
                json={
                    "scenario_version_id": version_id,
                    "mode": "shadow",
                    "input": {"question": "verified"},
                },
            )
            assert created.status_code == 202, created.text
            run_id = created.json()["id"]
            duplicate = await client.post(
                "/api/v1/scenario-runs",
                headers=headers,
                json={
                    "scenario_version_id": version_id,
                    "mode": "shadow",
                    "input": {"question": "verified"},
                },
            )
            assert duplicate.json()["id"] == run_id
            conflict = await client.post(
                "/api/v1/scenario-runs",
                headers=headers,
                json={
                    "scenario_version_id": version_id,
                    "mode": "shadow",
                    "input": {"question": "different"},
                },
            )
            assert conflict.status_code == 422
            pilot = await client.post(
                "/api/v1/scenario-runs",
                headers={"Idempotency-Key": f"pilot-{suffix}"},
                json={
                    "scenario_version_id": version_id,
                    "mode": "pilot",
                    "input": {"question": "blocked"},
                    "limits": {"max_total_tokens": 100},
                },
            )
            assert pilot.status_code == 403
            queued = await client.post(
                "/api/v1/scenario-runs",
                headers={"Idempotency-Key": f"cancel-{suffix}"},
                json={
                    "scenario_version_id": version_id,
                    "mode": "shadow",
                    "input": {"question": "cancel"},
                },
            )
            cancelled = await client.post(
                f"/api/v1/scenario-runs/{queued.json()['id']}/cancel"
            )
            assert cancelled.json()["status"] == "cancel_requested"

        monkeypatch.setattr(
            "agent_quality_harness.adapter_factory.create_target_adapter",
            lambda _target: ScenarioEchoAdapter(),
        )
        worker = RedisRunWorker(
            scenario_queue,
            ScenarioRuntimeExecutor(database, heartbeat_seconds=0.1).execute,
            claim_timeout_seconds=1,
        )
        assert await worker.process_once() is True
        assert await worker.process_once() is True
        with database.session() as session:
            completed = session.get(ScenarioRun, run_id)
            assert completed is not None and completed.status is RunStatus.COMPLETED
            assert completed.output == {"text": "verified", "node": "answer"}
            cancelled_row = session.get(ScenarioRun, queued.json()["id"])
            assert cancelled_row is not None and cancelled_row.status is RunStatus.CANCELLED
    finally:
        await scenario_queue.client.delete(
            scenario_queue.queue_key, scenario_queue.processing_key
        )
        await eval_queue.client.delete(eval_queue.queue_key, eval_queue.processing_key)
        await scenario_queue.close()
        await eval_queue.close()
        with database.session() as session:
            organization = session.get(Organization, organization_id)
            if organization is not None:
                session.delete(organization)
            user = session.get(User, admin_id)
            if user is not None:
                session.delete(user)
            session.commit()
        database.close()
