from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from agent_quality_harness.adapters.scenario import ScenarioPlan, validate_scenario_graph
from agent_quality_harness.domain.enums import TargetKind, TargetProtocol
from agent_quality_harness.domain.models import AgentVersion, EvaluationTarget
from agent_quality_harness.target_spec import TargetSpec


def freeze_scenario_metadata(
    session: Session,
    metadata: Mapping[str, Any],
    organization_id: int,
) -> tuple[dict[str, Any], ScenarioPlan, dict[int, TargetSpec]]:
    document = copy.deepcopy(dict(metadata))
    graph = document.get("scenario")
    if not isinstance(graph, Mapping):
        raise ValueError("scenario version metadata requires a scenario object")
    participants = resolve_scenario_participants(session, graph, organization_id)
    plan = validate_scenario_graph(graph, participants)
    document["scenario"] = _canonical_graph(plan)
    document["scenario_sha256"] = plan.sha256
    return document, plan, participants


def resolve_scenario_version(
    session: Session,
    version: AgentVersion,
    organization_id: int,
) -> tuple[ScenarioPlan, dict[int, TargetSpec]]:
    metadata, plan, participants = freeze_scenario_metadata(
        session, version.metadata_json, organization_id
    )
    if metadata["scenario_sha256"] != version.metadata_json.get("scenario_sha256"):
        raise ValueError("scenario version hash is missing or does not match its frozen graph")
    return plan, participants


def resolve_scenario_participants(
    session: Session,
    graph: Mapping[str, Any],
    organization_id: int,
) -> dict[int, TargetSpec]:
    raw_nodes = graph.get("nodes")
    if not isinstance(raw_nodes, list):
        raise ValueError("scenario nodes must be a list")
    version_ids = {
        item.get("target_version_id")
        for item in raw_nodes
        if isinstance(item, Mapping) and isinstance(item.get("target_version_id"), int)
    }
    rows = session.execute(
        select(AgentVersion, EvaluationTarget)
        .join(EvaluationTarget, EvaluationTarget.id == AgentVersion.target_id)
        .where(
            AgentVersion.id.in_(version_ids),
            EvaluationTarget.organization_id == organization_id,
        )
    ).all()
    if len(rows) != len(version_ids):
        raise LookupError("scenario references a missing or cross-organization target version")
    participants: dict[int, TargetSpec] = {}
    for version, target in rows:
        if target.target_kind is TargetKind.SCENARIO or target.protocol is TargetProtocol.SCENARIO:
            raise ValueError("nested scenario targets are not allowed")
        if not target.enabled:
            raise ValueError(f"scenario participant target is disabled: {target.id}")
        participants[version.id] = TargetSpec(
            id=target.id,
            protocol=target.protocol,
            endpoint=target.endpoint,
            auth_ref=target.auth_ref,
            timeout_seconds=target.timeout_seconds,
            capabilities=dict(target.capabilities),
            version_id=version.id,
            version_metadata=dict(version.metadata_json),
            target_kind=target.target_kind,
        )
    return participants


def scenario_snapshot(plan: ScenarioPlan) -> dict[str, Any]:
    return {
        "schema": "aqh.scenario/v1",
        "sha256": plan.sha256,
        "node_count": len(plan.nodes),
        "participant_version_ids": [node.target_version_id for node in plan.nodes],
        "limits": {
            "max_parallel_nodes": plan.max_parallel_nodes,
            "timeout_seconds": plan.timeout_seconds,
        },
    }


def _canonical_graph(plan: ScenarioPlan) -> dict[str, Any]:
    graph = {
        "schema": "aqh.scenario/v1",
        "nodes": [
            {
                "id": node.node_id,
                "target_version_id": node.target_version_id,
                "kind": node.kind,
                "depends_on": list(node.depends_on),
                "static_input": node.static_input,
                "input_map": node.input_map,
                "required": node.required,
                "timeout_seconds": node.timeout_seconds,
            }
            for node in plan.nodes
        ],
        "output": plan.output_ref,
        "limits": {
            "max_parallel_nodes": plan.max_parallel_nodes,
            "timeout_seconds": plan.timeout_seconds,
        },
    }
    actual = hashlib.sha256(
        json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if actual != plan.sha256:
        raise RuntimeError("scenario canonical hash mismatch")
    return graph
