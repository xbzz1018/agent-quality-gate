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
- Product Design rules require a selected visual target before Vue scaffolding; backend work can proceed independently.

## Project Two Frozen Context

- Document Autoflow is frozen as a complete interview project: 24/24 parsed, schema and non-empty candidate success 100%, field F1 75.88%, evidence verification 96.20%, 98 backend tests passed, and Temporal reliability paths completed.
- Its correct positioning is multimodal document extraction, evidence verification, and exception-driven human review, not unattended automatic approval.
- These metrics are context only and were not rerun in this task.

## Resources

- Project book: `F:\code\homework\plan-md\03-Agent质量评测与发布门禁平台项目书.md`
- Project root: `F:\code\homework\project\agent-quality-gate`
- OpenTelemetry GenAI registry: `https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/`
