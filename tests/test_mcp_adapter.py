from contextlib import asynccontextmanager

import httpx2
import pytest
from mcp import types as mcp_types
from mcp.server.mcpserver import MCPServer

from agent_quality_harness.adapter_factory import (
    TargetSpec,
    create_target_adapter,
    validate_contract_profile,
)
from agent_quality_harness.adapters import McpToolTargetAdapter, ToolTargetAdapter
from agent_quality_harness.domain.enums import MeasurementStatus, TargetProtocol
from agent_quality_harness.evaluation.scoring import score_agent_result


def _mcp_fixture() -> tuple[MCPServer, object]:
    server = MCPServer(
        "Agent Quality Harness MCP Fixture",
        version="1.2.3",
        description="Offline MCP contract target",
    )

    @server.tool()
    def add(a: int, b: int) -> dict[str, int]:
        return {"sum": a + b}

    @server.resource("fixture://quality-policy")
    def quality_policy() -> str:
        return "critical safety violations block release"

    @server.prompt()
    def review(name: str) -> str:
        return f"Review {name} against the quality policy"

    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        host="mcp",
    )
    return server, app


async def test_mcp_discovers_and_executes_tool_resource_and_prompt_contracts() -> None:
    _server, app = _mcp_fixture()
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url="http://mcp",
        ) as client:
            adapter = McpToolTargetAdapter("http://mcp/mcp", client=client)
            manifest = await adapter.discover()
            tool_result = await adapter.execute(
                {"operation": "call_tool", "tool": "add", "arguments": {"a": 2, "b": 3}},
                {"case_id": "mcp-tool"},
            )
            resource_result = await adapter.execute(
                {"operation": "read_resource", "uri": "fixture://quality-policy"},
                {"case_id": "mcp-resource"},
            )
            prompt_result = await adapter.execute(
                {"operation": "get_prompt", "prompt": "review", "arguments": {"name": "A2A"}},
                {"case_id": "mcp-prompt"},
            )

    assert manifest["server"]["version"] == "1.2.3"
    assert [item["name"] for item in manifest["tools"]] == ["add"]
    assert [item["uri"] for item in manifest["resources"]] == ["fixture://quality-policy"]
    assert [item["name"] for item in manifest["prompts"]] == ["review"]

    assert tool_result.final_action == "tool"
    assert tool_result.output["result"]["isError"] is False
    assert '"sum": 5' in tool_result.output["result"]["content"][0]["text"]
    assert tool_result.usage.status is MeasurementStatus.UNKNOWN
    tool_score = score_agent_result(
        {
            "final_action": "tool",
            "tools": {
                "required": ["add"],
                "arguments": [{"name": "add", "equals": {"a": 2, "b": 3}}],
            },
        },
        tool_result,
    )
    assert tool_score.passed is True
    assert resource_result.final_action == "resource"
    assert resource_result.output["result"]["contents"][0]["text"].startswith("critical")
    assert prompt_result.final_action == "prompt"
    assert "Review A2A" in prompt_result.output["result"]["messages"][0]["content"]["text"]


class _TaskSession:
    async def send_request(self, request, result_type, **kwargs):
        del kwargs
        if isinstance(request, mcp_types.CallToolRequest):
            return mcp_types.CreateTaskResult(task=_task("task-1", "working", poll_interval=1))
        if isinstance(request, mcp_types.GetTaskRequest):
            return mcp_types.GetTaskResult(**_task_data("task-1", "completed"))
        if isinstance(request, mcp_types.GetTaskPayloadRequest):
            return mcp_types.CallToolResult(
                content=[mcp_types.TextContent(type="text", text="task result")],
                isError=False,
            )
        if isinstance(request, mcp_types.CancelTaskRequest):
            return mcp_types.CancelTaskResult(**_task_data("task-1", "cancelled"))
        if isinstance(request, mcp_types.ListTasksRequest):
            return mcp_types.ListTasksResult(tasks=[_task("task-1", "completed")])
        raise AssertionError(f"unexpected request: {type(request)} / {result_type}")


class _TaskAdapter(McpToolTargetAdapter):
    @asynccontextmanager
    async def _session(self):
        yield (
            _TaskSession(),
            {
                "server": {"name": "task-fixture", "version": "1"},
                "capabilities": {
                    "tasks": {
                        "list": {},
                        "cancel": {},
                        "requests": {"tools": {"call": {}}},
                    }
                },
            },
        )


def _task_data(task_id: str, status: str, *, poll_interval: int | None = None) -> dict:
    return {
        "taskId": task_id,
        "status": status,
        "createdAt": "2026-08-25T00:00:00Z",
        "lastUpdatedAt": "2026-08-25T00:00:01Z",
        "ttl": 60000,
        "pollInterval": poll_interval,
    }


def _task(task_id: str, status: str, *, poll_interval: int | None = None):
    return mcp_types.Task(**_task_data(task_id, status, poll_interval=poll_interval))


async def test_mcp_tasks_execute_poll_result_list_and_cancel() -> None:
    adapter = _TaskAdapter("http://mcp/mcp", timeout_seconds=2)

    result = await adapter.execute(
        {
            "operation": "task_call_tool",
            "tool": "slow_echo",
            "arguments": {"text": "quality"},
        },
        {},
    )
    listed = await adapter.execute({"operation": "task_list"}, {})

    assert result.operation_id == "task-1"
    assert result.final_action == "tool"
    assert result.output["task_protocol"] == "mcp-core-2025-11-25-experimental"
    assert result.output["result"]["content"][0]["text"] == "task result"
    assert listed.final_action == "inspect_tasks"
    assert await adapter.cancel("task-1") is True


async def test_mcp_tasks_fail_closed_without_negotiated_capability() -> None:
    class UnsupportedAdapter(_TaskAdapter):
        @asynccontextmanager
        async def _session(self):
            yield _TaskSession(), {"server": {}, "capabilities": {}}

    adapter = UnsupportedAdapter("http://mcp/mcp")

    with pytest.raises(ValueError, match="did not negotiate Tasks"):
        await adapter.execute(
            {"operation": "task_call_tool", "tool": "slow_echo", "arguments": {}},
            {},
        )


def test_mcp_factory_returns_tool_adapter_not_agent_adapter() -> None:
    spec = TargetSpec(
        id=2,
        protocol=TargetProtocol.MCP,
        endpoint="http://mcp/mcp",
        auth_ref=None,
        timeout_seconds=30,
        capabilities={"contract_profile": "mcp_v1"},
    )
    adapter = create_target_adapter(spec)

    assert validate_contract_profile(TargetProtocol.MCP, {}) == "mcp_v1"
    assert isinstance(adapter, McpToolTargetAdapter)
    assert isinstance(adapter, ToolTargetAdapter)
