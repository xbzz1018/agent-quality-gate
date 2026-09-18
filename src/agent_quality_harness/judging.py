from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

import httpx


@dataclass(frozen=True, slots=True)
class JudgeObservation:
    status: str
    verdict: str | None = None
    confidence: float | None = None
    unsupported_claim_ids: tuple[str, ...] = ()
    model: str | None = None
    prompt_version: str | None = None
    response_sha256: str | None = None
    judge_tokens: int | None = None
    error_type: str | None = None


class HallucinationJudge(Protocol):
    async def evaluate(
        self,
        *,
        case_id: str,
        specification: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> JudgeObservation: ...


class DisabledHallucinationJudge:
    async def evaluate(
        self,
        *,
        case_id: str,
        specification: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> JudgeObservation:
        del case_id, specification, output
        return JudgeObservation(status="unknown", error_type="judge_not_configured")


class OpenAICompatibleHallucinationJudge:
    prompt_version = "aqh-hallucination-judge-v1"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 30,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    async def evaluate(
        self,
        *,
        case_id: str,
        specification: Mapping[str, Any],
        output: Mapping[str, Any],
    ) -> JudgeObservation:
        payload = _judge_payload(case_id, specification, output)
        request = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Classify whether every supplied claim is supported by the supplied "
                        "evidence. Return JSON only. Do not infer facts outside the evidence."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
        }
        try:
            if self.client is None:
                async with httpx.AsyncClient() as client:
                    response = await self._post(client, request)
            else:
                response = await self._post(self.client, request)
            document = response.json()
            content = document["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            verdict = str(parsed["verdict"]).lower()
            confidence = float(parsed["confidence"])
            unsupported = parsed.get("unsupported_claim_ids", [])
            if verdict not in {"supported", "unsupported", "uncertain"}:
                raise ValueError("invalid verdict")
            if not 0 <= confidence <= 1 or not isinstance(unsupported, list):
                raise ValueError("invalid judge result")
            normalized = {
                "verdict": verdict,
                "confidence": confidence,
                "unsupported_claim_ids": sorted(str(item) for item in unsupported),
            }
            usage = document.get("usage", {})
            tokens = usage.get("total_tokens") if isinstance(usage, Mapping) else None
            return JudgeObservation(
                status="known",
                verdict=verdict,
                confidence=confidence,
                unsupported_claim_ids=tuple(normalized["unsupported_claim_ids"]),
                model=self.model,
                prompt_version=self.prompt_version,
                response_sha256=_sha256(normalized),
                judge_tokens=int(tokens) if tokens is not None else None,
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return JudgeObservation(
                status="unknown",
                model=self.model,
                prompt_version=self.prompt_version,
                error_type="judge_provider_error",
            )

    async def _post(self, client: httpx.AsyncClient, request: dict[str, Any]) -> httpx.Response:
        response = await client.post(
            f"{self.base_url}/chat/completions",
            json=request,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        return response


def _judge_payload(
    case_id: str, specification: Mapping[str, Any], output: Mapping[str, Any]
) -> dict[str, Any]:
    claims = _lookup(output, str(specification.get("claims_path", "claims")))
    evidence = _lookup(output, str(specification.get("evidence_path", "evidence")))
    return {
        "schema": "aqh.hallucination-judge/v1",
        "case_id": case_id,
        "claims": _bounded_structure(claims),
        "evidence": _bounded_structure(evidence),
        "required_claim_ids": [str(item) for item in specification.get("required_claim_ids", [])],
        "response_schema": {
            "verdict": "supported|unsupported|uncertain",
            "confidence": "number between 0 and 1",
            "unsupported_claim_ids": ["claim id"],
        },
    }


def _lookup(value: Mapping[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split(".") if path else ():
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _bounded_structure(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        return {
            str(key): _bounded_structure(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [_bounded_structure(item, depth=depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:2000]


def _sha256(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
