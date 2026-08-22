from decimal import Decimal

from agent_quality_harness.adapters.base import TokenUsage
from agent_quality_harness.domain.enums import MeasurementStatus
from agent_quality_harness.pricing import TOKEN_FIELDS, calculate_model_cost


def test_pricing_known_only_when_every_token_category_and_price_is_known() -> None:
    usage = TokenUsage(**{field: 1 for field in TOKEN_FIELDS})
    result = calculate_model_cost(usage, {field: "1.0" for field in TOKEN_FIELDS})

    assert result.status is MeasurementStatus.KNOWN
    assert result.model_cost == Decimal("0.000008")


def test_pricing_partial_keeps_total_cost_unknown() -> None:
    result = calculate_model_cost(
        TokenUsage(input_tokens=100),
        {"input_tokens": "2.0"},
    )

    assert result.status is MeasurementStatus.PARTIAL
    assert result.model_cost is None
    assert result.components["input_tokens"] == "0.0002"


def test_pricing_unknown_is_null_not_zero() -> None:
    result = calculate_model_cost(TokenUsage(), None)

    assert result.status is MeasurementStatus.UNKNOWN
    assert result.model_cost is None
