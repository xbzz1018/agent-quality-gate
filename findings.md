# Findings and Decisions

## Requirements

- Build only project three in `F:\code\homework\project\agent-quality-gate`.
- Do not modify or rerun AgriGraph or Document Autoflow during platform construction.
- Every phase must end with real verification output; unfinished capabilities stay pending or optional.
- Installed packages are environment readiness, not implemented product features.
- Preserve the progression: Agent/GraphRAG governance, multimodal/Temporal workflow, then evaluation/trace/release gates.

## Baseline Findings

- The repository initially contained only `.gitignore`, `environment.yml`, `requirements.txt`, `README.md`, and local package caches.
- No `AGENTS.md` exists in the project ancestry checked from `F:\` through the project root.
- The project directory is not currently a Git repository.
- The Conda environment is named `agent-quality-gate` and specifies Python 3.12.
- Requirements include FastAPI, SQLAlchemy/Alembic/PostgreSQL, Redis, Inspect AI, DeepAgents, A2A, MCP, Kafka, OpenTelemetry, pytest, and Ruff.
- Package presence does not prove runtime integration.
- Installed Inspect AI 0.3.258 exposes `Task`, `MemoryDataset`, `Sample`, custom solver hooks, and `eval(..., max_samples=...)` needed for the MVP harness.
- Inspect AI `TaskState` is its own state class, not a Pydantic model; solvers set a `ModelOutput` on `state.output`.
- Redis 8.1.0 provides asyncio `lpush`/`brpop`, sufficient for a small whole-run MVP queue without adding another worker framework.
- Installed OpenTelemetry semantic-convention constants expose GenAI attributes from the incubating namespace; the application must isolate those imports behind its telemetry module.
- OpenTelemetry Semantic Conventions 1.44 marks GenAI conventions as moved/development. The MVP will emit the current low-cardinality keys (`gen_ai.operation.name`, `gen_ai.provider.name`, request/response model, input/output/cache/reasoning token counts) through a compatibility wrapper and will not record prompts, full private documents, API keys, or hidden reasoning.
- Agent invocation uses the well-known `invoke_agent` operation; tool execution uses `execute_tool`. Point-in-time run events belong in span events, while operations with duration remain child spans.

## Verified MVP Foundation

- PostgreSQL 17.11 and Redis 8 run in project-specific Docker Compose services on local ports 5432 and 6379.
- The initial Alembic migration upgrades, downgrades to an empty schema, upgrades again, and passes `alembic check` with no drift.
- A real integration path creates Target, two Versions, a frozen Dataset, and an EvalRun through FastAPI; Redis then dispatches one whole run to the Worker.
- Inspect AI executes both Baseline and Candidate across the dataset and persists four CaseResult/UsageMeasurement rows for two cases.
- HTTP and SSE adapters are contract-tested against an explicitly named Fake Agent.
- OTel GenAI attribute tests prove known token values are emitted and unknown values are omitted rather than reported as zero; the Worker has not yet initialized an SDK provider, so persisted Trace IDs are not yet verified.
- Collector/Jaeger runtime export is not yet verified because the required images are not local and Docker Hub access currently lacks a working HTTPS proxy.
- Dataset hashes are calculated at import time but are not yet recalculated before execution; immutability is therefore not yet enforced.

## Architecture Decisions

| Decision | Rationale |
|---|---|
| Use separate `AgentTargetAdapter` and `ToolTargetAdapter` interfaces | A2A/HTTP/SSE invoke agents; MCP evaluates tool/resource servers. Their contracts and threat models differ. |
| Use the database as the durable source of run state | Redis is an MVP dispatch mechanism, not the audit record. |
| Worker receives `run_id`, not one message per case | Inspect AI owns dataset execution and bounded concurrency inside the run. |
| Record telemetry as normalized observations with raw provenance | Provider token schemas vary and evolve. |
| Persist missing observations as null/UNKNOWN | Avoids turning unavailable measurements into false zero-cost claims. |
| Keep security and deterministic assertions outside judge overrides | Subjective graders cannot waive safety or tool-contract failures. |

## PostgreSQL Design Rules

- Use `bigint identity` primary keys for the single-database MVP.
- Add indexes for every foreign-key access path; PostgreSQL does not create them automatically.
- Use lowercase `snake_case`, `text`, `timestamptz`, booleans, and exact `numeric` monetary values.
- Add check constraints for persisted statuses, decisions, protocols, and measurement states.
- Match composite indexes to actual filters, with equality columns before time/range columns.
- Use partial indexes for active queue/run states where the predicate is stable.
- Never keep a database transaction open across target HTTP/SSE calls or evaluation execution.

## UI Findings

- Tiangong has no independent local frontend and is not a UI baseline.
- Chenguang is a React/Tailwind/shadcn management console with mock-first and placeholder surfaces; only its information categories may inspire navigation.
- The requested UI is a quiet, dense operations console with tables, split panes, audit trails, and real status data.
- The user selected Chenguang's checked-in frontend as the concrete visual source and Chrome as the browser verification target.
- Reuse is structural: sidebar/header/breadcrumbs, version tables, detail split panes, cost summaries, and audit tables. React components and mock services are not copied.
- The checked-in Chenguang frontend does not currently render: Vite cannot resolve `@/lib/utils` from its UI primitives. Source inspection remains usable, but Chenguang is not a runnable dependency or copy baseline.
- Vite will proxy relative `/api` requests to the local API so the backend does not need permissive CORS for development.
- The current public API lacks `GET /targets/{id}/versions`; the UI cannot choose Baseline/Candidate versions until that read endpoint is added.

## Multi-tenant Upgrade Decisions

- The identity record is global while organization membership and roles are tenant scoped; one user may switch among multiple memberships.
- Platform administration is a global user capability; organization administration is expressed through stable permission codes and organization roles.
- Browser access uses a short-lived access JWT held only in memory plus a rotating refresh-session cookie; service automation uses an organization-bound, hashed API key.
- Existing business rows must be assigned to a deterministic `default` organization by migration before tenant columns become non-null.
- Tenant isolation is enforced in service queries and route dependencies; PostgreSQL RLS and per-tenant databases remain outside the agreed scope.
- The captured Chenguang screenshots are the concrete visual source. React components and its mock data remain excluded; the Vue implementation adapts its spacing, navigation, hierarchy, and table density to real Quality Harness data.
- The migration creates a deterministic `default` organization, backfills every existing Target, Dataset, GatePolicy, PricingSnapshot, and EvalRun, then makes tenant columns non-null and replaces global unique constraints with organization-scoped constraints.
- Browser authentication retains only the access token in memory. The HttpOnly refresh cookie is SameSite Strict and rotates on every use; reuse revokes the whole session family.
- Service API keys are fixed to one organization, store only SHA-256 hashes plus display prefix, are returned in plaintext once, and can be revoked independently.
- The operations console now uses captured Chenguang proportions while its dashboard, cost chart, failure table, Gate audit, and management views are backed by live API data rather than copied mocks.

### Selected UI Design System

- App shell: fixed 256px white sidebar, 64px white breadcrumb header, and a cool gray full-height work area; mobile uses a navigation drawer.
- Palette: white surfaces, neutral gray text/borders/background, one restrained blue accent, and semantic green/amber/red only for decisions and failures.
- Geometry: 6-8px radii, 1px borders, almost no decorative shadow, 32-36px controls, and stable table row heights.
- Typography: system sans-serif, compact 13-14px controls/body, 20-24px page titles, normal letter spacing, and tabular numerals for metrics.
- Container model: full-width page bands, tables, split panes, drawers, dialogs, and only a small number of metric panels; no nested card grids.
- Core interaction: create/import/run workflows, selectable result rows, persistent event timelines, run cancellation, failed-case replay, comparison, and gate audit.
- Icons: Lucide outline icons for navigation and commands; text buttons remain only for explicit actions.
- Allowed first-screen copy: product name, current route/breadcrumb, real connection status, page title, filters, table labels, and explicit `Demo Fixture` provenance.

## Project Two Frozen Context

- Document Autoflow is frozen as a complete interview project: 24/24 parsed, schema and non-empty candidate success 100%, field F1 75.88%, evidence verification 96.20%, 98 backend tests passed, and Temporal reliability paths completed.
- Its correct positioning is multimodal document extraction, evidence verification, and exception-driven human review, not unattended automatic approval.
- These metrics are context only and were not rerun in this task.

## Resources

- Project book: `F:\code\homework\plan-md\03-Agent质量评测与发布门禁平台项目书.md`
- Project root: `F:\code\homework\project\agent-quality-gate`
- OpenTelemetry GenAI registry: `https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/`
