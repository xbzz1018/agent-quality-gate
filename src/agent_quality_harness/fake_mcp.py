from mcp.server.mcpserver import MCPServer

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


app = server.streamable_http_app(
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
    host="0.0.0.0",
)
