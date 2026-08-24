from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .config import Settings

_provider: TracerProvider | None = None
_httpx_instrumented = False


def configure_telemetry(app: FastAPI, settings: Settings) -> None:
    provider = configure_tracing(settings, settings.otel_service_name)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def configure_tracing(settings: Settings, service_name: str) -> TracerProvider:
    global _httpx_instrumented, _provider
    if _provider is None:
        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        if settings.otel_enabled:
            exporter = OTLPSpanExporter(
                endpoint=settings.otel_exporter_otlp_endpoint,
                insecure=settings.otel_exporter_otlp_endpoint.startswith("http://"),
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _provider = provider
    if not _httpx_instrumented:
        HTTPXClientInstrumentor().instrument(tracer_provider=_provider)
        _httpx_instrumented = True
    return _provider


def get_tracer():
    return trace.get_tracer("agent_quality_harness")


def agent_span_attributes(
    *,
    target_id: int,
    version_id: int,
    protocol: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "gen_ai.operation.name": "invoke_agent",
        "aqh.target.id": target_id,
        "aqh.version.id": version_id,
        "aqh.target.protocol": protocol,
    }
    if provider:
        attributes["gen_ai.provider.name"] = provider
    if model:
        attributes["gen_ai.request.model"] = model
    return attributes


def tool_span_attributes(*, target_id: int, version_id: int, protocol: str) -> dict[str, Any]:
    return {
        "gen_ai.operation.name": "execute_tool",
        "aqh.target.id": target_id,
        "aqh.version.id": version_id,
        "aqh.target.protocol": protocol,
    }


def add_usage_attributes(span: trace.Span, usage: Mapping[str, int | None]) -> None:
    mapping = {
        "input_tokens": "gen_ai.usage.input_tokens",
        "output_tokens": "gen_ai.usage.output_tokens",
        "cache_read_tokens": "gen_ai.usage.cache_read.input_tokens",
        "cache_write_tokens": "gen_ai.usage.cache_creation.input_tokens",
        "reasoning_tokens": "gen_ai.usage.reasoning.output_tokens",
    }
    for source, target in mapping.items():
        value = usage.get(source)
        if value is not None:
            span.set_attribute(target, value)


def current_trace_id() -> str | None:
    span_context = trace.get_current_span().get_span_context()
    if not span_context.is_valid:
        return None
    return f"{span_context.trace_id:032x}"
