from dataclasses import dataclass
from typing import Any

from agent_quality_harness.adapters import (
    AgentAdapter,
    AgriGraphAdapter,
    DocumentAutoflowAdapter,
    HttpAgentAdapter,
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
    profile = str(capabilities.get("contract_profile", "standard_v1"))
    supported = {"standard_v1", "agrigraph_v1", "document_autoflow_v1"}
    if profile not in supported:
        raise ValueError(f"unsupported contract profile: {profile}")
    if profile != "standard_v1" and protocol is not TargetProtocol.HTTP:
        raise ValueError(f"{profile} requires the HTTP target protocol")
    return profile
