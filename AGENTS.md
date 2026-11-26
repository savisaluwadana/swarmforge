# SwarmForge coding agent instructions
Read README, docs/product.md, docs/architecture.md, docs/coordination.md, docs/workflows.md, docs/api.md, docs/database.md, docs/benchmark.md, docs/implementation.md and contracts/openapi.json before coding. These are proposed contracts, not implemented features. 
- Work in small testable increments; state files and acceptance criteria before changes; do not claim completion without actual test output.
- First implement deterministic Python core and CLI; no LLM, wall-clock or database in simulation policy; use typed local views and virtual ticks. Enforce authority and movement invariants; all policies share same physical gate.
- Build application/API and worker separately around core, using canonical SQL and OpenAPI. Use tenant-scoped queries, atomic idempotency, fenced leases, immutable revisions and ordered events. No hidden retries or invented endpoints. 
- If contract inconsistency found, document and update contract + tests in same PR before downstream code.
- UI: premium restrained industrial design, responsive and accessible, actual persisted data, explicit loading/empty/error states. Mock fixtures only in tests/storybook clearly labeled.
- All experiments must be reproducible. No fake charts, invented benchmark numbers, unverifiable citations or claims of physical safety, novelty or production readiness.
- Keep AI assistant read-only and optional. Do not add physical robotics control, Kubernetes, Redis, Kafka, GPU training, or paid cloud resources without explicit approval.
- Never commit keys, credentials or personal data. Use env placeholders.
- Tests: unit, property, integration against real PostgreSQL, API contract, SSE recovery, E2E critical path. Report exact commands and results.
- Update implementation progress in docs with what is done, blockers and next tasks. Do not modify unrelated files.
