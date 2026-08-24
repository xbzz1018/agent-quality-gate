from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urljoin


def endpoint(base_url: str, path: str) -> str:
    return urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/"))


def unwrap_envelope(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("target response must be a JSON object")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("target response data must be a JSON object")
    return data


def optional_int(*values: Any) -> int | None:
    for value in values:
        if value is not None:
            result = int(value)
            if result < 0:
                raise ValueError("token usage cannot be negative")
            return result
    return None


def optional_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("cost must be a decimal value") from exc
