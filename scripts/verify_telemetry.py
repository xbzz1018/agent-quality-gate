from __future__ import annotations

import argparse
import json
from typing import Any
from urllib.request import urlopen

SENSITIVE = ("authorization", "api_key", "password", "cookie", "prompt", "reasoning.content")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify an AQH Trace through Collector and Jaeger")
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--expected-service", required=True)
    parser.add_argument("--collector-health", default="http://127.0.0.1:13133/")
    parser.add_argument("--jaeger", default="http://127.0.0.1:16686")
    args = parser.parse_args()

    _request(args.collector_health)
    payload = _request(f"{args.jaeger.rstrip('/')}/api/traces/{args.trace_id}")
    traces = payload.get("data", [])
    if len(traces) != 1:
        raise SystemExit("Trace ID is not queryable in Jaeger")
    trace = traces[0]
    processes = trace.get("processes", {})
    services = sorted(
        {
            item.get("serviceName")
            for item in processes.values()
            if isinstance(item, dict) and item.get("serviceName")
        }
    )
    if args.expected_service not in services:
        raise SystemExit(f"expected service is absent from Trace: {args.expected_service}")
    sensitive = []
    for span in trace.get("spans", []):
        for tag in span.get("tags", []):
            key = str(tag.get("key", "")).casefold()
            if any(name in key for name in SENSITIVE):
                sensitive.append(key)
    if sensitive:
        raise SystemExit(f"sensitive Trace tags detected: {sorted(set(sensitive))}")
    print(
        json.dumps(
            {
                "trace_id": trace.get("traceID"),
                "services": services,
                "span_count": len(trace.get("spans", [])),
                "operations": sorted(
                    {str(span.get("operationName")) for span in trace.get("spans", [])}
                ),
                "sensitive_tag_count": 0,
            },
            sort_keys=True,
        )
    )
    return 0


def _request(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5) as response:  # noqa: S310 - URLs are explicit local probes.
        body = response.read()
    if not body:
        return {}
    value = json.loads(body)
    return value if isinstance(value, dict) else {}


if __name__ == "__main__":
    raise SystemExit(main())
