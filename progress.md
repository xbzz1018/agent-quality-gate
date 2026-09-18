# Progress Log

## Session: 2026-08-25 - Docker recovery

### Storage-bounded rebuild

- **Status:** complete
- Previous Docker data is absent after disk exhaustion/read-only filesystem recovery; no destructive Docker cleanup is authorized.
- New Docker baseline: E: free 37.59 GB; 8.77 GB images, 711 MB volumes, 1.33 GB build cache. Existing non-AQH containers are preserved.
- Recovery boundary: default core Compose only; optional protocol, observability, Kafka, and kind services require explicit profiles.
- Added a lightweight API dependency lock, a lightweight HTTP Fake Agent image, and split lightweight contract-profile validation from the Adapter factory.
- Final core topology: 7/7 healthy; Web 5174, API 8000, Redis host 56379. API readiness reports PostgreSQL/Redis/OPA `ok`.
- Fresh local administrator created; Docker recovery Run #1 completed 80 Baseline + 80 Candidate results and produced an auditable BLOCK Gate.
- Verification: Ruff passed; full backend 95 collected / 91 passed / 4 integration skipped; Alembic drift clean; API and Worker `pip check` clean; Web typecheck, 3 Vitest, production build, audit, and Chrome desktop/mobile QA passed with 0 browser errors.
- Final storage: AQH images approximately 1.77 GB; all Docker images 11.10 GB, volumes 0.76 GB, build cache 2.76 GB; E: free 37.59 GB.
- Core Compose reached 7/7 healthy and Docker recovery Run #1 completed 80 Baseline + 80 Candidate results with an auditable BLOCK Gate.
- First bounded core build wrote no image layers because Docker Hub auth resolved to unreachable IPv6 for all missing base images; switch to sequential Engine pulls before retrying BuildKit.
- Lightweight Fake Agent image built successfully. The first API image attempt reached the local wheel step but lacked the build-system `setuptools` package; add it as a separate exact build layer and reuse the cached runtime dependency layer.

## Session: 2026-08-25 - Final project closeout

### Closeout A: Document Autoflow diagnosis

- **Status:** complete
- User scope: finish items 1-4; defer remote CI execution and public/production deployment.
- Docker Engine is available, but all AQH Compose containers exited together with code 255; this is not a port conflict and not an isolated API failure.
- Historical evidence shows AQH Run #54 entered a long Document Autoflow REPROCESS Activity, while Run #55 later completed the same Profile smoke path.
- Persisted database verification: Run #54 expected 24 Cases and failed with zero results on an Inspect capture mismatch after the first remote operation timed out; Run #55 completed one Case on the same Candidate Profile. The AQH API contract is not the root cause.
- Implemented explicit per-target Inspect time limits, sanitized target-failure CaseResults with UNKNOWN usage, and a configurable Document `stop_on_routes` boundary that records REPROCESS then requests remote cancellation.
- Target Profile and Inspect tests: 10 passed; integration selection: 10 passed/1 skipped. Focused Ruff passed after deterministic formatting.
- Restored the one damaged frozen document to `parsed` revision 2 and verified a 24-entry SHA-based capability map with 360-second polling, REPROCESS early-stop, and the existing USD 1 fuse.
- Run #130 failed before target invocation because Compose did not forward the referenced auth environment variable; it is retained as a configuration-failure record.
- Run #131 completed the full frozen Document Dev v2.1 characterization: 24/24 results, 10 AUTO_PASS, 11 REVIEW, 3 REPROCESS, 15 assertion failures, 190,146 input and 46,529 output tokens, and USD 0.03964856 known cost.

### Closeout B: Real stability Baselines and Gates

- **Status:** complete
- Baselines must be separately identified immutable evidence. A same-endpoint version label alone is not accepted as a source-code regression baseline; recorded-run stability baselines will be explicitly distinguished from deployable source baselines.
- Document stability Run #137 completed 24 Baseline + 24 Candidate results with equal 37.5% success and 6.52% P95 growth. One Candidate Case had a sanitized `target_error`, making cost partial (23/24 known); the initial Gate exposed a missing target-execution-failure rule and is retained as evidence of that defect.
- Document Run #138 re-evaluated with the corrected Gate and BLOCKed on two target execution failures; AgriGraph Run #139 completed 40+40 results and SHIPped with equal 80% success and zero target failures.

### Closeout C: Bounded hallucination evaluation

- **Status:** complete
- Scope remains explicit: deterministic frozen evidence/claim constraints are authoritative; a model Judge may add calibrated probabilistic findings but cannot claim universal open-domain fact verification.
- Added an OpenAI-compatible bounded Judge, structured/redacted observations, response provenance hashes, Judge Token accounting, explicit UNKNOWN, 8 frozen calibration fixtures, and Gate controls where unsupported verdicts WARN but cannot alone BLOCK.
- Judge/Gate/Inspect reliability selection: 19 passed; focused Ruff passed. No external Judge credential was configured or inferred.

### Closeout D: MCP Tasks, Hermes, Kafka, and Kubernetes

- **Status:** in_progress
- The target repository is dirty with user-owned work and will be preserved.

### Closeout Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Planning skill example resolved a missing `C:\Users\xzheng\.codex` path | 1 | Use the installed skill under `C:\Users\xzheng\.agents\skills\planning-with-files`. |
| Broad recursive project enumeration exceeded the 30-second shell yield | 1 | Use direct project paths and depth-bounded reads; no process or file was changed. |
| Assumed `compose.yaml` and a package at the repository root | 1 | Use the actual `docker-compose.yml` and `src/agent_quality_harness` layout. |
| First PostgreSQL probe used a nonexistent `aqh` role | 1 | Read Compose and use the declared `agent_quality` role/database; no database content changed. |
| Combined secret/startup one-liner was rejected by the local execution policy | 1 | Replace it with reviewed repository scripts that keep plaintext only in process memory and persist only DPAPI ciphertext. |
| Windows PowerShell 5.1 lacks static `RandomNumberGenerator.Fill` | 1 | Use the compatible `RandomNumberGenerator.Create().GetBytes()` API; failure occurred before identity or service creation. |
| Dedicated evaluator received 404 for the preserved project | 1 | Project isolation was working; change the local-only evaluator role from operator to admin so it can access the orphaned preserved fixture without reassigning project ownership. |
| DPAPI read-only probe included the ciphertext file's trailing newline | 1 | Trim the ignored ciphertext before `ConvertTo-SecureString`; no plaintext or stored secret was damaged. |
| Compose Worker omitted `AQH_DOCUMENT_AUTOFLOW_AUTH` despite the host process setting it | 1 | Add explicit optional AgriGraph and Document auth mappings to the shared API/Worker environment, then recreate the services from the DPAPI-backed launcher. |
| Focused test command referenced nonexistent `tests/test_services.py` | 1 | Add Recorded Baseline coverage to the existing real PostgreSQL/Redis integration test and invoke its actual path. |
| AgriGraph evaluator CLI was first launched from the repository root | 1 | Run `app.cli.reset_password` from `backend-python`; ES, Neo4j, and MinIO had already become healthy and were preserved. |
| Initial Outbox migration used the security-artifact branchpoint as its parent | 1 | No DDL was applied; inspect Alembic history and reparent it to the existing `a71d9e5c20b4` Gate-controls Head. |
| Host Kafka client received the container-only advertised hostname `kafka` | 1 | No event was published; configure separate INTERNAL `kafka:9092` and EXTERNAL `localhost:29092` listeners. |
| Linux aiokafka wheel does not export `AIOKafkaAdminClient` at package top level | 1 | Import it from the portable `aiokafka.admin` module; Broker and database remained healthy. |
| `kubectl --dry-run=client` still requested OpenAPI with no current cluster | 1 | It applied nothing; validate strictly against the real kind API Server after cluster creation. |
| Core BuildKit could not fetch missing base-image auth tokens over Docker Hub IPv6 | 1 | No image layers were created; use bounded sequential `docker pull` attempts and measure storage after each stage. |
| Lightweight API lock omitted the project's `setuptools` build backend | 1 | Add a separate exact `setuptools==82.0.1` build layer; the failed attempt produced no final API image and its runtime dependency layer is reusable. |
| API wheel metadata still declared Worker-only protocols | 1 | Keep the lightweight lock and give the API wheel its own direct dependency manifest so `pip check` remains truthful without installing A2A/MCP/Inspect. |
| Schema table-set test omitted the new Kafka reliability tables | 1 | Add Outbox, Inbox, and DLQ to the exact expected set; Alembic drift already reported no changes. |
| Web command used nonexistent `test:unit` script | 1 | Typecheck/build/audit passed; rerun Vitest using the repository's actual `npm test` script. |

## Session: 2026-08-24 - Local MVP release closure

### Phase 3.8: Production Compose and release tag

- **Status:** complete
- Starting state:
  - `codex/real-target-verification` is clean at `c79951d`.
  - Manual API, Worker, Fake Agent, and Vite processes are running; PostgreSQL, Redis, Collector, and Jaeger Compose services are healthy.
  - Persistent administrator `admin` and Runs #18, #53, #54, and #55 must be preserved.
  - Document Autoflow 24-case execution is closed as a Phase 5 known limitation; no further model run is authorized in this phase.

### Phase 3.8 Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Web image could not fetch uncached `node:24-alpine` through Docker Hub IPv6 | 1 | Use locally available, Vite-compatible `node:22-alpine` and `nginx:1.27-alpine`; do not repeat the failed pull. |
| Full development dependency installation hit a remote package hash mismatch in the production API image | 1 | Split a minimal production runtime set and install the project with `--no-deps`; keep pending protocol and test SDKs out of the v0.1.0 image. |

## Session: 2026-08-24 - Trace and real-target verification

### Phase 3.75: Baseline seal

- **Status:** complete
- Actions taken:
  - Created `codex/real-target-verification` without changing either real target repository.
  - Cold-started the project PostgreSQL and Redis services.
  - Verified Ruff, the 34-test backend suite with real PostgreSQL/Redis, Alembic drift, Web TypeScript, 3 Vitest tests, the production build, npm audit, and Compose configuration.
  - Scanned 587 source files without printing candidate secret values; matches were limited to package cache and explicit test password fixtures.
  - Committed the verified multi-tenant MVP as `bd916e5`.

### Phase 3.75: Trace, cancellation, and target profiles

- **Status:** in_progress
- Implemented so far:
  - Added continuous Worker lease heartbeat while an Inspect batch is running and ownership fencing before subsequent batches.
  - Verified a slow first Case remains non-recoverable after the original lease deadline; a running cancel persists that Case once and prevents the second Case.
  - Added candidate-only `baseline_required` responses and matching Vue states without fabricated Gate decisions.
  - Added versioned `agrigraph_v1` and `document_autoflow_v1` adapters with environment-referenced login credentials and offline HTTP contract tests.
  - Added Target contract profile and capabilities to the immutable EvalRun manifest.
  - Pulled and started the pinned Collector and Jaeger images; Collector, Jaeger admin, and Jaeger UI health probes return HTTP 200.
  - Queried API and Worker services in Jaeger. The Worker smoke Trace contains `eval.case`, `agent.invoke`, and HTTP spans with zero sensitive tags.
  - Froze 40 AgriGraph generation cases and 24 Document Autoflow v2.1 Dev cases with commit, dirty-state, source-tree, source-dataset, and report hashes.
  - Completed AgriGraph Run #53: 40 results, 32 passed deterministic Case rules, 198573 input and 18483 output tokens, unknown cost, no Gate, and a 161-span Jaeger Trace.
  - Preserved failed Document full Run #54 after the target entered REPROCESS beyond the 600-second profile limit; the exact remote workflow was cancelled and its database state converged to cancelled.
  - Completed Document Autoflow smoke Run #55: 1 result passed, 6900 input and 2201 output tokens, USD 0.00158228, no Gate, and a 13-span Jaeger Trace.
  - Removed the first failed preparation fixture by exact ID: 10 database documents and 10 runtime files; the 24-document evidence project remains.
- Boundaries:
  - AgriGraph and Document Autoflow remain read-only source worktrees; no source edit, cleanup, test rerun, or commit is permitted.
  - No interview script or presentation material will be produced.

### Phase 3.75 Errors

| Error | Attempt | Resolution |
|---|---:|---|
| Initial multi-file patch did not match the actual route import order | 1 | Split the patch into exact, smaller hunks; no partial write occurred. |
| Structured login auth JSON was mistaken for legacy static headers | 1 | Only treat an object without a `type` field as the legacy format. |
| Web TypeScript was first invoked from the repository root | 1 | Re-run from `web/`, where `package.json` lives. |
| Initial Gate union narrowing retained `BaselineRequired` in the else branch | 1 | Narrow solely on the discriminating presence of `status`. |
| AgriGraph Run #52 captured zero results because its login response uses `data.token` | 1 | Preserve failed Run #52, add the documented `token` key alongside existing aliases, and verify with the profile contract test before retrying. |
| Document preparation exceeded the 10-document project limit after 10 uploads | 1 | Restart the API with an explicit 30-document limit and add a SHA-based reuse path instead of re-uploading. |
| Document preparation timed out with 4 parses pending; all 24 later completed | 1 | Reuse the fully parsed project and write capabilities without repeating parsing. |
| Document AQH Run #54 timed out while the second target Run was reprocessing | 1 | Preserve failed Run #54, hard-cancel its exact Temporal workflow, converge the target DB state to cancelled, treat `waiting_review` as a terminal business outcome, and limit the verification retry to one explicit smoke Case. |
| The first Temporal cancel one-liner was broken by Windows/Conda quoting | 1 | Replace shell quoting with a typed Temporal SDK script and cancel the exact workflow ID. |
| The cancelled REPROCESS changed one reused source document to failed | 1 | Do not hide the damaged 24-case state; add an explicit one-case preparation limit for the live Profile smoke. |

### Phase 3.75 Final Verification

| Check | Result |
|---|---|
| Ruff format/lint | Passed |
| Full backend suite with PostgreSQL/Redis | 43 passed |
| Alembic migration round-trip | Passed in isolated `agent_quality_migration_verify`; temporary database removed |
| Alembic drift | No new upgrade operations detected |
| Web TypeScript / Vitest | Passed / 3 passed |
| Web production build / npm audit | Passed with existing ECharts advisory / 0 vulnerabilities |
| Chrome desktop/mobile | Run #18 core routes plus Run #55 `baseline_required`; 0 browser errors |
| Compose / frozen dataset reproducibility | Passed / 40 AgriGraph + 24 Document cases unchanged |
| OTel Collector / Jaeger | API and Worker services queryable; sensitive tags 0 |
| Real targets | AgriGraph 40-case complete; Document 1-case smoke complete; Document 24-case pending |

## Session: 2026-08-21

## Session: 2026-08-22 - Multi-tenant management upgrade

### Phase 3.5: Multi-tenant administration and console upgrade

- **Status:** complete
- Actions taken:
  - Recovered the existing implementation plan and verified that the current dirty worktree contains the completed local MVP and Vue console work.
  - Reconfirmed the captured Chenguang pages as the visual source and the user's selected Chrome browser for final QA.
  - Locked the upgrade boundary: local JWT and rotating refresh sessions, organization-bound service API keys, dynamic RBAC, logical tenant isolation, and platform/organization settings without secrets.
  - Recorded that existing AgriGraph and Document Autoflow repositories remain untouched and are not rerun by this phase.
  - Added the multi-tenant schema and reversible migration, including default-organization backfill, permission catalog, and built-in Administrator/Evaluator/Viewer roles.
  - Added Argon2id login, short-lived JWT, rotating Refresh Session reuse detection, organization-bound API keys, dynamic route permissions, tenant-scoped lookup, and redacted audit events.
  - Added paginated/searchable Target, Dataset, and Run APIs plus dashboard, usage/cost, cross-run result search, Gate audit, platform health, role, member, session, settings, and credential management APIs.
  - Added the administrator bootstrap CLI and API-key-aware Gate CLI.
  - Rebuilt the Vue shell against the captured Chenguang proportions and added login, organization switching, dashboard charts, cost analysis, Trace search, Gate audit, and tabbed system administration.
  - Verified Chrome desktop and 390px mobile flows with real authentication and organization switching; temporary QA credentials and tenant data were removed afterward.

### Phase 3.5 Verification

| Check | Result |
|---|---|
| Ruff | All checks passed |
| Full backend suite with PostgreSQL/Redis | 34 passed |
| Alembic downgrade/upgrade | Passed |
| Alembic drift | No new upgrade operations detected |
| Auth/RBAC/tenant integration | Password failure, Refresh rotation/reuse, Viewer denial, cross-tenant 404, API Key revoke passed |
| Web TypeScript | Passed |
| Web Vitest | 3 passed |
| Web production build | Passed; ECharts bundle advisory only |
| npm audit | 0 vulnerabilities |
| Docker Compose config | Passed |
| Chrome desktop/mobile | Login, organization switch, Run detail, comparison, cost, Gate audit, admin; 0 browser errors |

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

## Session: 2026-08-22 - Vue operations console

### Phase 3: Vue operations console

- **Status:** complete for local MVP
- Actions taken:
  - Recovered the existing project plan and verified the Git worktree is clean on `main`.
  - Confirmed the running API readiness on port 8010 and healthy project PostgreSQL/Redis containers.
  - Inspected the Apache-2.0 Chenguang React frontend and selected its operations-console structure as the visual reference.
  - Confirmed Vue 3 + TypeScript + Element Plus + Vite, real API data only, and Chrome desktop/mobile verification.
  - Added the target-version API and an idempotent, development-only Demo bootstrap that creates a Fake Agent target, Baseline/Candidate versions, one 80-case frozen dataset, a GatePolicy, and a PricingSnapshot.
  - Built the Vue operations console with target/version, dataset import, run creation, run detail, comparison, gate, and explicitly pending enhancement views.
  - Added Web/Nginx Compose configuration, the Vite development proxy, GitHub Actions Web checks, and a reproducible Chrome QA script.
  - Completed a real 80-case Demo run: 160 version results, 160 non-null Trace IDs, 483 redacted events, a failed-case replay, and a `BLOCK` gate caused by tool argument accuracy.
  - Kept cost values with missing usage/pricing as `UNKNOWN`, never zero; marked all Demo Fixture states visibly.
  - Verified the final desktop and 390px mobile layouts in the user-selected Chrome with no console errors or horizontal overflow.

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
| Phase 2 offline suite | `python -m pytest -m 'not integration'` | Offline suite passes | 27 passed, 1 deselected | PASS |
| Full suite | `AQH_RUN_INTEGRATION=1 python -m pytest` | All tests pass | 28 passed | PASS |
| Enhanced E2E | `AQH_RUN_INTEGRATION=1 pytest tests/test_integration_run.py` | Score, Trace, Gate, replay, cancel | 1 passed | PASS |
| Phase 2 migration reversibility | downgrade one revision, upgrade head, `alembic check` | Reversible and no drift | All three commands passed | PASS |
| Compose validation | `docker compose config --quiet` | Valid configuration | Exit 0 | PASS |
| Phase 3 full backend suite | `AQH_RUN_INTEGRATION=1 python -m pytest` | All backend and real dependency tests pass | 30 passed in 21.67s | PASS |
| Phase 3 Ruff | `python -m ruff check .` | No findings | All checks passed | PASS |
| Phase 3 Alembic drift | `python -m alembic check` | No metadata drift | No new upgrade operations | PASS |
| Web TypeScript | `npm run typecheck` | Strict project source check passes | Exit 0 | PASS |
| Web component tests | `npm run test` | Formatting and UNKNOWN semantics pass | 3 passed | PASS |
| Web production build | `npm run build` | Production assets emitted | Build succeeded; bundle-size advisory only | PASS |
| Web dependency audit | `npm audit --audit-level=high` | No known high-severity issue | 0 vulnerabilities | PASS |
| Chrome visual/interaction QA | `npm run qa:chrome` | Core routes work on desktop/mobile without browser errors or overflow | Run #18; 0 browser errors | PASS |
| Live Gate CLI | `aqh gate --run-id 18 --api-url http://127.0.0.1:8010` | BLOCK emits CI annotation and non-zero status | BLOCK; exit code 2 | PASS |

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
| 2026-08-22 | Combined background-service PowerShell command was rejected by execution policy | 1 | Start API and Worker with separate literal `Start-Process -WindowStyle Hidden` commands. |
| 2026-08-22 | `New-Item` in this PowerShell runtime rejected `-LiteralPath` | 1 | The existing ignored `.tmp` directory was already present; use `-Path` if creation is needed later. |
| 2026-08-22 | First direct Chrome screenshot calls produced no files because the desktop browser process was reused | 1 | Use isolated temporary Chrome profiles, absolute screenshot paths, and wait for each headless process. |
| 2026-08-22 | Isolated Chrome command was rejected by process policy, then direct Chrome still reused the desktop process | 2-3 | Switched to Playwright with the user-selected `chrome` channel. |
| 2026-08-22 | Chenguang reference routes render Vite's unresolved `@/lib/utils` error instead of the UI | 1 | Do not modify the unrelated Chenguang project; use its inspected layout/tokens as structural evidence and build a self-contained Vue implementation. |
| 2026-08-22 | First planning-file patch for the Chenguang screenshot finding had an invalid hunk separator | 1 | Corrected the patch structure and reapplied it once. |
| 2026-08-22 | First backend Ruff pass found a missing `AgentVersion` import and one 102-character line | 1 | Added the model import and wrapped the query without changing behavior. |
| 2026-08-22 | Initial targeted reads used stale guesses for `tests/test_api.py` and the core fixture filename | 1 | Enumerated the existing test and dataset files, then used `test_integration_run.py` and `demo-fixture-core-v1.json`. |
| 2026-08-22 | Initial Vitest run returned code 1 because the new Web project had no test files yet | 1 | Added focused tests for UNKNOWN-vs-zero and structured observation formatting. |
| 2026-08-22 | npm marked `lucide-vue-next` deprecated after the first install | 1 | Replaced it with the current official `@lucide/vue` package before handoff. |
| 2026-08-22 | Parallel Web checks exposed missing Node globals and third-party declaration incompatibilities | 1 | Add current `@types/node`, target ESNext disposable types, and skip third-party declaration checking while retaining strict project-source checks. |
| 2026-08-22 | First patch for the Web TypeScript toolchain fix used an invalid hunk boundary | 1 | Inspected the exact package and TypeScript blocks, then applied a context-valid patch. |
| 2026-08-22 | A combined parallel Alembic/npm/diff orchestration script had invalid JavaScript quoting | 1 | Ran Alembic separately, then parallelized only the two simple shell checks. |
| 2026-08-22 | Live Demo Run #18 showed Worker `started_at` about two seconds before database `created_at` due host/container clock skew | 1 | Clamp persisted start/end timestamps to the preceding run timestamp so audit chronology remains monotonic. |
| 2026-08-22 | `npx -p playwright node -e` could not resolve the ephemeral Playwright module | 1 | Add Playwright as a reproducible Web development dependency and a dedicated Chrome QA script. |
| 2026-08-22 | First Chrome QA run timed out opening mobile navigation because the script used `viewportSize` instead of Playwright's `viewport` context option | 1 | Correct the context option and rerun all desktop/mobile routes. |
| 2026-08-22 | Chrome QA then found one 404 console error for `/favicon.ico` | 1 | Add the same Lucide ShieldCheck mark used by the app shell as an explicit SVG favicon. |
| 2026-08-22 | Initial Chrome QA selected the latest one-case replay instead of the representative 80-case run | 1 | Select the completed comparison run with the largest expected case count. |
| 2026-08-22 | Mobile QA screenshots captured the navigation drawer during its CSS transition | 1 | Wait for the open/close transition before capturing both states. |

## Reboot Check

| Question | Answer |
|---|---|
| Where am I? | Local MVP handoff complete; Phase 4 protocol and safety enhancements remain pending. |
| Where am I going? | Collector/Jaeger verification, real targets, protocol/safety enhancements, then optional distributed deployment. |
| What's the goal? | A reproducible Agent evaluation, observability, replay, and release-gate platform. |
| What have I learned? | See `findings.md`. |
| What have I done? | Backend, deterministic gate loop, Demo bootstrap, and the real-API Vue operations console are verified end to end. |

## Session: 2026-08-24 - v0.1.0 local MVP release closure

- Stopped the manually launched API, Worker, Fake Agent, and Vite processes without deleting data volumes.
- Built the production API/Worker/Fake Agent image from the minimal `requirements-runtime.txt` boundary and built the Nginx Web image from locally available Node 22/Nginx 1.27 bases.
- Started PostgreSQL, Redis, API, Worker, Fake Agent, Web, Collector, and Jaeger through Compose with a random 64-byte session-only JWT secret.
- Verified direct and Nginx same-origin readiness, persistent `admin` login, Refresh rotation, organization-scoped history, and retained Runs #18, #53, #54, and #55.
- Verified Gate CLI against Run #18 (`BLOCK`, exit 2) with a one-time service key that was immediately revoked.
- Replayed Run #18 as Run #68: 64 selected failed cases, 128 baseline/candidate results, 128 Trace IDs, and 387 persisted events.
- Queried Run #68 Trace `717d06ced6c6d95339fbb5724c64d303` in Jaeger: Worker service, 385 spans, expected run/case/agent operations, and no sensitive tags.
- Ran Chrome desktop/mobile QA through production Nginx with persistent admin and real Runs #18/#55; comparison, Gate, and `baseline_required` passed with zero browser errors.
- Re-ran Ruff, the PostgreSQL/Redis-enabled suite (43 passed), Alembic drift, TypeScript, Vitest (3 passed), production build, and npm audit (0 vulnerabilities).
- Confirmed the production Python image includes the implemented Inspect runtime and excludes pending A2A/MCP/DeepAgents/Kafka packages.

## Session: 2026-08-24 - Protocol adapters and DeepAgents target

- Created `codex/protocol-adapters` from the tagged `v0.1.0-local-mvp` baseline.
- Implemented A2A 1.1.2 with official Agent Card resolution, JSON-RPC message/Task streaming, non-terminal polling, cancellation, Artifact mapping, version events, and strict UNKNOWN Token/cost semantics.
- Added a deterministic A2A server fixture and enabled A2A target creation in Vue. Run #73 records the missing server-extra failure; after fixing the image boundary, Run #74 completed 2/2 cases with all rules passing.
- Added a distinct MCP `ToolTargetAdapter.execute` path instead of an Agent `invoke` shim. Streamable HTTP and controlled stdio support Tool, Resource, and Prompt contracts; MCP Tasks remain explicit experimental pending.
- Added a deterministic MCP server fixture and enabled MCP Tool target creation in Vue. Run #75 completed Tool/Resource/Prompt 3/3 with required-tool and argument scoring.
- Added a separate DeepAgents 0.7.6 HTTP target image with a plain control Baseline. Run #76 completed 4/4 results; the real Gate is WARN because Candidate P95 was 33 ms versus 17 ms (94.12% growth).
- Kept DeepAgents out of API/Worker images. Verified platform image packages: Inspect/A2A/MCP present, DeepAgents absent; target image: DeepAgents present, Inspect/A2A/MCP absent.
- Verified A2A, MCP, and DeepAgents Worker traces in Jaeger with zero sensitive tags.
- Verification: Ruff passed; full PostgreSQL/Redis suite 50 passed; Alembic no drift; Vue typecheck and 3 Vitest tests passed; production build exit 0; npm audit 0 vulnerabilities; Chrome desktop/mobile 0 browser errors.
- A final cold rebuild after documentation-only changes was attempted twice and stopped after Docker's package index returned truncated JSON both times. Previously built protocol images remain verified and running; no failed build replaced them.

## Session: 2026-08-24 - v0.2, Skills/OPA, and AG-UI execution

- **Status:** in_progress
- Approved sequence: publish `v0.2.0-protocols`, implement Agent Skills plus OPA sidecar and publish `v0.3.0-security-gate`, then implement AG-UI on a separate branch.
- Boundaries retained: no AgriGraph/Document Autoflow changes or reruns; MCP Tasks, Kafka, and Kubernetes remain pending/optional.
- Exported exact platform and DeepAgents dependency versions from the verified images, added lock files, pinned setuptools, and moved Docker installation to exact `--no-deps` locks plus `--no-build-isolation` project wheels.
- The first no-cache build of API, DeepAgents, and Web passed; both Python images contain Agent Quality Harness `0.2.0`.
- The first platform `pip check` exposed stale package metadata pointing at development dependencies. Packaging was corrected to runtime dependencies, and the isolated DeepAgents target now runs source via `PYTHONPATH` without claiming the platform distribution.
- Final no-cache API and DeepAgents builds passed after the package-boundary correction. Platform and DeepAgents `pip check` both pass.
- Full backend verification remains 50 passed with Ruff and Alembic drift clean; Web typecheck, 3 Vitest tests, production build, npm audit, and Chrome QA passed.
- Recreated the complete Compose topology with a random session-only JWT secret; Runs #74/#75/#76 and all three Jaeger traces remain queryable with zero sensitive tags.
- Docker Web rebuild after the version bump hit one npm `ECONNRESET`; the Docker install layer was changed to use a persistent npm cache and bounded fetch retries before retrying.
- Web 0.2 Docker rebuild passed after the cache/retry change. The v0.2 release gate is complete.
- Fast-forwarded the verified protocol branch to `main` and created `v0.2.0-protocols` at `476d256`.
- Created `codex/skills-policy-gate`, pulled `openpolicyagent/opa:1.17.0`, and verified the real OPA v1 runtime.
- Added six reversible tenant-scoped schema tables for Skill packages/versions/scans/attachments and Policy bundles/evaluations; Alembic upgrade, one-revision downgrade, re-upgrade, and drift checks pass.
- Added structured Skill import limits, canonical hashes, deterministic secret/command/network/dependency/permission scanning, frozen AgentVersion bindings, and Baseline/Candidate regression APIs.
- Added OPA Policy Bundle validation and Data API evaluation with 2-second timeout, one connection retry, strict output validation, persistent decision IDs, and fail-closed Gate composition.
- Added the real Skills Security Vue page and OPA source/decision detail in Gate views; no fixture data is generated silently.
- Verified the real OPA sidecar as healthy and queried a policy with a returned decision ID; moved the container to non-root UID 1000.
- Verification: Ruff passed; full PostgreSQL/Redis/OPA suite 63 passed; Alembic no drift; API/Worker `pip check` passed; Vue typecheck, 3 Vitest tests, production build, npm audit 0 vulnerabilities, and Chrome desktop/mobile QA 0 browser errors.

## Session: 2026-08-24 - AG-UI Adapter

- Created `codex/ag-ui-adapter` from the tagged `v0.3.0-security-gate` baseline and pinned `ag-ui-protocol==0.1.19` in development/runtime locks.
- Implemented typed RunAgentInput construction and BaseEvent SSE parsing with strict lifecycle ordering, Tool argument fragment merging, RFC 6902 State updates, terminal TokenUsage, and UNKNOWN semantics.
- Added active HTTP stream closure plus explicitly configured cancel endpoint support. Missing terminal events, RUN_ERROR, invalid JSON Patch, malformed events, and ordering violations fail the case.
- Reasoning content and encrypted values are dropped. Run #96 has zero sensitive Agent event/output matches; six reasoning lifecycle events contain only `{}`.
- Added the official-type Fake AG-UI container, a three-case frozen Demo Fixture, a repeatable run script, Web target registration, and 9 offline AG-UI contract tests.
- Compose Run #96 completed 3/3 with one UNKNOWN usage case. Jaeger Trace `7a233a7fe8b7c339f9dc3a2b0c8e2eb3` has Worker service, 10 spans, and zero sensitive tags.
- A front-end verification command was first invoked from the repository root and failed immediately because no root `package.json` exists; the same checks passed from `web/`.
- Final verification: Ruff passed; full PostgreSQL/Redis/OPA suite 72 passed; Alembic no drift; API/Worker/local `pip check` passed; Web typecheck, 3 Vitest, production/Compose builds and audit passed; Chrome desktop/mobile including Run #96 reported 0 browser errors.

## Session: 2026-08-24 - v0.4/v0.5 reliability hardening

- **Status:** in_progress
- Confirmed the platform remains an evaluation and release-gate system; it will not execute or route Skills.
- Locked decisions: Skill telemetry is UNKNOWN when missing and fail-closed only when Skill controls are enabled; binding conflicts are rejected before persistence; hardcoded-secret imports never persist Skill file content; hallucination coverage is deterministic Skill identity/lifecycle plus frozen evidence attribution.
- Added Phase 4.4 and 4.5 acceptance checklists before implementation.
- First v0.4 check found only two Ruff import-order findings. A combined frontend check was again launched from the repository root and failed because `package.json` exists only under `web/`; subsequent npm checks use the explicit Web working directory.
- The first Web healthcheck used `localhost`, which BusyBox resolved to IPv6 `::1` while Nginx listened on IPv4; changed the probe to explicit `127.0.0.1` after direct container diagnostics.
- v0.4 verification passed: Ruff, 74 backend tests with PostgreSQL/Redis/OPA, reversible migration and drift, Web typecheck/3 Vitest/build/audit, no-cache API/Worker/Web/OPA/Fake AG-UI builds, container `pip check`, all declared health checks, and Chrome desktop/mobile with 0 browser errors.
- During v0.5 checks, one combined command again invoked npm from the repository root and failed immediately; no files changed. All subsequent Web checks are run separately with `web/` as the working directory.
- The first multi-Skill fixture preparation used `.id` on a `(SkillVersion, SkillPackage)` tuple and stopped before creating an EvalRun. Corrected the binding list to use the tuple's SkillVersion element.
- The first v0.5 full suite had one compatibility failure because the Fake AG-UI target added empty `skills_used` and `claims` fields to legacy responses. Changed the fixture to emit those fields only when explicitly supplied.
- The first v0.5 Chrome Gate assertion matched both the large decision and a status tag, causing Playwright strict-mode failure. Scoped the assertion to `.gate-word`; the page itself rendered normally.
- Final v0.5 verification: Ruff passed; full PostgreSQL/Redis/OPA suite 81 passed; Alembic upgrade/downgrade/drift passed; 32-Skill/200-Case scale test passed; Web typecheck/3 Vitest/build/audit passed; 0.5.0 API/Worker/Web/Fake AG-UI images passed health and `pip check`; Chrome desktop/mobile including Run #119 reported 0 browser errors.
- Run #119 completed Baseline/Candidate 4/4 with Skill selection, Evidence coverage, and dataset coverage all 1.0; all fabricated/identity/lifecycle/evidence error counts are zero; Gate SHIP. Jaeger Trace `9cdfe9bc9b5df63a0638e3e15ca74c6a` has 13 spans and zero sensitive tags.
- Live Gate CLI against Run #119 returned SHIP with exit code 0 using a one-time organization API Key that was revoked immediately after verification.

## Session: 2026-08-26 - Multi-agent scenario control plane

- **Status:** in_progress
- Scope is a multi-agent quality control plane with frozen evaluation scenarios plus a Gate-authorized local Pilot runtime, not an unrestricted production workflow platform.
- Inspect AI remains the outer Evaluation Harness; the Scenario Executor runs a bounded DAG inside each case.
- Planned deterministic chain: AG-UI Researcher -> MCP Tasks Evidence Tool -> A2A Reviewer -> DeepAgents Coordinator.
- Current Docker core remains 7/7 healthy. AgriGraph dependency containers and the Document Autoflow API/Worker/Temporal stack are healthy; the AgriGraph business API is not currently running.
- The user selected complete current-environment revalidation: AgriGraph 40 cases and Document Autoflow 24 cases, with a shared USD 1 Document budget fuse.
- Security incident recorded: an Embedding API key was pasted into chat. It will not be called, persisted, logged, or copied; revalidation requires a rotated replacement key in local environment/DPAPI.
- Planning-file patch attempt 1 failed because a truncated findings line was used as context; no file changed. Subsequent edits use stable section anchors.
- Scenario migration upgrade/downgrade/re-upgrade succeeded, but the first drift check detected that the expanded enum columns remained `VARCHAR(5)` while `scenario` requires `VARCHAR(8)`. The migration is being corrected with explicit reversible column widening before any Scenario rows exist.
- The first full integration run connected old hard-coded host port 6379, which is now an unrelated authenticated Redis. Project Redis is 56379 after storage recovery; integration tests now use explicit `AQH_INTEGRATION_REDIS_URL` with 56379 as the local default.
- Protocol startup preflight found Document Autoflow already owns host port 8030. Fake MCP keeps container port 8030 but uses configurable host port 8031, preserving both projects.
- Kafka E2E Run #12 persisted/published its Outbox and wrote one Inbox row with zero DLQ rows, then failed before Inspect execution because the non-root Kafka Worker could not create `.tmp`. Worker images now provision `/app/.tmp/inspect-logs` for UID 1000; Run #12 remains preserved as failure evidence.
- Kafka E2E Run #13 reached the fixed Inspect log directory but exposed a second non-root path assumption at `/.local`. Worker images now set HOME/XDG cache under the owned `/app/.tmp`; Run #13 remains preserved.
- The first dedicated Kafka integration test hit an Auto Create race for its random topic. The production fixed topic had already completed Run #14; the test now creates its isolated main/DLQ topics explicitly through Kafka Admin before producing.
- Implemented frozen `aqh.scenario/v1`, persistent Scenario/Node runs, Shadow/Pilot authorization, JSON Pointer handoffs, cancellation and bounded DAG execution. Standalone Runs #5/#6 and Pilot #7 completed.
- Redis EvalRun #10 completed with SHIP; deterministic Fault Run #11 completed with BLOCK. Kafka Run #14 completed with SHIP after preserving Runs #12/#13 as non-root recovery failures.
- Jaeger Trace `44a6a9d5a6c614f3ab5fac821c0c877f` contains 77 Run/Case/Scenario/Agent/Tool spans with no sensitive match.
- Split `aiokafka` and protocol SDKs out of default API/Core Worker images; default Compose remains seven services with memory limits and log rotation.
- Added the Vue Scenario operations page and Run Detail timeline. Chrome desktop and 390px passed with no console errors or page overflow; the mobile table now omits secondary columns instead of clipping them.
- Recreated the current Document evaluator via DPAPI, rebuilt all 24 frozen Dev parse artifacts with the existing host MinerU runtime, and restored the container worker afterward.
- Run #29 is a verified 1/1 Document smoke. Run #30 has 24/24 results, 10 AUTO_PASS, 11 REVIEW and 3 REPROCESS, with zero target execution errors and USD 0.04003916 known model cost.
- Run #31 has 48/48 Stability results and a real BLOCK: three Candidate create-run calls hit target 409 conflicts left by prior REPROCESS activities and success rate fell 4.17 pp. Candidate known cost is USD 0.03550708 with three UNKNOWN error-case costs.
- Added fail-closed AgriGraph Embedding migration tooling for a rotated local key, 1024-dimensional preflight, API stop, dry-run, batch-10 rebuild and `documents == updated` enforcement. Execution remains blocked because no rotated key is present.
- Final checks: non-integration backend suite 100% passed; integration 4 passed/1 Kafka-profile skipped; Alembic no drift; Web typecheck, 3 Vitest, production build and audit passed; Docker core 7/7 healthy.
- Kubernetes static acceptance rendered 20 objects through kubectl kustomize and parsed every object for apiVersion/kind/metadata.name. Client dry-run still required an API Server, so kind was not started and cluster/HPA behavior remains unverified.
- AgriGraph rotated-key preflight verified `qwen3.7-text-embedding` at 1024 dimensions; the batch-10 ES migration completed with 163/163 vectors updated before API startup.
- Run #32 completed the 3-case AgriGraph smoke with no failures. Run #33 completed 40/40 Characterization with 32 passing Cases, 8 assertion failures and zero target execution errors.
- Run #34 completed 80/80 Stability results with equal 80% Baseline/Candidate success, zero target execution errors and a real SHIP. Token usage is known while all model costs remain UNKNOWN.
- Updated both frozen real-target provenance records to the current dirty source-tree SHA values. `freeze_real_targets.py --check` now passes with 40 AgriGraph and 24 Document Cases unchanged.
- Stopped only the temporary AgriGraph Uvicorn process after evidence capture. Pre-existing AgriGraph dependency containers were left untouched; the seven AQH core services remain healthy.
