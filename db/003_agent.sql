BEGIN;
CREATE TABLE agent_plans (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(), actor_id uuid NOT NULL REFERENCES users(id),
 plan_json jsonb NOT NULL, plan_hash text NOT NULL CHECK(plan_hash ~ '^[0-9a-f]{64}$'), engine_version text NOT NULL,
 status text NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','approved','denied','executed')), execution jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), expires_at timestamptz NOT NULL,
 PRIMARY KEY(workspace_id,id), CHECK((status='executed')=(execution IS NOT NULL))
);
CREATE TABLE agent_approvals (
 workspace_id uuid NOT NULL, plan_id uuid NOT NULL, approver_id uuid NOT NULL REFERENCES users(id), approved_hash text NOT NULL,
 decision text NOT NULL CHECK(decision IN ('approved','denied')), created_at timestamptz NOT NULL DEFAULT now(), consumed_at timestamptz,
 PRIMARY KEY(workspace_id,plan_id), FOREIGN KEY(workspace_id,plan_id) REFERENCES agent_plans(workspace_id,id)
);
CREATE TABLE agent_sessions (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(), actor_id uuid NOT NULL REFERENCES users(id),
 status text NOT NULL CHECK(status IN ('planning','planned','failed')), plan_id uuid, error_code text, reserved_cost numeric NOT NULL DEFAULT 0 CHECK(reserved_cost>=0),
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id), FOREIGN KEY(workspace_id,plan_id) REFERENCES agent_plans(workspace_id,id)
);
CREATE TABLE agent_tool_audit (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(), actor_id uuid NOT NULL REFERENCES users(id),
 tool text NOT NULL, request_hash text NOT NULL, outcome text NOT NULL CHECK(outcome IN ('started','succeeded','failed')), result_hash text,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id)
);
CREATE INDEX agent_audit_rate ON agent_tool_audit(workspace_id,actor_id,created_at);
CREATE INDEX agent_session_budget ON agent_sessions(workspace_id,created_at);
COMMIT;
