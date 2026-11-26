# MVP demonstration and customer presentation
Status: proposed storyboard; all actions below are acceptance criteria for release, not currently implemented. Current CLI-only evidence is linked from progress.md.

## Who and why
Primary: warehouse robotics integration engineer / reliability lead. Problem: "Will our fleet continue useful work if connectivity to the fleet manager is interrupted?" Buyer wants evidence to inform engineering tests before physical deployment. Researchers want repeatable comparison and failure traces. Judge wants a differentiated hypothesis and a credible path to market.

## Complete user journey (manual or agent)
1. Open landing page; clear simulation-only label and CTA "Open reliability lab".
2. Choose a 10-robot warehouse preset or configure map, robots, zones, delivery tasks and network. Save immutable revision.
3. Choose healthy and short controller-outage cases; same task generation, map, seeds and environmental model across policies. Use explicit fault start/end. Agent path: type "Test a 15-tick controller outage with 10 robots. Compare all three policies on two seeds. Explain any stalled tasks." Agent creates validated proposed config and plan: 2 conditions × 3 policies × 2 seeds = 12 runs. Preview exact plan, limits and assumptions; user approves in UI. External MCP path: discover tools, create draft, open approval URL, execute approved ID, poll results and read evidence. Manual path uses same app service without model provider.
4. Watch live run: simulated grid, robot state, zone authority, network fault banner, timeline, metrics. Select robot and task to see grant issuer/epoch and event seq. Pause visual playback only; clear difference from execution. Reconnect resumes committed cursor.
5. Benchmark center: compare matched successful seeds, raw completion/latency/overhead, failed/cancelled counts, negative controls and uncertainty. Do not present small smoke as statistical proof. Identify where scoped work helps or stops, including lease expiry and cross-zone deferrals. If no improvement, show honest results and explain limitations.
6. Ask agent "Why did task X stall?" Return evidence-backed explanation with clickable run/event refs, distinguish inferred explanation from observed event. Export JSON/CSV and frozen manifest. Replay using same engine build and verify digest.
7. End with "We can help integrators investigate fleet reliability before physical deployment; next step is validation with actual operators and stronger baselines."

## Three-minute live demo
0:00–0:25 show problem, preset and natural-language goal. 0:25–0:55 plan preview and human approval; no hidden action. 0:55–1:30 actual simulated failure and local authorized work; show event evidence. 1:30–2:05 compare measured results including non-winning cases. 2:05–2:35 inspect agent explanation and export trace hash. 2:35–3:00 external MCP discovery/approved plan execution (or previously executed real run labeled recorded), roadmap and commercial hypothesis. If live benchmark exceeds slot, show a precomputed real artifact with manifest, clearly label it; never fake progress or speed.
## Customer evaluation checklist
- Can the engineer construct or describe a fault scenario without code?
- Can a user verify what the agent plans before it consumes resources?
- Do the results survive reload and replay?
- Can they explain why work stops or continues, with evidence?
- Would this reduce time spent reproducing incidents or testing fleet software? Ask about existing process, frequency, budget holder and willingness to pay. No invented customer feedback.
## Assets for release PR
README quick start, 1-page architecture diagram, 3-minute demo script and recording or explicit recording not produced, actual benchmark CSV/JSON with commit/manifest hashes, limitations and research methodology, screenshots from real running UI, MCP integration guide with tested client and auth config, slide-ready product positioning (problem/solution/demo/evidence/business/roadmap). No claim of physical safety, certified control, proven novelty or customer deployment.
