# Progress Log

## Session: 2026-08-21

### Phase 0: Scope and decision baseline

- **Status:** needs hardening
- Actions taken:
  - Re-read the project book, README, environment definition, and requirements.
  - Checked the project ancestry for `AGENTS.md`; none was found.
  - Confirmed the directory had environment files only and was not a Git repository.
  - Recorded the final product, adapter, telemetry, token/cost, UI, and enhancement boundaries.
  - Selected PostgreSQL schema rules for keys, foreign-key indexes, data types, constraints, run-query indexes, and short transactions.
- Files created/modified:
  - `task_plan.md` (created)
  - `findings.md` (created)
  - `progress.md` (created)
  - `findings.md` (updated with PostgreSQL design rules)

### Phase 1: Runnable MVP foundation

- **Status:** complete
- Actions taken:
  - Created the FastAPI application, versioned API routes, liveness, and PostgreSQL/Redis readiness probes.
  - Added 10 SQLAlchemy models and an Alembic initial migration with foreign-key, composite, and partial indexes.
  - Added HTTP/SSE AgentTargetAdapters and an explicitly named Fake Agent.
  - Added Redis whole-EvalRun queue and a runnable Worker.
  - Added Inspect AI Task/MemoryDataset/custom-solver execution with bounded sample concurrency.
  - Added eval.run/eval.case/agent.invoke span definitions and GenAI token attributes that omit unknown values; Worker provider initialization remains pending.
  - Verified real API -> PostgreSQL -> Redis -> Worker -> Inspect -> PostgreSQL execution.
- Files created/modified:
  - `pyproject.toml`, `.env.example`, `docker-compose.yml`
  - `alembic.ini`, `alembic/env.py`, initial migration
  - `src/agent_quality_harness/` application package
  - `tests/` unit, contract, schema, telemetry, and integration tests

### Phase 2: Evaluation and release-gate core

- **Status:** backend MVP complete
- Actions taken:
  - Added pre-run Dataset/Case SHA-256 revalidation and strict capture-count checks.
  - Added ready/processing/ack Redis semantics, database lease, heartbeat, stale recovery, and duplicate-safe claims.
  - Added Inspect custom deterministic scoring for final action, output/schema, tools, citations, safety, and business rules.
  - Added immutable PricingSnapshot, eight token categories, cost status, and separate external tool cost.
  - Added versioned SHIP/WARN/BLOCK policies, comparison metrics, persistent redacted RunEvent records, cancellation, and failed-case replay.
  - Added list/detail/event/comparison/gate APIs, Gate CLI, GitHub Actions, backend Docker image, and API/Worker Compose services.
  - Added 80 core plus 20 stability Demo Fixture cases and read-only target templates for AgriGraph and Document Autoflow.
  - Collector/Jaeger export, Vue UI, and live target rounds remain pending.

## Test Results

| Test | Command | Expected | Actual | Status |
|---|---|---|---|---|
| Planning session catch-up | `session-catchup.py` | Detect prior unsynced work | No prior session data reported | PASS |
| Git baseline check | `git status --short --branch` | Report repository state | Not a Git repository | INFO |
| Ruff | `python -m ruff check .` | No findings | All checks passed | PASS |
| Unit and contract tests | `python -m pytest -m 'not integration'` | Offline suite passes | 11 passed, 1 deselected | PASS |
| PostgreSQL/Redis probes | project service probes | Both dependencies healthy | PostgreSQL 17.11, Redis PING true | PASS |
| Alembic forward migration | `python -m alembic upgrade head` | Initial schema created | Revision 3b92e7aa7d28 applied | PASS |
| Alembic reversibility | downgrade base then upgrade head | Empty schema rebuilds | Both commands succeeded | PASS |
| Alembic drift | `python -m alembic check` | No metadata drift | No new upgrade operations | PASS |
| Real run integration | `AQH_RUN_INTEGRATION=1 pytest tests/test_integration_run.py` | API/Redis/Inspect/PostgreSQL chain passes | 1 passed | PASS |
| Worker idle resilience | background Worker plus Redis retry regression | Worker remains alive after empty queue/timeout | Worker PID 45740 alive; retry test passed | PASS |
| Live API readiness | `GET http://127.0.0.1:8010/api/v1/health/ready` | PostgreSQL and Redis ready | Both components `ok` | PASS |
| Phase 2 Ruff | `python -m ruff check .` | No findings | All checks passed | PASS |
| Phase 2 offline suite | `python -m pytest -m 'not integration'` | Offline suite passes | 26 passed, 1 deselected | PASS |
| Full suite | `AQH_RUN_INTEGRATION=1 python -m pytest` | All tests pass | 27 passed | PASS |
| Enhanced E2E | `AQH_RUN_INTEGRATION=1 pytest tests/test_integration_run.py` | Score, Trace, Gate, replay, cancel | 1 passed | PASS |
| Phase 2 migration reversibility | downgrade one revision, upgrade head, `alembic check` | Reversible and no drift | All three commands passed | PASS |
| Compose validation | `docker compose config --quiet` | Valid configuration | Exit 0 | PASS |

## Error Log

| Timestamp | Error | Attempt | Resolution |
|---|---|---:|---|
| 2026-08-16 | `rg.exe` access denied on F: | 1 | Switched to PowerShell read-only enumeration. |
| 2026-08-21 | `git status` failed because no `.git` exists | 1 | Recorded the absence; no destructive or implicit Git initialization. |
| 2026-08-21 | Inspect AI `TaskState` has no `model_fields` attribute | 1 | Switched from Pydantic introspection to source/signature inspection. |
| 2026-08-21 | Ruff found 9 issues in the first implementation pass | 1 | Fixing dependency annotations, imports, and formatting before rerun. |
| 2026-08-21 | `agent_quality_harness` was not importable before package install | 1 | Editable project install scheduled after lint cleanup. |
| 2026-08-21 | Bare `pytest` resolved to the separate `openai` Conda environment | 1 | Standardized commands on `conda run -n agent-quality-gate python -m ...`. |
| 2026-08-21 | Ruff found 2 import-order findings | 1 | Using Ruff's deterministic import fix before rerun. |
| 2026-08-21 | Inspect run failed because custom solver lacked registry metadata | 1 | Added Inspect's `@solver` decorator and scheduled a focused rerun. |
| 2026-08-21 | Inspect warned that AF_UNIX control server is unavailable on Windows | 1 | Disable the optional control server with `ctl_server=False`. |
| 2026-08-21 | Docker Hub pull for `postgres:17-alpine` timed out | 1 | Check existing images and already-running local PostgreSQL/Redis services; do not repeat identical pull. |
| 2026-08-21 | One-line async Redis connectivity probe was invalid syntax | 1 | Switched the probe to the synchronous Redis client. |
| 2026-08-21 | PostgreSQL version probe lost nested SQL quotes | 1 | Replaced it with `select version()`; container health was already green. |
| 2026-08-21 | Conda output wrapper could not encode Ruff output as GBK | 1 | Use the environment's absolute Python executable for subsequent commands. |
| 2026-08-21 | Alembic generated one overlong check-constraint line | 1 | Split the literal while preserving generated SQL. |
| 2026-08-21 | Port 8000 was already listening | 1 | Preserve the existing service and start project three on port 8010. |
| 2026-08-21 | Worker exited on a Redis blocking-pop read timeout | 1 | Added a 60-second socket timeout and bounded exponential retry for Redis errors. |
| 2026-08-21 | Worker retry test loop starved task cancellation | 1 | Added an explicit cooperative yield and terminated only the stuck pytest process. |
| 2026-08-22 | Planning catch-up script was first invoked from a missing `.codex` path | 1 | Located and used the installed script under `C:\Users\xzheng\.agents\skills\planning-with-files\scripts`. |
| 2026-08-22 | Enhanced integration test could not persist `Decimal` values in PricingSnapshot JSONB | 1 | Normalize the `prices` field with Pydantic JSON mode at the API boundary while retaining exact decimal parsing in the Pricing Engine. |
| 2026-08-22 | Built-in Image Gen tool is unavailable in this task | 1 | Stop before Vue scaffolding; the CLI fallback requires explicit user approval and an API key. |

## Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Phase 2, deterministic evaluation and release-gate core. |
| Where am I going? | Gate/Trace/Cost, UI, protocol/safety enhancements, real targets, optional distributed deployment. |
| What's the goal? | A reproducible Agent evaluation, observability, replay, and release-gate platform. |
| What have I learned? | See `findings.md`. |
| What have I done? | Phase 1 is verified; frozen dataset and Baseline/Candidate execution are already present. |
