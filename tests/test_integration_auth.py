import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select

from agent_quality_harness.administration import bootstrap_platform_admin
from agent_quality_harness.core.config import Settings
from agent_quality_harness.core.database import Database
from agent_quality_harness.domain.models import (
    Organization,
    ServiceAccount,
    User,
)
from agent_quality_harness.main import create_app
from agent_quality_harness.queue import RedisRunQueue

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("AQH_RUN_INTEGRATION") != "1",
        reason="set AQH_RUN_INTEGRATION=1 with project services running",
    ),
]


async def test_auth_rotation_rbac_api_key_and_tenant_isolation() -> None:
    suffix = uuid4().hex[:10]
    settings = Settings(
        redis_queue_key=f"aqh:auth-test:{suffix}",
        otel_enabled=False,
        jwt_secret=f"integration-secret-long-enough-{suffix}",
    )
    database = Database(settings.database_url)
    queue = RedisRunQueue(settings.redis_url, settings.redis_queue_key)
    app = create_app(settings, database=database, run_queue=queue)
    admin_username = f"admin-{suffix}"
    viewer_username = f"viewer-{suffix}"
    password = "Integration!Password123"
    with database.session() as session:
        admin = bootstrap_platform_admin(
            session,
            username=admin_username,
            password=password,
            display_name="Auth Test Admin",
            email=None,
        )
        admin_id = admin.id
        default_org = session.scalar(select(Organization).where(Organization.slug == "default"))
        assert default_org is not None
        default_org_id = default_org.id
    created_org_id: int | None = None
    viewer_id: int | None = None
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            bad_login = await client.post(
                "/api/v1/auth/login",
                json={"username": admin_username, "password": "incorrect-password"},
            )
            assert bad_login.status_code == 401

            login = await client.post(
                "/api/v1/auth/login",
                json={"username": admin_username, "password": password},
            )
            assert login.status_code == 200
            old_refresh = client.cookies.get(settings.refresh_cookie_name)
            assert old_refresh
            admin_headers = {
                "Authorization": f"Bearer {login.json()['access_token']}",
                "X-Organization-ID": str(default_org_id),
            }

            refreshed = await client.post("/api/v1/auth/refresh")
            assert refreshed.status_code == 200
            assert client.cookies.get(settings.refresh_cookie_name) != old_refresh

            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
                cookies={settings.refresh_cookie_name: old_refresh},
            ) as reuse_client:
                reused = await reuse_client.post("/api/v1/auth/refresh")
                assert reused.status_code == 401

            relogin = await client.post(
                "/api/v1/auth/login",
                json={"username": admin_username, "password": password},
            )
            admin_headers["Authorization"] = f"Bearer {relogin.json()['access_token']}"

            second_org = await client.post(
                "/api/v1/organizations",
                headers=admin_headers,
                json={"slug": f"tenant-{suffix}", "name": "Second Tenant"},
            )
            assert second_org.status_code == 201, second_org.text
            created_org_id = second_org.json()["id"]
            second_headers = admin_headers | {"X-Organization-ID": str(created_org_id)}
            second_target = await client.post(
                "/api/v1/targets",
                headers=second_headers,
                json={
                    "name": f"isolated-{suffix}",
                    "protocol": "http",
                    "endpoint": "http://target.invalid/invoke",
                },
            )
            assert second_target.status_code == 201, second_target.text

            roles = await client.get("/api/v1/roles", headers=admin_headers)
            viewer_role = next(item for item in roles.json() if item["name"] == "Viewer")
            member = await client.post(
                "/api/v1/members",
                headers=admin_headers,
                json={
                    "username": viewer_username,
                    "display_name": "Tenant Viewer",
                    "password": password,
                    "role_ids": [viewer_role["id"]],
                },
            )
            assert member.status_code == 201, member.text
            viewer_id = member.json()["user_id"]

            viewer_login = await client.post(
                "/api/v1/auth/login",
                json={"username": viewer_username, "password": password},
            )
            viewer_headers = {
                "Authorization": f"Bearer {viewer_login.json()['access_token']}",
                "X-Organization-ID": str(default_org_id),
            }
            denied_write = await client.post(
                "/api/v1/targets",
                headers=viewer_headers,
                json={
                    "name": "denied",
                    "protocol": "http",
                    "endpoint": "http://target.invalid/invoke",
                },
            )
            assert denied_write.status_code == 403
            hidden_cross_tenant = await client.get(
                f"/api/v1/targets/{second_target.json()['id']}/versions",
                headers=viewer_headers,
            )
            assert hidden_cross_tenant.status_code == 404

            account = await client.post(
                "/api/v1/service-accounts",
                headers=admin_headers,
                json={"name": f"ci-{suffix}", "description": "integration"},
            )
            assert account.status_code == 201, account.text
            key_response = await client.post(
                f"/api/v1/service-accounts/{account.json()['id']}/api-keys",
                headers=admin_headers,
                json={"name": "quality-gate"},
            )
            assert key_response.status_code == 201, key_response.text
            api_key = key_response.json()["api_key"]
            assert key_response.json()["prefix"] in api_key
            key_list = await client.get(
                "/api/v1/targets",
                headers={"X-API-Key": api_key},
            )
            assert key_list.status_code == 200
            revoked = await client.delete(
                f"/api/v1/api-keys/{key_response.json()['id']}",
                headers=admin_headers,
            )
            assert revoked.status_code == 204
            rejected_key = await client.get(
                "/api/v1/targets",
                headers={"X-API-Key": api_key},
            )
            assert rejected_key.status_code == 401
    finally:
        with database.session() as session:
            if created_org_id is not None:
                organization = session.get(Organization, created_org_id)
                if organization is not None:
                    session.delete(organization)
            for user_id in (viewer_id, admin_id):
                user = session.get(User, user_id) if user_id is not None else None
                if user is not None:
                    session.delete(user)
            session.execute(delete(ServiceAccount).where(ServiceAccount.name == f"ci-{suffix}"))
            session.commit()
        await queue.client.delete(queue.queue_key, queue.processing_key)
        await queue.close()
        database.close()
