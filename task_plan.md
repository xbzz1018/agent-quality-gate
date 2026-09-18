# Agent Quality Harness Implementation Plan

## Goal

Build a runnable, testable Agent evaluation, observability, replay, and release-gate platform whose claims are backed by frozen datasets and reproducible reports.

## Current Phase

Phase 7 - multi-agent scenario control plane and current-environment revalidation (complete)

## Status Semantics

- `complete`: code, tests, documentation, and a reproducible verification command exist.
- `in_progress`: implementation has started but cannot be claimed as complete.
- `pending`: not implemented.
- `optional`: only starts after the MVP and preceding enhancements pass their acceptance checks.

## Phases

### Phase 0: Scope and decision baseline

- [x] Confirm project positioning and exclusions.
- [x] Separate Agent target adapters from Tool target adapters.
- [x] Define Token/Cost unknown-value semantics.
- [x] Freeze UI information architecture and non-goals.
- **Status:** complete

### Phase 1: Runnable MVP foundation

- [x] Create the FastAPI application and versioned API surface.
- [x] Add SQLAlchemy/Alembic models for targets, versions, datasets, runs, results, pricing, and gates.
- [x] Add PostgreSQL and Redis configuration plus health/readiness probes.
- [x] Implement a Redis Worker that claims a whole EvalRun; Inspect AI owns case concurrency inside the run.
- [x] Initialize OpenTelemetry in both API and Worker processes and verify non-null Trace IDs.
- [x] Add a deterministic Fake Agent and HTTP/SSE contract tests.
- **Status:** complete

### Phase 2: Evaluation and release-gate core

- [x] Import immutable datasets and calculate canonical dataset hashes.
- [x] Recalculate Dataset/Case hashes before execution and fail closed on drift.
- [x] Implement deterministic scorers before optional LLM-as-Judge scorers.
- [x] Run Baseline and Candidate versions through Inspect AI.
- [x] Implement SHIP/WARN/BLOCK with versioned policies and auditable reasons.
- [x] Implement persistent Trace/event lookup, failed-case replay, and cancellation state transitions.
- [x] Implement Token/Cost Engine and immutable versioned PricingSnapshot records.
- **Status:** complete for backend MVP; Collector export and slow-target running cancellation are verified

### Phase 3: Vue operations console

- [x] Select Chenguang's operations-console structure as the visual reference without copying its React/mock implementation.
- [x] Add target-version listing and an explicit Demo bootstrap path required by the UI.
- [x] Create Vue 3 + TypeScript + Element Plus + Vite application shell.
- [x] Implement target/version, dataset import, and run creation workflows.
- [x] Implement Eval Run detail with Eval Case + Trace split view.
- [x] Implement Baseline/Candidate comparison.
- [x] Implement release-gate audit view.
- [x] Bind all product states to real APIs; label demo fixtures explicitly.
- [x] Add the Web service and same-origin API proxy to Docker Compose.
- [x] Verify TypeScript, tests, production build, real-API E2E, and Chrome desktop/mobile rendering.
- **Status:** complete for local MVP; Collector/Jaeger export is verified, while the production Web image runtime remains a separate deployment check

### Phase 3.5: Multi-tenant administration and console upgrade

- [x] Add Organization, User, Membership, dynamic Role/Permission, session, service-account, API-key, audit, and setting models.
- [x] Backfill all existing business data into a generated `default` organization without data loss.
- [x] Enforce 15-minute access JWTs, rotating 7-day refresh sessions, Argon2id passwords, and organization-bound API keys.
- [x] Enforce tenant-scoped resource lookup and dynamic backend permissions; cross-tenant identifiers return 404.
- [x] Add organization-scoped pagination, search, dashboard, usage/cost, trace/failure, gate-audit, and management APIs.
- [x] Add the `aqh admin bootstrap --password-stdin` path and API-key-aware Gate CLI.
- [x] Upgrade the Vue shell to the captured Chenguang operations-console density and add login, organization switching, cost, audit, and administration workflows.
- [x] Verify migration reversibility, auth/RBAC/tenant isolation, backend suites, Web type/test/build/audit, and Chrome desktop/mobile flows.
- **Status:** complete for the local multi-tenant console; Collector/Jaeger export was verified in Phase 3.75

### Phase 3.75: Trace, cancellation, and real-target verification

- [x] Seal the verified multi-tenant MVP on `codex/real-target-verification`.
- [x] Verify API/Worker export through Collector into a queryable Jaeger Trace.
- [x] Keep the Worker lease alive during long Inspect batches and verify cooperative cancellation.
- [x] Add versioned `agrigraph_v1` and `document_autoflow_v1` HTTP contract profiles.
- [x] Return `baseline_required` for candidate-only comparison and Gate requests.
- [x] Freeze source fingerprints and normalized real-target dataset manifests.
- [x] Complete the 40-case AgriGraph candidate-only characterization.
- [x] Complete a one-case Document Autoflow live Profile smoke characterization.
- [x] Complete a current-database 24-case Document Autoflow characterization and Stability Gate; Runs #30/#31 preserve REVIEW/REPROCESS and target-conflict outcomes.
- [x] Re-run backend, migration, Web, Compose, and Trace verification.
- **Status:** complete for platform engineering and current Document target revalidation

### Phase 3.8: Local MVP release closure

- [x] Stop manual development processes without deleting PostgreSQL or Redis data.
- [x] Build and run API, Worker, Fake Agent, Web, Collector, Jaeger, PostgreSQL, and Redis through production Compose.
- [x] Verify same-origin Nginx API access, persistent admin login, refresh, replay, Gate CLI, cost views, and Trace links.
- [x] Re-run backend, migration, Web, dependency, and Chrome checks against the Compose topology.
- [x] Fast-forward the verified branch to `main` and create `v0.1.0-local-mvp`.
- **Status:** complete

### Phase 4: Protocol and safety enhancements

- [x] Add A2A AgentTargetAdapter.
- [x] Add MCP ToolTargetAdapter for Tool, Resource, and Prompt operations.
- [x] Add DeepAgents as a constrained complex execution harness and a plain Tool Agent control.
- [x] Add Agent Skills versioning and security regression coverage.
- [x] Add OPA/Rego Policy-as-Code integration.
- [x] Add AG-UI AgentTargetAdapter.
- [x] Evaluate MCP Tasks as an experimental 2025-11-25 lifecycle fixture with explicit SDK compatibility limits.
- [x] Treat Hermes only as an optional compatible target with contract coverage.
- **Status:** complete for planned protocol and safety adapters; MCP Tasks remains experimental and Hermes remains optional

### Phase 4.1: v0.2 protocol release closure

- [x] Export exact platform and DeepAgents transitive dependency locks from verified images.
- [x] Pass a no-cache production build, `pip check`, full Compose, backend, migration, Web, Chrome, and Trace verification.
- [x] Fast-forward `codex/protocol-adapters` to `main` and create `v0.2.0-protocols`.
- **Status:** complete

### Phase 4.2: Agent Skills and OPA policy gate

- [x] Add immutable tenant-scoped Skill package/version/attachment/scan models and APIs.
- [x] Add deterministic security scanning and Baseline/Candidate Skill regression.
- [x] Add immutable Rego Policy Bundles, OPA sidecar evaluation, fail-closed composition, and audit APIs.
- [x] Replace the Skills Security placeholder with real Skill, regression, and Policy views.
- [x] Pass backend, OPA, migration, Web, E2E, Trace, and tenant-isolation acceptance.
- [x] Merge and create `v0.3.0-security-gate`.
- **Status:** complete

### Phase 4.3: AG-UI AgentTargetAdapter

- [x] Add the stable AG-UI protocol runtime and typed HTTP/SSE adapter.
- [x] Map lifecycle, message, tool, state, usage, cancellation, and redacted reasoning events.
- [x] Add a deterministic Fake AG-UI target, Compose E2E, Trace, and Web target registration.
- **Status:** complete on `codex/ag-ui-adapter`; no release tag has been assigned

### Phase 4.4: v0.4 AG-UI reliability release

- [x] Run OPA 1.17.0 in CI and include it in readiness checks.
- [x] Propagate running cancellation into active AG-UI streams.
- [x] Reject hardcoded-secret Skill imports before content persistence.
- [x] Require a non-BLOCK scan before Skill binding and enforce frozen-row immutability.
- [x] Complete PolicyBundle-to-GatePolicy Web workflow and container health checks.
- [x] Cold-build, verify, merge, and create `v0.4.0-ag-ui`.
- **Status:** complete

### Phase 4.5: v0.5 multi-Skill reliability

- [x] Validate `aqh.skill-manifest/v1` and atomically validate/replace Skill bindings.
- [x] Normalize cross-protocol `aqh.skill-event/v1` telemetry without raw content.
- [x] Score Skill selection, identity, lifecycle, coverage, and evidence grounding.
- [x] Add versioned Skill/Evidence Gate controls with UNKNOWN fail-closed behavior.
- [x] Add binding, coverage, reliability, and Gate-source Web views.
- [x] Pass 32-Skill/200-Case scale checks and create `v0.5.0-multi-skill-reliability`.
- **Status:** complete

### Phase 5: Real-system targets

- [x] Register AgriGraph as a real target without modifying its repository.
- [x] Register Document Autoflow as a real target without modifying its repository.
- [x] Freeze cross-project contract fixtures and source fingerprints.
- [x] Record an AgriGraph 40-case characterization and a Document Autoflow live smoke result.
- [x] Record current Document Run #30 with 24/24 Characterization results and Run #31 with a real Stability BLOCK.
- [x] Revalidate AgriGraph after a rotated Embedding key and atomic 1024-dimensional index rebuild; Runs #32/#33/#34 complete with a real Stability SHIP.
- **Status:** complete for both current real targets; comparisons are explicitly current-snapshot Stability Gates

### Phase 6: Distributed deployment enhancements

- [x] Add PostgreSQL Outbox and Kafka as an optional distributed profile after the verified Redis MVP.
- [x] Add Kafka consumer, Inbox idempotency, recovery and DLQ tests; Run #14 verifies the distributed path.
- [x] Keep Redis as the default queue; Kafka does not silently replace the core topology.
- [x] Add Kubernetes manifests and statically render/validate 20 objects.
- [ ] Run kind/HPA acceptance; intentionally excluded from the storage-bounded local closeout.
- **Status:** optional Kafka path and static manifests complete; local cluster and remote deployment unverified

### Project closeout A-D

- [x] **A - Document target:** diagnose Run #54 from persisted AQH, Document Autoflow, and Temporal state; complete the frozen 24-case characterization with bounded per-case terminal behavior and the existing USD 1 budget fuse.
- [x] **B - Real release gates:** create legitimate Baseline/Candidate versions from real, separately identified target snapshots; rerun only the minimum frozen evaluation needed and produce non-fabricated Gate decisions.
- [x] **C - Hallucination evaluation:** retain deterministic EvidenceRef/claim checks, add a bounded optional model-judge path with provenance, calibration fixtures, UNKNOWN handling, and a policy control; never claim universal open-domain hallucination detection.
- [x] **D - Remaining enhancements:** verify experimental MCP Tasks, optional Hermes compatibility, Kafka Outbox/Inbox/DLQ, and static Kubernetes manifests.
- [x] Re-run backend, migration, Web, Compose, protocol/event paths and static manifest validation; keep kind/HPA explicitly unverified.
- **Status:** complete within the storage-bounded scope; local cluster acceptance remains optional/unverified
- **Explicit exclusions:** remote GitHub Actions execution and public/production deployment hardening are not part of this closeout.

### Docker recovery and storage budget

- [x] Make the default Compose topology core-only; protocol, observability, distributed, and kind services require explicit profiles.
- [x] Split the API and HTTP Fake Agent from the full Worker dependency image.
- [x] Use conflict-free configurable host ports without changing container service discovery.
- [x] Rebuild only the core topology and keep Docker total usage below 20 GB with at least 20 GB free on E:.
- [x] Bootstrap a fresh local administrator and execute a real Fake Agent EvalRun through the rebuilt stack.
- [x] Record image, volume, cache, and free-space measurements after acceptance.
- **Status:** complete

## Product Boundaries

- The product is `Agent Quality Harness: Agent Evaluation, Observability, and Release Gates`.
- Inspect AI is the Evaluation Harness execution core.
- DeepAgents is a complex system under test, not the platform runtime.
- HTTP, SSE, AG-UI, and A2A are AgentTargetAdapters.
- MCP is a ToolTargetAdapter and is not interchangeable with A2A.
- The platform is not a model management console or a generic Agent CRUD suite.
- It does not copy Chenguang source code or inherit its mock-first behavior.

## UI Boundaries

- Framework: Vue 3, TypeScript, Element Plus, Vite; Apache ECharts is allowed for real metrics.
- Navigation: Overview, Targets, Datasets, Runs, Version Compare, Trace & Replay, Release Gates, Usage & Cost, Skills Security, Connections.
- First product screens: Eval Run detail, Version Compare, Release Gate.
- No marketing landing page, placeholder charts, silent mocks, knowledge-base CRUD, prompt CRUD, model/tool marketplaces, general chat, star ratings, or broad RBAC CRUD.

### Phase 7: Multi-agent scenario control plane and current-environment revalidation

- [x] Add frozen `aqh.scenario/v1` targets, validation, deterministic DAG execution, and persistent ScenarioRun/ScenarioNodeRun state.
- [x] Add Shadow and Gate-authorized local Pilot execution with idempotency, limits, cancellation, and fail-closed budget handling.
- [x] Connect AG-UI Researcher, MCP Tasks Evidence Tool, A2A Reviewer, and DeepAgents Coordinator through Inspect AI.
- [x] Verify Good/Bad through Redis and the Good path through PostgreSQL Outbox/Kafka; preserve failed Kafka recovery attempts as evidence.
- [x] Split Kafka client dependencies from default API/Core Worker images and enforce storage-aware Compose limits.
- [x] Revalidate AgriGraph after 1024-dimensional preflight and atomic ES rebuild: Run #32 smoke, Run #33 40-case Characterization, and Run #34 Stability SHIP.
- [x] Revalidate Document Autoflow in the rebuilt database: Run #29 smoke, Run #30 24-case Characterization, and Run #31 Stability BLOCK.
- [x] Reconcile README, task plan, traceability, progress, and findings; remove interview/demo material.
- **Status:** complete within the storage-bounded local scope
- **Security resolution:** the exposed key was not used; a locally supplied rotated key completed the preflight and vector rebuild without entering logs or the repository.

## Key Technical Decisions

| Decision | Rationale |
|---|---|
| Redis claims one EvalRun per job | Keeps MVP queue semantics simple while Inspect AI controls bounded case concurrency. |
| Unknown token and cost fields use `null` plus explicit provenance/status | Zero is a measured value and must never stand in for missing telemetry. |
| External tool charges are recorded separately | Model token pricing and third-party tool billing have different units and provenance. |
| PricingSnapshot is immutable and versioned | Historical reports must remain reproducible after price changes. |
| Deterministic scorers outrank judges | Safety, tool, schema, and business assertions must remain reproducible. |
| Kafka and Kubernetes are optional | They are resume claims only after the underlying evaluation path is real and tested. |

## Errors Encountered

| Error | Attempt | Resolution |
|---|---:|---|
| `rg.exe` access denied on the F: drive during initial read-only inspection | 1 | Use PowerShell file enumeration and `Select-String` on this machine. |
| Inspect AI `TaskState.model_fields` introspection failed | 1 | Treat `TaskState` as Inspect's state class and inspect its source/signature instead of assuming Pydantic. |
| First Ruff pass reported 9 findings | 1 | Use `Annotated` FastAPI dependencies, remove the unused import, and format the long import. |
| Package import failed before editable install | 1 | Install this project with `pip install -e .` after the first lint fixes. |
| Bare `pytest` under `conda run` resolved to the `openai` environment | 1 | Always invoke tools as `conda run -n agent-quality-gate python -m pytest/ruff`. |
| Second Ruff pass found 2 import-order issues | 1 | Apply Ruff's deterministic import sort, then rerun through the environment Python. |
| Inspect run log rejected an unregistered custom solver | 1 | Register the adapter solver with Inspect AI's `@solver` decorator. |
| Inspect control server cannot use AF_UNIX on Windows | 1 | Disable the optional control server explicitly; evaluation continues without it. |
| Docker could not pull `postgres:17-alpine` | 1 | Docker Desktop has no working HTTPS proxy; inspect existing images and local services instead of repeating the pull. |
| One-line async Redis probe had invalid Python syntax | 1 | Use the synchronous Redis client for the connectivity probe. |
| PostgreSQL version probe lost quotes around `current_setting` argument | 1 | Use `select version()` to avoid shell/Python nested quoting. |
| Conda wrapper raised GBK `UnicodeEncodeError` while forwarding Ruff output | 1 | Invoke `D:\\Codesoftwares\\anaconda\\Anaconda3\\envs\\agent-quality-gate\\python.exe` directly for project tooling. |
| Generated Alembic migration had one 133-character constraint line | 1 | Split the Python string without changing the SQL expression. |
| Port 8000 was already in use when starting the API | 1 | Leave the existing process untouched and use port 8010 for this session. |
| Worker exited on Redis `BRPOP` read timeout while idle | 1 | Set socket timeout above claim timeout and retry transient Redis errors with bounded exponential backoff. |
| Worker retry test could starve cancellation with an immediate queue stub | 1 | Yield to the event loop after every worker iteration; terminate only the stuck test process. |
| Planning catch-up example pointed to a missing `.codex` installation path | 1 | Use the installed script under `C:\Users\xzheng\.agents\skills\planning-with-files\scripts`. |
| PricingSnapshot API passed `Decimal` objects directly to JSONB | 1 | Normalize prices through Pydantic JSON mode at the API boundary. |
