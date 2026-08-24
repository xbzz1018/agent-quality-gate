import asyncio
from dataclasses import dataclass, field
from typing import Any

import httpx
from a2a import types
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    add_a2a_routes_to_fastapi,
    create_agent_card_routes,
    create_jsonrpc_routes,
)
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from fastapi import FastAPI
from google.protobuf.json_format import MessageToDict

from agent_quality_harness.adapter_factory import (
    TargetSpec,
    create_agent_adapter,
    validate_contract_profile,
)
from agent_quality_harness.adapters import A2AAgentAdapter
from agent_quality_harness.domain.enums import MeasurementStatus, TargetProtocol


@dataclass
class _DeterministicExecutor(AgentExecutor):
    delay_seconds: float = 0
    block_until_cancelled: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)
    task_id: str | None = None
    observed_input: dict[str, Any] = field(default_factory=dict)

    async def execute(self, context, event_queue) -> None:
        self.task_id = context.task_id
        self.observed_input = MessageToDict(context.message.parts[0].data)
        await event_queue.enqueue_event(
            types.Task(
                id=context.task_id,
                context_id=context.context_id,
                status=types.TaskStatus(state=types.TaskState.TASK_STATE_SUBMITTED),
            )
        )
        self.started.set()
        if self.block_until_cancelled:
            await asyncio.Event().wait()
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()
        await updater.add_artifact(
            [types.Part(text="deterministic A2A answer")],
            name="answer",
        )
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


def _a2a_app(
    executor: AgentExecutor, *, streaming: bool = True
) -> tuple[FastAPI, types.AgentCard]:
    card = types.AgentCard(
        name="Deterministic A2A Fixture",
        description="Offline A2A contract target",
        version="2.3.4",
        supported_interfaces=[
            types.AgentInterface(
                url="http://a2a/",
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=types.AgentCapabilities(streaming=streaming),
        default_input_modes=["application/json"],
        default_output_modes=["text/plain"],
        skills=[
            types.AgentSkill(
                id="answer",
                name="Answer",
                description="Returns a deterministic answer",
                tags=["fixture"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = FastAPI()
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/"),
    )
    return app, card


async def test_a2a_discovers_version_invokes_polls_and_keeps_usage_unknown() -> None:
    executor = _DeterministicExecutor(delay_seconds=0.02)
    app, _card = _a2a_app(executor, streaming=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://a2a") as client:
        adapter = A2AAgentAdapter(
            "http://a2a",
            client=client,
            capabilities={"streaming": False, "poll_interval_seconds": 0.005},
        )
        manifest = await adapter.discover()
        result = await adapter.invoke(
            {"prompt": "quality check", "attempt": 1},
            {"case_id": "a2a-1"},
        )

    assert manifest["version"] == "2.3.4"
    assert manifest["interfaces"][0]["protocol_binding"] == "JSONRPC"
    assert executor.observed_input == {"prompt": "quality check", "attempt": 1.0}
    assert result.final_action == "answer"
    assert result.output["state"] == "completed"
    assert result.output["text"] == "deterministic A2A answer"
    assert result.usage.status is MeasurementStatus.UNKNOWN
    assert result.usage.input_tokens is None
    assert any(event.event_type == "a2a.task.polled" for event in result.events)


async def test_a2a_cancel_uses_task_protocol_and_stops_running_invocation() -> None:
    executor = _DeterministicExecutor(block_until_cancelled=True)
    app, _card = _a2a_app(executor, streaming=False)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://a2a") as client:
        adapter = A2AAgentAdapter(
            "http://a2a",
            timeout_seconds=2,
            client=client,
            capabilities={"streaming": False, "poll_interval_seconds": 0.005},
        )
        invocation = asyncio.create_task(adapter.invoke({"prompt": "wait"}, {}))
        await asyncio.wait_for(executor.started.wait(), timeout=1)
        assert executor.task_id is not None
        assert await adapter.cancel(executor.task_id) is True
        result = await asyncio.wait_for(invocation, timeout=1)

    assert result.run_id == executor.task_id
    assert result.final_action == "cancelled"
    assert result.output["state"] == "canceled"


def test_a2a_profile_is_runnable_and_mcp_remains_a_separate_pending_adapter() -> None:
    spec = TargetSpec(
        id=1,
        protocol=TargetProtocol.A2A,
        endpoint="http://a2a",
        auth_ref=None,
        timeout_seconds=30,
        capabilities={"contract_profile": "a2a_v1"},
    )

    assert validate_contract_profile(spec.protocol, spec.capabilities) == "a2a_v1"
    assert isinstance(create_agent_adapter(spec), A2AAgentAdapter)
    try:
        validate_contract_profile(
            TargetProtocol.MCP,
            {"contract_profile": "a2a_v1"},
        )
    except ValueError as exc:
        assert "incompatible" in str(exc)
    else:
        raise AssertionError("MCP must not be accepted as an A2A profile")
