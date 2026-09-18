from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import uuid4

from agent_quality_harness.core.telemetry import get_tracer

from .base import (
    AgentRunEvent,
    AgentRunResult,
    TokenUsage,
    ToolTargetAdapter,
)

SCENARIO_SCHEMA = "aqh.scenario/v1"
_NODE_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_REFERENCE = re.compile(
    r"^\$(?:case\.input(?:\.[A-Za-z0-9_-]+)*|nodes\.[a-z][a-z0-9_-]{0,63}\.output(?:\.[A-Za-z0-9_-]+)*)$"
)
_SENSITIVE_KEY = re.compile(
    r"password|secret|api[_-]?key|authorization|cookie|token|private[_-]?key",
    re.IGNORECASE,
)


class ScenarioValidationError(ValueError):
    pass


class ScenarioCancelled(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScenarioNode:
    node_id: str
    target_version_id: int
    kind: str
    depends_on: tuple[str, ...]
    static_input: dict[str, Any]
    input_map: dict[str, str]
    required: bool
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class ScenarioPlan:
    nodes: tuple[ScenarioNode, ...]
    output_ref: str
    max_parallel_nodes: int
    timeout_seconds: float
    sha256: str


@dataclass(frozen=True, slots=True)
class NodeOutcome:
    node_id: str
    target_version_id: int
    status: str
    invocation_id: str | None
    output: dict[str, Any] | None
    final_action: str | None
    usage: TokenUsage
    model_cost: Decimal | None
    external_tool_cost: Decimal | None
    latency_ms: int
    events: tuple[AgentRunEvent, ...] = ()
    failure_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ScenarioExecution:
    run_id: str
    final_action: str
    output: dict[str, Any]
    events: tuple[AgentRunEvent, ...]
    outcomes: tuple[NodeOutcome, ...]
    usage: TokenUsage
    model_cost: Decimal | None
    external_tool_cost: Decimal | None


def validate_scenario_graph(
    value: Mapping[str, Any],
    participants: Mapping[int, Any],
) -> ScenarioPlan:
    document = copy.deepcopy(dict(value))
    if document.get("schema") != SCENARIO_SCHEMA:
        raise ScenarioValidationError(f"scenario schema must be {SCENARIO_SCHEMA}")
    raw_nodes = document.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes or len(raw_nodes) > 16:
        raise ScenarioValidationError("scenario nodes must contain 1..16 entries")
    limits = document.get("limits", {})
    if not isinstance(limits, Mapping):
        raise ScenarioValidationError("scenario limits must be an object")
    max_parallel = int(limits.get("max_parallel_nodes", 4))
    timeout_seconds = float(limits.get("timeout_seconds", 180))
    if not 1 <= max_parallel <= 4:
        raise ScenarioValidationError("max_parallel_nodes must be 1..4")
    if not 1 <= timeout_seconds <= 180:
        raise ScenarioValidationError("scenario timeout_seconds must be 1..180")
    nodes: list[ScenarioNode] = []
    seen: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise ScenarioValidationError("scenario node must be an object")
        node_id = str(raw.get("id", ""))
        if not _NODE_ID.fullmatch(node_id) or node_id in seen:
            raise ScenarioValidationError(f"invalid or duplicate scenario node id: {node_id}")
        seen.add(node_id)
        version_id = raw.get("target_version_id")
        if not isinstance(version_id, int) or version_id not in participants:
            raise ScenarioValidationError(f"unresolved target version for node {node_id}")
        participant = participants[version_id]
        kind = str(raw.get("kind", ""))
        target_kind = str(getattr(participant, "target_kind", ""))
        if target_kind.endswith(".AGENT"):
            target_kind = "agent"
        elif target_kind.endswith(".TOOL"):
            target_kind = "tool"
        if kind not in {"agent", "tool"} or kind != target_kind:
            raise ScenarioValidationError(f"node kind does not match target for {node_id}")
        depends_on = tuple(str(item) for item in raw.get("depends_on", []))
        static_input = raw.get("static_input", {})
        input_map = raw.get("input_map", {})
        if not isinstance(static_input, Mapping) or not isinstance(input_map, Mapping):
            raise ScenarioValidationError(f"node input must be objects for {node_id}")
        if _contains_sensitive_key(static_input):
            raise ScenarioValidationError(f"sensitive keys are forbidden in node {node_id}")
        normalized_map: dict[str, str] = {}
        for destination, reference in input_map.items():
            destination = str(destination)
            reference = str(reference)
            if not destination or _SENSITIVE_KEY.search(destination):
                raise ScenarioValidationError(f"invalid input destination for node {node_id}")
            if not _REFERENCE.fullmatch(reference):
                raise ScenarioValidationError(f"invalid input reference for node {node_id}")
            normalized_map[destination] = reference
        node_timeout = float(raw.get("timeout_seconds", 60))
        if not 0.1 <= node_timeout <= 60:
            raise ScenarioValidationError(f"node timeout must be 0.1..60 for {node_id}")
        nodes.append(
            ScenarioNode(
                node_id=node_id,
                target_version_id=version_id,
                kind=kind,
                depends_on=depends_on,
                static_input=dict(static_input),
                input_map=normalized_map,
                required=bool(raw.get("required", True)),
                timeout_seconds=node_timeout,
            )
        )
    _validate_dag(nodes)
    output_ref = str(document.get("output", f"$nodes.{nodes[-1].node_id}.output"))
    if not _REFERENCE.fullmatch(output_ref) or not output_ref.startswith("$nodes."):
        raise ScenarioValidationError("scenario output must reference a node output")
    output_node = output_ref.split(".", 3)[1]
    if output_node not in seen:
        raise ScenarioValidationError("scenario output references an unknown node")
    canonical = {
        "schema": SCENARIO_SCHEMA,
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
            for node in nodes
        ],
        "output": output_ref,
        "limits": {
            "max_parallel_nodes": max_parallel,
            "timeout_seconds": timeout_seconds,
        },
    }
    return ScenarioPlan(
        nodes=tuple(nodes),
        output_ref=output_ref,
        max_parallel_nodes=max_parallel,
        timeout_seconds=timeout_seconds,
        sha256=_sha256(canonical),
    )


class ScenarioTargetAdapter:
    def __init__(
        self,
        graph: Mapping[str, Any],
        participants: Mapping[int, Any],
        *,
        timeout_seconds: float = 180,
    ) -> None:
        self.participants = dict(participants)
        self.plan = validate_scenario_graph(graph, participants)
        self.timeout_seconds = min(float(timeout_seconds), self.plan.timeout_seconds)
        self._active: dict[str, asyncio.Event] = {}

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        run_id = str(context.get("scenario_run_id") or uuid4().hex)
        cancelled = asyncio.Event()
        self._active[run_id] = cancelled
        try:
            execution = await asyncio.wait_for(
                execute_scenario(
                    self.plan,
                    self.participants,
                    input_data,
                    context,
                    cancelled,
                ),
                timeout=self.timeout_seconds,
            )
        finally:
            self._active.pop(run_id, None)
        return AgentRunResult(
            run_id=execution.run_id,
            final_action=execution.final_action,
            output=execution.output,
            events=execution.events,
            usage=execution.usage,
            model_cost=execution.model_cost,
            external_tool_cost=execution.external_tool_cost,
        )

    async def cancel(self, run_id: str) -> bool:
        event = self._active.get(run_id)
        if event is None:
            return False
        event.set()
        return True

    async def cancel_active(self) -> None:
        for event in tuple(self._active.values()):
            event.set()

    async def stream(self, input_data, context):
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event


async def execute_scenario(
    plan: ScenarioPlan,
    participants: Mapping[int, Any],
    input_data: Mapping[str, Any],
    context: Mapping[str, Any],
    cancelled: asyncio.Event | None = None,
) -> ScenarioExecution:
    if _contains_sensitive_key(input_data):
        raise ScenarioValidationError("sensitive keys are forbidden in scenario input")
    cancelled = cancelled or asyncio.Event()
    run_id = str(context.get("scenario_run_id") or uuid4().hex)
    outputs: dict[str, dict[str, Any]] = {}
    outcomes: dict[str, NodeOutcome] = {}
    events: list[AgentRunEvent] = [
        AgentRunEvent(
            "scenario.started",
            {"scenario_run_id": run_id, "scenario_sha256": plan.sha256},
        )
    ]
    pending = {node.node_id: node for node in plan.nodes}
    semaphore = asyncio.Semaphore(plan.max_parallel_nodes)
    while pending:
        if cancelled.is_set():
            raise ScenarioCancelled("scenario cancellation requested")
        ready = [
            node
            for node in pending.values()
            if all(dependency in outcomes for dependency in node.depends_on)
        ]
        if not ready:
            raise ScenarioValidationError("scenario has unresolved dependencies")
        batch = ready[: plan.max_parallel_nodes]
        for node in batch:
            events.extend(
                AgentRunEvent(
                    "scenario.handoff",
                    {"from_node": dependency, "to_node": node.node_id},
                )
                for dependency in node.depends_on
            )
        results = await asyncio.gather(
            *(
                _run_node(
                    node,
                    participants[node.target_version_id],
                    input_data,
                    outputs,
                    context,
                    run_id,
                    cancelled,
                    semaphore,
                )
                for node in batch
            ),
            return_exceptions=True,
        )
        required_failure: Exception | None = None
        for node, result in zip(batch, results, strict=True):
            pending.pop(node.node_id)
            if isinstance(result, BaseException):
                outcome = NodeOutcome(
                    node_id=node.node_id,
                    target_version_id=node.target_version_id,
                    status="failed",
                    invocation_id=None,
                    output=None,
                    final_action=None,
                    usage=TokenUsage(),
                    model_cost=None,
                    external_tool_cost=None,
                    latency_ms=0,
                    events=(),
                    failure_reason=type(result).__name__,
                )
                if node.required and isinstance(result, Exception):
                    required_failure = result
            else:
                outcome = result
                if outcome.output is not None:
                    outputs[node.node_id] = outcome.output
            outcomes[node.node_id] = outcome
            events.extend(
                AgentRunEvent(
                    event.event_type,
                    {**dict(event.data), "scenario_node_id": node.node_id},
                    event.event_id,
                    event.occurred_at,
                )
                for event in outcome.events
            )
            events.append(
                AgentRunEvent(
                    f"scenario.node.{outcome.status}",
                    {
                        "node_id": node.node_id,
                        "target_version_id": node.target_version_id,
                        "invocation_id": outcome.invocation_id,
                        "latency_ms": outcome.latency_ms,
                        "failure_type": outcome.failure_reason,
                    },
                )
            )
        if required_failure is not None:
            raise required_failure
    final_output = _resolve_reference(plan.output_ref, input_data, outputs)
    if not isinstance(final_output, Mapping):
        final_output = {"value": final_output}
    ordered = tuple(outcomes[node.node_id] for node in plan.nodes)
    usage = _aggregate_usage(
        [
            outcome.usage
            for node, outcome in zip(plan.nodes, ordered, strict=True)
            if node.kind == "agent"
        ]
    )
    model_cost = _aggregate_decimal([item.model_cost for item in ordered])
    tool_cost = _aggregate_decimal([item.external_tool_cost for item in ordered])
    events.append(
        AgentRunEvent(
            "scenario.completed",
            {
                "scenario_run_id": run_id,
                "scenario_sha256": plan.sha256,
                "node_count": len(ordered),
            },
        )
    )
    return ScenarioExecution(
        run_id=run_id,
        final_action=ordered[-1].final_action or "completed",
        output=dict(final_output),
        events=tuple(events),
        outcomes=ordered,
        usage=usage,
        model_cost=model_cost,
        external_tool_cost=tool_cost,
    )


async def _run_node(
    node: ScenarioNode,
    participant: Any,
    case_input: Mapping[str, Any],
    outputs: Mapping[str, Mapping[str, Any]],
    context: Mapping[str, Any],
    scenario_run_id: str,
    cancelled: asyncio.Event,
    semaphore: asyncio.Semaphore,
) -> NodeOutcome:
    from agent_quality_harness.adapter_factory import create_target_adapter

    input_data = copy.deepcopy(node.static_input)
    for destination, reference in node.input_map.items():
        _assign_path(input_data, destination, _resolve_reference(reference, case_input, outputs))
    adapter = create_target_adapter(participant)
    node_context = {
        **dict(context),
        "scenario_run_id": scenario_run_id,
        "scenario_node_id": node.node_id,
    }
    started = time.perf_counter()
    async with semaphore:
        if cancelled.is_set():
            raise ScenarioCancelled("scenario cancellation requested")
        invocation = asyncio.create_task(
            _invoke_node_with_span(adapter, participant, node, input_data, node_context)
        )
        cancel_wait = asyncio.create_task(cancelled.wait())
        done, _ = await asyncio.wait(
            {invocation, cancel_wait},
            timeout=node.timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if invocation not in done:
            invocation.cancel()
            await asyncio.gather(invocation, return_exceptions=True)
            if cancelled.is_set():
                raise ScenarioCancelled("scenario cancellation requested")
            raise TimeoutError(f"scenario node timed out: {node.node_id}")
        cancel_wait.cancel()
        await asyncio.gather(cancel_wait, return_exceptions=True)
        result = await invocation
    latency_ms = round((time.perf_counter() - started) * 1000)
    return NodeOutcome(
        node_id=node.node_id,
        target_version_id=node.target_version_id,
        status="completed",
        invocation_id=result.run_id,
        output=dict(result.output),
        final_action=result.final_action,
        usage=result.usage,
        model_cost=result.model_cost,
        external_tool_cost=result.external_tool_cost,
        latency_ms=latency_ms,
        events=result.events,
    )


async def _invoke_adapter(adapter: Any, input_data: Mapping[str, Any], context: Mapping[str, Any]):
    if isinstance(adapter, ToolTargetAdapter):
        return await adapter.execute(input_data, context)
    return await adapter.invoke(input_data, context)


async def _invoke_node_with_span(
    adapter: Any,
    participant: Any,
    node: ScenarioNode,
    input_data: Mapping[str, Any],
    context: Mapping[str, Any],
):
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "scenario.node",
        attributes={
            "aqh.scenario.node.id": node.node_id,
            "aqh.scenario.node.kind": node.kind,
            "aqh.target.id": participant.id,
            "aqh.target.version.id": node.target_version_id,
            "aqh.target.protocol": participant.protocol.value,
        },
    ):
        return await _invoke_adapter(adapter, input_data, context)


def _validate_dag(nodes: list[ScenarioNode]) -> None:
    node_ids = {node.node_id for node in nodes}
    for node in nodes:
        unknown = set(node.depends_on) - node_ids
        if unknown or node.node_id in node.depends_on:
            raise ScenarioValidationError(f"invalid dependency for node {node.node_id}")
    remaining = {node.node_id: set(node.depends_on) for node in nodes}
    while remaining:
        ready = {node_id for node_id, dependencies in remaining.items() if not dependencies}
        if not ready:
            raise ScenarioValidationError("scenario graph contains a cycle")
        remaining = {
            node_id: dependencies - ready
            for node_id, dependencies in remaining.items()
            if node_id not in ready
        }


def _resolve_reference(
    reference: str,
    case_input: Mapping[str, Any],
    outputs: Mapping[str, Mapping[str, Any]],
) -> Any:
    parts = reference[1:].split(".")
    if parts[:2] == ["case", "input"]:
        value: Any = case_input
        path = parts[2:]
    else:
        value = outputs.get(parts[1])
        path = parts[3:]
    for part in path:
        if not isinstance(value, Mapping) or part not in value:
            raise ScenarioValidationError(f"scenario reference is missing: {reference}")
        value = value[part]
    return copy.deepcopy(value)


def _assign_path(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = document
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ScenarioValidationError(f"input destination collides at {path}")
        current = child
    current[parts[-1]] = value


def _aggregate_usage(values: list[TokenUsage]) -> TokenUsage:
    names = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
        "embedding_tokens",
        "vision_tokens",
        "judge_tokens",
    )
    totals = {
        name: None
        if any(getattr(item, name) is None for item in values)
        else sum(int(getattr(item, name)) for item in values)
        for name in names
    }
    return TokenUsage(**totals, raw={"source": "scenario.aggregate", "nodes": len(values)})


def _aggregate_decimal(values: list[Decimal | None]) -> Decimal | None:
    if any(value is None for value in values):
        return None
    return sum((value for value in values if value is not None), Decimal("0"))


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _SENSITIVE_KEY.search(str(key)) or _contains_sensitive_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
