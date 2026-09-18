from typing import Any

from agent_quality_harness.domain.enums import TargetProtocol


def validate_contract_profile(protocol: TargetProtocol, capabilities: dict[str, Any]) -> str:
    default_profile = {
        TargetProtocol.AG_UI: "ag_ui_v1",
        TargetProtocol.A2A: "a2a_v1",
        TargetProtocol.MCP: "mcp_v1",
        TargetProtocol.SCENARIO: "multi_agent_scenario_v1",
    }.get(protocol, "standard_v1")
    profile = str(capabilities.get("contract_profile", default_profile))
    supported = {
        "standard_v1",
        "agrigraph_v1",
        "document_autoflow_v1",
        "a2a_v1",
        "mcp_v1",
        "ag_ui_v1",
        "hermes_v1",
        "multi_agent_scenario_v1",
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
        "hermes_v1": {TargetProtocol.HTTP},
        "multi_agent_scenario_v1": {TargetProtocol.SCENARIO},
    }
    if protocol not in expected_protocols[profile]:
        raise ValueError(f"{profile} is incompatible with the {protocol.value} protocol")
    return profile
