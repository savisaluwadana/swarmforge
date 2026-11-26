# Implementation plan — 26–30 November 2026
This is a proposed sprint; actual competition portal availability, team eligibility and research novelty remain unverified. Scope by critical path, not by number of features.

| Stage | Deliverable | Exit gate |
|---|---|---|
| 0 (2–4h) | Freeze contract, verify application/team; bootstrap monorepo and fixtures | CI lint, dependency lock, runnable engine skeleton |
| 1 (8–12h) | Deterministic grid, event loop, network, motion, baseline scheduler | CLI healthy and faulted runs; invariants and repeatability |
| 2 (8–12h) | Local auction + scoped lease, recovery, fault cases | Partition/heal, crash-before/after pickup, stale authority tests |
| 3 (6–10h) | PostgreSQL migration, API, worker lease and events | Create scenario/run, persisted metrics, cancel, restart tests |
| 4 (6–10h) | Lab UI, live timeline, comparison, export | End-to-end actual simulation from browser; no mock metrics |
| 5 (4–8h) | Benchmark matrix, reproducible evidence, pitch | Raw manifests/results, limitations, recorded demo |
Estimates uncertain. If time slips, defer live injection, AI assistant, map editor, multi-user admin, cloud deployment and visuals before compromising algorithm correctness. If the core hypothesis fails, still report measured results or pivot the research question; no made-up win.

## Tasks / parallel agent work
A Core: domain types, virtual clock, event ordering, grid and network. B Algorithms: policy ports, baseline and experimental scheduler, no hidden oracle. C Persistence/API: migration, repo transactions, auth and generated contract, SSE. D Frontend: generated types, scenario form, canvas renderer, benchmark UI; start with clearly labeled fixture data then remove all demo mock pathways for real results. E Verification: property tests, reproducible manifests, comparison and CI. Integration owner reviews shared schema and state changes; no simultaneous edits to canonical contracts. 
Branch by module, small PRs, review before merge. Contract-first; run unit and integration tests, then smoke CLI, then UI. No broad rewrites or unrequested dependency upgrades. 
## Definition of done
- README commands actually work on fresh checkout.
- Docker Compose starts postgres, migrator, API, worker, web; secrets absent.
- OpenAPI validates and frontend types generated; endpoints return agreed status/errors.
- DB migration tested on PostgreSQL; tenant checks, leases and idempotency tested.
- Tests cover all listed invariants and representative failures; no skipped core tests.
- Real benchmark JSON/CSV and trace digest recorded; report does not overclaim.
- README and demo explain simulation-only boundary; no physical command path.
## Go/no-go
Within first six hours: confirm eligibility/portal and teammate; implement one map with two robots, one task, one controller outage; obtain deterministic trace and demonstrable authority behavior. If not, reduce scope to CLI experiment; no polished dashboard before core. 
