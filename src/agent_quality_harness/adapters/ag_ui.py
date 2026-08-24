from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
from collections.abc import AsyncIterator, Mapping
from typing import Any
from urllib.parse import urljoin
from uuid import uuid4

import httpx
import jsonpatch
from ag_ui.core.events import (
    ActivityDeltaEvent,
    ActivitySnapshotEvent,
    Event,
    EventType,
    ReasoningEndEvent,
    ReasoningMessageChunkEvent,
    ReasoningMessageContentEvent,
    ReasoningMessageEndEvent,
    ReasoningMessageStartEvent,
    ReasoningStartEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateDeltaEvent,
    StateSnapshotEvent,
    TextMessageChunkEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ThinkingTextMessageStartEvent,
    ToolCallArgsEvent,
    ToolCallChunkEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)
from ag_ui.core.types import Context, Message, RunAgentInput, Tool, UserMessage
from pydantic import TypeAdapter, ValidationError

from .base import AgentRunEvent, AgentRunResult, TokenUsage

_EVENT_ADAPTER = TypeAdapter(Event)
_MESSAGE_LIST_ADAPTER = TypeAdapter(list[Message])
_TOOL_LIST_ADAPTER = TypeAdapter(list[Tool])
_CONTEXT_LIST_ADAPTER = TypeAdapter(list[Context])
_HIDDEN_KEY = re.compile(r"reasoning|encrypted[_-]?value|hidden[_-]?thought", re.IGNORECASE)


class AgUiAgentAdapter:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30,
        headers: Mapping[str, str] | None = None,
        capabilities: Mapping[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})
        self.capabilities = dict(capabilities or {})
        self._client = client
        self._active: dict[str, httpx.Response] = {}
        self._active_lock = asyncio.Lock()

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        request = _run_input(input_data, context)
        request_payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        events: list[AgentRunEvent] = []
        state = copy.deepcopy(request.state)
        text_messages: dict[str, list[str]] = {}
        completed_text: list[str] = []
        tools: dict[str, dict[str, Any]] = {}
        reasoning_active = False
        thinking_active = False
        started = False
        terminal = False
        external_run_id = request.run_id
        terminal_result: Any = None
        async with self._client_context() as client:
            async with client.stream(
                "POST",
                self.endpoint,
                json=request_payload,
                headers={"Accept": "text/event-stream", **self.headers},
                timeout=self.timeout_seconds,
            ) as response:
                response.raise_for_status()
                async with self._active_lock:
                    self._active[request.run_id] = response
                try:
                    async for event in _event_stream(response):
                        if terminal:
                            raise ValueError("AG-UI event received after terminal event")
                        if not started and not isinstance(event, (RunStartedEvent, RunErrorEvent)):
                            raise ValueError("AG-UI stream must start with RUN_STARTED")
                        if isinstance(event, RunStartedEvent):
                            if started:
                                raise ValueError("duplicate AG-UI RUN_STARTED")
                            started = True
                            external_run_id = event.run_id
                            events.append(
                                AgentRunEvent(
                                    "run.started",
                                    {"run_id": event.run_id, "thread_id": event.thread_id},
                                )
                            )
                        elif isinstance(event, TextMessageStartEvent):
                            if event.message_id in text_messages:
                                raise ValueError("duplicate AG-UI text message start")
                            text_messages[event.message_id] = []
                        elif isinstance(event, TextMessageContentEvent):
                            if event.message_id not in text_messages:
                                raise ValueError("AG-UI text content has no active message")
                            text_messages[event.message_id].append(event.delta)
                        elif isinstance(event, TextMessageEndEvent):
                            parts = text_messages.pop(event.message_id, None)
                            if parts is None:
                                raise ValueError("AG-UI text end has no active message")
                            completed_text.append("".join(parts))
                        elif isinstance(event, TextMessageChunkEvent):
                            _consume_text_chunk(event, text_messages, completed_text)
                        elif isinstance(event, ToolCallStartEvent):
                            if event.tool_call_id in tools:
                                raise ValueError("duplicate AG-UI tool call start")
                            tools[event.tool_call_id] = {
                                "name": event.tool_call_name,
                                "arguments": "",
                                "ended": False,
                            }
                        elif isinstance(event, ToolCallArgsEvent):
                            _append_tool_args(tools, event.tool_call_id, event.delta)
                        elif isinstance(event, ToolCallChunkEvent):
                            _consume_tool_chunk(event, tools)
                        elif isinstance(event, ToolCallEndEvent):
                            tool = tools.get(event.tool_call_id)
                            if tool is None or tool["ended"]:
                                raise ValueError("AG-UI tool end has no active tool call")
                            arguments = _tool_arguments(tool["arguments"])
                            tool["ended"] = True
                            tool["parsed_arguments"] = arguments
                            events.append(
                                AgentRunEvent(
                                    "tool.completed",
                                    {
                                        "tool_call_id": event.tool_call_id,
                                        "name": tool["name"],
                                        "arguments": arguments,
                                    },
                                )
                            )
                        elif isinstance(event, ToolCallResultEvent):
                            tool = tools.get(event.tool_call_id)
                            if tool is None or not tool["ended"]:
                                raise ValueError("AG-UI tool result precedes tool completion")
                            events.append(
                                AgentRunEvent(
                                    "tool.result",
                                    {
                                        "tool_call_id": event.tool_call_id,
                                        "name": tool["name"],
                                        "result_present": bool(event.content),
                                    },
                                )
                            )
                        elif isinstance(event, StateSnapshotEvent):
                            state = copy.deepcopy(event.snapshot)
                            events.append(AgentRunEvent("state.snapshot", _state_summary(state)))
                        elif isinstance(event, StateDeltaEvent):
                            try:
                                state = jsonpatch.JsonPatch(event.delta).apply(
                                    state, in_place=False
                                )
                            except (jsonpatch.JsonPatchException, TypeError, ValueError) as exc:
                                raise ValueError("invalid AG-UI JSON Patch") from exc
                            events.append(
                                AgentRunEvent(
                                    "state.delta",
                                    {"operation_count": len(event.delta), **_state_summary(state)},
                                )
                            )
                        elif isinstance(
                            event,
                            (
                                ReasoningStartEvent,
                                ThinkingStartEvent,
                                ThinkingTextMessageStartEvent,
                            ),
                        ):
                            if reasoning_active or thinking_active:
                                raise ValueError("nested AG-UI reasoning lifecycle")
                            reasoning_active = isinstance(event, ReasoningStartEvent)
                            thinking_active = not reasoning_active
                            events.append(AgentRunEvent("reasoning.started", {}))
                        elif isinstance(
                            event,
                            (ReasoningEndEvent, ThinkingEndEvent, ThinkingTextMessageEndEvent),
                        ):
                            if not reasoning_active and not thinking_active:
                                raise ValueError("AG-UI reasoning end has no active lifecycle")
                            reasoning_active = False
                            thinking_active = False
                            events.append(AgentRunEvent("reasoning.ended", {}))
                        elif isinstance(
                            event,
                            (
                                ReasoningMessageStartEvent,
                                ReasoningMessageContentEvent,
                                ReasoningMessageChunkEvent,
                                ReasoningMessageEndEvent,
                                ThinkingTextMessageContentEvent,
                            ),
                        ):
                            if not reasoning_active and not thinking_active:
                                raise ValueError("AG-UI reasoning content is out of order")
                        elif event.type is EventType.REASONING_ENCRYPTED_VALUE:
                            if not reasoning_active:
                                raise ValueError("AG-UI encrypted reasoning is out of order")
                        elif isinstance(event, (ActivitySnapshotEvent, ActivityDeltaEvent)):
                            events.append(
                                AgentRunEvent(
                                    "activity.updated",
                                    {
                                        "message_id": event.message_id,
                                        "activity_type": event.activity_type,
                                    },
                                )
                            )
                        elif isinstance(event, RunErrorEvent):
                            code = event.code or "unspecified"
                            raise ValueError(f"AG-UI RUN_ERROR ({code})")
                        elif isinstance(event, RunFinishedEvent):
                            if text_messages or any(not tool["ended"] for tool in tools.values()):
                                raise ValueError(
                                    "AG-UI stream finished with incomplete message or tool"
                                )
                            if reasoning_active or thinking_active:
                                raise ValueError("AG-UI stream finished with active reasoning")
                            if event.run_id != external_run_id:
                                raise ValueError("AG-UI RUN_FINISHED run id mismatch")
                            terminal = True
                            terminal_result = event.result
                            events.append(
                                AgentRunEvent(
                                    "run.finished",
                                    {"run_id": event.run_id, "thread_id": event.thread_id},
                                )
                            )
                finally:
                    async with self._active_lock:
                        self._active.pop(request.run_id, None)
        if not terminal:
            raise ValueError("AG-UI stream ended without RUN_FINISHED or RUN_ERROR")
        output, final_action, usage = _final_result(
            terminal_result,
            completed_text,
            state,
            include_state=bool(self.capabilities.get("include_state_output", True)),
        )
        return AgentRunResult(
            run_id=external_run_id,
            final_action=final_action,
            output=output,
            events=tuple(events),
            usage=usage,
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event

    async def cancel(self, run_id: str) -> bool:
        async with self._active_lock:
            response = self._active.get(run_id)
        closed = False
        if response is not None:
            await response.aclose()
            closed = True
        endpoint = self.capabilities.get("cancel_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            return closed
        cancel_url = endpoint.replace("{run_id}", run_id)
        if cancel_url.startswith("/"):
            cancel_url = urljoin(self.endpoint, cancel_url)
        async with self._client_context() as client:
            result = await client.post(
                cancel_url,
                json={"runId": run_id},
                headers=self.headers,
                timeout=self.timeout_seconds,
            )
        return closed or result.status_code in {200, 202, 204}

    def _client_context(self) -> _ClientContext:
        return _ClientContext(self._client)


class _ClientContext:
    def __init__(self, client: httpx.AsyncClient | None) -> None:
        self.client = client
        self.owned = client is None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient()
        return self.client

    async def __aexit__(self, *_: object) -> None:
        if self.owned and self.client is not None:
            await self.client.aclose()


async def _event_stream(response: httpx.Response) -> AsyncIterator[Any]:
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield _parse_event(data_lines)
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data_lines.append(value[1:] if value.startswith(" ") else value)
    if data_lines:
        yield _parse_event(data_lines)


def _parse_event(data_lines: list[str]) -> Any:
    raw = "\n".join(data_lines)
    if raw == "[DONE]":
        raise ValueError("AG-UI stream ended with [DONE] instead of RUN_FINISHED")
    try:
        return _EVENT_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        raise ValueError("invalid AG-UI event") from exc


def _run_input(input_data: Mapping[str, Any], context: Mapping[str, Any]) -> RunAgentInput:
    run_id = str(input_data.get("run_id") or uuid4())
    thread_id = str(
        input_data.get("thread_id")
        or f"aqh-{context.get('target_name', 'target')}-{context.get('case_id', 'case')}"
    )
    raw_messages = input_data.get("messages")
    if raw_messages is None:
        content = str(input_data.get("prompt") or input_data.get("text") or "")
        messages = [UserMessage(id=f"user-{uuid4().hex[:12]}", content=content)]
    else:
        messages = _MESSAGE_LIST_ADAPTER.validate_python(raw_messages)
    tools = _TOOL_LIST_ADAPTER.validate_python(input_data.get("tools", []))
    ag_ui_context = _CONTEXT_LIST_ADAPTER.validate_python(input_data.get("ag_ui_context", []))
    return RunAgentInput(
        thread_id=thread_id,
        run_id=run_id,
        parent_run_id=input_data.get("parent_run_id"),
        state=copy.deepcopy(input_data.get("state", {})),
        messages=messages,
        tools=tools,
        context=ag_ui_context,
        forwarded_props=copy.deepcopy(input_data.get("forwarded_props", {})),
    )


def _consume_text_chunk(
    event: TextMessageChunkEvent,
    messages: dict[str, list[str]],
    completed: list[str],
) -> None:
    message_id = event.message_id
    if not message_id:
        raise ValueError("AG-UI text chunk requires message_id")
    if message_id not in messages:
        if event.role is None:
            raise ValueError("AG-UI text chunk has no active message")
        messages[message_id] = []
    if event.delta is not None:
        messages[message_id].append(event.delta)
    if event.delta is None and event.role is None:
        parts = messages.pop(message_id, None)
        if parts is None:
            raise ValueError("AG-UI text chunk end has no active message")
        completed.append("".join(parts))


def _append_tool_args(tools: dict[str, dict[str, Any]], tool_call_id: str, delta: str) -> None:
    tool = tools.get(tool_call_id)
    if tool is None or tool["ended"]:
        raise ValueError("AG-UI tool arguments have no active tool call")
    tool["arguments"] += delta


def _consume_tool_chunk(event: ToolCallChunkEvent, tools: dict[str, dict[str, Any]]) -> None:
    tool_call_id = event.tool_call_id
    if not tool_call_id:
        raise ValueError("AG-UI tool chunk requires tool_call_id")
    if tool_call_id not in tools:
        if not event.tool_call_name:
            raise ValueError("AG-UI tool chunk has no active tool call")
        tools[tool_call_id] = {
            "name": event.tool_call_name,
            "arguments": "",
            "ended": False,
        }
    if event.delta is not None:
        _append_tool_args(tools, tool_call_id, event.delta)


def _tool_arguments(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AG-UI tool arguments are not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("AG-UI tool arguments must be a JSON object")
    return parsed


def _state_summary(state: Any) -> dict[str, Any]:
    canonical = json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)
    keys = sorted(str(key) for key in state)[:50] if isinstance(state, dict) else []
    return {
        "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "top_level_keys": keys,
    }


def _final_result(
    result: Any,
    text: list[str],
    state: Any,
    *,
    include_state: bool,
) -> tuple[dict[str, Any], str, TokenUsage]:
    result_dict = result if isinstance(result, dict) else {}
    raw_output = result_dict.get("output")
    output = dict(raw_output) if isinstance(raw_output, dict) else {}
    if text:
        output.setdefault("text", "".join(text))
    if not output and result is not None and not isinstance(result, dict):
        output["result"] = result
    if include_state:
        output["state"] = state
    output = _drop_hidden(output)
    usage_payload = result_dict.get("usage", result_dict.get("tokenUsage", {}))
    usage_payload = usage_payload if isinstance(usage_payload, dict) else {}
    normalized_usage = {
        "input_tokens": usage_payload.get("input_tokens", usage_payload.get("inputTokens")),
        "output_tokens": usage_payload.get("output_tokens", usage_payload.get("outputTokens")),
        "cache_read_tokens": usage_payload.get(
            "cache_read_tokens", usage_payload.get("cacheReadTokens")
        ),
        "cache_write_tokens": usage_payload.get(
            "cache_write_tokens", usage_payload.get("cacheWriteTokens")
        ),
        "reasoning_tokens": usage_payload.get(
            "reasoning_tokens", usage_payload.get("reasoningTokens")
        ),
    }
    usage = TokenUsage(
        input_tokens=_optional_token(normalized_usage["input_tokens"]),
        output_tokens=_optional_token(normalized_usage["output_tokens"]),
        cache_read_tokens=_optional_token(normalized_usage["cache_read_tokens"]),
        cache_write_tokens=_optional_token(normalized_usage["cache_write_tokens"]),
        reasoning_tokens=_optional_token(normalized_usage["reasoning_tokens"]),
        raw={key: value for key, value in normalized_usage.items() if value is not None}
        or {"protocol": "ag_ui", "status": "not_provided"},
    )
    final_action = str(
        result_dict.get("final_action", result_dict.get("finalAction", "answer"))
    )
    return output, final_action, usage


def _optional_token(value: Any) -> int | None:
    if value is None:
        return None
    token = int(value)
    if token < 0:
        raise ValueError("AG-UI TokenUsage cannot be negative")
    return token


def _drop_hidden(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _drop_hidden(item)
            for key, item in value.items()
            if not _HIDDEN_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_drop_hidden(item) for item in value]
    return value
