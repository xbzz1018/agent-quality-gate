from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from .auth import ResolvedAuth
from .base import AgentRunEvent, AgentRunResult, TokenUsage
from .profile_common import endpoint, optional_int


class HermesAgentAdapter:
    """Optional Hermes-compatible OpenAI Chat Completions target profile."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        auth: ResolvedAuth,
        capabilities: Mapping[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.auth = auth
        self.capabilities = dict(capabilities)
        self.client = client

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        messages = input_data.get("messages")
        if not isinstance(messages, list):
            prompt = str(input_data.get("prompt", input_data.get("question", ""))).strip()
            if not prompt:
                raise ValueError("hermes_v1 requires messages, prompt, or question")
            messages = [{"role": "user", "content": prompt}]
        request = {
            "model": str(
                input_data.get("model", self.capabilities.get("model", "hermes-compatible"))
            ),
            "messages": messages,
            "temperature": float(input_data.get("temperature", 0)),
            "stream": False,
        }
        tools = input_data.get("tools")
        if isinstance(tools, list):
            request["tools"] = tools
        owned = self.client is None
        client = self.client or httpx.AsyncClient()
        try:
            response = await client.post(
                endpoint(
                    self.base_url,
                    str(self.capabilities.get("chat_path", "/v1/chat/completions")),
                ),
                json=request,
                headers=dict(self.auth.headers),
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            document = response.json()
        finally:
            if owned:
                await client.aclose()
        choice = document["choices"][0]
        message = choice["message"]
        tool_calls = _tool_calls(message.get("tool_calls", []))
        events = tuple(
            AgentRunEvent(
                "tool.completed",
                {
                    "name": call["name"],
                    "arguments": call["arguments"],
                    "call_id": call["id"],
                },
            )
            for call in tool_calls
        )
        usage = document.get("usage", {})
        usage = usage if isinstance(usage, Mapping) else {}
        return AgentRunResult(
            run_id=str(document.get("id", context.get("case_id"))),
            final_action="tool" if tool_calls else "answer",
            output={
                "text": message.get("content"),
                "tool_calls": tool_calls,
                "finish_reason": choice.get("finish_reason"),
                "model": document.get("model"),
            },
            events=events,
            usage=TokenUsage(
                input_tokens=optional_int(usage.get("prompt_tokens")),
                output_tokens=optional_int(usage.get("completion_tokens")),
                reasoning_tokens=optional_int(
                    (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
                    if isinstance(usage.get("completion_tokens_details"), Mapping)
                    else None
                ),
                raw={
                    "prompt_tokens": usage.get("prompt_tokens"),
                    "completion_tokens": usage.get("completion_tokens"),
                    "total_tokens": usage.get("total_tokens"),
                    "model": document.get("model"),
                },
            ),
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event

    async def cancel(self, run_id: str) -> bool:
        del run_id
        return False


def _tool_calls(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    calls: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        function = item.get("function")
        if not isinstance(function, Mapping):
            continue
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, Mapping):
            raise ValueError("Hermes tool arguments must be a JSON object")
        calls.append(
            {
                "id": str(item.get("id", "")),
                "name": str(function.get("name", "")),
                "arguments": dict(arguments),
            }
        )
    return calls
