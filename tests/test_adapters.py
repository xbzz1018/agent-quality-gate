import httpx
import pytest

from agent_quality_harness.adapters import HttpAgentAdapter, SseAgentAdapter
from agent_quality_harness.domain.enums import MeasurementStatus
from agent_quality_harness.fake_agent import create_fake_agent_app


async def test_http_adapter_maps_standard_response_and_partial_usage() -> None:
    transport = httpx.ASGITransport(app=create_fake_agent_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as client:
        adapter = HttpAgentAdapter("http://fake/invoke", client=client)
        result = await adapter.invoke({"prompt": "hello world"}, {"case_id": "case-1"})

    assert result.final_action == "answer"
    assert result.output == {"text": "hello world"}
    assert result.usage.input_tokens is not None
    assert result.usage.status is MeasurementStatus.PARTIAL
    assert [event.event_type for event in result.events] == ["run_started", "run_completed"]


async def test_sse_adapter_parses_event_boundaries_and_completion() -> None:
    transport = httpx.ASGITransport(app=create_fake_agent_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://fake") as client:
        adapter = SseAgentAdapter("http://fake/stream", client=client)
        events = [event async for event in adapter.stream({"prompt": "streamed"}, {"case_id": "c"})]

    assert [event.event_type for event in events] == [
        "run_started",
        "message_delta",
        "run_completed",
    ]
    assert events[-1].data["output"] == {"text": "streamed"}


@pytest.mark.parametrize(
    ("stream", "expected_ids"),
    [
        ('id: run-1\ndata: {}\n\ndata: {}\n\n', ["run-1", "run-1"]),
        ('id: run-1\n\ndata: {}\n\n', ["run-1"]),
        ('id: run-1\ndata: {}\n\nid:\ndata: {}\n\ndata: {}\n\n', ["run-1", "", ""]),
        ('id: run-1\ndata: {}\n\nid: bad\x00id\ndata: {}\n\n', ["run-1", "run-1"]),
    ],
)
async def test_sse_adapter_preserves_last_event_id(stream, expected_ids) -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"Content-Type": "text/event-stream"}, content=stream.encode(),
    ))
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = SseAgentAdapter("http://fake/stream", client=client)
        events = [event async for event in adapter.stream({}, {})]

    assert [event.event_id for event in events] == expected_ids
