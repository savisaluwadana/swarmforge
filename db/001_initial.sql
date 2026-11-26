-- Proposed initial migration; run against a clean PostgreSQL 16+ database.
BEGIN;
CREATE TABLE users (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), issuer text NOT NULL, subject text NOT NULL,
 display_name text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE(issuer,subject)
);
CREATE TABLE workspaces (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(), name text NOT NULL CHECK(length(name) BETWEEN 1 AND 120),
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE memberships (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), user_id uuid NOT NULL REFERENCES users(id),
 role text NOT NULL CHECK(role IN ('owner','editor','viewer')), PRIMARY KEY(workspace_id,user_id)
);
CREATE TABLE scenarios (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(),
 name text NOT NULL CHECK(length(name) BETWEEN 1 AND 120), archived_at timestamptz,
 created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,id)
);
CREATE TABLE scenario_revisions (
 workspace_id uuid NOT NULL, scenario_id uuid NOT NULL, version integer NOT NULL CHECK(version>0),
 config jsonb NOT NULL CHECK(jsonb_typeof(config)='object'), config_hash text NOT NULL CHECK(config_hash ~ '^[0-9a-f]{64}$'),
 created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,scenario_id,version),
 FOREIGN KEY(workspace_id,scenario_id) REFERENCES scenarios(workspace_id,id)
);
CREATE TABLE benchmarks (
 workspace_id uuid NOT NULL, id uuid NOT NULL DEFAULT gen_random_uuid(), scenario_id uuid NOT NULL, revision integer NOT NULL,
 algorithms jsonb NOT NULL CHECK(jsonb_typeof(algorithms)='array' AND jsonb_array_length(algorithms) BETWEEN 2 AND 3),
 seeds jsonb NOT NULL CHECK(jsonb_typeof(seeds)='array' AND jsonb_array_length(seeds) BETWEEN 1 AND 60),
 engine_version text NOT NULL, created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,id), UNIQUE(workspace_id,id,scenario_id,revision),
 FOREIGN KEY(workspace_id,scenario_id,revision) REFERENCES scenario_revisions(workspace_id,scenario_id,version),
 CHECK(jsonb_array_length(algorithms)*jsonb_array_length(seeds)<=120)
);
CREATE TABLE runs (
 workspace_id uuid NOT NULL, id uuid NOT NULL DEFAULT gen_random_uuid(), scenario_id uuid NOT NULL, revision integer NOT NULL,
 benchmark_id uuid, algorithm text NOT NULL CHECK(algorithm IN ('centralized_greedy','local_auction','scoped_lease')),
 seed bigint NOT NULL CHECK(seed BETWEEN 0 AND 2147483647), mode text NOT NULL CHECK(mode IN ('scripted','interactive')),
 engine_version text NOT NULL, manifest jsonb NOT NULL CHECK(jsonb_typeof(manifest)='object'),
 manifest_hash text NOT NULL CHECK(manifest_hash ~ '^[0-9a-f]{64}$'),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','cancelling','succeeded','failed','cancelled')),
 created_by uuid NOT NULL REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(),
 started_at timestamptz, finished_at timestamptz, failure_code text,
 worker_id text, lease_token uuid, lease_until timestamptz,
 last_seq bigint NOT NULL DEFAULT 0 CHECK(last_seq>=0), last_tick bigint NOT NULL DEFAULT 0 CHECK(last_tick>=0),
 last_command_seq bigint NOT NULL DEFAULT 0 CHECK(last_command_seq>=0),
 PRIMARY KEY(workspace_id,id),
 FOREIGN KEY(workspace_id,scenario_id,revision) REFERENCES scenario_revisions(workspace_id,scenario_id,version),
 FOREIGN KEY(workspace_id,benchmark_id,scenario_id,revision) REFERENCES benchmarks(workspace_id,id,scenario_id,revision),
 UNIQUE(workspace_id,benchmark_id,algorithm,seed),
 CHECK(benchmark_id IS NULL OR mode='scripted'),
 CHECK((status IN ('running','cancelling')) = (lease_token IS NOT NULL AND lease_until IS NOT NULL AND worker_id IS NOT NULL)),
 CHECK((status IN ('succeeded','failed','cancelled')) = (finished_at IS NOT NULL)),
 CHECK(status <> 'failed' OR failure_code IS NOT NULL)
);
CREATE INDEX runs_queue_idx ON runs(created_at,id) WHERE status='queued';
CREATE INDEX runs_active_lease_idx ON runs(lease_until) WHERE status IN ('running','cancelling');
CREATE INDEX runs_workspace_idx ON runs(workspace_id,status,created_at DESC,id);
CREATE INDEX runs_benchmark_idx ON runs(workspace_id,benchmark_id);
CREATE TABLE run_events (
 workspace_id uuid NOT NULL, run_id uuid NOT NULL, seq bigint NOT NULL CHECK(seq>0),
 tick bigint NOT NULL CHECK(tick>=0), event_type text NOT NULL, schema_version integer NOT NULL DEFAULT 1 CHECK(schema_version>0),
 payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'), recorded_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,run_id,seq),
 FOREIGN KEY(workspace_id,run_id) REFERENCES runs(workspace_id,id) ON DELETE CASCADE
);
CREATE TABLE run_snapshots (
 workspace_id uuid NOT NULL, run_id uuid NOT NULL, seq bigint NOT NULL, tick bigint NOT NULL CHECK(tick>=0),
 state jsonb NOT NULL CHECK(jsonb_typeof(state)='object'),
 PRIMARY KEY(workspace_id,run_id,seq),
 FOREIGN KEY(workspace_id,run_id,seq) REFERENCES run_events(workspace_id,run_id,seq) ON DELETE CASCADE
);
CREATE TABLE run_commands (
 workspace_id uuid NOT NULL, run_id uuid NOT NULL, command_seq bigint NOT NULL CHECK(command_seq>0),
 actor_id uuid NOT NULL REFERENCES users(id), payload jsonb NOT NULL CHECK(jsonb_typeof(payload)='object'),
 status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','applied','rejected')),
 applied_tick bigint CHECK(applied_tick>=0), rejection_reason text, created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,run_id,command_seq),
 FOREIGN KEY(workspace_id,run_id) REFERENCES runs(workspace_id,id) ON DELETE CASCADE,
 CHECK((status='applied')=(applied_tick IS NOT NULL)), CHECK(status<>'rejected' OR rejection_reason IS NOT NULL)
);
CREATE INDEX commands_pending_idx ON run_commands(workspace_id,run_id,command_seq) WHERE status='queued';
CREATE TABLE run_metrics (
 workspace_id uuid NOT NULL, run_id uuid NOT NULL,
 released integer NOT NULL CHECK(released>=0), completed integer NOT NULL CHECK(completed BETWEEN 0 AND released),
 stranded integer NOT NULL CHECK(stranded BETWEEN 0 AND released), duration_ticks bigint NOT NULL CHECK(duration_ticks>=0),
 attempted_conflicts integer NOT NULL CHECK(attempted_conflicts>=0), accepted_duplicates integer NOT NULL CHECK(accepted_duplicates>=0),
 actual_collisions integer NOT NULL CHECK(actual_collisions>=0), stale_rejections integer NOT NULL CHECK(stale_rejections>=0),
 messages_sent bigint NOT NULL CHECK(messages_sent>=0), messages_delivered bigint NOT NULL CHECK(messages_delivered BETWEEN 0 AND messages_sent),
 trace_hash text NOT NULL CHECK(trace_hash ~ '^[0-9a-f]{64}$'),
 breakdown jsonb NOT NULL CHECK(jsonb_typeof(breakdown)='object'), created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(workspace_id,run_id), FOREIGN KEY(workspace_id,run_id) REFERENCES runs(workspace_id,id) ON DELETE CASCADE,
 CHECK(completed+stranded<=released)
);
CREATE TABLE idempotency_keys (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), actor_id uuid NOT NULL REFERENCES users(id),
 operation text NOT NULL, key text NOT NULL CHECK(length(key) BETWEEN 1 AND 128), request_hash text NOT NULL CHECK(request_hash ~ '^[0-9a-f]{64}$'),
 response_status integer NOT NULL, response_body jsonb NOT NULL, expires_at timestamptz NOT NULL,
 PRIMARY KEY(workspace_id,actor_id,operation,key)
);
CREATE INDEX idempotency_expiry_idx ON idempotency_keys(expires_at);
CREATE TABLE audit_log (
 workspace_id uuid NOT NULL REFERENCES workspaces(id), id uuid NOT NULL DEFAULT gen_random_uuid(), actor_id uuid REFERENCES users(id),
 action text NOT NULL, resource_type text NOT NULL, resource_id text, request_id text NOT NULL, detail jsonb NOT NULL DEFAULT '{}'::jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(workspace_id,id)
);
CREATE INDEX audit_time_idx ON audit_log(workspace_id,created_at DESC,id);
COMMIT;
