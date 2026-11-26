# Competition demonstration — slide-ready narrative

**Problem.** Robotics integration engineers need to understand what happens when a fleet loses connectivity to its coordinator. Field experiments are disruptive and difficult to reproduce. This is a buyer hypothesis, not validated customer feedback.

**Solution.** SwarmForge is an agent-assisted simulation lab: model a warehouse, inject faults, compare coordination policies, audit real event evidence before field testing.

**Architecture.** Web or local MCP client → validated immutable experiment plan → human approval → PostgreSQL durable queue → deterministic worker → trace and benchmark evidence. The LLM never controls robot motion or assignments.

**Research.** The experimental scoped-lease policy predelegates limited authority and conservatively defers uncertain work. Compare against centralized greedy and simplified peer auction under identical synthetic workloads. The prior CI ran 72 of 72 planned experiments successfully, with trace audit and replay. This is engineering evidence, not a finding that one policy always wins; use measured comparison tables, including non-winning cases.

**Demo in three minutes.** 0:00–0:25 problem and lab. 0:25–0:55 exact plan preview and human approval. 0:55–1:30 interactive network disruption and real event inspector. 1:30–2:05 pre-run measured matched benchmark (clearly labeled recorded run). 2:05–2:35 inspect observed deferrals or stranded tasks, export trace and manifest. 2:35–3:00 show official MCP client and roadmap. If model disabled, use manual draft or local external host; do not fake a response.

**Commercial hypothesis.** Start with AMR integrators, fleet reliability engineering teams and warehouse automation test leads. Interview buyers about incident reproduction, fault-testing frequency, current tools, procurement and willingness to pay; offer a paid pilot only after customer discovery. No invented revenue, traction or certification.

**Next research.** Stronger distributed baselines, source-model ablation, larger workload profiling, operator feedback and eventual read-only integration with robotics frameworks. No physical control in this release.
