from enum import StrEnum


class TargetKind(StrEnum):
    AGENT = "agent"
    TOOL = "tool"


class TargetProtocol(StrEnum):
    HTTP = "http"
    SSE = "sse"
    AG_UI = "ag_ui"
    A2A = "a2a"
    MCP = "mcp"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


class VersionRole(StrEnum):
    BASELINE = "baseline"
    CANDIDATE = "candidate"


class GateDecision(StrEnum):
    SHIP = "ship"
    WARN = "warn"
    BLOCK = "block"


class MeasurementStatus(StrEnum):
    KNOWN = "known"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
