import json

from agent_quality_harness.adapters.a2a import _skill_events_from_parts
from agent_quality_harness.adapters.base import AgentRunResult
from agent_quality_harness.adapters.mapping import run_result_from_payload
from agent_quality_harness.adapters.sse import _event as sse_event
from agent_quality_harness.api.schemas import ExpectedRules
from agent_quality_harness.domain.enums import GateDecision
from agent_quality_harness.evaluation.scoring import score_agent_result
from agent_quality_harness.gates import aggregate_metrics, evaluate_gate
from agent_quality_harness.skill_events import normalize_skill_event

SHA_A = "a" * 64
SHA_B = "b" * 64


def _identity(name: str, version: str, sha256: str) -> dict:
    return {"name": name, "version": version, "sha256": sha256}


def _event(event_type: str, invocation: str, identity: dict, **extra):
    return normalize_skill_event(
        {
            "schema": "aqh.skill-event/v1",
            "type": event_type,
            "invocation_id": invocation,
            "skill": identity,
            **extra,
        }
    )


def _result(events=(), output=None) -> AgentRunResult:
    return AgentRunResult(
        run_id="run-1",
        final_action="answer",
        output=output or {"text": "ok"},
        events=tuple(events),
    )


def _bound() -> list[dict]:
    return [
        {"package_name": "lookup", "version": "1.0.0", "sha256": SHA_A},
        {"package_name": "summarize", "version": "2.0.0", "sha256": SHA_B},
    ]


def test_skill_event_normalization_drops_unknown_and_raw_fields() -> None:
    event = normalize_skill_event(
        {
            "schema": "aqh.skill-event/v1",
            "type": "skill.selected",
            "invocation_id": "invoke-1",
            "skill": _identity("lookup", "1.0.0", SHA_A),
            "reason_code": "intent_match",
            "arguments_sha256": SHA_B,
            "raw_arguments": {"secret": "must-not-persist"},
            "reasoning": "must-not-persist",
        }
    )

    assert event.data == {
        "schema": "aqh.skill-event/v1",
        "invocation_id": "invoke-1",
        "skill": _identity("lookup", "1.0.0", SHA_A),
        "reason_code": "intent_match",
        "arguments_sha256": SHA_B,
        "status": None,
    }
    assert "must-not-persist" not in str(event)


def test_http_sse_and_a2a_normalize_the_same_skill_event() -> None:
    payload = {
        "schema": "aqh.skill-event/v1",
        "type": "skill.selected",
        "invocation_id": "cross-protocol",
        "skill": _identity("lookup", "1.0.0", SHA_A),
    }
    http_result = run_result_from_payload(
        {
            "output": {},
            "events": [{"event_type": "skill.selected", "data": payload}],
        }
    )
    sse_result = sse_event(
        "skill.selected",
        "event-1",
        [json.dumps(payload)],
    )
    a2a_result = _skill_events_from_parts(
        [{"data": {"aqh_skill_event": payload}}]
    )[0]

    assert http_result.events[0].data == sse_result.data == a2a_result.data


def test_multi_skill_selection_lifecycle_and_claims_pass() -> None:
    events = [
        _event("skill.selected", "one", _identity("lookup", "1.0.0", SHA_A)),
        _event("skill.started", "one", _identity("lookup", "1.0.0", SHA_A)),
        _event(
            "skill.completed",
            "one",
            _identity("lookup", "1.0.0", SHA_A),
            status="success",
        ),
        _event("skill.selected", "two", _identity("summarize", "2.0.0", SHA_B)),
        _event("skill.started", "two", _identity("summarize", "2.0.0", SHA_B)),
        _event(
            "skill.completed",
            "two",
            _identity("summarize", "2.0.0", SHA_B),
            status="success",
        ),
    ]
    expected = ExpectedRules.model_validate(
        {
            "skills": {
                "required": ["lookup", "summarize"],
                "allowed": ["lookup", "summarize"],
                "order": ["lookup", "summarize"],
                "max_calls": 2,
                "telemetry_required": True,
            }
        }
    ).model_dump(mode="json", exclude_none=True)

    report = score_agent_result(
        expected,
        _result(events, {"text": "ok", "skills_used": ["lookup", "summarize"]}),
        _bound(),
    )

    assert report.passed is True
    assert all(rule.passed for rule in report.rules if rule.critical)


def test_fabricated_identity_lifecycle_and_missing_telemetry_fail() -> None:
    fabricated = _identity("invented", "9.9.9", "c" * 64)
    report = score_agent_result(
        {"skills": {"required": ["lookup"], "telemetry_required": True}},
        _result([_event("skill.completed", "bad", fabricated, status="success")]),
        _bound(),
    )
    failures = {rule.failure_reason for rule in report.rules if not rule.passed}
    assert report.passed is False
    assert "fabricated_skill: Skill is not bound to this AgentVersion" in failures
    assert "skill_identity_mismatch" in failures
    assert "Skill lifecycle transition is invalid" in failures

    missing = score_agent_result(
        {"skills": {"telemetry_required": True}}, _result(), _bound()
    )
    assert missing.passed is False
    assert next(rule for rule in missing.rules if rule.rule_id == "skills.telemetry").observed == (
        "unknown"
    )


def test_evidence_grounding_detects_unknown_refs_and_unsupported_claims() -> None:
    expected = {
        "evidence": {
            "required": True,
            "allowed_refs": ["doc-1", "doc-2"],
            "required_claims": [{"id": "claim-1", "allowed_refs": ["doc-1"]}],
            "minimum_coverage": 1.0,
        }
    }
    passed = score_agent_result(
        expected,
        _result(output={"claims": [{"id": "claim-1", "evidence_refs": ["doc-1"]}]}),
    )
    assert passed.passed is True

    failed = score_agent_result(
        expected,
        _result(
            output={
                "claims": [
                    {"id": "claim-1", "evidence_refs": ["invented-doc"]},
                    {"id": "claim-2", "evidence_refs": []},
                ]
            }
        ),
    )
    assert failed.passed is False
    assert next(
        rule for rule in failed.rules if rule.rule_id == "evidence.invalid_refs"
    ).observed == ["invented-doc"]


def test_skill_and_evidence_gate_fail_closed_only_when_enabled() -> None:
    baseline = {
        "success_rate": 1.0,
        "tool_argument_accuracy": None,
        "safety_violations": 0,
        "p95_latency_ms": 10,
        "average_model_cost": None,
        "average_skill_calls": 1.0,
    }
    candidate = baseline | {
        "skill_telemetry_unknown_count": 1,
        "unbound_skill_calls": 1,
        "skill_identity_mismatches": 0,
        "skill_lifecycle_violations": 0,
        "required_skill_omissions": 0,
        "skill_selection_accuracy": None,
        "skill_coverage_ratio": 0.5,
        "invalid_evidence_ref_count": 1,
        "unsupported_claim_count": 1,
        "evidence_coverage": None,
    }
    assert evaluate_gate(baseline, candidate).decision is GateDecision.SHIP

    gate = evaluate_gate(
        baseline,
        candidate,
        controls={"skill": {"enabled": True}, "evidence": {"enabled": True}},
    )
    assert gate.decision is GateDecision.BLOCK
    assert {reason["rule_id"] for reason in gate.reasons} >= {
        "skill_telemetry_unknown",
        "fabricated_skill",
        "skill_coverage",
        "invalid_evidence_ref",
        "unsupported_claim",
        "evidence_coverage_unknown",
    }


def test_32_skills_and_200_cases_score_deterministically() -> None:
    bound = [
        {"package_name": f"skill-{index}", "version": "1.0.0", "sha256": f"{index:064x}"}
        for index in range(32)
    ]
    identity = _identity("skill-0", "1.0.0", f"{0:064x}")
    events = [
        _event("skill.selected", "scale", identity),
        _event("skill.started", "scale", identity),
        _event("skill.completed", "scale", identity, status="success"),
    ]
    expected = {
        "skills": {
            "required": ["skill-0"],
            "allowed": ["skill-0"],
            "telemetry_required": True,
        }
    }

    reports = [score_agent_result(expected, _result(events), bound) for _ in range(200)]
    metrics = aggregate_metrics(
        [
            {
                "scores": report.as_dict(),
                "latency_ms": 1,
                "model_cost": None,
                "external_tool_cost": None,
            }
            for report in reports
        ]
    )

    assert len(reports) == 200
    assert metrics["skill_selection_accuracy"] == 1.0
    assert metrics["unbound_skill_calls"] == 0
