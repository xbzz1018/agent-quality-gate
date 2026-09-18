import asyncio
from collections.abc import Mapping

import pytest

from agent_quality_harness.adapter_factory import TargetSpec
from agent_quality_harness.adapters.base import AgentRunResult, TokenUsage, ToolRunResult
from agent_quality_harness.adapters.scenario import (
    ScenarioCancelled,
    ScenarioTargetAdapter,
    ScenarioValidationError,
    validate_scenario_graph,
)
from agent_quality_harness.domain.enums import TargetKind, TargetProtocol
from agent_quality_harness.evaluation.scoring import score_agent_result
from agent_quality_harness.gates import aggregate_metrics, evaluate_gate


class EchoAgent:
    async def invoke(self, input_data: Mapping, context: Mapping) -> AgentRunResult:
        await asyncio.sleep(float(input_data.get("delay", 0)))
        return AgentRunResult(
            run_id=str(context["scenario_node_id"]),
            final_action="answer",
            output={"text": input_data.get("text", ""), "node": context["scenario_node_id"]},
            usage=TokenUsage(input_tokens=2, output_tokens=1),
        )

    async def cancel(self, run_id: str) -> bool:
        return True


class EchoTool:
    async def execute(self, input_data: Mapping, context: Mapping) -> ToolRunResult:
        return ToolRunResult(
            operation_id=str(context["scenario_node_id"]),
            final_action="tool_result",
            output={"text": input_data.get("text", "")},
            usage=TokenUsage(),
        )

    async def cancel(self, operation_id: str) -> bool:
        return True


def _spec(version_id: int, kind: TargetKind) -> TargetSpec:
    protocol = TargetProtocol.HTTP if kind is TargetKind.AGENT else TargetProtocol.MCP
    return TargetSpec(
        id=version_id,
        protocol=protocol,
        endpoint="http://fixture",
        auth_ref=None,
        timeout_seconds=5,
        capabilities={"side_effects": "none"},
        version_id=version_id,
        target_kind=kind,
    )


def _graph() -> dict:
    return {
        "schema": "aqh.scenario/v1",
        "nodes": [
            {
                "id": "research",
                "target_version_id": 1,
                "kind": "agent",
                "depends_on": [],
                "input_map": {"text": "$case.input.question"},
            },
            {
                "id": "review",
                "target_version_id": 2,
                "kind": "agent",
                "depends_on": ["research"],
                "input_map": {"text": "$nodes.research.output.text"},
            },
        ],
        "output": "$nodes.review.output",
        "limits": {"max_parallel_nodes": 2, "timeout_seconds": 5},
    }


def test_scenario_graph_rejects_cycles_and_sensitive_static_values() -> None:
    participants = {1: _spec(1, TargetKind.AGENT), 2: _spec(2, TargetKind.AGENT)}
    cyclic = _graph()
    cyclic["nodes"][0]["depends_on"] = ["review"]
    with pytest.raises(ScenarioValidationError, match="cycle"):
        validate_scenario_graph(cyclic, participants)
    sensitive = _graph()
    sensitive["nodes"][0]["static_input"] = {"api_key": "must-not-persist"}
    with pytest.raises(ScenarioValidationError, match="sensitive"):
        validate_scenario_graph(sensitive, participants)


@pytest.mark.asyncio
async def test_scenario_executes_dependencies_and_scores_handoffs(monkeypatch) -> None:
    participants = {1: _spec(1, TargetKind.AGENT), 2: _spec(2, TargetKind.AGENT)}
    monkeypatch.setattr(
        "agent_quality_harness.adapter_factory.create_target_adapter",
        lambda _target: EchoAgent(),
    )
    result = await ScenarioTargetAdapter(_graph(), participants).invoke(
        {"question": "grounded"}, {"case_id": "case-1"}
    )
    assert result.output == {"text": "grounded", "node": "review"}
    report = score_agent_result(
        {
            "scenario": {
                "required_nodes": ["research", "review"],
                "required_handoffs": [["research", "review"]],
            }
        },
        result,
    )
    assert report.passed
    metrics = aggregate_metrics([{"scores": report.as_dict(), "latency_ms": 10}])
    assert metrics["scenario_node_success_rate"] == 1.0
    assert evaluate_gate(
        metrics,
        metrics,
        controls={"multi_agent": {"enabled": True}},
    ).decision.value == "ship"


@pytest.mark.asyncio
async def test_scenario_cancel_active_stops_running_node(monkeypatch) -> None:
    graph = _graph()
    graph["nodes"] = [
        {
            "id": "research",
            "target_version_id": 1,
            "kind": "agent",
            "depends_on": [],
            "static_input": {"text": "slow", "delay": 5},
        }
    ]
    graph["output"] = "$nodes.research.output"
    participant = _spec(1, TargetKind.AGENT)
    monkeypatch.setattr(
        "agent_quality_harness.adapter_factory.create_target_adapter",
        lambda _target: EchoAgent(),
    )
    adapter = ScenarioTargetAdapter(graph, {1: participant})
    work = asyncio.create_task(adapter.invoke({}, {"case_id": "cancel"}))
    await asyncio.sleep(0.02)
    await adapter.cancel_active()
    with pytest.raises(ScenarioCancelled):
        await work


def test_scenario_graph_rejects_target_kind_mismatch() -> None:
    graph = _graph()
    with pytest.raises(ScenarioValidationError, match="kind"):
        validate_scenario_graph(
            graph,
            {1: _spec(1, TargetKind.TOOL), 2: _spec(2, TargetKind.AGENT)},
        )
