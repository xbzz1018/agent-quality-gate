from datetime import UTC, datetime
from types import MethodType
from uuid import uuid4

from mcp import types
from mcp.server import runner as server_runner
from mcp.server.mcpserver import MCPServer
from starlette.responses import JSONResponse

server = MCPServer(
    "Agent Quality Harness MCP Fixture",
    version="1.0.0",
    description="Deterministic MCP ToolTargetAdapter fixture",
)


@server.tool()
def echo(text: str) -> str:
    return text


@server.resource("fixture://quality-policy")
def quality_policy() -> str:
    return "critical safety violations block release"


@server.prompt()
def review(name: str) -> str:
    return f"Review {name} against the quality policy"


def _install_task_fixture(mcp_server: MCPServer) -> None:
    lowlevel = mcp_server._lowlevel_server
    original = lowlevel.get_request_handler("tools/call")
    if original is None:
        raise RuntimeError("MCP tools/call handler is unavailable")
    tasks: dict[str, types.Task] = {}
    results: dict[str, types.CallToolResult] = {}
    serialize_server_result = server_runner._methods.serialize_server_result

    def task_aware_serialize(method, version, result):
        if method == "tools/call" and isinstance(result, dict) and "task" in result:
            return result
        return serialize_server_result(method, version, result)

    # MCP 2.0.0 exposes Tasks client/types but its 2025-11-25 server sieve still
    # fixes tools/call to CallToolResult. Keep the compatibility seam fixture-only.
    server_runner._methods.serialize_server_result = task_aware_serialize

    async def call_tool(context, params):
        if params.task is None:
            return await original.handler(context, params)
        result = await original.handler(context, params)
        if not isinstance(result, types.CallToolResult):
            return result
        task_id = uuid4().hex
        now = datetime.now(UTC).isoformat()
        task = types.Task(
            taskId=task_id,
            status="completed",
            createdAt=now,
            lastUpdatedAt=now,
            ttl=params.task.ttl,
            pollInterval=50,
        )
        tasks[task_id] = task
        results[task_id] = result
        return types.CreateTaskResult(task=task)

    async def get_task(_context, params):
        task = tasks.get(params.task_id)
        if task is None:
            raise ValueError("task not found")
        return types.GetTaskResult.model_validate(task.model_dump(by_alias=True))

    async def get_result(_context, params):
        result = results.get(params.task_id)
        if result is None:
            raise ValueError("task result not found")
        return result

    async def cancel_task(_context, params):
        task = tasks.get(params.task_id)
        if task is None:
            raise ValueError("task not found")
        cancelled = task.model_copy(
            update={
                "status": "cancelled",
                "last_updated_at": datetime.now(UTC).isoformat(),
            }
        )
        tasks[params.task_id] = cancelled
        return types.CancelTaskResult.model_validate(cancelled.model_dump(by_alias=True))

    lowlevel.add_request_handler("tools/call", types.CallToolRequestParams, call_tool)
    lowlevel.add_request_handler("tasks/get", types.GetTaskRequestParams, get_task)
    lowlevel.add_request_handler(
        "tasks/result", types.GetTaskPayloadRequestParams, get_result
    )
    lowlevel.add_request_handler("tasks/cancel", types.CancelTaskRequestParams, cancel_task)
    original_capabilities = lowlevel.get_capabilities

    def get_capabilities(self, *args, **kwargs):
        capabilities = original_capabilities(*args, **kwargs)
        return capabilities.model_copy(
            update={
                "tasks": types.ServerTasksCapability(
                    cancel=types.TasksCancelCapability(),
                    requests=types.ServerTasksRequestsCapability(
                        tools=types.TasksToolsCapability(call=types.TasksCallCapability())
                    ),
                )
            }
        )

    lowlevel.get_capabilities = MethodType(get_capabilities, lowlevel)


_install_task_fixture(server)


app = server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
)


async def health(_request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


app.add_route("/health", health, methods=["GET"])
