from dataclasses import dataclass
from typing import Any

from agent_quality_harness.adapters import (
    A2AAgentAdapter,
    AgentAdapter,
    AgriGraphAdapter,
    AgUiAgentAdapter,
    DocumentAutoflowAdapter,
    HttpAgentAdapter,
    McpToolTargetAdapter,
    SseAgentAdapter,
)
from agent_quality_harness.adapters.auth import resolve_auth
from agent_quality_harness.domain.enums import TargetProtocol


@dataclass(frozen=True, slots=True)
class TargetSpec:
    id: int
    protocol: TargetProtocol
    endpoint: str
    auth_ref: str | None
    timeout_seconds: int
    capabilities: dict[str, Any]


def create_target_adapter(target: TargetSpec) -> AgentAdapter | McpToolTargetAdapter:
    if target.protocol is TargetProtocol.MCP:
        return create_tool_adapter(target)
    return create_agent_adapter(target)


def create_tool_adapter(target: TargetSpec) -> McpToolTargetAdapter:
    profile = validate_contract_profile(target.protocol, target.capabilities)
    if profile != "mcp_v1":
        raise ValueError(f"unsupported tool contract profile: {profile}")
    auth = resolve_auth(target.auth_ref)
    if auth.kind != "headers":
        raise ValueError("mcp_v1 currently supports static header authentication")
    return McpToolTargetAdapter(
        target.endpoint,
        timeout_seconds=target.timeout_seconds,
        headers=auth.headers,
        capabilities=target.capabilities,
    )


def create_agent_adapter(target: TargetSpec) -> AgentAdapter:
    profile = validate_contract_profile(target.protocol, target.capabilities)
    auth = resolve_auth(target.auth_ref)
    if profile == "agrigraph_v1":
        return AgriGraphAdapter(
            target.endpoint,
            timeout_seconds=target.timeout_seconds,
            auth=auth,
            capabilities=target.capabilities,
        )
    if profile == "document_autoflow_v1":
        return DocumentAutoflowAdapter(
            target.endpoint,
            timeout_seconds=target.timeout_seconds,
            auth=auth,
            capabilities=target.capabilities,
        )
    if profile == "a2a_v1":
        if auth.kind != "headers":
            raise ValueError("a2a_v1 currently supports static header authentication")
        return A2AAgentAdapter(
            target.endpoint,
            timeout_seconds=target.timeout_seconds,
            headers=auth.headers,
            capabilities=target.capabilities,
        )
    if profile == "ag_ui_v1":
        if auth.kind != "headers":
            raise ValueError("ag_ui_v1 currently supports static header authentication")
        return AgUiAgentAdapter(
            target.endpoint,
            timeout_seconds=target.timeout_seconds,
            headers=auth.headers,
            capabilities=target.capabilities,
        )
    if auth.kind != "headers":
        raise ValueError("standard_v1 only supports static header authentication")
    common = {
        "endpoint": target.endpoint,
        "timeout_seconds": target.timeout_seconds,
        "headers": auth.headers,
    }
    if target.protocol is TargetProtocol.HTTP:
        return HttpAgentAdapter(**common)
    if target.protocol is TargetProtocol.SSE:
        return SseAgentAdapter(**common)
    raise NotImplementedError(f"{target.protocol.value} AgentTargetAdapter is pending")


def validate_contract_profile(protocol: TargetProtocol, capabilities: dict[str, Any]) -> str:
    default_profile = {
        TargetProtocol.AG_UI: "ag_ui_v1",
        TargetProtocol.A2A: "a2a_v1",
        TargetProtocol.MCP: "mcp_v1",
    }.get(protocol, "standard_v1")
    profile = str(capabilities.get("contract_profile", default_profile))
    supported = {
        "standard_v1",
        "agrigraph_v1",
        "document_autoflow_v1",
        "a2a_v1",
        "mcp_v1",
        "ag_ui_v1",
    }
    if profile not in supported:
        raise ValueError(f"unsupported contract profile: {profile}")
    expected_protocols = {
        "standard_v1": {TargetProtocol.HTTP, TargetProtocol.SSE},
        "agrigraph_v1": {TargetProtocol.HTTP},
        "document_autoflow_v1": {TargetProtocol.HTTP},
        "a2a_v1": {TargetProtocol.A2A},
        "mcp_v1": {TargetProtocol.MCP},
        "ag_ui_v1": {TargetProtocol.AG_UI},
    }
    if protocol not in expected_protocols[profile]:
        raise ValueError(f"{profile} is incompatible with the {protocol.value} protocol")
    return profile
