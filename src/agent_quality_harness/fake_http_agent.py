import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse


class FakeRequest(BaseModel):
    input: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


app = FastAPI(title="Agent Quality Harness HTTP Fixture")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


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
            {"event_type": "run_completed", "data": {"run_id": run_id}},
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
        yield _sse(
            "run_completed",
            {"run_id": run_id, "final_action": "answer", "output": {"text": text}},
            "3",
        )

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/invoke/{run_id}/cancel", status_code=202)
async def cancel(run_id: str) -> dict[str, str]:
    return {"run_id": run_id, "status": "cancel_requested"}


def _answer(input_data: dict) -> str:
    return str(input_data.get("prompt") or input_data.get("text") or "ok")


def _sse(event: str, data: dict, event_id: str) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {payload}\n\n"
