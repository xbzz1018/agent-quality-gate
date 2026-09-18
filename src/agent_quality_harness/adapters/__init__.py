from importlib import import_module
from typing import Any

from .base import (
    AgentAdapter,
    AgentRunEvent,
    AgentRunResult,
    TargetAdapter,
    TargetRunResult,
    TokenUsage,
    ToolRunResult,
    ToolTargetAdapter,
)

_LAZY_EXPORTS = {
    "A2AAgentAdapter": ".a2a",
    "AgUiAgentAdapter": ".ag_ui",
    "AgriGraphAdapter": ".agrigraph",
    "DocumentAutoflowAdapter": ".document_autoflow",
    "HermesAgentAdapter": ".hermes",
    "HttpAgentAdapter": ".http",
    "McpToolTargetAdapter": ".mcp",
    "ScenarioTargetAdapter": ".scenario",
    "SseAgentAdapter": ".sse",
}

__all__ = [
    "AgentAdapter",
    "AgentRunEvent",
    "AgentRunResult",
    "A2AAgentAdapter",
    "AgUiAgentAdapter",
    "AgriGraphAdapter",
    "DocumentAutoflowAdapter",
    "HermesAgentAdapter",
    "HttpAgentAdapter",
    "McpToolTargetAdapter",
    "ScenarioTargetAdapter",
    "SseAgentAdapter",
    "TargetAdapter",
    "TargetRunResult",
    "TokenUsage",
    "ToolRunResult",
    "ToolTargetAdapter",
]


def __getattr__(name: str) -> Any:
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value
