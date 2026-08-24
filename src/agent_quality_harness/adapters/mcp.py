import os
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

from .base import AgentRunEvent, TokenUsage, ToolRunResult


class McpToolTargetAdapter:
    """MCP ToolTargetAdapter with distinct Tool/Resource/Prompt operations."""

    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30,
        headers: Mapping[str, str] | None = None,
        capabilities: Mapping[str, Any] | None = None,
        client: httpx2.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})
        self.capabilities = dict(capabilities or {})
        self._client = client

    async def discover(self) -> dict[str, Any]:
        async with self._session() as (session, manifest):
            tools = await session.list_tools()
            resources = await session.list_resources()
            prompts = await session.list_prompts()
        return {
            **manifest,
            "tools": [_dump(item) for item in tools.tools],
            "resources": [_dump(item) for item in resources.resources],
            "prompts": [_dump(item) for item in prompts.prompts],
        }

    async def execute(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> ToolRunResult:
        del context
        operation = str(input_data.get("operation") or "call_tool")
        if operation.startswith("task"):
            raise NotImplementedError("MCP Tasks are an experimental pending enhancement")

        async with self._session() as (session, manifest):
            result, final_action = await self._execute_operation(session, operation, input_data)

        output = {
            "protocol": "mcp",
            "operation": operation,
            "server": manifest["server"],
            "result": result,
        }
        events = [
            AgentRunEvent("mcp.initialized", manifest),
            AgentRunEvent(
                "mcp.operation.completed",
                {"operation": operation, "final_action": final_action},
            ),
        ]
        if operation == "call_tool":
            events.append(
                AgentRunEvent(
                    "tool.completed",
                    {
                        "name": _required_string(input_data, "tool", fallback="name"),
                        "arguments": dict(input_data.get("arguments", {})),
                        "is_error": final_action == "tool_error",
                    },
                )
            )
        return ToolRunResult(
            operation_id=None,
            final_action=final_action,
            output=output,
            events=tuple(events),
            usage=TokenUsage(raw={"protocol": "mcp", "status": "not_provided"}),
        )

    async def cancel(self, operation_id: str) -> bool:
        del operation_id
        # MCP requests are cancelled while their ClientSession is live. There is no
        # portable server-side operation id outside the optional MCP Tasks extension.
        return False

    async def _execute_operation(
        self,
        session: ClientSession,
        operation: str,
        input_data: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        if operation == "list_tools":
            result = await session.list_tools()
            return _dump(result), "inspect_tools"
        if operation == "call_tool":
            name = _required_string(input_data, "tool", fallback="name")
            arguments = input_data.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise ValueError("MCP tool arguments must be an object")
            result = await session.call_tool(
                name,
                dict(arguments),
                read_timeout_seconds=self.timeout_seconds,
            )
            payload = _dump(result)
            return payload, "tool_error" if payload.get("is_error") else "tool"
        if operation == "list_resources":
            result = await session.list_resources()
            return _dump(result), "inspect_resources"
        if operation == "read_resource":
            result = await session.read_resource(_required_string(input_data, "uri"))
            return _dump(result), "resource"
        if operation == "list_prompts":
            result = await session.list_prompts()
            return _dump(result), "inspect_prompts"
        if operation == "get_prompt":
            name = _required_string(input_data, "prompt", fallback="name")
            arguments = input_data.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise ValueError("MCP prompt arguments must be an object")
            result = await session.get_prompt(
                name,
                {str(key): str(value) for key, value in arguments.items()},
            )
            return _dump(result), "prompt"
        raise ValueError(f"unsupported MCP operation: {operation}")

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[tuple[ClientSession, dict[str, Any]]]:
        async with AsyncExitStack() as stack:
            if self.endpoint.startswith(("http://", "https://")):
                owned = self._client is None
                http_client = self._client or httpx2.AsyncClient(
                    headers=self.headers,
                    timeout=self.timeout_seconds,
                )
                if self._client is not None:
                    http_client.headers.update(self.headers)
                if owned:
                    await stack.enter_async_context(http_client)
                read_stream, write_stream = await stack.enter_async_context(
                    streamable_http_client(self.endpoint, http_client=http_client)
                )
                transport = "streamable_http"
            elif self.endpoint.startswith("stdio://"):
                if self.headers:
                    raise ValueError("stdio MCP targets do not support HTTP headers")
                parameters = self._stdio_parameters()
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(parameters)
                )
                transport = "stdio"
            else:
                raise ValueError("MCP endpoint must use http(s):// or stdio://")

            session = await stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=self.timeout_seconds,
                )
            )
            initialized = await session.initialize()
            manifest = {
                "protocol_version": initialized.protocol_version,
                "transport": transport,
                "server": _dump(initialized.server_info),
                "capabilities": _dump(initialized.capabilities),
            }
            yield session, manifest

    def _stdio_parameters(self) -> StdioServerParameters:
        command = str(self.capabilities.get("command") or "").strip()
        if not command:
            raise ValueError("stdio MCP target requires capabilities.command")
        raw_args = self.capabilities.get("args", [])
        if not isinstance(raw_args, list) or not all(isinstance(item, str) for item in raw_args):
            raise ValueError("stdio MCP capabilities.args must be a string array")
        env = get_default_environment()
        raw_env_refs = self.capabilities.get("env_refs", {})
        if not isinstance(raw_env_refs, Mapping):
            raise ValueError("stdio MCP capabilities.env_refs must be an object")
        for target_name, source_name in raw_env_refs.items():
            source = str(source_name)
            if source not in os.environ:
                raise ValueError(f"MCP environment reference is not set: {source}")
            env[str(target_name)] = os.environ[source]
        return StdioServerParameters(
            command=command,
            args=list(raw_args),
            env=env,
            cwd=self.capabilities.get("cwd"),
        )


def _required_string(
    value: Mapping[str, Any], key: str, *, fallback: str | None = None
) -> str:
    raw = value.get(key)
    if raw is None and fallback:
        raw = value.get(fallback)
    result = str(raw or "").strip()
    if not result:
        raise ValueError(f"MCP operation requires {key}")
    return result


def _dump(value: Any) -> dict[str, Any]:
    dumped = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    if not isinstance(dumped, dict):
        raise ValueError("MCP SDK result must serialize to an object")
    return dumped
