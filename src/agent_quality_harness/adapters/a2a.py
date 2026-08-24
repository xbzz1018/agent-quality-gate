import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import httpx
from a2a import types
from a2a.client import A2ACardResolver, A2AClientError, Client, ClientConfig, ClientFactory
from google.protobuf.json_format import MessageToDict, ParseDict
from google.protobuf.struct_pb2 import Value

from .base import AgentRunEvent, AgentRunResult, TokenUsage

_TERMINAL_STATES = {
    types.TaskState.TASK_STATE_COMPLETED,
    types.TaskState.TASK_STATE_FAILED,
    types.TaskState.TASK_STATE_CANCELED,
    types.TaskState.TASK_STATE_REJECTED,
}
_INTERRUPTED_STATES = {
    types.TaskState.TASK_STATE_INPUT_REQUIRED,
    types.TaskState.TASK_STATE_AUTH_REQUIRED,
}


class A2AAgentAdapter:
    """A2A 1.x AgentTargetAdapter backed by the official A2A SDK."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30,
        headers: Mapping[str, str] | None = None,
        capabilities: Mapping[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})
        self.capabilities = dict(capabilities or {})
        self.poll_interval_seconds = max(
            0.01, float(self.capabilities.get("poll_interval_seconds", 0.25))
        )
        self.card_path = str(
            self.capabilities.get("agent_card_path", "/.well-known/agent-card.json")
        )
        self._client = client

    async def discover(self) -> dict[str, Any]:
        """Resolve the public Agent Card and return its non-sensitive version manifest."""
        async with asyncio.timeout(self.timeout_seconds):
            async with self._sdk_client() as (client, card):
                del client
                return _card_manifest(card)

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        events: list[AgentRunEvent] = []
        async with asyncio.timeout(self.timeout_seconds):
            async with self._sdk_client() as (client, card):
                card_manifest = _card_manifest(card)
                events.append(AgentRunEvent("a2a.agent_card", card_manifest))
                request = _send_request(input_data, context)
                task: types.Task | None = None
                message: types.Message | None = None

                async for response in client.send_message(request):
                    observed_task, observed_message = _capture_response(response, events)
                    task = observed_task or task
                    message = observed_message or message

                while task is not None and task.status.state not in (
                    _TERMINAL_STATES | _INTERRUPTED_STATES
                ):
                    await asyncio.sleep(self.poll_interval_seconds)
                    task = await client.get_task(
                        types.GetTaskRequest(id=task.id, history_length=10)
                    )
                    events.append(_task_event("a2a.task.polled", task))

                if task is not None:
                    return _result_from_task(task, card_manifest, events)
                if message is not None:
                    return _result_from_message(message, card_manifest, events)
                raise ValueError("A2A response contained neither a Task nor a Message")

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event

    async def cancel(self, run_id: str) -> bool:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with self._sdk_client() as (client, _card):
                    task = await client.cancel_task(types.CancelTaskRequest(id=run_id))
            return task.status.state == types.TaskState.TASK_STATE_CANCELED
        except (A2AClientError, httpx.HTTPError, TimeoutError, ValueError):
            return False

    @asynccontextmanager
    async def _sdk_client(self) -> AsyncIterator[tuple[Client, types.AgentCard]]:
        owned = self._client is None
        http_client = self._client or httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout_seconds,
        )
        if self._client is not None:
            http_client.headers.update(self.headers)
        config = ClientConfig(
            streaming=bool(self.capabilities.get("streaming", True)),
            polling=True,
            httpx_client=http_client,
        )
        resolver = A2ACardResolver(
            http_client,
            self.endpoint,
            agent_card_path=self.card_path,
        )
        card = await resolver.get_agent_card(
            http_kwargs={"headers": self.headers, "timeout": self.timeout_seconds},
        )
        factory = ClientFactory(config)
        client = factory.create(card)
        try:
            yield client, card
        finally:
            if owned:
                await client.close()


def _send_request(
    input_data: Mapping[str, Any], context: Mapping[str, Any]
) -> types.SendMessageRequest:
    value = Value()
    ParseDict(dict(input_data), value)
    request = types.SendMessageRequest(
        message=types.Message(
            message_id=uuid4().hex,
            role=types.Role.ROLE_USER,
            parts=[types.Part(data=value)],
        )
    )
    ParseDict({"aqh_context": dict(context)}, request.metadata)
    return request


def _capture_response(
    response: types.StreamResponse, events: list[AgentRunEvent]
) -> tuple[types.Task | None, types.Message | None]:
    if response.HasField("task"):
        events.append(_task_event("a2a.task", response.task))
        return response.task, None
    if response.HasField("message"):
        events.append(AgentRunEvent("a2a.message", _message_payload(response.message)))
        return None, response.message
    if response.HasField("status_update"):
        update = response.status_update
        events.append(
            AgentRunEvent(
                "a2a.task.status",
                {
                    "task_id": update.task_id,
                    "context_id": update.context_id,
                    "state": _state_name(update.status.state),
                    "message": _message_payload(update.status.message)
                    if update.status.HasField("message")
                    else None,
                },
            )
        )
        return None, None
    if response.HasField("artifact_update"):
        update = response.artifact_update
        events.append(
            AgentRunEvent(
                "a2a.task.artifact",
                {
                    "task_id": update.task_id,
                    "context_id": update.context_id,
                    "artifact": _artifact_payload(update.artifact),
                    "append": update.append,
                    "last_chunk": update.last_chunk,
                },
            )
        )
    return None, None


def _card_manifest(card: types.AgentCard) -> dict[str, Any]:
    return {
        "name": card.name,
        "version": card.version,
        "interfaces": [
            {
                "url": item.url,
                "protocol_binding": item.protocol_binding,
                "protocol_version": item.protocol_version,
            }
            for item in card.supported_interfaces
        ],
        "streaming": card.capabilities.streaming,
        "skills": [
            {"id": skill.id, "name": skill.name, "tags": list(skill.tags)}
            for skill in card.skills
        ],
    }


def _result_from_task(
    task: types.Task,
    card: Mapping[str, Any],
    events: list[AgentRunEvent],
) -> AgentRunResult:
    artifacts = [_artifact_payload(artifact) for artifact in task.artifacts]
    message = (
        _message_payload(task.status.message) if task.status.HasField("message") else None
    )
    text_parts = [
        str(part["text"])
        for artifact in artifacts
        for part in artifact["parts"]
        if "text" in part
    ]
    if message:
        text_parts.extend(str(part["text"]) for part in message["parts"] if "text" in part)
    state = _state_name(task.status.state)
    output: dict[str, Any] = {
        "protocol": "a2a",
        "agent": {"name": card["name"], "version": card["version"]},
        "state": state,
        "context_id": task.context_id,
        "artifacts": artifacts,
    }
    if message:
        output["message"] = message
    if text_parts:
        output["text"] = "\n".join(text_parts)
    return AgentRunResult(
        run_id=task.id,
        final_action=_final_action(task.status.state),
        output=output,
        events=tuple(events),
        usage=_unknown_usage(),
    )


def _result_from_message(
    message: types.Message,
    card: Mapping[str, Any],
    events: list[AgentRunEvent],
) -> AgentRunResult:
    payload = _message_payload(message)
    text_parts = [str(part["text"]) for part in payload["parts"] if "text" in part]
    output: dict[str, Any] = {
        "protocol": "a2a",
        "agent": {"name": card["name"], "version": card["version"]},
        "state": "message",
        "message": payload,
    }
    if text_parts:
        output["text"] = "\n".join(text_parts)
    return AgentRunResult(
        run_id=message.task_id or None,
        final_action="answer",
        output=output,
        events=tuple(events),
        usage=_unknown_usage(),
    )


def _task_event(event_type: str, task: types.Task) -> AgentRunEvent:
    return AgentRunEvent(
        event_type,
        {
            "task_id": task.id,
            "context_id": task.context_id,
            "state": _state_name(task.status.state),
            "artifact_count": len(task.artifacts),
        },
    )


def _artifact_payload(artifact: types.Artifact) -> dict[str, Any]:
    return {
        "artifact_id": artifact.artifact_id,
        "name": artifact.name or None,
        "parts": [_part_payload(part) for part in artifact.parts],
    }


def _message_payload(message: types.Message) -> dict[str, Any]:
    return {
        "message_id": message.message_id,
        "role": types.Role.Name(message.role).removeprefix("ROLE_").lower(),
        "parts": [_part_payload(part) for part in message.parts],
    }


def _part_payload(part: types.Part) -> dict[str, Any]:
    kind = part.WhichOneof("content")
    if kind == "data":
        return {"data": MessageToDict(part.data)}
    if kind == "raw":
        return {"raw_size": len(part.raw), "media_type": part.media_type or None}
    if kind == "url":
        return {"url": part.url, "media_type": part.media_type or None}
    return {"text": part.text}


def _state_name(state: int) -> str:
    return types.TaskState.Name(state).removeprefix("TASK_STATE_").lower()


def _final_action(state: int) -> str:
    return {
        types.TaskState.TASK_STATE_COMPLETED: "answer",
        types.TaskState.TASK_STATE_CANCELED: "cancelled",
        types.TaskState.TASK_STATE_FAILED: "failed",
        types.TaskState.TASK_STATE_REJECTED: "rejected",
        types.TaskState.TASK_STATE_INPUT_REQUIRED: "input_required",
        types.TaskState.TASK_STATE_AUTH_REQUIRED: "auth_required",
    }.get(state, "unknown")


def _unknown_usage() -> TokenUsage:
    return TokenUsage(raw={"protocol": "a2a", "status": "not_provided"})
