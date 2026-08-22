from agent_quality_harness.domain.enums import GateDecision
from agent_quality_harness.gates import evaluate_gate


def _metrics(**overrides):
    return {
        "success_rate": 0.95,
        "tool_argument_accuracy": 1.0,
        "safety_violations": 0,
        "p95_latency_ms": 100,
        "average_model_cost": "1.00",
    } | overrides


def test_gate_boundary_values_do_not_trigger() -> None:
    gate = evaluate_gate(
        _metrics(),
        _metrics(success_rate=0.92, p95_latency_ms=120, average_model_cost="1.20"),
    )

    assert gate.decision is GateDecision.SHIP


def test_gate_blocks_over_three_percentage_point_drop() -> None:
    gate = evaluate_gate(_metrics(), _metrics(success_rate=0.919))

    assert gate.decision is GateDecision.BLOCK
    assert gate.reasons[0]["rule_id"] == "success_rate_drop"


def test_gate_warns_over_twenty_percent_growth() -> None:
    gate = evaluate_gate(_metrics(), _metrics(p95_latency_ms=121))

    assert gate.decision is GateDecision.WARN


def test_gate_ignores_unknown_cost_but_safety_always_blocks() -> None:
    gate = evaluate_gate(
        _metrics(average_model_cost=None),
        _metrics(average_model_cost=None, safety_violations=1, p95_latency_ms=130),
    )

    assert gate.decision is GateDecision.BLOCK
    assert gate.reasons[0]["rule_id"] == "critical_safety"
