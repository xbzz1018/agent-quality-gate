from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from agent_quality_harness.core.telemetry import get_tracer

_PACKAGE_LINE = re.compile(r"(?m)^\s*package\s+([A-Za-z0-9_.]+)\s*$")
_DECISIONS = {"ship", "warn", "block"}


class PolicyEngineError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision: str
    reasons: list[dict[str, Any]]
    decision_id: str | None
    input_sha256: str
    latency_ms: int
    error: str | None = None


def canonical_policy_sha256(
    *, rego: str, data: dict[str, Any], package_path: str, entrypoint: str
) -> str:
    payload = {
        "rego": rego.replace("\r\n", "\n").replace("\r", "\n"),
        "data": data,
        "package_path": package_path,
        "entrypoint": entrypoint,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_package_namespace(rego: str, package_path: str, organization_id: int) -> None:
    match = _PACKAGE_LINE.search(rego)
    if match is None:
        raise ValueError("Rego package declaration is required")
    if match.group(1) != package_path:
        raise ValueError("Rego package declaration does not match package_path")
    if not package_path.startswith(f"aqh.org_{organization_id}."):
        raise ValueError("Rego package must use the current organization namespace")
    if len(package_path.split(".")) < 4:
        raise ValueError("Rego package must include policy and version namespaces")


class OpaClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def validate(self, *, policy_id: str, rego: str) -> list[dict[str, Any]]:
        try:
            response = self._request(
                "PUT",
                f"/v1/policies/{policy_id}",
                content=rego.encode("utf-8"),
                headers={"content-type": "text/plain"},
            )
        except PolicyEngineError as exc:
            return [{"code": "policy_engine_error", "message": str(exc)}]
        if response.status_code == 200:
            return []
        return _validation_errors(response)

    def evaluate(
        self,
        *,
        policy_id: str,
        rego: str,
        data: dict[str, Any],
        data_path: str,
        package_path: str,
        entrypoint: str,
        input_data: dict[str, Any],
    ) -> PolicyDecision:
        canonical_input = json.dumps(
            input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        input_sha = hashlib.sha256(canonical_input.encode("utf-8")).hexdigest()
        started = time.perf_counter()
        try:
            policy_response = self._request(
                "PUT",
                f"/v1/policies/{policy_id}",
                content=rego.encode("utf-8"),
                headers={"content-type": "text/plain"},
            )
            if policy_response.status_code != 200:
                raise PolicyEngineError("OPA rejected the validated policy")
            data_response = self._request("PUT", f"/v1/data/{data_path}", json=data)
            if data_response.status_code not in {200, 204}:
                raise PolicyEngineError("OPA rejected policy data")
            decision_path = f"/v1/data/{package_path.replace('.', '/')}/{entrypoint}"
            with get_tracer().start_as_current_span(
                "policy.evaluate",
                attributes={"aqh.policy.id": policy_id, "aqh.policy.entrypoint": entrypoint},
            ):
                response = self._request(
                    "POST",
                    decision_path,
                    params={"metrics": "true"},
                    json={"input": input_data},
                )
            if response.status_code != 200:
                raise PolicyEngineError(f"OPA evaluation returned HTTP {response.status_code}")
            payload = response.json()
            result = payload.get("result")
            decision, reasons = _parse_result(result)
            return PolicyDecision(
                decision=decision,
                reasons=reasons,
                decision_id=payload.get("decision_id"),
                input_sha256=input_sha,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
        except (PolicyEngineError, httpx.HTTPError, ValueError, TypeError) as exc:
            return PolicyDecision(
                decision="block",
                reasons=[
                    {
                        "rule_id": "policy_engine_error",
                        "severity": "block",
                        "actual": {"status": "error"},
                        "threshold": {"status": "valid_decision"},
                    }
                ],
                decision_id=None,
                input_sha256=input_sha,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=f"{type(exc).__name__}: {exc}"[:500],
            )

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        for attempt in range(2):
            try:
                with httpx.Client(
                    base_url=self.base_url,
                    timeout=self.timeout_seconds,
                    transport=self.transport,
                ) as client:
                    return client.request(method, path, **kwargs)
            except httpx.ConnectError as exc:
                if attempt == 1:
                    raise PolicyEngineError("OPA connection failed") from exc
            except httpx.TimeoutException as exc:
                raise PolicyEngineError("OPA request timed out") from exc
        raise PolicyEngineError("OPA connection failed")


def _parse_result(result: Any) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(result, dict):
        raise PolicyEngineError("OPA decision is undefined or not an object")
    decision = result.get("decision")
    reasons = result.get("reasons")
    if decision not in _DECISIONS or not isinstance(reasons, list):
        raise PolicyEngineError("OPA decision has an invalid structure")
    normalized: list[dict[str, Any]] = []
    for reason in reasons:
        if not isinstance(reason, dict):
            raise PolicyEngineError("OPA reason must be an object")
        rule_id = reason.get("rule_id")
        severity = reason.get("severity")
        actual = reason.get("actual")
        threshold = reason.get("threshold")
        if (
            not isinstance(rule_id, str)
            or severity not in {"warn", "block"}
            or not isinstance(actual, dict)
            or not isinstance(threshold, dict)
        ):
            raise PolicyEngineError("OPA reason has an invalid structure")
        normalized.append(
            {
                "rule_id": rule_id[:200],
                "severity": severity,
                "actual": actual,
                "threshold": threshold,
                "source": "opa",
            }
        )
    return decision, normalized


def _validation_errors(response: httpx.Response) -> list[dict[str, Any]]:
    try:
        payload = response.json()
    except ValueError:
        return [{"code": "opa_validation_error", "message": "OPA rejected the policy"}]
    errors = payload.get("errors")
    if not isinstance(errors, list):
        return [
            {
                "code": str(payload.get("code", "opa_validation_error")),
                "message": str(payload.get("message", "OPA rejected the policy"))[:500],
            }
        ]
    return [
        {
            "code": str(item.get("code", "rego_error")),
            "message": str(item.get("message", "invalid Rego"))[:500],
            "location": item.get("location"),
        }
        for item in errors[:20]
        if isinstance(item, dict)
    ]
