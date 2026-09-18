from agent_quality_harness.adapters import (
    A2AAgentAdapter,
    AgentAdapter,
    AgriGraphAdapter,
    AgUiAgentAdapter,
    DocumentAutoflowAdapter,
    HermesAgentAdapter,
    HttpAgentAdapter,
    McpToolTargetAdapter,
    SseAgentAdapter,
)
from agent_quality_harness.adapters.auth import resolve_auth
from agent_quality_harness.contract_profiles import validate_contract_profile
from agent_quality_harness.domain.enums import TargetProtocol
from agent_quality_harness.target_spec import TargetSpec


def create_target_adapter(target: TargetSpec) -> AgentAdapter | McpToolTargetAdapter:
    if target.protocol is TargetProtocol.SCENARIO:
        from agent_quality_harness.adapters.scenario import ScenarioTargetAdapter

        return ScenarioTargetAdapter(
            target.version_metadata.get("scenario", {}),
            target.participants,
            timeout_seconds=target.timeout_seconds,
        )
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
    if profile == "hermes_v1":
        if auth.kind != "headers":
            raise ValueError("hermes_v1 supports static header authentication")
        return HermesAgentAdapter(
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
