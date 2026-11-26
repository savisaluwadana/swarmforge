# Implementation progress

## Milestone 1 — deterministic core (26 November 2026)
Based on merged architecture PR #1. Implemented code for scenario validation, a pure integer-tick simulator, deterministic JSON and trace hashing, directed network emulator with scripted outages/partition/loss/latency/crash, bounded space-time A*, shared conservative movement arbiter, centralized greedy policy using delivered statuses, modeled task authority, crash-while-carrying stranding, CLI run/replay and measured metrics. Added a two-robot fixture, Makefile, Python package and CI. Runtime has no third-party dependencies.

### Verification
CI is configured to compile, execute unit/randomized invariant tests, run the actual smoke scenario and verify replay. No passing test claim until execution results are observed. The local assistant execution environment could not resolve github.com, so the exact checkout cannot be cloned there. See PR checks for actual remote verification.

### Deliberate limitations / contract clarifications
- This is a partial milestone, not the final application. Local auction and scoped lease fail closed. No multi-policy benchmarks, database/API, worker, UI, Docker Compose or deployment.
- Tick 0 initial snapshot is captured immediately after run.started. The run executes ticks [0,duration); terminal event uses duration. Central grants expire at run end, are retried until acknowledged, and are never reassigned yet. Unpicked crash or lost grant remains assigned/uncertain, rather than pretending recovery. Controller outage isolates links; task release at controller is exogenous. Controller decisions use delivered statuses (freshness based on receipt tick), not current global robot state.
- Conservative path planner uses static map, not other robot positions; arbiter rejects all currently occupied cells, even if vacating. Deadlock detection only, no resolution. Local completion tombstones are repeatedly transmitted; bounded by task cap but traffic overhead is intentionally visible. No physical safety claim.
- Current CLI export is an internal core result (manifest, events, snapshots, metrics), not yet REST RunExport shape. Core metrics include basic counters and latency; recovery, utilization, paired comparisons, full payload schema validation, failure-result preservation and database integration remain open.
- JSON canonicalization uses Python sorted compact JSON, normalizes integral floats/negative zero, rejects nonfinite values; cross-runtime canonicalization not yet guaranteed. CLI engine version defaults to package version; pass git SHA with --engine-version for research evidence and replay with the identical build. Runtime lock hash identifies the stdlib-only core; a full environment lock remains pending.
- Tests include randomized movement invariants using seeded stdlib PRNG; Hypothesis and integration tests remain pending.
- API example lacks optional due_tick, allowed by contract; no changes to the OpenAPI/SQL schema. No database migration executed yet.

### Next gate
Inspect CI and fix any failures before implementing scoped authority, local auction and reconciliation. Add event payload and OpenAPI schema validation, test stale grants and safe unpicked release, then benchmark matched scenarios. Do not start UI before core correctness gates pass.
