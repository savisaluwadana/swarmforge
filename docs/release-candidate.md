# R7 release candidate — acceptance record

Status: PR #11 under review, **not a v1.0.0 release**. Release owner must review final green checks, limitations, recording and dependencies before tagging.

## Verified prior code
| Gate | Evidence |
|---|---|
| M1–M3 | [Core research CI](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973614): 72/72 synthetic runs completed with audit and replay; [raw bundle](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973614/artifacts/15099854353) |
| M4–M5 | [PostgreSQL/API/agent CI](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973327): passed |
| M6–M7 | [Browser and official SDK CI](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973303): 2 browser tests passed; MCP protocol 2025-11-25, 13 tools, approved two-run experiment succeeded; [screenshots](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973303/artifacts/15099928907) |
| M8 | New candidate CI pending: fresh Compose, security smoke, SDK/browser, restart evidence, dependency locks, scale boundaries and release evidence |

## Explicit limitations and sign-off
The 72 successes mean execution and replay/audit passed, not that all tasks completed or scoped lease won. Research model is synthetic with conservative motion and shared execution gate. Baselines are simplified. No hardware tests or real customer validation. Optional model planner verified using test fake, not a live paid provider. Deterministic evidence report is implemented, model narrative is not. Remote OAuth, public multi-user deployment, production step-up and combined maximum workload not accepted. No demo recording produced. Actual screenshots are available but visual quality has not been independently reviewed in this release step. Dependency lockfiles must be committed and clean installs verified. Release tag is not created here. If gates remain open, label the product research preview, not production-ready v1.0.0.
