# SwarmForge

**Resilience infrastructure for physical AI.**

SwarmForge is a simulation-first robotics fleet reliability laboratory. Design failure scenarios, compare three deterministic coordination policies, inspect committed events, and run human-approved agent experiments through the web lab or local MCP. This is a research preview, not a physical robot controller, certified safety system or production SaaS.

## Run the local laboratory

Prerequisites: Git, Python 3.12+, Docker with Compose v2. From a clean checkout:

```bash
python3 scripts/init_local.py
docker compose up --build -d
docker compose exec api python -m swarmforge.api.seed
```

Open http://127.0.0.1:3000. Read the generated `.env` privately and use LOCAL_DEMO_TOKEN to connect. Use AGENT_APPROVAL_SECRET only in the approval UI, and LOCAL_MCP_TOKEN only in the MCP client. The three credentials are independent; never publish them. The init script refuses to overwrite existing configuration. No paid model calls are enabled by default.

- Web lab: http://127.0.0.1:3000
- API readiness: http://127.0.0.1:8000/health/ready
- REST contract: http://127.0.0.1:8000/openapi.json
- Local MCP: http://127.0.0.1:8000/mcp (Streamable HTTP)

PostgreSQL is not published to the host. Do not publicly expose local mode. See [operations](docs/operations.md) for startup, backup, troubleshooting and deployment boundaries.

## What to try

1. Create the ten-robot outage preset in Scenario Studio, validate and save.
2. Launch an interactive simulation, inject packet loss, inspect events and export the real trace.
3. Run matched-seed benchmarks across centralized greedy, peer auction and scoped lease.
4. Open Agent Console, draft without AI, review exact plan and approve with the separate credential. Execute and inspect the measured evidence report.
5. Connect an external MCP host with its own model and the separate local token. See [MCP guide](docs/mcp-quickstart.md).

## Actual verified evidence

PR #10 final CI: [72/72 research experiments](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973614), [database/API/agent tests](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973327), [official MCP client and browser acceptance](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973303). The official SDK negotiated 2025-11-25 and executed an approved two-run experiment. These checks verify prior code, not the unmerged release candidate.

Download the [research artifact](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973614/artifacts/15099854353) and [actual UI screenshots](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973303/artifacts/15099928907) from GitHub Actions. The benchmark success count describes completed and audited simulations, not all tasks completed or superiority.

## Research CLI

```bash
python3 -m pip install -r services/swarmforge/requirements-benchmark.txt
make test
make demo && make replay
make demo-auction && make replay-auction
make demo-scoped && make replay-scoped
make benchmark-research
make evidence
```

The 72-run predeclared synthetic suite covers nine conditions, including healthy, short and long outage, partition, crash, loss, latency, skewed/cross-zone workload and lost delegation. Raw traces and failed outcomes retained. See [benchmark](docs/benchmark.md).

## Architecture and release documents

| Document | Purpose |
|---|---|
| [Product](docs/product.md) | Users and use cases |
| [Architecture](docs/architecture.md) | Core, API, worker, database |
| [Coordination](docs/coordination.md) | Model assumptions and algorithms |
| [Workflows](docs/workflows.md) | Runtime flows |
| [OpenAPI](contracts/openapi.json) | 39 REST operations |
| [Database](docs/database.md) | Canonical SQL migrations |
| [Agent platform](docs/agent-platform.md) | Approval, budgets, MCP |
| [MCP tools](contracts/agent-tools.json) | 13 executable schemas |
| [Release scope](docs/mvp-release.md) | Acceptance gates |
| [Release candidate](docs/release-candidate.md) | Verified results and open gates |
| [Demo](docs/demo-guide.md) | Customer and competition walkthrough |
| [Progress](docs/progress.md) | Implementation history |

No physical integrations, autonomous model execution loops, public remote OAuth MCP, safety or novelty claims. Built-in model provider is optional and requires operator configuration; live paid provider interoperability is not yet verified. No release tag until the acceptance gates are reviewed.
