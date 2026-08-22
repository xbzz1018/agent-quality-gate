from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from .base import AgentRunEvent, AgentRunResult
from .mapping import run_result_from_payload


class HttpAgentAdapter:
    def __init__(
        self,
        endpoint: str,
        *,
        timeout_seconds: float = 30,
        headers: Mapping[str, str] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})
        self._client = client

    async def invoke(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AgentRunResult:
        async with self._client_context() as client:
            response = await client.post(
                self.endpoint,
                json={"input": dict(input_data), "context": dict(context)},
                headers=self.headers,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("agent response must be a JSON object")
        return run_result_from_payload(payload)

    async def stream(
        self, input_data: Mapping[str, Any], context: Mapping[str, Any]
    ) -> AsyncIterator[AgentRunEvent]:
        result = await self.invoke(input_data, context)
        for event in result.events:
            yield event

    async def cancel(self, run_id: str) -> bool:
        async with self._client_context() as client:
            response = await client.post(
                f"{self.endpoint.rstrip('/')}/{run_id}/cancel",
                headers=self.headers,
                timeout=self.timeout_seconds,
            )
        return response.status_code in {200, 202, 204}

    def _client_context(self) -> "_ClientContext":
        return _ClientContext(self._client)


class _ClientContext:
    def __init__(self, client: httpx.AsyncClient | None) -> None:
        self._client = client
        self._owned = client is None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def __aexit__(self, *_: object) -> None:
        if self._owned and self._client is not None:
            await self._client.aclose()
