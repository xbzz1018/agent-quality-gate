from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agent_quality_harness.domain.enums import GateDecision

DEFAULT_THRESHOLDS: dict[str, float] = {
    "success_rate_drop_pp_block": 3.0,
    "tool_argument_accuracy_min": 0.95,
    "latency_growth_warn": 0.20,
    "cost_growth_warn": 0.20,
}


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    decision: GateDecision
    reasons: tuple[dict[str, Any], ...]
    metric_deltas: dict[str, Any]


def aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "case_count": 0,
            "success_rate": None,
            "tool_argument_accuracy": None,
            "safety_violations": 0,
            "p95_latency_ms": None,
            "average_model_cost": None,
            "external_tool_cost": None,
        }
    successes = tool_rules = tool_passes = safety_violations = 0
    latencies: list[int] = []
    model_costs: list[Decimal] = []
    external_total = Decimal("0")
    external_known = False
    for row in rows:
        scores = row.get("scores") or {}
        successes += int(bool(scores.get("passed")))
        for rule in scores.get("rules", []):
            if rule.get("category") == "tool_arguments":
                tool_rules += 1
                tool_passes += int(bool(rule.get("passed")))
            if rule.get("category") == "safety" and not rule.get("passed"):
                safety_violations += 1
        if row.get("latency_ms") is not None:
            latencies.append(int(row["latency_ms"]))
        if row.get("model_cost") is not None:
            model_costs.append(Decimal(str(row["model_cost"])))
        if row.get("external_tool_cost") is not None:
            external_total += Decimal(str(row["external_tool_cost"]))
            external_known = True
    return {
        "case_count": len(rows),
        "success_rate": successes / len(rows),
        "tool_argument_accuracy": tool_passes / tool_rules if tool_rules else None,
        "safety_violations": safety_violations,
        "p95_latency_ms": _percentile_95(latencies),
        "average_model_cost": str(sum(model_costs, Decimal("0")) / len(model_costs))
        if len(model_costs) == len(rows)
        else None,
        "external_tool_cost": str(external_total) if external_known else None,
    }


def evaluate_gate(
    baseline: dict[str, Any], candidate: dict[str, Any], thresholds: dict[str, Any] | None = None
) -> GateEvaluation:
    limits = DEFAULT_THRESHOLDS | (thresholds or {})
    reasons: list[dict[str, Any]] = []
    deltas: dict[str, Any] = {}
    violations = int(candidate.get("safety_violations") or 0)
    if violations > 0:
        reasons.append(_reason("critical_safety", "block", 0, violations))
    base_success = baseline.get("success_rate")
    candidate_success = candidate.get("success_rate")
    if base_success is not None and candidate_success is not None:
        drop_pp = (float(base_success) - float(candidate_success)) * 100
        deltas["success_rate_drop_pp"] = drop_pp
        if drop_pp > float(limits["success_rate_drop_pp_block"]):
            reasons.append(
                _reason("success_rate_drop", "block", limits["success_rate_drop_pp_block"], drop_pp)
            )
    tool_accuracy = candidate.get("tool_argument_accuracy")
    if tool_accuracy is not None and float(tool_accuracy) < float(
        limits["tool_argument_accuracy_min"]
    ):
        reasons.append(
            _reason(
                "tool_argument_accuracy",
                "block",
                limits["tool_argument_accuracy_min"],
                tool_accuracy,
            )
        )
    _growth_rule(
        "p95_latency_ms",
        "latency_growth",
        baseline,
        candidate,
        float(limits["latency_growth_warn"]),
        reasons,
        deltas,
    )
    _growth_rule(
        "average_model_cost",
        "cost_growth",
        baseline,
        candidate,
        float(limits["cost_growth_warn"]),
        reasons,
        deltas,
    )
    if any(reason["severity"] == "block" for reason in reasons):
        decision = GateDecision.BLOCK
    elif reasons:
        decision = GateDecision.WARN
    else:
        decision = GateDecision.SHIP
    return GateEvaluation(decision, tuple(reasons), deltas)


def _growth_rule(
    metric: str,
    rule_id: str,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    threshold: float,
    reasons: list[dict[str, Any]],
    deltas: dict[str, Any],
) -> None:
    base = baseline.get(metric)
    current = candidate.get(metric)
    if base in {None, 0, "0"} or current is None:
        deltas[f"{metric}_growth"] = None
        return
    growth = (float(current) - float(base)) / float(base)
    deltas[f"{metric}_growth"] = growth
    if growth > threshold:
        reasons.append(_reason(rule_id, "warn", threshold, growth))


def _reason(rule_id: str, severity: str, threshold: Any, actual: Any) -> dict[str, Any]:
    return {"rule_id": rule_id, "severity": severity, "threshold": threshold, "actual": actual}


def _percentile_95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]
