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
DEFAULT_CONTROLS: dict[str, Any] = {
    "skill": {
        "enabled": False,
        "require_telemetry": True,
        "minimum_selection_accuracy": 1.0,
        "block_unbound": True,
        "block_lifecycle_errors": True,
        "minimum_coverage_ratio": 1.0,
        "redundant_call_growth_warn": 0.20,
    },
    "evidence": {
        "enabled": False,
        "minimum_coverage": 1.0,
        "block_invalid_refs": True,
        "block_unsupported_claims": True,
    },
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
    skill_rules = skill_passes = telemetry_unknown = 0
    unbound_calls = identity_mismatches = lifecycle_violations = omissions = 0
    redundant_calls = skill_calls = 0
    evidence_rules = evidence_passes = invalid_refs = unsupported_claims = 0
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
            category = rule.get("category")
            rule_id = str(rule.get("rule_id", ""))
            if category == "skill_selection":
                skill_rules += 1
                skill_passes += int(bool(rule.get("passed")))
                if rule_id.startswith("skills.required.") and not rule.get("passed"):
                    omissions += 1
            if category == "skill_telemetry" and rule.get("observed") == "unknown":
                telemetry_unknown += 1
            if category == "skill_identity" and not rule.get("passed"):
                if rule_id.startswith("skills.bound."):
                    unbound_calls += 1
                else:
                    identity_mismatches += 1
            if category == "skill_lifecycle":
                observed = rule.get("observed")
                if isinstance(observed, dict) and observed.get("event") == "skill.selected":
                    skill_calls += 1
                if not rule.get("passed"):
                    lifecycle_violations += 1
            if category == "skill_redundancy":
                redundant_calls += int(rule.get("observed") or 0)
            if category in {"evidence_claim", "evidence_coverage"}:
                evidence_rules += 1
                evidence_passes += int(bool(rule.get("passed")))
            if category == "evidence_invalid_ref" and not rule.get("passed"):
                invalid_refs += len(rule.get("observed") or [])
            if category == "evidence_unsupported_claim" and not rule.get("passed"):
                unsupported_claims += len(rule.get("observed") or [])
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
        "skill_selection_accuracy": skill_passes / skill_rules if skill_rules else None,
        "skill_telemetry_status": "unknown" if telemetry_unknown else "known",
        "skill_telemetry_unknown_count": telemetry_unknown,
        "unbound_skill_calls": unbound_calls,
        "skill_identity_mismatches": identity_mismatches,
        "skill_lifecycle_violations": lifecycle_violations,
        "required_skill_omissions": omissions,
        "redundant_skill_calls": redundant_calls,
        "average_skill_calls": skill_calls / len(rows),
        "evidence_coverage": evidence_passes / evidence_rules if evidence_rules else None,
        "invalid_evidence_ref_count": invalid_refs,
        "unsupported_claim_count": unsupported_claims,
    }


def evaluate_gate(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
    controls: dict[str, Any] | None = None,
) -> GateEvaluation:
    limits = DEFAULT_THRESHOLDS | (thresholds or {})
    reasons: list[dict[str, Any]] = []
    deltas: dict[str, Any] = {}
    effective_controls = _merge_controls(controls)
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
    _skill_gate_rules(baseline, candidate, effective_controls["skill"], reasons, deltas)
    _evidence_gate_rules(candidate, effective_controls["evidence"], reasons)
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


def _merge_controls(controls: dict[str, Any] | None) -> dict[str, Any]:
    controls = controls or {}
    return {
        name: dict(defaults) | (
            dict(controls.get(name, {})) if isinstance(controls.get(name), dict) else {}
        )
        for name, defaults in DEFAULT_CONTROLS.items()
    }


def _skill_gate_rules(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    controls: dict[str, Any],
    reasons: list[dict[str, Any]],
    deltas: dict[str, Any],
) -> None:
    if not controls["enabled"]:
        return
    unknown = int(candidate.get("skill_telemetry_unknown_count") or 0)
    if controls["require_telemetry"] and unknown > 0:
        reasons.append(_reason("skill_telemetry_unknown", "block", 0, unknown))
    unbound = int(candidate.get("unbound_skill_calls") or 0)
    if controls["block_unbound"] and unbound > 0:
        reasons.append(_reason("fabricated_skill", "block", 0, unbound))
    mismatches = int(candidate.get("skill_identity_mismatches") or 0)
    if mismatches > 0:
        reasons.append(_reason("skill_identity_mismatch", "block", 0, mismatches))
    lifecycle = int(candidate.get("skill_lifecycle_violations") or 0)
    if controls["block_lifecycle_errors"] and lifecycle > 0:
        reasons.append(_reason("skill_lifecycle", "block", 0, lifecycle))
    omissions = int(candidate.get("required_skill_omissions") or 0)
    if omissions > 0:
        reasons.append(_reason("required_skill_omission", "block", 0, omissions))
    accuracy = candidate.get("skill_selection_accuracy")
    minimum = float(controls["minimum_selection_accuracy"])
    if accuracy is not None and float(accuracy) < minimum:
        reasons.append(_reason("skill_selection_accuracy", "block", minimum, accuracy))
    coverage = candidate.get("skill_coverage_ratio")
    minimum_coverage = float(controls["minimum_coverage_ratio"])
    if coverage is not None and float(coverage) < minimum_coverage:
        reasons.append(_reason("skill_coverage", "block", minimum_coverage, coverage))
    _growth_rule(
        "average_skill_calls",
        "redundant_skill_call_growth",
        baseline,
        candidate,
        float(controls["redundant_call_growth_warn"]),
        reasons,
        deltas,
    )


def _evidence_gate_rules(
    candidate: dict[str, Any],
    controls: dict[str, Any],
    reasons: list[dict[str, Any]],
) -> None:
    if not controls["enabled"]:
        return
    invalid = int(candidate.get("invalid_evidence_ref_count") or 0)
    if controls["block_invalid_refs"] and invalid > 0:
        reasons.append(_reason("invalid_evidence_ref", "block", 0, invalid))
    unsupported = int(candidate.get("unsupported_claim_count") or 0)
    if controls["block_unsupported_claims"] and unsupported > 0:
        reasons.append(_reason("unsupported_claim", "block", 0, unsupported))
    coverage = candidate.get("evidence_coverage")
    minimum = float(controls["minimum_coverage"])
    if coverage is None:
        reasons.append(_reason("evidence_coverage_unknown", "block", minimum, None))
    elif float(coverage) < minimum:
        reasons.append(_reason("evidence_coverage", "block", minimum, coverage))
