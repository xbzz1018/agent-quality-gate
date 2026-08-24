import asyncio

import httpx
import pytest

from agent_quality_harness.adapters.ag_ui import AgUiAgentAdapter
from agent_quality_harness.domain.enums import MeasurementStatus, TargetProtocol
from agent_quality_harness.execution import InspectRunExecutor, RunCancelled
from agent_quality_harness.fake_ag_ui import create_fake_ag_ui_app


async def _adapter(
    *, capabilities: dict | None = None
) -> tuple[AgUiAgentAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_fake_ag_ui_app()),
        base_url="http://ag-ui",
    )
    return (
        AgUiAgentAdapter(
            "http://ag-ui/ag-ui",
            timeout_seconds=5,
            capabilities=capabilities,
            client=client,
        ),
        client,
    )


async def test_ag_ui_maps_official_events_tool_state_usage_and_drops_reasoning() -> None:
    adapter, client = await _adapter()
    try:
        result = await adapter.invoke(
            {"prompt": "quality answer", "state": {"phase": "initial"}},
            {"target_name": "AG-UI Fixture", "case_id": "case-1"},
        )
    finally:
        await client.aclose()

    assert result.output == {
        "text": "quality answer",
        "fixture": "ag-ui",
        "state": {"phase": "finished", "count": 1},
    }
    assert result.final_action == "answer"
    assert result.usage.input_tokens == 4
    assert result.usage.output_tokens == 2
    assert result.usage.status is MeasurementStatus.PARTIAL
    tool = next(event for event in result.events if event.event_type == "tool.completed")
    assert tool.data == {
        "tool_call_id": "tool-1",
        "name": "quality_lookup",
        "arguments": {"query": "quality"},
    }
    serialized = str(result)
    assert "hidden chain of thought" not in serialized
    assert "encrypted-hidden-value" not in serialized
    assert "reasoning_content" not in serialized
    reasoning = [event for event in result.events if event.event_type.startswith("reasoning.")]
    assert [event.event_type for event in reasoning] == [
        "reasoning.started",
        "reasoning.ended",
    ]
    assert all(event.data == {} for event in reasoning)


async def test_ag_ui_unknown_token_usage_stays_unknown() -> None:
    adapter, client = await _adapter()
    try:
        result = await adapter.invoke(
            {
                "prompt": "unknown usage",
                "forwarded_props": {"mode": "unknown_usage"},
            },
            {"target_name": "AG-UI Fixture", "case_id": "unknown"},
        )
    finally:
        await client.aclose()

    assert result.usage.status is MeasurementStatus.UNKNOWN
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None


async def test_ag_ui_custom_event_normalizes_skill_telemetry() -> None:
    identity = {"name": "lookup", "version": "1.0.0", "sha256": "a" * 64}
    lifecycle = [
        {
            "schema": "aqh.skill-event/v1",
            "type": event_type,
            "invocation_id": "skill-one",
            "skill": identity,
            "status": "success" if event_type == "skill.completed" else None,
        }
        for event_type in ("skill.selected", "skill.started", "skill.completed")
    ]
    adapter, client = await _adapter()
    try:
        result = await adapter.invoke(
            {"prompt": "skill", "forwarded_props": {"skill_events": lifecycle}},
            {"target_name": "AG-UI Fixture", "case_id": "skill"},
        )
    finally:
        await client.aclose()

    skill_events = [event for event in result.events if event.event_type.startswith("skill.")]
    assert [event.event_type for event in skill_events] == [
        "skill.selected",
        "skill.started",
        "skill.completed",
    ]
    assert result.output["skills_used"] == ["lookup"]


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("invalid_patch", "invalid AG-UI JSON Patch"),
        ("disconnect", "without RUN_FINISHED"),
        ("bad_order", "must start with RUN_STARTED"),
        ("run_error", "AG-UI RUN_ERROR (fixture)"),
    ],
)
async def test_ag_ui_rejects_invalid_streams(mode: str, message: str) -> None:
    adapter, client = await _adapter()
    try:
        with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
            await adapter.invoke(
                {"prompt": "failure", "forwarded_props": {"mode": mode}},
                {"target_name": "AG-UI Fixture", "case_id": mode},
            )
    finally:
        await client.aclose()


async def test_ag_ui_calls_only_explicit_cancel_endpoint() -> None:
    adapter, client = await _adapter(capabilities={"cancel_endpoint": "/ag-ui/cancel/{run_id}"})
    try:
        assert await adapter.cancel("run-123") is True
    finally:
        await client.aclose()

    adapter_without_endpoint, client_without_endpoint = await _adapter()
    try:
        assert await adapter_without_endpoint.cancel("run-123") is False
    finally:
        await client_without_endpoint.aclose()


async def test_ag_ui_cancel_closes_active_http_stream() -> None:
    class TrackedStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.closed = False

        async def __aiter__(self):
            yield b""

        async def aclose(self) -> None:
            self.closed = True

    stream = TrackedStream()
    response = httpx.Response(200, stream=stream)
    adapter, client = await _adapter()
    adapter._active["active-run"] = (asyncio.get_running_loop(), response)
    try:
        assert await adapter.cancel("active-run") is True
        assert stream.closed is True
    finally:
        await client.aclose()


def test_ag_ui_protocol_is_registered_as_runnable_agent_target() -> None:
    from agent_quality_harness.adapter_factory import TargetSpec, create_agent_adapter

    adapter = create_agent_adapter(
        TargetSpec(
            id=1,
            protocol=TargetProtocol.AG_UI,
            endpoint="http://ag-ui/ag-ui",
            auth_ref=None,
            timeout_seconds=5,
            capabilities={"contract_profile": "ag_ui_v1"},
        )
    )

    assert isinstance(adapter, AgUiAgentAdapter)


async def test_executor_propagates_running_cancel_to_active_adapter() -> None:
    cancelled = asyncio.Event()

    class ActiveAdapter:
        async def cancel_active(self) -> int:
            cancelled.set()
            return 1

    executor = object.__new__(InspectRunExecutor)
    executor.heartbeat_seconds = 0.01
    executor._cancel_requested = lambda run_id: True

    async def active_work() -> None:
        await cancelled.wait()

    with pytest.raises(RunCancelled):
        await executor._run_with_heartbeat(1, active_work(), adapter=ActiveAdapter())
    assert cancelled.is_set()
