import asyncio
import hashlib
from collections.abc import AsyncIterator, Mapping
from decimal import Decimal
from time import monotonic
from typing import Any

import httpx

from .auth import ResolvedAuth
from .base import AgentRunEvent, AgentRunResult, TokenUsage
from .http import _ClientContext
from .profile_common import endpoint, optional_decimal, optional_int, unwrap_envelope


class DocumentAutoflowAdapter:
    _TERMINAL = {"completed", "failed", "cancelled", "waiting_review"}

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float,
        auth: ResolvedAuth,
        capabilities: Mapping[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.auth = auth
        self.capabilities = dict(capabilities)
        self._client = client
        self.poll_interval = float(self.capabilities.get("poll_interval_seconds", 2))
        self.max_poll_seconds = float(self.capabilities.get("max_poll_seconds", timeout_seconds))
        raw_budget = self.capabilities.get("budget", {})
        self.budget = dict(raw_budget) if isinstance(raw_budget, dict) else {}
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.known_cost = Decimal("0")

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        self._check_preflight_budget()
        self.calls += 1
        project_id = _required_from(input_data, self.capabilities, "project_id")
        template_id = _required_from(input_data, self.capabilities, "template_id")
        document_ids = input_data.get("document_ids")
        if document_ids is None and input_data.get("document_id") is not None:
            document_ids = [input_data["document_id"]]
        if document_ids is None:
            sample_id = input_data.get("source_sample_id", input_data.get("sample_id"))
            document_map = self.capabilities.get("document_map", {})
            if isinstance(document_map, dict) and sample_id in document_map:
                mapped = document_map[sample_id]
                document_ids = mapped if isinstance(mapped, list) else [mapped]
        if not isinstance(document_ids, list) or not document_ids:
            raise ValueError("document_autoflow_v1 input requires document_id or document_ids")
        async with _ClientContext(self._client) as client:
            headers = await self._authenticate(client)
            create_response = await client.post(
                endpoint(
                    self.base_url,
                    str(
                        self.capabilities.get(
                            "create_run_path", "/api/v1/projects/{project_id}/runs"
                        )
                    ).format(project_id=project_id),
                ),
                json={"template_id": template_id, "document_ids": document_ids},
                headers=headers,
                timeout=self.timeout_seconds,
            )
            create_response.raise_for_status()
            current = unwrap_envelope(create_response.json())
            run_id = _required(current, "id")
            events = [AgentRunEvent("workflow.run_started", {"run_id": run_id})]
            seen_status: str | None = None
            deadline = monotonic() + self.max_poll_seconds
            while True:
                status = str(current.get("status", "unknown")).lower()
                if status != seen_status:
                    events.append(AgentRunEvent("workflow.status", {"status": status}))
                    seen_status = status
                if status in self._TERMINAL:
                    break
                if monotonic() >= deadline:
                    raise TimeoutError("Document Autoflow run did not reach a terminal state")
                await asyncio.sleep(self.poll_interval)
                response = await client.get(
                    endpoint(
                        self.base_url,
                        str(self.capabilities.get("get_run_path", "/api/v1/runs/{run_id}")).format(
                            run_id=run_id
                        ),
                    ),
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                response.raise_for_status()
                current = unwrap_envelope(response.json())
        usage = TokenUsage(
            input_tokens=optional_int(current.get("input_tokens")),
            output_tokens=optional_int(current.get("output_tokens")),
            raw={
                "input_tokens": current.get("input_tokens"),
                "output_tokens": current.get("output_tokens"),
                "model": current.get("model_name"),
                "prompt_version": current.get("prompt_version"),
            },
        )
        field_hashes, evidence_verified = _candidate_observations(current.get("candidates", []))
        output = {
            "status": str(current.get("status", "unknown")).lower(),
            "route": current.get("route"),
            "candidates": current.get("candidates", []),
            "field_hashes": field_hashes,
            "evidence_verified": evidence_verified,
            "validation_result": current.get("validation_result"),
            "review_task": current.get("review_task"),
            "error_type": current.get("error_type"),
            "snapshot_sha256": current.get("snapshot_sha256"),
        }
        final_action = {
            "completed": "extract",
            "waiting_review": "review",
            "cancelled": "cancel",
            "failed": "error",
        }.get(output["status"], "error")
        events.append(AgentRunEvent("workflow.run_completed", {"status": output["status"]}))
        model_cost = optional_decimal(current.get("estimated_cost"))
        self._record_budget(usage, model_cost)
        return AgentRunResult(
            run_id=run_id,
            final_action=final_action,
            output=output,
            events=tuple(events),
            usage=usage,
            model_cost=model_cost,
        )

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event

    async def cancel(self, run_id: str) -> bool:
        async with _ClientContext(self._client) as client:
            headers = await self._authenticate(client)
            response = await client.post(
                endpoint(
                    self.base_url,
                    str(
                        self.capabilities.get("cancel_run_path", "/api/v1/runs/{run_id}/cancel")
                    ).format(run_id=run_id),
                ),
                headers=headers,
                timeout=self.timeout_seconds,
            )
        return response.status_code in {200, 202, 204}

    async def _authenticate(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self.auth.kind == "headers":
            return dict(self.auth.headers)
        if self.auth.kind != "cookie_login":
            raise ValueError("document_autoflow_v1 requires headers or cookie_login auth")
        response = await client.post(
            endpoint(
                self.base_url,
                str(self.capabilities.get("login_path", "/api/v1/auth/login")),
            ),
            json={"username": self.auth.username, "password": self.auth.password},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise PermissionError("Document Autoflow login rejected")
        return dict(self.auth.headers)

    def _check_preflight_budget(self) -> None:
        maximum = int(self.budget.get("max_requests", 0) or 0)
        if maximum and self.calls >= maximum:
            raise RuntimeError("Document Autoflow request budget exhausted")

    def _record_budget(self, usage: TokenUsage, model_cost: Decimal | None) -> None:
        self.input_tokens += usage.input_tokens or 0
        self.output_tokens += usage.output_tokens or 0
        if model_cost is not None:
            self.known_cost += model_cost
        limits = (
            ("input token", self.input_tokens, int(self.budget.get("max_input_tokens", 0) or 0)),
            (
                "output token",
                self.output_tokens,
                int(self.budget.get("max_output_tokens", 0) or 0),
            ),
        )
        for name, actual, maximum in limits:
            if maximum and actual > maximum:
                raise RuntimeError(f"Document Autoflow {name} budget exceeded")
        maximum_cost = optional_decimal(self.budget.get("max_cost_usd"))
        if maximum_cost is not None and self.known_cost > maximum_cost:
            raise RuntimeError("Document Autoflow cost budget exceeded")


def _required(value: Mapping[str, Any], key: str) -> str:
    item = value.get(key)
    if item is None or str(item).strip() == "":
        raise ValueError(f"document_autoflow_v1 input requires {key}")
    return str(item)


def _required_from(primary: Mapping[str, Any], fallback: Mapping[str, Any], key: str) -> str:
    value = primary.get(key, fallback.get(key))
    if value is None or str(value).strip() == "":
        raise ValueError(f"document_autoflow_v1 requires {key} in input or capabilities")
    return str(value)


def _candidate_observations(value: Any) -> tuple[dict[str, str], dict[str, bool]]:
    if not isinstance(value, list):
        return {}, {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in value:
        if isinstance(item, dict) and item.get("field_key") is not None:
            grouped.setdefault(str(item["field_key"]), []).append(item)
    hashes: dict[str, str] = {}
    evidence: dict[str, bool] = {}
    for field_key, candidates in grouped.items():
        if len(candidates) != 1:
            continue
        candidate = candidates[0]
        normalized = candidate.get("normalized_value")
        if normalized is not None:
            hashes[field_key] = hashlib.sha256(_canonical_value(normalized).encode()).hexdigest()
        refs = candidate.get("evidence_refs", [])
        evidence[field_key] = bool(refs) and all(
            isinstance(ref, dict) and ref.get("verified") is True for ref in refs
        )
    return hashes, evidence


def _canonical_value(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    if isinstance(value, float):
        return f"{value:.8g}"
    return str(value)
