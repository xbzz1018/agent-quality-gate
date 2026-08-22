from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from agent_quality_harness.core.telemetry import add_usage_attributes, agent_span_attributes


def test_genai_attributes_emit_known_usage_and_omit_unknown_values() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    attributes = agent_span_attributes(
        target_id=7,
        version_id=9,
        protocol="http",
        provider="openai",
        model="gpt-test",
    )

    with tracer.start_as_current_span("agent.invoke", attributes=attributes) as span:
        add_usage_attributes(
            span,
            {
                "input_tokens": 12,
                "output_tokens": 4,
                "cache_read_tokens": None,
                "cache_write_tokens": None,
                "reasoning_tokens": 2,
            },
        )

    exported = exporter.get_finished_spans()[0]
    assert exported.attributes["gen_ai.operation.name"] == "invoke_agent"
    assert exported.attributes["gen_ai.usage.input_tokens"] == 12
    assert exported.attributes["gen_ai.usage.reasoning.output_tokens"] == 2
    assert "gen_ai.usage.cache_read.input_tokens" not in exported.attributes
