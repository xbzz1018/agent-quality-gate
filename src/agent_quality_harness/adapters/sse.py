import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

from agent_quality_harness.skill_events import skill_event_from_transport

from .base import AgentRunEvent, AgentRunResult
from .http import HttpAgentAdapter


class SseAgentAdapter(HttpAgentAdapter):
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        events = [event async for event in self.stream(input_data, context)]
        completed = next(
            (event for event in reversed(events) if event.event_type == "run_completed"), None
        )
        if completed is None:
            raise ValueError("SSE stream ended without run_completed")
        output = completed.data.get("output", {})
        if not isinstance(output, dict):
            output = {"text": str(output)}
        return AgentRunResult(
            run_id=_optional_string(completed.data.get("run_id")),
            final_action=str(completed.data.get("final_action", "answer")),
            output=output,
            events=tuple(events),
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        async with self._client_context() as client:
            async with client.stream(
                "POST",
                self.endpoint,
                json={"input": dict(input_data), "context": dict(context)},
                headers={"Accept": "text/event-stream", **self.headers},
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                event_name = "message"
                event_id: str | None = None
                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line == "":
                        if data_lines:
                            yield _event(event_name, event_id, data_lines)
                        event_name, event_id, data_lines = "message", None, []
                        continue
                    if line.startswith(":"):
                        continue
                    field, _, value = line.partition(":")
                    value = value[1:] if value.startswith(" ") else value
                    if field == "event":
                        event_name = value
                    elif field == "id":
                        event_id = value
                    elif field == "data":
                        data_lines.append(value)
                if data_lines:
                    yield _event(event_name, event_id, data_lines)


def _event(event_name: str, event_id: str | None, data_lines: list[str]) -> AgentRunEvent:
    raw = "\n".join(data_lines)
    decoded = json.loads(raw)
    data = decoded if isinstance(decoded, dict) else {"value": decoded}
    skill_event = skill_event_from_transport(event_name, data)
    if skill_event is not None:
        return skill_event
    return AgentRunEvent(event_type=event_name, event_id=event_id, data=data)


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
