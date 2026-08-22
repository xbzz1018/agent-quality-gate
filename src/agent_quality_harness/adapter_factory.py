import json
import os
from dataclasses import dataclass
from typing import Any

from agent_quality_harness.adapters import AgentAdapter, HttpAgentAdapter, SseAgentAdapter
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
    headers = _resolve_headers(target.auth_ref)
    common = {
        "endpoint": target.endpoint,
        "timeout_seconds": target.timeout_seconds,
        "headers": headers,
    }
    if target.protocol is TargetProtocol.HTTP:
        return HttpAgentAdapter(**common)
    if target.protocol is TargetProtocol.SSE:
        return SseAgentAdapter(**common)
    raise NotImplementedError(f"{target.protocol.value} AgentTargetAdapter is pending")


def _resolve_headers(auth_ref: str | None) -> dict[str, str]:
    if auth_ref is None:
        return {}
    raw = os.getenv(auth_ref)
    if raw is None:
        raise RuntimeError(f"auth reference environment variable is not set: {auth_ref}")
    value = json.loads(raw)
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise ValueError("auth reference must contain a JSON object of string headers")
    return value
