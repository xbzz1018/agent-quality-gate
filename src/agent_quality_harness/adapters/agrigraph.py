from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from .auth import ResolvedAuth
from .base import AgentRunEvent, AgentRunResult, TokenUsage
from .http import _ClientContext
from .profile_common import endpoint, optional_decimal, optional_int, unwrap_envelope


class AgriGraphAdapter:
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

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        question = input_data.get("question", input_data.get("prompt"))
        if not isinstance(question, str) or not question.strip():
            raise ValueError("agrigraph_v1 input requires question or prompt")
        async with _ClientContext(self._client) as client:
            headers = await self._headers(client)
            response = await client.post(
                endpoint(
                    self.base_url,
                    str(self.capabilities.get("answer_path", "/api/v1/evaluation/answer")),
                ),
                json={
                    "question": question,
                    "crop": str(input_data.get("crop", "AUTO")),
                    "requestId": str(context.get("case_id", "")),
                },
                headers=headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = unwrap_envelope(response.json())
        usage_payload = data.get("modelUsage")
        usage_payload = usage_payload if isinstance(usage_payload, dict) else {}
        usage = TokenUsage(
            input_tokens=optional_int(
                usage_payload.get("input_tokens"), usage_payload.get("inputTokens")
            ),
            output_tokens=optional_int(
                usage_payload.get("output_tokens"), usage_payload.get("outputTokens")
            ),
            cache_read_tokens=optional_int(
                usage_payload.get("cache_read_tokens"), usage_payload.get("cacheReadTokens")
            ),
            reasoning_tokens=optional_int(
                usage_payload.get("reasoning_tokens"), usage_payload.get("reasoningTokens")
            ),
            raw=usage_payload,
        )
        events = [
            AgentRunEvent("workflow.step", {"name": str(step)}) for step in data.get("workflow", [])
        ]
        for item in data.get("toolEvents", []):
            if isinstance(item, dict):
                events.append(AgentRunEvent("tool.completed", dict(item)))
        output = {
            "answer": data.get("answer"),
            "citations": data.get("citations", []),
            "graph_evidence": data.get("graphEvidence", []),
            "grounded": data.get("grounded"),
            "degraded": data.get("degraded"),
            "warnings": data.get("warnings", []),
            "workflow": data.get("workflow", []),
            "model": data.get("modelUsed"),
            "answer_mode": data.get("answerMode"),
            "coverage_status": data.get("coverageStatus"),
            "retrieval_stats": data.get("retrievalStats", {}),
        }
        raw_cost = data.get("estimatedCostUsd")
        model_cost = optional_decimal(raw_cost) if raw_cost not in {None, 0, "0"} else None
        return AgentRunResult(
            run_id=_optional_string(data.get("agentRunId")),
            final_action="answer",
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
            headers = await self._headers(client)
            response = await client.post(
                endpoint(
                    self.base_url,
                    str(
                        self.capabilities.get(
                            "cancel_path", f"/api/v1/agriculture-chat/streams/{run_id}/cancel"
                        )
                    ).format(run_id=run_id),
                ),
                headers=headers,
                timeout=self.timeout_seconds,
            )
        return response.status_code in {200, 202, 204}

    async def _headers(self, client: httpx.AsyncClient) -> dict[str, str]:
        headers = dict(self.auth.headers)
        if self.auth.kind == "headers":
            return headers
        if self.auth.kind != "bearer_login":
            raise ValueError("agrigraph_v1 requires headers or bearer_login auth")
        response = await client.post(
            endpoint(
                self.base_url,
                str(self.capabilities.get("login_path", "/api/v1/users/login")),
            ),
            json={"username": self.auth.username, "password": self.auth.password},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise PermissionError("AgriGraph login rejected")
        data = unwrap_envelope(response.json())
        token = data.get("token", data.get("accessToken", data.get("access_token")))
        if not isinstance(token, str) or not token:
            raise PermissionError("AgriGraph login did not return an access token")
        headers["Authorization"] = f"Bearer {token}"
        return headers


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)
