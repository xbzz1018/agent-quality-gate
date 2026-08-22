# MVP Traceability

| Requirement | Implementation | Verification |
|---|---|---|
| Frozen dataset integrity | Import hash plus pre-run case/dataset rehash | tests/test_dataset_integrity.py, integration test |
| Baseline/Candidate isolation | Same-target validation; explicit benchmark mode | integration test |
| Deterministic scoring | Inspect custom scorer plus persisted rule reports | tests/test_scoring.py, integration test |
| Token and cost unknown semantics | Eight token categories, cost status, immutable snapshot API | tests/test_pricing.py |
| Release gate | Versioned policy and SHIP/WARN/BLOCK engine | tests/test_gates.py, integration test |
| Trace and events | Worker SDK provider, Trace ID, redacted RunEvent, Jaeger link | telemetry tests, integration test |
| Replay and cancellation | Failed Candidate case replay; queued/running state transitions | integration test |
| Reliable dispatch | ready/processing/ack, requeue, DB lease and heartbeat | queue tests, integration test |
| CI gate | Ruff, pytest, PostgreSQL/Redis, Alembic drift, Gate CLI | .github/workflows/quality-gate.yml |

Collector/Jaeger image execution, Vue UI, and the two live-system evaluation rounds remain pending and must not be presented as completed.
