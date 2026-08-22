from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from agent_quality_harness.domain.enums import MeasurementStatus


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_write_tokens: int | None = None
    reasoning_tokens: int | None = None
    embedding_tokens: int | None = None
    vision_tokens: int | None = None
    judge_tokens: int | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> MeasurementStatus:
        values = (
            self.input_tokens,
            self.output_tokens,
            self.cache_read_tokens,
            self.cache_write_tokens,
            self.reasoning_tokens,
            self.embedding_tokens,
            self.vision_tokens,
            self.judge_tokens,
        )
        known = sum(value is not None for value in values)
        if known == 0:
            return MeasurementStatus.UNKNOWN
        if known == len(values):
            return MeasurementStatus.KNOWN
        return MeasurementStatus.PARTIAL


@dataclass(frozen=True, slots=True)
class AgentRunEvent:
    event_type: str
    data: Mapping[str, Any] = field(default_factory=dict)
    event_id: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: str | None
    final_action: str
    output: Mapping[str, Any]
    events: tuple[AgentRunEvent, ...] = ()
    usage: TokenUsage = field(default_factory=TokenUsage)
    model_cost: Decimal | None = None
    external_tool_cost: Decimal | None = None


class AgentAdapter(Protocol):
    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult: ...

    def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]: ...

    async def cancel(self, run_id: str) -> bool: ...
