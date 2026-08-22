from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from agent_quality_harness.adapters.base import TokenUsage
from agent_quality_harness.domain.enums import MeasurementStatus

TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "embedding_tokens",
    "vision_tokens",
    "judge_tokens",
)


@dataclass(frozen=True, slots=True)
class CostCalculation:
    status: MeasurementStatus
    model_cost: Decimal | None
    components: dict[str, str | None]


def calculate_model_cost(
    usage: TokenUsage, prices_per_million: dict[str, Any] | None
) -> CostCalculation:
    components: dict[str, str | None] = {}
    known = 0
    total = Decimal("0")
    complete = prices_per_million is not None
    for field in TOKEN_FIELDS:
        tokens = getattr(usage, field)
        raw_price = None if prices_per_million is None else prices_per_million.get(field)
        if tokens is None or raw_price is None:
            components[field] = None
            complete = False
            continue
        component = Decimal(tokens) * Decimal(str(raw_price)) / Decimal(1_000_000)
        components[field] = str(component)
        total += component
        known += 1
    if complete:
        return CostCalculation(MeasurementStatus.KNOWN, total, components)
    if known:
        return CostCalculation(MeasurementStatus.PARTIAL, None, components)
    return CostCalculation(MeasurementStatus.UNKNOWN, None, components)
