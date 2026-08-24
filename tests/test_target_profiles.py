import hashlib
import json
from decimal import Decimal

import httpx
import pytest
from fastapi import FastAPI, Header, Response

from agent_quality_harness.adapters import AgriGraphAdapter, DocumentAutoflowAdapter, TokenUsage
from agent_quality_harness.adapters.auth import ResolvedAuth, resolve_auth
from agent_quality_harness.domain.enums import MeasurementStatus


async def test_agrigraph_profile_logs_in_and_maps_quality_observations() -> None:
    app = FastAPI()

    @app.post("/api/v1/users/login")
    async def login() -> dict:
        return {"data": {"token": "target-token"}}

    @app.post("/api/v1/evaluation/answer")
    async def answer(authorization: str = Header()) -> dict:
        assert authorization == "Bearer target-token"
        return {
            "data": {
                "agentRunId": "ag-run-1",
                "answer": "Use verified crop guidance.",
                "citations": [{"id": "doc-1"}],
                "grounded": True,
                "degraded": False,
                "workflow": ["retrieve", "answer"],
                "modelUsed": "test-model",
                "modelUsage": {"inputTokens": 11, "outputTokens": 7},
                "estimatedCostUsd": "0.002",
            }
        }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://target") as client:
        adapter = AgriGraphAdapter(
            "http://target",
            timeout_seconds=5,
            auth=ResolvedAuth(kind="bearer_login", username="quality", password="not-logged"),
            capabilities={},
            client=client,
        )
        result = await adapter.invoke({"question": "How?", "crop": "TOMATO"}, {"case_id": "1"})

    assert result.run_id == "ag-run-1"
    assert result.output["grounded"] is True
    assert result.output["citations"] == [{"id": "doc-1"}]
    assert result.usage.input_tokens == 11
    assert result.usage.status is MeasurementStatus.PARTIAL
    assert str(result.model_cost) == "0.002"


async def test_document_autoflow_profile_uses_cookie_and_polls_terminal_run() -> None:
    app = FastAPI()
    reads = 0

    @app.post("/api/v1/auth/login")
    async def login(response: Response) -> dict:
        response.set_cookie("autoflow_session", "private-cookie", httponly=True)
        return {"user": {"username": "quality"}}

    @app.post("/api/v1/projects/project-1/runs", status_code=202)
    async def create_run(
        autoflow_session: str | None = Header(default=None, alias="cookie"),
    ) -> dict:
        assert autoflow_session is not None
        return {"id": "run-1", "status": "queued"}

    @app.get("/api/v1/runs/run-1")
    async def get_run() -> dict:
        nonlocal reads
        reads += 1
        if reads == 1:
            return {"id": "run-1", "status": "running"}
        return {
            "id": "run-1",
            "status": "completed",
            "route": "auto_pass",
            "input_tokens": 23,
            "output_tokens": 9,
            "estimated_cost": "0.004",
            "candidates": [
                {
                    "field_key": "invoice_no",
                    "normalized_value": "A-1",
                    "evidence_refs": [{"verified": True}],
                }
            ],
            "validation_result": {"passed": True},
        }

    @app.post("/api/v1/runs/run-1/cancel", status_code=202)
    async def cancel() -> dict:
        return {"run_id": "run-1", "status": "cancel_requested"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://target") as client:
        adapter = DocumentAutoflowAdapter(
            "http://target",
            timeout_seconds=5,
            auth=ResolvedAuth(kind="cookie_login", username="quality", password="not-logged"),
            capabilities={"poll_interval_seconds": 0.01},
            client=client,
        )
        result = await adapter.invoke(
            {
                "project_id": "project-1",
                "template_id": "template-1",
                "document_id": "document-1",
            },
            {"case_id": "doc-1"},
        )
        assert await adapter.cancel("run-1") is True

    assert result.run_id == "run-1"
    assert result.final_action == "extract"
    assert result.output["status"] == "completed"
    assert result.output["field_hashes"]["invoice_no"] == hashlib.sha256(b"a-1").hexdigest()
    assert result.output["evidence_verified"] == {"invoice_no": True}
    assert result.usage.input_tokens == 23
    assert str(result.model_cost) == "0.004"
    assert [event.data.get("status") for event in result.events if "status" in event.data] == [
        "queued",
        "running",
        "completed",
        "completed",
    ]


def test_auth_reference_is_versioned_and_does_not_repr_credentials(monkeypatch) -> None:
    monkeypatch.setenv(
        "AQH_TEST_TARGET_AUTH",
        json.dumps(
            {
                "type": "bearer_login",
                "username": "quality",
                "password": "sensitive-password",
            }
        ),
    )
    auth = resolve_auth("AQH_TEST_TARGET_AUTH")

    assert auth.kind == "bearer_login"
    assert "sensitive-password" not in repr(auth)


def test_auth_reference_rejects_unknown_type(monkeypatch) -> None:
    monkeypatch.setenv("AQH_TEST_TARGET_AUTH", '{"type":"unknown"}')
    with pytest.raises(ValueError, match="auth reference type"):
        resolve_auth("AQH_TEST_TARGET_AUTH")


def test_static_auth_headers_are_not_in_repr(monkeypatch) -> None:
    monkeypatch.setenv("AQH_TEST_TARGET_AUTH", '{"Authorization":"Bearer private-token"}')
    auth = resolve_auth("AQH_TEST_TARGET_AUTH")

    assert "private-token" not in repr(auth)


async def test_document_waiting_review_is_a_terminal_business_outcome() -> None:
    app = FastAPI()

    @app.post("/api/v1/projects/project-1/runs", status_code=202)
    async def create_run() -> dict:
        return {
            "id": "run-review",
            "status": "waiting_review",
            "route": "REVIEW",
            "input_tokens": 3,
            "output_tokens": 2,
        }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://target") as client:
        adapter = DocumentAutoflowAdapter(
            "http://target",
            timeout_seconds=5,
            auth=ResolvedAuth(),
            capabilities={},
            client=client,
        )
        result = await adapter.invoke(
            {
                "project_id": "project-1",
                "template_id": "template-1",
                "document_id": "document-1",
            },
            {"case_id": "review"},
        )

    assert result.final_action == "review"
    assert result.output["status"] == "waiting_review"


def test_document_profile_enforces_known_cost_budget() -> None:
    adapter = DocumentAutoflowAdapter(
        "http://target",
        timeout_seconds=5,
        auth=ResolvedAuth(),
        capabilities={"budget": {"max_cost_usd": 1}},
    )

    with pytest.raises(RuntimeError, match="cost budget exceeded"):
        adapter._record_budget(TokenUsage(input_tokens=1, output_tokens=1), Decimal("1.01"))
