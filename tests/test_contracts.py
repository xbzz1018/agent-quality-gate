import pytest
from pydantic import ValidationError

from agent_quality_harness.adapters.base import TokenUsage
from agent_quality_harness.api.schemas import TargetCreate
from agent_quality_harness.domain.enums import MeasurementStatus, TargetKind, TargetProtocol
from agent_quality_harness.services import _code_version


def test_unknown_usage_is_not_zero() -> None:
    usage = TokenUsage()

    assert usage.status is MeasurementStatus.UNKNOWN
    assert usage.input_tokens is None
    assert usage.output_tokens is None


def test_mcp_cannot_be_registered_as_agent_protocol() -> None:
    with pytest.raises(ValidationError):
        TargetCreate(
            name="invalid",
            target_kind=TargetKind.AGENT,
            protocol=TargetProtocol.MCP,
            endpoint="http://example.test",
        )


def test_mcp_is_valid_for_tool_target() -> None:
    target = TargetCreate(
        name="tools",
        target_kind=TargetKind.TOOL,
        protocol=TargetProtocol.MCP,
        endpoint="stdio://fake",
    )

    assert target.protocol is TargetProtocol.MCP


def test_manifest_code_version_honors_ci_override(monkeypatch) -> None:
    monkeypatch.setenv("AQH_CODE_VERSION", "ci-commit-123")

    assert _code_version() == "ci-commit-123"
