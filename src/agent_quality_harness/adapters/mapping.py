from decimal import Decimal
from typing import Any

from .base import AgentRunEvent, AgentRunResult, TokenUsage


def token_usage_from_payload(payload: dict[str, Any] | None) -> TokenUsage:
    payload = payload or {}
    return TokenUsage(
        input_tokens=_optional_int(payload.get("input_tokens")),
        output_tokens=_optional_int(payload.get("output_tokens")),
        cache_read_tokens=_optional_int(payload.get("cache_read_tokens")),
        cache_write_tokens=_optional_int(payload.get("cache_write_tokens")),
        reasoning_tokens=_optional_int(payload.get("reasoning_tokens")),
        embedding_tokens=_optional_int(payload.get("embedding_tokens")),
        vision_tokens=_optional_int(payload.get("vision_tokens")),
        judge_tokens=_optional_int(payload.get("judge_tokens")),
        raw=payload,
    )


def run_result_from_payload(payload: dict[str, Any]) -> AgentRunResult:
    output = payload.get("output", {})
    if not isinstance(output, dict):
        output = {"text": str(output)}
    events = tuple(
        AgentRunEvent(
            event_type=str(item["event_type"]),
            event_id=item.get("event_id"),
            data=item.get("data") or {},
        )
        for item in payload.get("events", [])
    )
    return AgentRunResult(
        run_id=_optional_str(payload.get("run_id")),
        final_action=str(payload.get("final_action", "answer")),
        output=output,
        events=events,
        usage=token_usage_from_payload(payload.get("usage")),
        model_cost=_optional_decimal(payload.get("model_cost")),
        external_tool_cost=_optional_decimal(payload.get("external_tool_cost")),
    )


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    result = int(value)
    if result < 0:
        raise ValueError("token usage cannot be negative")
    return result


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
