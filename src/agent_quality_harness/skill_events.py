from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_quality_harness.adapters.base import AgentRunEvent

SKILL_EVENT_SCHEMA = "aqh.skill-event/v1"
SKILL_EVENT_TYPES = {
    "skill.selected",
    "skill.started",
    "skill.completed",
    "skill.failed",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def normalize_skill_event(payload: Mapping[str, Any]) -> AgentRunEvent:
    from agent_quality_harness.adapters.base import AgentRunEvent
    if payload.get("schema") != SKILL_EVENT_SCHEMA:
        raise ValueError(f"Skill event schema must be {SKILL_EVENT_SCHEMA}")
    event_type = str(payload.get("type", ""))
    if event_type not in SKILL_EVENT_TYPES:
        raise ValueError("unsupported Skill event type")
    invocation_id = payload.get("invocation_id")
    skill = payload.get("skill")
    if not isinstance(invocation_id, str) or not invocation_id:
        raise ValueError("Skill event requires invocation_id")
    if not isinstance(skill, Mapping):
        raise ValueError("Skill event requires skill identity")
    name = skill.get("name")
    version = skill.get("version")
    sha256 = skill.get("sha256")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise ValueError("Skill event requires name and version")
    if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
        raise ValueError("Skill event requires a lowercase SHA-256")
    arguments_sha256 = payload.get("arguments_sha256")
    if arguments_sha256 is not None and (
        not isinstance(arguments_sha256, str)
        or _SHA256.fullmatch(arguments_sha256) is None
    ):
        raise ValueError("arguments_sha256 must be a lowercase SHA-256")
    status = payload.get("status")
    if status is not None and status not in {"success", "failed", "cancelled"}:
        raise ValueError("invalid Skill event status")
    reason_code = payload.get("reason_code")
    if reason_code is not None and not isinstance(reason_code, str):
        raise ValueError("reason_code must be a string")
    return AgentRunEvent(
        event_type,
        {
            "schema": SKILL_EVENT_SCHEMA,
            "invocation_id": invocation_id,
            "skill": {"name": name, "version": version, "sha256": sha256},
            "reason_code": None if reason_code is None else reason_code[:100],
            "arguments_sha256": arguments_sha256,
            "status": status,
        },
    )


def skill_event_from_transport(
    event_type: str, data: Mapping[str, Any]
) -> AgentRunEvent | None:
    if event_type not in SKILL_EVENT_TYPES:
        return None
    return normalize_skill_event({"type": event_type, **data})
