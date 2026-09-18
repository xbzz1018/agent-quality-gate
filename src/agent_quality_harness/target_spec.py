from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_quality_harness.domain.enums import TargetKind, TargetProtocol


@dataclass(frozen=True, slots=True)
class TargetSpec:
    id: int
    protocol: TargetProtocol
    endpoint: str
    auth_ref: str | None
    timeout_seconds: int
    capabilities: dict[str, Any]
    version_id: int | None = None
    version_metadata: dict[str, Any] = field(default_factory=dict)
    participants: dict[int, TargetSpec] = field(default_factory=dict)
    target_kind: TargetKind = TargetKind.AGENT
