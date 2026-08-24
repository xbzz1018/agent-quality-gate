import os
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from agent_quality_harness.adapters.base import AgentRunEvent, AgentRunResult, TokenUsage
from agent_quality_harness.administration import bootstrap_platform_admin, provision_organization
from agent_quality_harness.core.config import Settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.models import (
    GateResult,
    Organization,
    PolicyEvaluation,
    User,
)
from agent_quality_harness.evaluation import InspectHarness
from agent_quality_harness.execution import InspectRunExecutor
from agent_quality_harness.main import create_app
from agent_quality_harness.policy import OpaClient
from agent_quality_harness.queue import RedisRunQueue, RedisRunWorker

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AQH_RUN_INTEGRATION") != "1",
        reason="set AQH_RUN_INTEGRATION=1 with PostgreSQL, Redis, and OPA running",
    ),
]


class StableAdapter:
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        return AgentRunResult(
            run_id=f"security-{context['case_id']}",
            final_action="answer",
            output={"text": input_data["prompt"]},
            usage=TokenUsage(input_tokens=2, output_tokens=1),
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        if False:
            yield AgentRunEvent("unused")

    async def cancel(self, run_id: str) -> bool:
        return True


async def test_skills_tenant_isolation_freeze_and_opa_gate(tmp_path: Path) -> None:
    suffix = uuid4().hex[:10]
    settings = Settings(
        redis_queue_key=f"aqh:security-gate-test:{suffix}",
        otel_enabled=False,
        opa_enabled=True,
        opa_url="http://127.0.0.1:8181",
        jwt_secret=f"integration-secret-long-enough-{suffix}",
    )
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    app = create_app(settings, database=database, run_queue=queue)
    username = f"security-admin-{suffix}"
    password = "Integration!Password123"
    with database.session() as session:
        admin = bootstrap_platform_admin(
            session,
            username=username,
            password=password,
            display_name="Security Gate Admin",
            email=None,
        )
        organization = provision_organization(
            session, slug=f"security-{suffix}", name="Security Test"
        )
        other_organization = provision_organization(
            session, slug=f"security-other-{suffix}", name="Other Security Test"
        )
        session.commit()
        admin_id = admin.id
        organization_id = organization.id
        other_organization_id = other_organization.id
    run_id: int | None = None
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/v1/auth/login", json={"username": username, "password": password}
            )
            assert login.status_code == 200
            headers = {
                "Authorization": f"Bearer {login.json()['access_token']}",
                "X-Organization-ID": str(organization_id),
            }
            target = await client.post(
                "/api/v1/targets",
                headers=headers,
                json={
                    "name": f"security-target-{suffix}",
                    "protocol": "http",
                    "endpoint": "http://fixture/invoke",
                },
            )
            assert target.status_code == 201, target.text
            version_ids = []
            for version_name in ("baseline", "candidate"):
                response = await client.post(
                    f"/api/v1/targets/{target.json()['id']}/versions",
                    headers=headers,
                    json={"version": version_name},
                )
                assert response.status_code == 201, response.text
                version_ids.append(response.json()["id"])
            dataset = await client.post(
                "/api/v1/datasets/import",
                headers=headers,
                json={
                    "name": f"security-dataset-{suffix}",
                    "version": "1",
                    "cases": [
                        {
                            "id": "case-1",
                            "input": {"prompt": "stable"},
                            "expected": {"final_action": "answer"},
                        }
                    ],
                },
            )
            assert dataset.status_code == 201, dataset.text
            skill_versions = []
            for skill_version, content in (
                ("1.0.0", "Use only the supplied input."),
                ("2.0.0", 'api_key="hardcoded-secret-value"'),
            ):
                imported = await client.post(
                    "/api/v1/skills/import",
                    headers=headers,
                    json={
                        "name": f"release-skill-{suffix}",
                        "version": skill_version,
                        "manifest": {"permissions": {}},
                        "files": [{"path": "SKILL.md", "content": content}],
                    },
                )
                assert imported.status_code == 201, imported.text
                skill_versions.append(imported.json()["version"]["id"])
                scan = await client.post(
                    f"/api/v1/skill-versions/{skill_versions[-1]}/scan", headers=headers
                )
                assert scan.status_code == 201, scan.text
            assert (
                await client.put(
                    f"/api/v1/versions/{version_ids[0]}/skills/{skill_versions[0]}",
                    headers=headers,
                )
            ).status_code == 200
            assert (
                await client.put(
                    f"/api/v1/versions/{version_ids[1]}/skills/{skill_versions[1]}",
                    headers=headers,
                )
            ).status_code == 200
            cross_tenant = await client.get(
                f"/api/v1/skills/{imported.json()['package']['id']}",
                headers={**headers, "X-Organization-ID": str(other_organization_id)},
            )
            assert cross_tenant.status_code == 404
            package_path = f"aqh.org_{organization_id}.release.v_1"
            rego = (
                f"package {package_path}\n\n"
                'decision := {"decision": "warn", "reasons": '
                '[{"rule_id": "manual_review", "severity": "warn", '
                '"actual": {"required": true}, "threshold": {"required": false}}]}'
            )
            bundle = await client.post(
                "/api/v1/policy-bundles",
                headers=headers,
                json={
                    "name": f"security-policy-{suffix}",
                    "version": "1",
                    "package_path": package_path,
                    "entrypoint": "decision",
                    "rego": rego,
                    "data": {},
                },
            )
            assert bundle.status_code == 201, bundle.text
            assert bundle.json()["status"] == "validated"
            gate_policy = await client.post(
                "/api/v1/gate-policies",
                headers=headers,
                json={
                    "name": f"security-gate-{suffix}",
                    "version": "1",
                    "policy_bundle_id": bundle.json()["id"],
                },
            )
            assert gate_policy.status_code == 201, gate_policy.text
            run = await client.post(
                "/api/v1/eval-runs",
                headers=headers,
                json={
                    "dataset_id": dataset.json()["id"],
                    "baseline_version_id": version_ids[0],
                    "candidate_version_id": version_ids[1],
                    "gate_policy_id": gate_policy.json()["id"],
                },
            )
            assert run.status_code == 202, run.text
            run_id = run.json()["id"]
            assert run.json()["manifest"]["versions"]["candidate"]["skills"][0][
                "sha256"
            ]
            assert run.json()["manifest"]["gate_policy"]["policy_bundle"]["sha256"]
            frozen = await client.put(
                f"/api/v1/versions/{version_ids[1]}/skills/{skill_versions[1]}",
                headers=headers,
            )
            assert frozen.status_code == 409

        worker = RedisRunWorker(
            queue,
            InspectRunExecutor(
                database,
                InspectHarness(max_samples=1, log_dir=tmp_path / "inspect"),
                adapter_factory=lambda _: StableAdapter(),
                opa_client=OpaClient(settings.opa_url),
            ).execute,
            claim_timeout_seconds=1,
        )
        assert await worker.process_once() is True
        with database.session() as session:
            gate = session.scalar(select(GateResult).where(GateResult.run_id == run_id))
            evaluation = session.scalar(
                select(PolicyEvaluation).where(PolicyEvaluation.run_id == run_id)
            )
            assert gate is not None and gate.decision.value == "block"
            assert evaluation is not None and evaluation.decision == "warn"
            assert evaluation.decision_id is not None
            assert any(reason.get("source") == "skills" for reason in gate.reasons)
            assert any(reason.get("source") == "opa" for reason in gate.reasons)
    finally:
        await queue.client.delete(queue.queue_key, queue.processing_key)
        await queue.close()
        with database.session() as session:
            session.execute(
                delete(Organization).where(
                    Organization.id.in_([organization_id, other_organization_id])
                )
            )
            session.execute(delete(User).where(User.id == admin_id))
            session.commit()
        database.close()
