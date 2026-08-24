import asyncio
import json
import os
from collections.abc import AsyncIterator
from uuid import uuid4

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
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse


class FakeRequest(BaseModel):
    input: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


def create_fake_agent_app() -> FastAPI:
    app = FastAPI(title="Agent Quality Harness Fake Agent")

    @app.post("/invoke")
    async def invoke(payload: FakeRequest) -> dict:
        run_id = str(uuid4())
        text = _answer(payload.input)
        return {
            "run_id": run_id,
            "final_action": "answer",
            "output": {"text": text},
            "usage": {
                "input_tokens": len(json.dumps(payload.input, ensure_ascii=False).split()),
                "output_tokens": len(text.split()),
            },
            "events": [
                {"event_type": "run_started", "data": {"run_id": run_id}},
                {
                    "event_type": "run_completed",
                    "data": {"run_id": run_id, "output": {"text": text}},
                },
            ],
        }

    @app.post("/stream")
    async def stream(payload: FakeRequest) -> StreamingResponse:
        run_id = str(uuid4())
        text = _answer(payload.input)

        async def events() -> AsyncIterator[str]:
            yield _sse("run_started", {"run_id": run_id}, "1")
            await asyncio.sleep(0)
            yield _sse("message_delta", {"delta": text}, "2")
            await asyncio.sleep(0)
            yield _sse(
                "run_completed",
                {
                    "run_id": run_id,
                    "final_action": "answer",
                    "output": {"text": text},
                },
                "3",
            )

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/invoke/{run_id}/cancel", status_code=202)
    async def cancel(run_id: str) -> dict[str, str]:
        return {"run_id": run_id, "status": "cancel_requested"}

    _add_a2a_fixture_routes(app)

    return app


class _FakeA2AExecutor(AgentExecutor):
    async def execute(self, context, event_queue) -> None:
        await event_queue.enqueue_event(
            types.Task(
                id=context.task_id,
                context_id=context.context_id,
                status=types.TaskStatus(state=types.TaskState.TASK_STATE_SUBMITTED),
            )
        )
        input_data = MessageToDict(context.message.parts[0].data)
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.start_work()
        await updater.add_artifact(
            [types.Part(text=_answer(input_data))],
            name="answer",
        )
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        await updater.cancel()


def _add_a2a_fixture_routes(app: FastAPI) -> None:
    endpoint = os.getenv("AQH_FAKE_A2A_URL", "http://127.0.0.1:8020/a2a")
    card = types.AgentCard(
        name="Agent Quality Harness A2A Fixture",
        description="Deterministic A2A protocol fixture",
        version="1.0.0",
        supported_interfaces=[
            types.AgentInterface(
                url=endpoint,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=types.AgentCapabilities(streaming=True),
        default_input_modes=["application/json"],
        default_output_modes=["text/plain"],
        skills=[
            types.AgentSkill(
                id="echo",
                name="Deterministic Echo",
                description="Returns prompt or text input without a model call",
                tags=["fixture", "deterministic"],
            )
        ],
    )
    handler = DefaultRequestHandler(
        agent_executor=_FakeA2AExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(
            card,
            card_url="/a2a/.well-known/agent-card.json",
        ),
        jsonrpc_routes=create_jsonrpc_routes(handler, rpc_url="/a2a"),
    )


def _answer(input_data: dict) -> str:
    return str(input_data.get("prompt") or input_data.get("text") or "ok")


def _sse(event: str, data: dict, event_id: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"


app = create_fake_agent_app()
