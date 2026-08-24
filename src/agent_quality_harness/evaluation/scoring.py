from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from jsonschema import Draft202012Validator

from agent_quality_harness.adapters.base import AgentRunEvent, TargetRunResult


@dataclass(frozen=True, slots=True)
class RuleScore:
    rule_id: str
    category: str
    expected: Any
    observed: Any
    score: float
    critical: bool
    failure_reason: str | None = None

    @property
    def passed(self) -> bool:
        return self.score == 1.0


@dataclass(frozen=True, slots=True)
class ScoreReport:
    passed: bool
    score: float
    rules: tuple[RuleScore, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": self.score,
            "rules": [asdict(rule) | {"passed": rule.passed} for rule in self.rules],
        }


def score_agent_result(
    expected: Mapping[str, Any],
    result: TargetRunResult,
    bound_skills: Sequence[Mapping[str, Any]] = (),
) -> ScoreReport:
    rules: list[RuleScore] = []
    _score_final_action(expected, result, rules)
    _score_output(expected, result, rules)
    _score_tools(expected, result.events, rules)
    _score_skills(expected, result, bound_skills, rules)
    _score_citations(expected, result, rules)
    _score_evidence(expected, result, rules)
    _score_safety(expected, result, rules)
    _score_business(expected, result, rules)
    score = sum(rule.score for rule in rules) / len(rules) if rules else 1.0
    passed = all(rule.passed for rule in rules if rule.critical)
    return ScoreReport(passed=passed, score=round(score, 6), rules=tuple(rules))


def _add(
    rules: list[RuleScore],
    *,
    rule_id: str,
    category: str,
    expected: Any,
    observed: Any,
    passed: bool,
    critical: bool = True,
    failure_reason: str | None = None,
) -> None:
    rules.append(
        RuleScore(
            rule_id=rule_id,
            category=category,
            expected=expected,
            observed=observed,
            score=1.0 if passed else 0.0,
            critical=critical,
            failure_reason=None if passed else failure_reason,
        )
    )


def _score_final_action(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    value = expected.get("final_action")
    if value is None:
        return
    accepted = [value] if isinstance(value, str) else list(value)
    _add(
        rules,
        rule_id="final_action",
        category="final_action",
        expected=accepted,
        observed=result.final_action,
        passed=result.final_action in accepted,
        failure_reason="final action did not match",
    )


def _score_output(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    spec = expected.get("output")
    if not isinstance(spec, Mapping):
        return
    if "equals" in spec:
        wanted = spec["equals"]
        _add(
            rules,
            rule_id="output.equals",
            category="output",
            expected=wanted,
            observed=dict(result.output),
            passed=result.output == wanted,
            failure_reason="output did not equal the expected value",
        )
    for index, assertion in enumerate(spec.get("assertions", [])):
        if not isinstance(assertion, Mapping):
            continue
        path = str(assertion.get("path", ""))
        observed = _lookup(result.output, path)
        operator = str(assertion.get("operator", "equals"))
        wanted = assertion.get("value")
        _add(
            rules,
            rule_id=str(assertion.get("id", f"output.assertion.{index}")),
            category="output",
            expected={"path": path, "operator": operator, "value": wanted},
            observed=observed,
            passed=_compare(observed, operator, wanted),
            critical=bool(assertion.get("critical", True)),
            failure_reason=f"output assertion failed at {path or '<root>'}",
        )
    schema = spec.get("json_schema")
    if isinstance(schema, Mapping):
        errors = sorted(
            Draft202012Validator(schema).iter_errors(dict(result.output)),
            key=lambda item: list(item.path),
        )
        _add(
            rules,
            rule_id="output.json_schema",
            category="schema",
            expected=dict(schema),
            observed=[error.message for error in errors],
            passed=not errors,
            failure_reason=errors[0].message if errors else None,
        )


def _tool_calls(events: Sequence[AgentRunEvent]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for event in events:
        if event.event_type not in {"tool", "tool_call", "tool.completed"}:
            continue
        name = event.data.get("name", event.data.get("tool_name"))
        if name is not None:
            calls.append(
                {
                    "name": str(name),
                    "arguments": event.data.get("arguments", event.data.get("args", {})),
                }
            )
    return calls


def _score_tools(
    expected: Mapping[str, Any],
    events: Sequence[AgentRunEvent],
    rules: list[RuleScore],
) -> None:
    spec = expected.get("tools")
    if not isinstance(spec, Mapping):
        return
    calls = _tool_calls(events)
    names = [call["name"] for call in calls]
    for name in spec.get("required", []):
        _add(
            rules,
            rule_id=f"tools.required.{name}",
            category="tool_required",
            expected=name,
            observed=names,
            passed=name in names,
            failure_reason=f"required tool was not called: {name}",
        )
    for name in spec.get("forbidden", []):
        _add(
            rules,
            rule_id=f"tools.forbidden.{name}",
            category="tool_forbidden",
            expected=name,
            observed=names,
            passed=name not in names,
            failure_reason=f"forbidden tool was called: {name}",
        )
    if "order" in spec:
        wanted_order = list(spec["order"])
        observed_order = [name for name in names if name in wanted_order]
        _add(
            rules,
            rule_id="tools.order",
            category="tool_order",
            expected=wanted_order,
            observed=observed_order,
            passed=observed_order == wanted_order,
            failure_reason="tool order did not match",
        )
    for index, assertion in enumerate(spec.get("arguments", [])):
        if not isinstance(assertion, Mapping):
            continue
        name = str(assertion.get("name", ""))
        matching = next((call for call in calls if call["name"] == name), None)
        wanted = assertion.get("equals", {})
        observed = None if matching is None else matching["arguments"]
        _add(
            rules,
            rule_id=str(assertion.get("id", f"tools.arguments.{index}")),
            category="tool_arguments",
            expected={"name": name, "equals": wanted},
            observed=observed,
            passed=matching is not None and observed == wanted,
            failure_reason=f"tool arguments did not match for {name}",
        )


def _score_citations(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    spec = expected.get("citations")
    if not isinstance(spec, Mapping):
        return
    citations = result.output.get("citations", [])
    count = (
        len(citations) if isinstance(citations, Sequence) and not isinstance(citations, str) else 0
    )
    minimum = int(spec.get("min_count", 1 if spec.get("required") else 0))
    _add(
        rules,
        rule_id="citations.min_count",
        category="citations",
        expected=minimum,
        observed=count,
        passed=count >= minimum,
        critical=bool(spec.get("critical", True)),
        failure_reason="not enough citations",
    )


def _score_skills(
    expected: Mapping[str, Any],
    result: TargetRunResult,
    bound_skills: Sequence[Mapping[str, Any]],
    rules: list[RuleScore],
) -> None:
    spec = expected.get("skills")
    spec = spec if isinstance(spec, Mapping) else {}
    events = [event for event in result.events if event.event_type.startswith("skill.")]
    telemetry_required = bool(spec.get("telemetry_required", False))
    _add(
        rules,
        rule_id="skills.telemetry",
        category="skill_telemetry",
        expected="known" if telemetry_required else "known_or_unknown",
        observed="known" if events else "unknown",
        passed=bool(events) or not telemetry_required,
        critical=telemetry_required,
        failure_reason="required Skill telemetry is UNKNOWN",
    )
    if not events:
        return
    bound = {
        str(item.get("package_name", item.get("name", ""))): item
        for item in bound_skills
    }
    lifecycle: dict[str, str] = {}
    selected_names: list[str] = []
    completed_names: list[str] = []
    argument_hashes: dict[str, list[str | None]] = {}
    for index, event in enumerate(events):
        identity = event.data.get("skill")
        identity = identity if isinstance(identity, Mapping) else {}
        name = str(identity.get("name", ""))
        invocation_id = str(event.data.get("invocation_id", ""))
        bound_skill = bound.get(name)
        _add(
            rules,
            rule_id=f"skills.bound.{index}",
            category="skill_identity",
            expected=sorted(bound),
            observed=name,
            passed=bound_skill is not None,
            failure_reason="fabricated_skill: Skill is not bound to this AgentVersion",
        )
        identity_matches = bound_skill is not None and (
            str(bound_skill.get("version")) == str(identity.get("version"))
            and str(bound_skill.get("sha256")) == str(identity.get("sha256"))
        )
        _add(
            rules,
            rule_id=f"skills.identity.{index}",
            category="skill_identity",
            expected=None
            if bound_skill is None
            else {
                "version": bound_skill.get("version"),
                "sha256": bound_skill.get("sha256"),
            },
            observed={"version": identity.get("version"), "sha256": identity.get("sha256")},
            passed=identity_matches,
            failure_reason="skill_identity_mismatch",
        )
        previous = lifecycle.get(invocation_id)
        valid_transition = False
        if event.event_type == "skill.selected":
            valid_transition = previous is None
            lifecycle[invocation_id] = "selected"
            selected_names.append(name)
            argument_hashes.setdefault(name, []).append(event.data.get("arguments_sha256"))
        elif event.event_type == "skill.started":
            valid_transition = previous == "selected"
            lifecycle[invocation_id] = "started"
        elif event.event_type in {"skill.completed", "skill.failed"}:
            valid_transition = previous == "started"
            lifecycle[invocation_id] = "terminal"
            completed_names.append(name)
        _add(
            rules,
            rule_id=f"skills.lifecycle.{index}",
            category="skill_lifecycle",
            expected="selected -> started -> completed|failed",
            observed={"previous": previous, "event": event.event_type},
            passed=valid_transition,
            failure_reason="Skill lifecycle transition is invalid",
        )
    unfinished = sorted(key for key, value in lifecycle.items() if value != "terminal")
    _add(
        rules,
        rule_id="skills.lifecycle.complete",
        category="skill_lifecycle",
        expected=[],
        observed=unfinished,
        passed=not unfinished,
        failure_reason="Skill lifecycle did not reach a terminal event",
    )
    required = list(spec.get("required", []))
    allowed = set(spec.get("allowed", []))
    forbidden = set(spec.get("forbidden", []))
    for name in required:
        _add(
            rules,
            rule_id=f"skills.required.{name}",
            category="skill_selection",
            expected=name,
            observed=selected_names,
            passed=name in selected_names,
            failure_reason=f"required Skill was not selected: {name}",
        )
    if allowed:
        unexpected = sorted(set(selected_names) - allowed)
        _add(
            rules,
            rule_id="skills.allowed",
            category="skill_selection",
            expected=sorted(allowed),
            observed=unexpected,
            passed=not unexpected,
            failure_reason="a Skill outside the case allow-list was selected",
        )
    for name in forbidden:
        _add(
            rules,
            rule_id=f"skills.forbidden.{name}",
            category="skill_selection",
            expected=name,
            observed=selected_names,
            passed=name not in selected_names,
            failure_reason=f"forbidden Skill was selected: {name}",
        )
    if spec.get("order") is not None:
        wanted = list(spec["order"])
        observed = [name for name in selected_names if name in wanted]
        _add(
            rules,
            rule_id="skills.order",
            category="skill_selection",
            expected=wanted,
            observed=observed,
            passed=observed == wanted,
            failure_reason="Skill selection order did not match",
        )
    max_calls = spec.get("max_calls")
    if max_calls is not None:
        _add(
            rules,
            rule_id="skills.max_calls",
            category="skill_selection",
            expected=int(max_calls),
            observed=len(selected_names),
            passed=len(selected_names) <= int(max_calls),
            failure_reason="Skill call count exceeded max_calls",
        )
    repeated = len(selected_names) - len(set(selected_names))
    allow_repeats = bool(spec.get("allow_repeats", False))
    _add(
        rules,
        rule_id="skills.redundant_calls",
        category="skill_redundancy",
        expected=0 if not allow_repeats else "allowed",
        observed=repeated,
        passed=allow_repeats or repeated == 0,
        critical=False,
        failure_reason="redundant Skill calls were observed",
    )
    for name, wanted_hash in dict(spec.get("arguments_sha256", {})).items():
        observed_hashes = argument_hashes.get(name, [])
        _add(
            rules,
            rule_id=f"skills.arguments_sha256.{name}",
            category="skill_selection",
            expected=wanted_hash,
            observed=observed_hashes,
            passed=wanted_hash in observed_hashes,
            failure_reason=f"Skill argument hash did not match for {name}",
        )
    claimed = result.output.get("skills_used")
    if claimed is not None:
        claimed_names = list(claimed) if isinstance(claimed, list) else []
        _add(
            rules,
            rule_id="skills.output_claim",
            category="skill_identity",
            expected=completed_names,
            observed=claimed_names,
            passed=claimed_names == completed_names,
            failure_reason="output skills_used does not match Skill telemetry",
        )


def _score_evidence(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    spec = expected.get("evidence")
    if not isinstance(spec, Mapping):
        return
    claims_value = result.output.get("claims", [])
    claims = claims_value if isinstance(claims_value, list) else []
    allowed_refs = set(str(item) for item in spec.get("allowed_refs", []))
    claim_map: dict[str, set[str]] = {}
    invalid_refs: list[str] = []
    unsupported_claims: list[str] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            continue
        claim_id = str(claim.get("id", ""))
        refs = {_evidence_ref_id(item) for item in claim.get("evidence_refs", [])}
        refs.discard(None)
        normalized_refs = {str(item) for item in refs}
        claim_map[claim_id] = normalized_refs
        invalid_refs.extend(sorted(normalized_refs - allowed_refs))
        if not normalized_refs:
            unsupported_claims.append(claim_id)
    _add(
        rules,
        rule_id="evidence.invalid_refs",
        category="evidence_invalid_ref",
        expected=[],
        observed=invalid_refs,
        passed=not invalid_refs,
        failure_reason="unknown or fabricated EvidenceRef was used",
    )
    _add(
        rules,
        rule_id="evidence.unsupported_claims",
        category="evidence_unsupported_claim",
        expected=[],
        observed=unsupported_claims,
        passed=not unsupported_claims,
        failure_reason="one or more Claims have no EvidenceRef",
    )
    required_claims = list(spec.get("required_claims", []))
    covered = 0
    for item in required_claims:
        if not isinstance(item, Mapping):
            continue
        claim_id = str(item.get("id", ""))
        allowed_for_claim = set(str(ref) for ref in item.get("allowed_refs", []))
        observed = claim_map.get(claim_id)
        valid = observed is not None and bool(observed) and observed <= allowed_for_claim
        covered += int(valid)
        _add(
            rules,
            rule_id=f"evidence.claim.{claim_id}",
            category="evidence_claim",
            expected={"claim_id": claim_id, "allowed_refs": sorted(allowed_for_claim)},
            observed=None if observed is None else sorted(observed),
            passed=valid,
            failure_reason="required Claim is missing or mapped to disallowed evidence",
        )
    coverage = covered / len(required_claims) if required_claims else (1.0 if claims else 0.0)
    minimum = float(spec.get("minimum_coverage", 1.0))
    required = bool(spec.get("required", False))
    _add(
        rules,
        rule_id="evidence.coverage",
        category="evidence_coverage",
        expected=minimum,
        observed=coverage,
        passed=coverage >= minimum and (bool(claims) or not required),
        critical=required,
        failure_reason="evidence coverage is below the required minimum",
    )


def _evidence_ref_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        identifier = value.get("id", value.get("ref_id"))
        return None if identifier is None else str(identifier)
    return None


def _score_safety(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    spec = expected.get("safety")
    if not isinstance(spec, Mapping):
        return
    searchable = json.dumps(result.output, ensure_ascii=False, sort_keys=True)
    for index, pattern in enumerate(spec.get("forbidden_patterns", [])):
        matched = re.search(str(pattern), searchable, re.IGNORECASE) is not None
        _add(
            rules,
            rule_id=f"safety.forbidden_pattern.{index}",
            category="safety",
            expected={"absent": pattern},
            observed={"matched": matched},
            passed=not matched,
            critical=True,
            failure_reason="forbidden safety pattern was present",
        )


def _score_business(
    expected: Mapping[str, Any], result: TargetRunResult, rules: list[RuleScore]
) -> None:
    for index, assertion in enumerate(expected.get("business", [])):
        if not isinstance(assertion, Mapping):
            continue
        path = str(assertion.get("path", ""))
        observed = _lookup(result.output, path)
        operator = str(assertion.get("operator", "equals"))
        wanted = assertion.get("value")
        _add(
            rules,
            rule_id=str(assertion.get("id", f"business.{index}")),
            category="business",
            expected={"path": path, "operator": operator, "value": wanted},
            observed=observed,
            passed=_compare(observed, operator, wanted),
            critical=bool(assertion.get("critical", True)),
            failure_reason=f"business assertion failed at {path or '<root>'}",
        )


def _lookup(value: Any, path: str) -> Any:
    current = value
    if not path:
        return current
    for part in path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        elif isinstance(current, Sequence) and not isinstance(current, str) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def _compare(observed: Any, operator: str, expected: Any) -> bool:
    if operator == "equals":
        return observed == expected
    if operator == "not_equals":
        return observed != expected
    if operator == "contains":
        return expected in observed if observed is not None else False
    if operator == "exists":
        return observed is not None
    if operator == "gte":
        return observed is not None and observed >= expected
    if operator == "lte":
        return observed is not None and observed <= expected
    if operator == "regex":
        return isinstance(observed, str) and re.search(str(expected), observed) is not None
    raise ValueError(f"unsupported assertion operator: {operator}")
