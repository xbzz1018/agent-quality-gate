# Current Target Verification Record

Recorded on 2026-08-26 before final closeout. Both target repositories were already dirty and were not modified, cleaned, committed, or tested by Agent Quality Harness.

| Target | Commit | Dirty | Current source-tree SHA-256 | Frozen Dataset SHA-256 |
|---|---|---:|---|---|
| AgriGraph | `8f667f4662b6331e7f94e9024c1ef7ae786f57ed` | true | `893b88425c332827893916335dc6e64da9aa258bfb8875cbf7f64a3dd2e53647` | `9b4a8c5ccf8f43532273bbdf1cc784fa2ccea5bb2956a0d577c06120d51c0b03` |
| Document Autoflow | `d25f7ebcc1dac2f220f4c69deeb020ae8347864f` | true | `c477b4456a6efa851ca0c55da2364d7e4d2a58eb3944ea2055a3896a8a7d1875` | `bcb57555cc6d8fa19cc184ee290e7fe6c666a7ac1abaafb3ddb4258485ad04b5` |

The regenerated Case arrays and current dirty source-tree SHA values exactly match both frozen files. Results below are current service-snapshot evidence, not different-commit regression evidence.

## Document Autoflow

- Contract profile: `document_autoflow_v1`.
- Non-secret capabilities SHA-256: `648782a9b04e4570e6bbcdcfae54d86ef911260a1fa9e88931e2d08ab336bd67`.
- Dedicated target: 24/24 frozen Dev documents parsed after Docker volume recovery.
- Run `#29`: 1/1 live smoke, no target execution error.
- Run `#30`: 24/24 Characterization; 10 AUTO_PASS, 11 REVIEW, 3 REPROCESS; zero target execution errors; known model cost USD 0.04003916.
- Run `#31`: 24 recorded Baseline plus 24 live Candidate results; Gate BLOCK. Candidate has 3 target conflicts, 12 assertion failures, 9 passing Cases, known model cost USD 0.03550708, and 3 UNKNOWN error-Case costs.
- Gate reasons: `target_execution_failure=3` and `success_rate_drop=4.166666666666669 pp` against a 3 pp threshold.

## AgriGraph

- Contract profile: `agrigraph_v1`.
- Frozen 40-Case content is reproducible.
- The rotated-key preflight returned `qwen3.7-text-embedding` with 1024 dimensions. Batch-10 ES rebuild completed with `163 discovered == 163 updated` before API startup.
- Run `#32`: 3/3 live smoke, no assertion or target execution failure.
- Run `#33`: 40/40 Characterization; 32 passing and 8 deterministic assertion failures; zero target execution errors; 200,119 input and 19,889 output Token; cost UNKNOWN.
- Run `#34`: 40 recorded Baseline plus 40 live Candidate results; Gate SHIP. Both roles have 80% success and zero target execution failures; Candidate P95 latency is 15,148 ms versus Baseline 23,863 ms; all costs remain UNKNOWN.
- The key previously exposed in chat was not called, persisted, or copied. The rotated local key was consumed only through the process environment and was not logged.

## Platform Context

- Agent Quality Harness source commit at verification start: `6bdf6ade6350360ec9b175a424fc571f2d651be9` with project-local uncommitted implementation changes.
- No Git branch, commit, tag, push, or GitHub operation was performed during this closeout.
