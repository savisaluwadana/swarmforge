# SwarmForge coding agent instructions
Read README, docs/product.md, docs/architecture.md, docs/coordination.md, docs/workflows.md, docs/api.md, docs/database.md, docs/benchmark.md, docs/implementation.md and contracts/openapi.json before coding. These are proposed contracts, not implemented features. 
- Work in small testable increments; state files and acceptance criteria before changes; do not claim completion without actual test output.
- First implement deterministic Python core and CLI; no LLM, wall-clock or database in simulation policy; use typed local views and virtual ticks. Enforce authority and movement invariants; all policies share same physical gate.
- Build application/API and worker separately around core, using canonical SQL and OpenAPI. Use tenant-scoped queries, atomic idempotency, fenced leases, immutable revisions and ordered events. No hidden retries or invented endpoints. 
- If contract inconsistency found, document and update contract + tests in same PR before downstream code.
- UI: premium restrained industrial design, responsive and accessible, actual persisted data, explicit loading/empty/error states. Mock fixtures only in tests/storybook clearly labeled.
- All experiments must be reproducible. No fake charts, invented benchmark numbers, unverifiable citations or claims of physical safety, novelty or production readiness.
- Keep model output advisory until an authenticated human approves an exact simulation plan. Implement bounded agent gateway and MCP in R6 according to docs/agent-platform.md; no agent may self-approve, bypass quota, control physical hardware or enter the deterministic control loop. Do not add physical robotics control, Kubernetes, Redis, Kafka, GPU training, or paid cloud resources without explicit approval.
- Never commit keys, credentials or personal data. Use env placeholders.
- Tests: unit, property, integration against real PostgreSQL, API contract, SSE recovery, E2E critical path. Report exact commands and results.
- Update implementation progress in docs with what is done, blockers and next tasks. Do not modify unrelated files.

- Read docs/mvp-release.md, docs/agent-platform.md, docs/demo-guide.md and contracts/agent-tools.json before any further implementation. Follow R0–R7 gates, keep each PR scoped, update progress with actual CI and artifacts; no new feature creep. Current tool contract is a proposal; R6 must add executable schemas and authorization tests before exposing MCP.
