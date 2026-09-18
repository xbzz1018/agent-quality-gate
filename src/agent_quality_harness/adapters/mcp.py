import asyncio
import os
from collections.abc import AsyncIterator, Mapping
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp import types as mcp_types
from mcp.client.stdio import get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared.inbound import MCP_NAME_HEADER, encode_header_value

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
        async with self._session() as (session, manifest):
            result, final_action, operation_id = await self._execute_operation(
                session, manifest, operation, input_data
            )

        output = {
            "protocol": "mcp",
            "operation": operation,
            "server": manifest["server"],
            "result": result,
        }
        if operation.startswith("task_"):
            output["task_protocol"] = "mcp-core-2025-11-25-experimental"
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
            operation_id=operation_id,
            final_action=final_action,
            output=output,
            events=tuple(events),
            usage=TokenUsage(raw={"protocol": "mcp", "status": "not_provided"}),
        )

    async def cancel(self, operation_id: str) -> bool:
        if not operation_id:
            return False
        try:
            async with self._session() as (session, manifest):
                self._require_task_capability(manifest, "cancel")
                result = await session.send_request(
                    mcp_types.CancelTaskRequest(
                        params=mcp_types.CancelTaskRequestParams(taskId=operation_id)
                    ),
                    mcp_types.CancelTaskResult,
                    request_read_timeout_seconds=self.timeout_seconds,
                )
            return result.status == "cancelled"
        except Exception:
            return False

    async def _execute_operation(
        self,
        session: ClientSession,
        manifest: Mapping[str, Any],
        operation: str,
        input_data: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str, str | None]:
        if operation == "list_tools":
            result = await session.list_tools()
            return _dump(result), "inspect_tools", None
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
            return payload, "tool_error" if payload.get("is_error") else "tool", None
        if operation == "list_resources":
            result = await session.list_resources()
            return _dump(result), "inspect_resources", None
        if operation == "read_resource":
            result = await session.read_resource(_required_string(input_data, "uri"))
            return _dump(result), "resource", None
        if operation == "list_prompts":
            result = await session.list_prompts()
            return _dump(result), "inspect_prompts", None
        if operation == "get_prompt":
            name = _required_string(input_data, "prompt", fallback="name")
            arguments = input_data.get("arguments", {})
            if not isinstance(arguments, Mapping):
                raise ValueError("MCP prompt arguments must be an object")
            result = await session.get_prompt(
                name,
                {str(key): str(value) for key, value in arguments.items()},
            )
            return _dump(result), "prompt", None
        if operation == "task_call_tool":
            return await self._task_call_tool(session, manifest, input_data)
        if operation == "task_get":
            result = await self._task_get(
                session, manifest, _required_string(input_data, "task_id")
            )
            return _dump(result), f"task_{result.status}", result.task_id
        if operation == "task_result":
            task_id = _required_string(input_data, "task_id")
            result = await self._task_result(session, manifest, task_id)
            payload = _dump(result)
            return payload, "tool_error" if payload.get("is_error") else "tool", task_id
        if operation == "task_list":
            self._require_task_capability(manifest, "list")
            result = await self._send_task_request(
                session,
                mcp_types.ListTasksRequest(),
                mcp_types.ListTasksResult,
            )
            return _dump(result), "inspect_tasks", None
        if operation == "task_cancel":
            task_id = _required_string(input_data, "task_id")
            self._require_task_capability(manifest, "cancel")
            result = await self._send_task_request(
                session,
                mcp_types.CancelTaskRequest(
                    params=mcp_types.CancelTaskRequestParams(taskId=task_id)
                ),
                mcp_types.CancelTaskResult,
            )
            return _dump(result), f"task_{result.status}", task_id
        raise ValueError(f"unsupported MCP operation: {operation}")

    async def _task_call_tool(
        self,
        session: ClientSession,
        manifest: Mapping[str, Any],
        input_data: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str, str]:
        self._require_task_capability(manifest, "tools_call")
        name = _required_string(input_data, "tool", fallback="name")
        arguments = input_data.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise ValueError("MCP tool arguments must be an object")
        ttl = int(input_data.get("ttl_ms", self.capabilities.get("task_ttl_ms", 60_000)))
        created = await self._send_task_request(
            session,
            mcp_types.CallToolRequest(
                params=mcp_types.CallToolRequestParams(
                    name=name,
                    arguments=dict(arguments),
                    task=mcp_types.TaskMetadata(ttl=ttl),
                )
            ),
            mcp_types.CreateTaskResult,
        )
        task_id = created.task.task_id
        if not bool(input_data.get("wait", True)):
            return _dump(created), "task_created", task_id
        deadline = asyncio.get_running_loop().time() + float(
            self.capabilities.get("task_timeout_seconds", self.timeout_seconds)
        )
        current = created.task
        while current.status == "working":
            if asyncio.get_running_loop().time() >= deadline:
                return _dump(current), "task_timeout", task_id
            interval = max(0.05, min(float(current.poll_interval or 250) / 1000, 5.0))
            await asyncio.sleep(interval)
            current = await self._task_get(session, manifest, task_id)
        if current.status == "completed":
            result = await self._task_result(session, manifest, task_id)
            payload = _dump(result)
            return payload, "tool_error" if payload.get("is_error") else "tool", task_id
        return _dump(current), f"task_{current.status}", task_id

    async def _task_get(
        self, session: ClientSession, manifest: Mapping[str, Any], task_id: str
    ) -> mcp_types.GetTaskResult:
        self._require_tasks(manifest)
        return await self._send_task_request(
            session,
            mcp_types.GetTaskRequest(params=mcp_types.GetTaskRequestParams(taskId=task_id)),
            mcp_types.GetTaskResult,
        )

    async def _task_result(
        self, session: ClientSession, manifest: Mapping[str, Any], task_id: str
    ) -> mcp_types.CallToolResult:
        self._require_tasks(manifest)
        return await self._send_task_request(
            session,
            mcp_types.GetTaskPayloadRequest(
                params=mcp_types.GetTaskPayloadRequestParams(taskId=task_id)
            ),
            mcp_types.CallToolResult,
        )

    async def _send_task_request(self, session, request, result_type):
        dispatcher = getattr(session, "_dispatcher", None)
        if dispatcher is None:
            return await session.send_request(
                request,
                result_type,
                request_read_timeout_seconds=self.timeout_seconds,
            )
        data = request.model_dump(by_alias=True, mode="json", exclude_none=True)
        method = data["method"]
        params = data.get("params")
        options: dict[str, Any] = {"timeout": self.timeout_seconds}
        if method == "tools/call" and isinstance(params, Mapping):
            name = params.get("name")
            if isinstance(name, str):
                options["headers"] = {MCP_NAME_HEADER: encode_header_value(name)}
        # MCP 2.0.0 validates 2025-11-25 tools/call as CallToolResult before
        # applying the requested CreateTaskResult type. Tasks stay experimental.
        raw = await dispatcher.send_raw_request(method, params, options)
        return result_type.model_validate(raw, by_name=False)

    @staticmethod
    def _require_tasks(manifest: Mapping[str, Any]) -> Mapping[str, Any]:
        capabilities = manifest.get("capabilities", {})
        tasks = capabilities.get("tasks") if isinstance(capabilities, Mapping) else None
        if not isinstance(tasks, Mapping):
            raise ValueError("MCP server did not negotiate Tasks capability")
        return tasks

    def _require_task_capability(self, manifest: Mapping[str, Any], capability: str) -> None:
        tasks = self._require_tasks(manifest)
        if capability in {"list", "cancel"}:
            supported = isinstance(tasks.get(capability), Mapping)
        else:
            requests = tasks.get("requests", {})
            tools = requests.get("tools", {}) if isinstance(requests, Mapping) else {}
            supported = isinstance(tools, Mapping) and isinstance(tools.get("call"), Mapping)
        if not supported:
            raise ValueError(f"MCP server did not negotiate Tasks {capability} capability")

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


def _required_string(value: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
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
