import asyncio
from collections.abc import AsyncIterator

from ag_ui.core.events import (
    ReasoningEncryptedValueEvent,
    ReasoningEndEvent,
    ReasoningMessageContentEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.types import RunAgentInput
from ag_ui.encoder import EventEncoder
from fastapi import FastAPI
from starlette.responses import StreamingResponse


def create_fake_ag_ui_app() -> FastAPI:
    app = FastAPI(title="Agent Quality Harness Fake AG-UI Target")
    encoder = EventEncoder()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "protocol": "ag-ui", "version": "0.1.19"}

    @app.post("/ag-ui")
    async def run(payload: RunAgentInput) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            mode = (
                payload.forwarded_props.get("mode")
                if isinstance(payload.forwarded_props, dict)
                else None
            )
            if mode == "bad_order":
                yield encoder.encode(TextMessageContentEvent(message_id="answer", delta="bad"))
                return
            yield encoder.encode(
                RunStartedEvent(thread_id=payload.thread_id, run_id=payload.run_id)
            )
            await asyncio.sleep(0)
            if mode == "run_error":
                yield encoder.encode(RunErrorEvent(message="fixture failure", code="fixture"))
                return
            yield encoder.encode(ReasoningStartEvent(message_id="reasoning-1"))
            yield encoder.encode(
                ReasoningMessageContentEvent(
                    message_id="reasoning-1",
                    delta="hidden chain of thought must never persist",
                )
            )
            yield encoder.encode(
                ReasoningEncryptedValueEvent(
                    subtype="message",
                    entity_id="reasoning-1",
                    encrypted_value="encrypted-hidden-value",
                )
            )
            yield encoder.encode(ReasoningEndEvent(message_id="reasoning-1"))
            yield encoder.encode(StateSnapshotEvent(snapshot={"phase": "started", "count": 0}))
            patch = (
                [{"op": "replace", "path": "/missing", "value": "bad"}]
                if mode == "invalid_patch"
                else [
                    {"op": "replace", "path": "/phase", "value": "finished"},
                    {"op": "replace", "path": "/count", "value": 1},
                ]
            )
            yield encoder.encode(StateDeltaEvent(delta=patch))
            answer = _answer(payload)
            yield encoder.encode(
                ToolCallStartEvent(
                    tool_call_id="tool-1",
                    tool_call_name="quality_lookup",
                    parent_message_id="answer",
                )
            )
            yield encoder.encode(ToolCallArgsEvent(tool_call_id="tool-1", delta='{"query":'))
            yield encoder.encode(ToolCallArgsEvent(tool_call_id="tool-1", delta='"quality"}'))
            yield encoder.encode(ToolCallEndEvent(tool_call_id="tool-1"))
            yield encoder.encode(
                ToolCallResultEvent(
                    message_id="tool-result-1",
                    tool_call_id="tool-1",
                    content="fixture result",
                )
            )
            yield encoder.encode(TextMessageStartEvent(message_id="answer", role="assistant"))
            midpoint = max(1, len(answer) // 2)
            yield encoder.encode(
                TextMessageContentEvent(message_id="answer", delta=answer[:midpoint])
            )
            yield encoder.encode(
                TextMessageContentEvent(message_id="answer", delta=answer[midpoint:])
            )
            yield encoder.encode(TextMessageEndEvent(message_id="answer"))
            if mode == "disconnect":
                return
            result = {
                "output": {
                    "text": answer,
                    "fixture": "ag-ui",
                    "reasoning_content": "must be removed",
                },
                "finalAction": "answer",
            }
            if mode != "unknown_usage":
                result["tokenUsage"] = {"inputTokens": 4, "outputTokens": 2}
            yield encoder.encode(
                RunFinishedEvent(
                    thread_id=payload.thread_id,
                    run_id=payload.run_id,
                    result=result,
                )
            )

        return StreamingResponse(events(), media_type=encoder.get_content_type())

    @app.post("/ag-ui/cancel/{run_id}", status_code=202)
    async def cancel(run_id: str) -> dict[str, str]:
        return {"runId": run_id, "status": "cancel_requested"}

    return app


def _answer(payload: RunAgentInput) -> str:
    for message in reversed(payload.messages):
        if message.role == "user":
            return str(message.content)
    return "ok"


app = create_fake_ag_ui_app()
