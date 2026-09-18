# Current Traceability

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
| Multi-agent Scenario | Frozen `aqh.scenario/v1`, DAG validation/execution, persistent Scenario/Node runs | `tests/test_scenario.py`, `tests/test_integration_scenario.py`, Scenario Runs `#5/#6/#7` |
| Scenario release control | Shadow restrictions; SHA/Gate/OPA/idempotency/budget-authorized Pilot | scenario unit/integration tests, Pilot Run `#7` |
| Cross-protocol scenario | AG-UI Researcher, MCP Tasks Tool, A2A Reviewer, DeepAgents Coordinator | Redis Runs `#10/#11`, Jaeger Trace `44a6a9d5a6c614f3ab5fac821c0c877f` |
| Distributed dispatch | PostgreSQL Outbox, Kafka publisher/consumer, Inbox idempotency and DLQ | `tests/test_kafka_integration.py`, Kafka Run `#14` |
| Dependency isolation | API/Core Worker exclude aiokafka and protocol SDKs; distributed images use separate locks | image `pip check` and import probes, Compose profile validation |
| Operations console | Vue scenario list/editor/run control and Run Detail scenario timeline | TypeScript, Vitest, production build, Chrome desktop/mobile QA |
| Storage guardrails | Core-only default Compose, log rotation, memory limits, optional profiles, no long-lived Kafka volume | Compose config verification and `scripts/start_closeout_stack.ps1` |

## Verification boundaries

- Collector/Jaeger and Vue are currently verified. Optional protocol/distributed/observability services are stopped outside bounded E2E windows.
- AgriGraph Embedding preflight and atomic rebuild completed with `qwen3.7-text-embedding`, 1024 dimensions and `163 discovered == 163 updated`. Runs `#32/#33/#34` verify smoke, 40-case Characterization and a real Stability SHIP.
- Document Autoflow runs `#19/#20/#21/#22` are retained failure evidence, not success: 401 credentials and then a stale project ID produced `target_error`. Run `#29` verifies the repaired live profile. Run `#30` has 24/24 Characterization results and no target execution error; Run `#31` has 48/48 Stability results and a real BLOCK caused by 3 target conflicts plus a 4.17 pp success-rate drop.
- Document known model cost is `$0.04003916` for Run `#30` and `$0.03550708` for Run `#31` Candidate. Three target-error Case costs remain UNKNOWN, so the exact shared total is not claimed.
- Both real-target Case sets and current dirty source-tree SHA values reproduce exactly. These remain service-snapshot Stability results, not different-commit regression results.
- Historical Run IDs from the deleted Docker data disk are historical evidence only. Current acceptance claims must reference rows present in the rebuilt PostgreSQL database.
- Kubernetes manifests are statically validated only; kind/public HA remain unverified. Hermes and MCP Tasks are compatibility/experimental enhancements, not default control-plane dependencies.
