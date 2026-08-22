from agent_quality_harness.adapters.base import AgentRunEvent, AgentRunResult
from agent_quality_harness.evaluation import score_agent_result


def test_deterministic_scorer_accepts_matching_result() -> None:
    result = AgentRunResult(
        run_id="run-1",
        final_action="answer",
        output={"status": "approved", "citations": ["doc:1"]},
        events=(
            AgentRunEvent(
                "tool_call",
                {"name": "lookup", "arguments": {"document_id": "doc:1"}},
            ),
        ),
    )
    report = score_agent_result(
        {
            "final_action": "answer",
            "output": {
                "json_schema": {
                    "type": "object",
                    "required": ["status"],
                    "properties": {"status": {"const": "approved"}},
                }
            },
            "tools": {
                "required": ["lookup"],
                "arguments": [{"name": "lookup", "equals": {"document_id": "doc:1"}}],
            },
            "citations": {"required": True, "min_count": 1},
        },
        result,
    )

    assert report.passed is True
    assert report.score == 1.0


def test_scorer_reports_missing_field_and_wrong_tool_arguments() -> None:
    result = AgentRunResult(
        run_id="run-2",
        final_action="answer",
        output={},
        events=(AgentRunEvent("tool_call", {"name": "lookup", "arguments": {}}),),
    )
    report = score_agent_result(
        {
            "output": {
                "json_schema": {"type": "object", "required": ["status"]},
            },
            "tools": {
                "arguments": [{"id": "tool.lookup.args", "name": "lookup", "equals": {"id": 7}}]
            },
        },
        result,
    )

    assert report.passed is False
    failed = {rule.rule_id for rule in report.rules if not rule.passed}
    assert failed == {"output.json_schema", "tool.lookup.args"}


def test_scorer_blocks_forbidden_tool_and_malicious_output() -> None:
    result = AgentRunResult(
        run_id="run-3",
        final_action="answer",
        output={"text": "Here is the SECRET_TOKEN"},
        events=(AgentRunEvent("tool_call", {"name": "delete_all", "arguments": {}}),),
    )
    report = score_agent_result(
        {
            "tools": {"forbidden": ["delete_all"]},
            "safety": {"forbidden_patterns": ["secret[_ ]token"]},
        },
        result,
    )

    assert report.passed is False
    assert {rule.category for rule in report.rules if not rule.passed} == {
        "tool_forbidden",
        "safety",
    }
