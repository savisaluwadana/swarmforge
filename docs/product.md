# Product specification

## Problem and target customer
Robotics operators can lose throughput when fleet managers become unreachable, network links degrade or individual robots fail. SwarmForge lets engineers evaluate coordination policies under controlled disruptions, quantify tradeoffs and identify scenarios needing mitigation before attempting field deployment. Whether operators would pay for this is a hypothesis.

Initial buyer: robotics system integrator or warehouse automation engineering lead. Users: reliability engineer, robotics researcher, simulation engineer, operations analyst. Viewer: judge or technical stakeholder. Later buyers: AMR manufacturers, factories and hospitals with non-clinical logistics fleets. No military, medical safety or physical control feature in v1.

## Use cases and acceptance
| ID | Persona / problem | Workflow | Acceptance |
|---|---|---|---|
| UC01 | Researcher needs repeatable baseline | Create map, fleet, workload, seed; run centralized scheduler | Manifest captures all inputs; replay same seed yields same event digest |
| UC02 | Reliability engineer tests controller outage | Schedule outage and recovery; compare policies | Timeline shows lost connectivity, paused/continuing work and measured recovery |
| UC03 | Integrator tests robot crash | Crash-stop idle robot or robot in transit | Failed robot stops; eligible unpicked tasks may be reallocated only with authority; carrying robot requires recovery |
| UC04 | Network engineer tests split and heal | Divide nodes by explicit links; restore links | No invisible cross-partition messages; convergence and conflicts reported |
| UC05 | Researcher compares algorithms | Run matched seeds, workload and fault schedules | Per-seed raw metrics, uncertainty, paired differences and failure flags |
| UC06 | Reviewer audits a decision | Select robot or task; inspect event evidence | Policy reason, inputs, authority and tick available |
| UC07 | Engineer validates regression | Export manifest and replay via CLI | CI checks invariants and deterministic digest |
| UC08 | Operator learns recovery behavior | Inject live fault in interactive run; play event log | Accepted command recorded at actual applied tick; interactive trace export |
| UC09 | Research lead prepares report | Select benchmark and export JSON/CSV | Report derives only from stored measured runs; labels failed and excluded runs |
| UC10 | Future integrator | Connect ROS 2/Open-RMF adapter in isolated lab | Separate field validation, safety review and interface contracts; NOT v1 |

## Scope / requirements
P0: workspace-scoped scenarios with immutable revisions, map validator, 10–100 simulated robots, deterministic event engine, three scheduler strategies, collision-aware movement, scripted faults, task audit, run lifecycle, resumable SSE, results, matched benchmark suite, CLI, reproducibility. Interactive fault injection is P0 if time permits after scripted scenarios; otherwise P1. 
P1: read-only AI analyst, saved presets, experiment reports, replay timeline, map editor polish. P2: multi-site support, richer physical simulation, battery/charging, adapters, enterprise SSO, RBAC granularity. Production robot commands explicitly excluded.
Performance targets (not observed): 100 robots, map <= 100x100, <= 1000 tasks, <= 10000 logical ticks, <= 4 concurrent jobs globally in demo; interactive UI capped at 10 frames/sec; 95% API reads <500 ms on local test hardware excluding streaming and heavy exports. Enforce budgets and measure on actual hardware. Defaults: 20 robots, 24x18 map, 100 tasks, 1000 ticks, tick_ms=1000 simulated time. Fleet size minimum 1 for unit/smoke tests.

## Screens
- / : landing, research question, transparent simulation-only status, launch lab.
- /lab : scenario cards, presets, create scenario.
- /lab/scenarios/:id : grid/map editor, fleet spawn, tasks, network topology, timeline faults, validation, immutable save.
- /lab/runs/:id : playback/pause of visualization (not engine pause), speed, run status, robots/tasks filters, event inspector, current metrics, fault form in interactive mode.
- /benchmarks : choose scenario revision, algorithms, explicit seed array; show run count before launch.
- /benchmarks/:id : progress, per-policy and per-seed comparison, paired differences, failures, CSV export.
- /reports : export entry points / history via run and benchmark data (P1).
- /settings : active workspace, role, limits; no keys in browser.

Empty/loading/error/offline states on every screen. Use a restrained industrial design (graphite, white, muted teal, amber for degraded, red for failed; accessible text and symbols, not color alone). Canvas for moving robots; DOM for accessible controls and table. Never display invented performance metrics. If no runs exist say so.

## Business hypotheses
Sell simulation/reliability testing to integrators before operational control. Validate with 5–10 robotics engineers, request failure incident examples, compare current test process, identify budget holder and willingness to pay. Potential model: per engineering seat or per benchmark quota, later annual enterprise license; no revenue assumptions treated as evidence. Competition demo: normal run → same workload and seed with partition → compare three policies → inspect fenced/deferred work → export manifest. Demonstrate tradeoffs even if experimental policy loses.
