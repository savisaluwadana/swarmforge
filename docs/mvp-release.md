# SwarmForge MVP v1.0 — release scope and PR roadmap
Decision date: 2026-11-26. Proposed scope revision following merged PR #3. This is a plan, not a claim of implemented features. This document controls release scope; detailed protocols, schemas and contracts control implementation. Update those contracts and tests before changing behavior. See agent-platform.md for the new agentic boundary.

## Product promise
SwarmForge is an agent-assisted robotics fleet reliability testing platform. Engineers describe failure scenarios, run deterministic simulated experiments, compare coordination policies and inspect reproducible evidence before field deployment. Primary user: robotics integration/reliability engineer. Buyer hypothesis: AMR system integrator or warehouse automation engineering lead. Judge/researcher can inspect evidence without an account controlling real hardware. No physical control, safety certification, guaranteed performance improvement or customer validation claim.

## MVP acceptance matrix
| ID | Capability | Acceptance / proof | Planned PR |
|---|---|---|---|
| M1 | Three deterministic policies | centralized_greedy, local_auction, scoped_lease on identical scenario; deterministic replay; no hidden scheduler oracle | 5 |
| M2 | Fault and recovery model | controller isolation, directed partition, latency, loss, crash; epoch fencing, expiry, safe release only with delivered evidence; uncertain/picked work deferred | 5 |
| M3 | Evidence suite | schema-valid trace, matching build/config/seed; >=12-run smoke matrix (10 robots, 2 seeds, 3 policies, healthy/outage), larger predeclared matrix when feasible; negative controls, failed runs retained | 6 |
| M4 | Durable multi-workspace backend | SQL migration, frozen revisions, transaction-safe job claims/fencing, cancellation and tenant isolation tested against PostgreSQL | 7 |
| M5 | REST + SSE | canonical v1 endpoints, validation, idempotency, role checks, snapshot + cursor reconnect, benchmark fanout, measured exports | 8 |
| M6 | Functional web lab | scenario preset/edit/validate/save; live event-driven canvas, scheduled and bounded interactive faults, inspector, replay and benchmark comparison; no mock data | 9 |
| M7 | Agentic operations | provider-neutral built-in agent plus authenticated MCP endpoint; plan validation, human approval, bounded enqueue, polling, evidence-backed report, audit and budgets | 10 |
| M8 | Release | clean checkout Compose, seeded demo, dependency locks, E2E UI and MCP flows, security regression, reproducible results, demo recording/runbook and release tag | 11 |

Mandatory P0: above. Interactive fault injection can be reduced to a scripted fault editor if the deadline forces a scope amendment; do not silently waive M6. Agent-assisted planning/execution is now P0, not optional, but LLM provider failure must not block manual operation. Read-only deterministic report/export remains available with no provider key. P1: richer map editing, long-term agent memory, arbitrary external MCP tools, model routing across providers, cloud deployment automation, advanced maps, ROS/Open-RMF adapters. P2: physical hardware research after safety review. No billing UI, agent marketplace, Kubernetes, Kafka, Redis, multi-agent swarm of LLMs or autonomous physical commands in MVP.

## PR train (eight planned PRs including this documentation change)
Numbers below are expected sequence numbers, not reserved GitHub IDs; refer to milestone labels if intervening PRs change numbering. Current merged #1 design, #2 baseline core, #3 initial scoped coordination. This docs PR + seven implementation/release PRs; corrective PRs if checks fail, not a promise of exact total. No feature scope expansion without release owner review.
| Expected PR | Scope and dependency | Exit gate / required CI |
|---|---|---|
| #4 / R0 | Freeze release scope, user journeys, demo, agent gateway/MCP contract proposal, research fairness; docs only | Review docs, no runtime claims; establish acceptance ownership |
| #5 / R1 | Core completion: standalone simplified local auction, common fencing/authority semantics, fixed-scope renewal/reconciliation with explicit message evidence and conservative fallback, equal task-source model; depends R0 | all existing tests + targeted adversarial/property cases, all three scripted replays, no hidden oracle; version bump |
| #6 / R2 | Benchmark CLI/metrics, validation of events against OpenAPI + payload schema, matched seeds, negative controls, artifact export, preserve failed outcomes; depends R1 | 12-run smoke + predeclared larger subset when resources permit; actual JSON/CSV and hashes, no claim of superiority; reproduce matched runs |
| #7 / R3 | PostgreSQL migration, explicit repo adapters, workspace principal/roles, durable worker, fenced batch writes, snapshots, cancellation, local Compose DB/API/worker foundations; depends R2 | real PostgreSQL integration tests, stale lease/concurrency/tenant/cancel tests, clean migration |
| #8 / R4 | FastAPI REST + SSE, validation and canonical contracts, benchmark fanout/exports, interactive commands, auth + idempotency; depends R3 | all 31 original operations or explicitly reviewed amendment; contract and reconnect tests, unauthorized/cross-tenant failures, no fabricated metrics |
| #9 / R5 | Next.js Lab and Bench, preset + form, live/replay canvas, failure editor, event inspector, results and exports; depends R4 | browser E2E against real API and worker; keyboard accessibility, no fixture/mock production path, loading/error/reconnect handling |
| #10 / R6 | SwarmForge Agent + MCP + gateway, approval page and evidence view, versioned agent contracts and migration, provider adapter, budgets and audit; depends R4/R5 | real MCP client interoperability, real or explicitly test-only fake provider, approve/deny/replay/tenant/budget/prompt-injection tests, real approved simulation and evidence report; manual flow works offline |
| #11 / R7 | Release hardening, Compose full stack, security and performance smoke, customer demo and competition assets; depends all | fresh checkout through full browser and MCP demo, CI green on release commit, real artifact bundle, README/runbook, signed-off limitations, tag v1.0.0 |

Parallelize R2 benchmark harness design and R3 persistence interface design while R1 contracts settle; R5 UI and R6 gateway design can start against frozen R4 interfaces. Merge in sequence to keep one tested source of truth. Do not publish speculative dependencies as implemented. If time pressure: ship a labeled research preview with fewer features, NOT v1.0.0; keep unmet gate list. Prioritize correctness and proof over visual polish; do not bypass security to hit competition date.

## Release scorecard
At R0, only R1 partial foundations verified: 19 tests, 2 policies, both replay checks in CI run 45774606858. No app backend, web UI, agent runtime or MCP endpoint yet. Use pass/fail/not run per M1–M8, with commit/CI links, not subjective percent complete. Progress document updated on every PR with tests executed, observed outputs, decisions, limitations and remaining gates. Release owner must check competition eligibility separately.

## Definition of done and demo
See demo-guide.md. One real scenario from browser and one via MCP must enqueue through the same application service and durable worker, show actual events and results, verify manifest replay, expose failure tradeoffs and no unsupported claims. Product manual mode must be functional without LLM provider. Any hosted deployment is optional and separately authorized; local Compose is release gate. No physical integrations.

## R7 status update
R6 merged with all three workflows passing. See [release candidate](release-candidate.md) for evidence and open gates. R7 must not tag v1.0.0 while required gates remain open. Local research preview is the truthful fallback if release criteria cannot be fully met.
