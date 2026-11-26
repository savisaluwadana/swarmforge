# Local MCP client guide

The official Python SDK interoperability test in PR #10 negotiated **2025-11-25**, listed thirteen tools, drafted a two-policy experiment, confirmed rejection before human approval, executed after approval and retrieved real measured evidence. [Workflow](https://github.com/savisaluwadana/swarmforge/actions/runs/45785973303).

Start the stack using the README. Use an MCP host that supports Streamable HTTP and configurable authorization headers. URL: `http://127.0.0.1:8000/mcp`. Header: Authorization: Bearer followed by LOCAL_MCP_TOKEN, read privately from .env. Do not send the REST or approval credential to the MCP host. Remote SaaS clients cannot reach loopback on your machine; use a local client. Remote OAuth and public exposure are not supported.

1. Use list_scenarios with the workspace UUID displayed in Agent Console.
2. Use get_scenario to inspect a frozen revision; optionally validate_scenario.
3. Use create_experiment_plan with objective, cases, algorithms, seeds and idempotency_key. The total matrix is capped at 12. Drafting does not enqueue.
4. Open returned approval_url in the local web app; authenticate normally and review config, fault schedule, run count and plan hash. Approve with the separate credential.
5. Call execute_approved_plan with the exact plan ID/hash and idempotency key. Duplicate calls return the same run handles.
6. Poll get_benchmark_status or get_run_status; read get_evidence_report or get_run_metrics when complete. Event references are observations, not causal conclusions.

Run the same tested SDK workflow from the checkout in a dedicated local lab (creates two real simulation runs):
```bash
python3 -m pip install -r services/swarmforge/requirements-persistence.txt
set -a; . ./.env; set +a
python3 services/swarmforge/tests/mcp_client_smoke.py
```
No model subscription is required for this test. The built-in provider is optional, separately configured and disabled by default. Do not use a model to approve its own plan.
