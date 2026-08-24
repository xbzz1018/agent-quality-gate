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


def score_agent_result(expected: Mapping[str, Any], result: TargetRunResult) -> ScoreReport:
    rules: list[RuleScore] = []
    _score_final_action(expected, result, rules)
    _score_output(expected, result, rules)
    _score_tools(expected, result.events, rules)
    _score_citations(expected, result, rules)
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
