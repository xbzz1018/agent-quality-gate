import httpx
from fastapi import FastAPI, Header

from agent_quality_harness.adapter_factory import TargetSpec, create_target_adapter
from agent_quality_harness.adapters import HermesAgentAdapter
from agent_quality_harness.adapters.auth import ResolvedAuth
from agent_quality_harness.domain.enums import MeasurementStatus, TargetProtocol
from agent_quality_harness.evaluation.scoring import score_agent_result


async def test_hermes_profile_maps_openai_tool_calls_without_reasoning_content() -> None:
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def complete(body: dict, authorization: str = Header()) -> dict:
        assert authorization == "Bearer fixture-token"
        assert body["stream"] is False
        return {
            "id": "hermes-run-1",
            "model": "hermes-4",
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "reasoning_content": "must never persist",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "lookup_quality",
                                    "arguments": '{"case_id":"42"}',
                                },
                            }
                        ],
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 11,
                "completion_tokens": 7,
                "total_tokens": 18,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://hermes") as client:
        adapter = HermesAgentAdapter(
            "http://hermes",
            timeout_seconds=5,
            auth=ResolvedAuth(kind="headers", headers={"Authorization": "Bearer fixture-token"}),
            capabilities={"model": "hermes-4"},
            client=client,
        )
        result = await adapter.invoke({"prompt": "inspect case"}, {"case_id": "case-1"})

    assert result.run_id == "hermes-run-1"
    assert result.final_action == "tool"
    assert result.usage.status is MeasurementStatus.PARTIAL
    assert result.usage.reasoning_tokens == 3
    assert "reasoning_content" not in str(result.output)
    report = score_agent_result(
        {
            "tools": {
                "required": ["lookup_quality"],
                "arguments": [{"name": "lookup_quality", "equals": {"case_id": "42"}}],
            }
        },
        result,
    )
    assert report.passed is True


def test_hermes_factory_is_optional_http_target_profile() -> None:
    adapter = create_target_adapter(
        TargetSpec(
            id=1,
            protocol=TargetProtocol.HTTP,
            endpoint="http://hermes",
            auth_ref=None,
            timeout_seconds=30,
            capabilities={"contract_profile": "hermes_v1", "model": "hermes-4"},
        )
    )

    assert isinstance(adapter, HermesAgentAdapter)
