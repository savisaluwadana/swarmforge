"""Canonical public shapes, deliberately excluding internal lease and identity fields."""
from datetime import datetime
from uuid import UUID


def wire(value):
    if isinstance(value,(datetime,UUID)):
        return value.isoformat() if isinstance(value,datetime) else str(value)
    if isinstance(value,dict): return {k:wire(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [wire(v) for v in value]
    return value


def select(row,keys):
    return wire({k:row[k] for k in keys.split()})


def run_view(row):
    return {**select(row,"id scenario_id revision benchmark_id algorithm seed mode engine_version manifest_hash status last_seq last_tick created_at started_at finished_at failure_code"),
            "duration_ticks":row["manifest"]["config"]["duration_ticks"]}


def revision_view(row):
    return select(row,"scenario_id version config config_hash created_at")


def scenario_view(c,w,sid):
    row=c.execute("""SELECT s.*, (SELECT max(version) FROM scenario_revisions r
       WHERE r.workspace_id=s.workspace_id AND r.scenario_id=s.id) AS latest_revision
       FROM scenarios s WHERE s.workspace_id=%s AND s.id=%s""",(w,sid)).fetchone()
    if not row:
        from swarmforge.application.identity import NotFound
        raise NotFound("scenario")
    return select(row,"id name latest_revision archived_at created_at")
