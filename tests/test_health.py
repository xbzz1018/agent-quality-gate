from contextlib import contextmanager

import httpx

from agent_quality_harness.core.config import Settings
from agent_quality_harness.main import create_app


class HealthyDatabase:
    def ping(self) -> None:
        return None

    @contextmanager
    def session(self):
        yield None

    def close(self) -> None:
        return None


class HealthyQueue:
    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


async def test_liveness_and_readiness() -> None:
    app = create_app(
        Settings(otel_enabled=False),
        database=HealthyDatabase(),
        run_queue=HealthyQueue(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        live = await client.get("/api/v1/health/live")
        ready = await client.get("/api/v1/health/ready")

    assert live.json() == {"status": "ok"}
    assert ready.json() == {
        "status": "ready",
        "components": {"postgresql": "ok", "redis": "ok"},
    }


async def test_business_routes_require_authentication() -> None:
    app = create_app(
        Settings(environment="production", otel_enabled=False),
        database=HealthyDatabase(),
        run_queue=HealthyQueue(),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/demo/bootstrap", json={})

    assert response.status_code == 401
