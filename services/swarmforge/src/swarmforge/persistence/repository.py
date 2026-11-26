"""Transactional tenant-scoped commands and fenced worker operations."""
from uuid import UUID,uuid4
from dataclasses import dataclass
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from swarmforge.application.identity import Principal,NotFound,Forbidden,Conflict,QuotaExceeded,LeaseLost,CancelRequested
from swarmforge.core.trace import digest
from swarmforge.core.simulator import build_manifest
from swarmforge.domain.model import validate_config
from swarmforge.application.views import run_view,revision_view,scenario_view

CLAIM_LOCK=734182902
TERMINAL=("succeeded","failed","cancelled")


@dataclass(frozen=True)
class Lease:
    workspace_id: UUID
    run_id: UUID
    token: UUID
    manifest: dict


class Repository:
    def __init__(self,dsn,engine_version,max_active=4,max_workspace_active=2,max_workspace_pending=120,lease_seconds=30):
        if min(max_active,max_workspace_active,max_workspace_pending,lease_seconds)<1:
            raise ValueError("positive repository limits required")
        self.dsn=dsn
        self.engine_version=engine_version
        self.max_active=max_active
        self.max_workspace_active=max_workspace_active
        self.max_workspace_pending=max_workspace_pending
        self.lease_seconds=lease_seconds

    def connect(self):
        return psycopg.connect(self.dsn,row_factory=dict_row,connect_timeout=5)

    def _authorize(self,c,principal,w,write=False):
        if not isinstance(principal,Principal):
            raise Forbidden("authenticated principal required")
        if write:
            if not c.execute("SELECT id FROM workspaces WHERE id=%s FOR UPDATE",(w,)).fetchone():
                raise NotFound("workspace")
        role=c.execute("SELECT role FROM memberships WHERE workspace_id=%s AND user_id=%s FOR SHARE",(w,principal.user_id)).fetchone()
        if not role:
            raise NotFound("workspace")
        if write and role["role"] not in ("owner","editor"):
            raise Forbidden("editor role required")

    def _audit(self,c,w,actor,action,kind,rid):
        c.execute("INSERT INTO audit_log(workspace_id,actor_id,action,resource_type,resource_id,request_id) VALUES (%s,%s,%s,%s,%s,%s)",(w,actor,action,kind,str(rid),str(uuid4())))

    def _idem(self,c,p,w,operation,key,body,status,fn):
        if not isinstance(key,str) or not 1<=len(key)<=128:
            raise ValueError("Idempotency-Key length 1..128 required")
        h=digest(body)
        args=(w,p.user_id,operation,key)
        c.execute("DELETE FROM idempotency_keys WHERE workspace_id=%s AND actor_id=%s AND operation=%s AND key=%s AND expires_at<=clock_timestamp()",args)
        row=c.execute("SELECT request_hash,response_body FROM idempotency_keys WHERE workspace_id=%s AND actor_id=%s AND operation=%s AND key=%s",args).fetchone()
        if row:
            if row["request_hash"]!=h:
                raise Conflict("idempotency key reused with different body")
            return row["response_body"]
        result=fn()
        c.execute("INSERT INTO idempotency_keys(workspace_id,actor_id,operation,key,request_hash,response_status,response_body,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+interval '24 hours')",(*args,h,status,Jsonb(result)))
        return result

    def create_scenario(self,p,w,name,config,key):
        validate_config(config)
        if not isinstance(name,str) or not 1<=len(name)<=120:
            raise ValueError("invalid scenario name")
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def create():
                sid=uuid4()
                c.execute("INSERT INTO scenarios(workspace_id,id,name,created_by) VALUES (%s,%s,%s,%s)",(w,sid,name,p.user_id))
                self._insert_revision(c,p,w,sid,1,config)
                self._audit(c,w,p.user_id,"scenario.created","scenario",sid)
                return {"scenario_id":str(sid),"revision":1,"response":{"scenario":scenario_view(c,w,sid),"revision":revision_view(c.execute("SELECT * FROM scenario_revisions WHERE workspace_id=%s AND scenario_id=%s AND version=1",(w,sid)).fetchone())}}
            return self._idem(c,p,w,"create_scenario",key,{"name":name,"config":config},201,create)

    def _insert_revision(self,c,p,w,sid,version,config):
        c.execute("INSERT INTO scenario_revisions(workspace_id,scenario_id,version,config,config_hash,created_by) VALUES (%s,%s,%s,%s,%s,%s)",(w,sid,version,Jsonb(config),digest(config),p.user_id))

    def create_revision(self,p,w,sid,config,key):
        validate_config(config)
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def create():
                s=c.execute("SELECT archived_at FROM scenarios WHERE workspace_id=%s AND id=%s FOR UPDATE",(w,sid)).fetchone()
                if not s: raise NotFound("scenario")
                if s["archived_at"]: raise Conflict("archived scenario")
                version=c.execute("SELECT max(version)+1 AS version FROM scenario_revisions WHERE workspace_id=%s AND scenario_id=%s",(w,sid)).fetchone()["version"]
                self._insert_revision(c,p,w,sid,version,config)
                self._audit(c,w,p.user_id,"scenario.revised","scenario",sid)
                return {"scenario_id":str(sid),"revision":version,"response":revision_view(c.execute("SELECT * FROM scenario_revisions WHERE workspace_id=%s AND scenario_id=%s AND version=%s",(w,sid,version)).fetchone())}
            return self._idem(c,p,w,"create_revision:"+str(sid),key,config,201,create)

    def get_revision(self,p,w,sid,version):
        with self.connect() as c:
            self._authorize(c,p,w)
            row=c.execute("SELECT * FROM scenario_revisions WHERE workspace_id=%s AND scenario_id=%s AND version=%s",(w,sid,version)).fetchone()
            if not row: raise NotFound("revision")
            return row

    def enqueue(self,p,w,sid,revision,algorithm,seed,key,mode="scripted"):
        if mode!="scripted":
            raise Conflict("interactive execution not implemented in R3")
        body={"scenario_id":str(sid),"revision":revision,"algorithm":algorithm,"seed":seed,"mode":mode}
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def create():
                r=c.execute("SELECT r.config,r.config_hash,s.archived_at FROM scenario_revisions r JOIN scenarios s ON s.workspace_id=r.workspace_id AND s.id=r.scenario_id WHERE r.workspace_id=%s AND r.scenario_id=%s AND r.version=%s",(w,sid,revision)).fetchone()
                if not r: raise NotFound("revision")
                if r["archived_at"]: raise Conflict("archived scenario")
                count=c.execute("SELECT count(*) AS n FROM runs WHERE workspace_id=%s AND status IN ('queued','running','cancelling')",(w,)).fetchone()["n"]
                if count>=self.max_workspace_pending: raise QuotaExceeded("workspace pending run limit")
                manifest=build_manifest(r["config"],seed,self.engine_version,str(sid),revision,algorithm)
                if manifest["config_hash"]!=r["config_hash"]: raise Conflict("revision hash mismatch")
                rid=uuid4()
                c.execute("INSERT INTO runs(workspace_id,id,scenario_id,revision,algorithm,seed,mode,engine_version,manifest,manifest_hash,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",(w,rid,sid,revision,algorithm,seed,mode,self.engine_version,Jsonb(manifest),digest(manifest),p.user_id))
                self._audit(c,w,p.user_id,"run.enqueued","run",rid)
                return {"run_id":str(rid),"status":"queued","response":run_view(self._get_run(c,w,rid))}
            return self._idem(c,p,w,"enqueue",key,body,202,create)

    def _get_run(self,c,w,rid,lock=False):
        row=c.execute("SELECT * FROM runs WHERE workspace_id=%s AND id=%s"+(" FOR UPDATE" if lock else ""),(w,rid)).fetchone()
        if not row: raise NotFound("run")
        return row

    def get_run(self,p,w,rid):
        with self.connect() as c:
            self._authorize(c,p,w)
            row=self._get_run(c,w,rid)
            # Worker tokens must never enter a user-facing response.
            return {k:v for k,v in row.items() if k not in ("lease_token","lease_until","worker_id")}

    def read_events(self,p,w,rid,after=0,limit=200):
        if type(after) is not int or after<0 or type(limit) is not int or not 1<=limit<=1000:
            raise ValueError("invalid event cursor")
        with self.connect() as c:
            self._authorize(c,p,w)
            row=self._get_run(c,w,rid)
            if after>row["last_seq"]: raise Conflict("cursor ahead")
            rows=c.execute("SELECT seq,tick,event_type AS type,schema_version,payload FROM run_events WHERE workspace_id=%s AND run_id=%s AND seq>%s ORDER BY seq LIMIT %s",(w,rid,after,limit)).fetchall()
            return [{"run_id":str(rid),**r} for r in rows]

    def get_snapshot(self,p,w,rid,at_seq=None):
        with self.connect() as c:
            self._authorize(c,p,w)
            self._get_run(c,w,rid)
            row=c.execute("SELECT state FROM run_snapshots WHERE workspace_id=%s AND run_id=%s AND seq<=%s ORDER BY seq DESC LIMIT 1",(w,rid,at_seq if at_seq is not None else 9007199254740991)).fetchone()
            if not row: raise Conflict("snapshot not ready")
            return row["state"]

    def get_metrics(self,p,w,rid):
        with self.connect() as c:
            self._authorize(c,p,w)
            self._get_run(c,w,rid)
            row=c.execute("SELECT result_json FROM run_metrics WHERE workspace_id=%s AND run_id=%s",(w,rid)).fetchone()
            if not row: raise Conflict("metrics not ready")
            return row["result_json"]

    def cancel(self,p,w,rid,key):
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def change():
                row=self._get_run(c,w,rid,True)
                status=row["status"]
                if status=="queued":
                    c.execute("UPDATE runs SET status='cancelled',finished_at=clock_timestamp() WHERE workspace_id=%s AND id=%s",(w,rid))
                    status="cancelled"
                elif status=="running":
                    c.execute("UPDATE runs SET status='cancelling' WHERE workspace_id=%s AND id=%s",(w,rid))
                    status="cancelling"
                elif status!="cancelling":
                    raise Conflict("terminal run")
                self._audit(c,w,p.user_id,"run.cancel_requested","run",rid)
                return {"run_id":str(rid),"status":status,"response":run_view(self._get_run(c,w,rid))}
            return self._idem(c,p,w,"cancel:"+str(rid),key,{},202,change)

    # Worker-only methods below. No user-supplied lease token is accepted by HTTP.
    def claim(self,worker_id):
        with self.connect() as c:
            # Serialize admission, not execution. Prevent concurrent quota races.
            c.execute("SELECT pg_advisory_xact_lock(%s)",(CLAIM_LOCK,))
            n=c.execute("SELECT count(*) AS n FROM runs WHERE status IN ('running','cancelling')").fetchone()["n"]
            if n>=self.max_active: return None
            row=c.execute("""SELECT q.* FROM runs q WHERE q.status='queued'
                AND q.engine_version=%s AND
                (SELECT count(*) FROM runs a WHERE a.workspace_id=q.workspace_id AND a.status IN ('running','cancelling'))<%s
                ORDER BY q.created_at,q.id FOR UPDATE OF q SKIP LOCKED LIMIT 1""",(self.engine_version,self.max_workspace_active)).fetchone()
            if not row: return None
            token=uuid4()
            c.execute("UPDATE runs SET status='running',worker_id=%s,lease_token=%s,lease_until=clock_timestamp()+%s*interval '1 second',started_at=clock_timestamp() WHERE workspace_id=%s AND id=%s",(worker_id,token,self.lease_seconds,row["workspace_id"],row["id"]))
            return Lease(row["workspace_id"],row["id"],token,row["manifest"])

    def _fence(self,c,lease):
        row=self._get_run(c,lease.workspace_id,lease.run_id,True)
        now=c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]
        if row["status"] not in ("running","cancelling") or row["lease_token"]!=lease.token or row["lease_until"]<=now:
            raise LeaseLost("lease invalid or expired")
        return row

    def renew(self,lease):
        with self.connect() as c:
            row=self._fence(c,lease)
            c.execute("UPDATE runs SET lease_until=clock_timestamp()+%s*interval '1 second' WHERE workspace_id=%s AND id=%s",(self.lease_seconds,lease.workspace_id,lease.run_id))
            return row["status"]

    def _append(self,c,lease,row,events,snapshot):
        seq=row["last_seq"];tick=row["last_tick"]
        for e in events:
            if e["run_id"]!=str(lease.run_id) or e["seq"]!=seq+1 or e["tick"]<tick or e["tick"]>row["manifest"]["config"]["duration_ticks"]:
                raise Conflict("noncontiguous event batch")
            seq=e["seq"];tick=e["tick"]
        if events:
            with c.cursor() as cur:
                cur.executemany("INSERT INTO run_events(workspace_id,run_id,seq,tick,event_type,schema_version,payload) VALUES (%s,%s,%s,%s,%s,%s,%s)",[(lease.workspace_id,lease.run_id,e["seq"],e["tick"],e["type"],e["schema_version"],Jsonb(e["payload"])) for e in events])
            if snapshot is not None:
                if snapshot["run_id"]!=str(lease.run_id) or snapshot["seq"]!=seq or snapshot["tick"]<tick:
                    raise Conflict("snapshot cursor mismatch")
                c.execute("INSERT INTO run_snapshots(workspace_id,run_id,seq,tick,state) VALUES (%s,%s,%s,%s,%s)",(lease.workspace_id,lease.run_id,seq,snapshot["tick"],Jsonb(snapshot)))
                tick=snapshot["tick"]
            c.execute("UPDATE runs SET last_seq=%s,last_tick=%s WHERE workspace_id=%s AND id=%s",(seq,tick,lease.workspace_id,lease.run_id))
        return seq

    def commit_batch(self,lease,events,snapshot):
        with self.connect() as c:
            row=self._fence(c,lease)
            if row["status"]=="cancelling": raise CancelRequested()
            if any(e["type"]=="run.finished" for e in events): raise Conflict("terminal event requires finish")
            return self._append(c,lease,row,events,snapshot)

    def finish(self,lease,events,snapshot,metrics):
        with self.connect() as c:
            row=self._fence(c,lease)
            if row["status"]=="cancelling": raise CancelRequested()
            if not events or events[-1]["type"]!="run.finished" or events[-1]["payload"]["status"]!="succeeded" or not metrics["complete"] or metrics["run_id"]!=str(lease.run_id) or events[-1]["payload"]["trace_hash"]!=metrics["trace_hash"]:
                raise Conflict("invalid terminal result")
            self._append(c,lease,row,events,snapshot)
            cols=("released","completed","stranded","duration_ticks","attempted_conflicts","accepted_duplicates","actual_collisions","stale_rejections","messages_sent","messages_delivered","trace_hash")
            c.execute("INSERT INTO run_metrics(workspace_id,run_id,"+",".join(cols)+",breakdown,result_json) VALUES ("+",".join(["%s"]*(len(cols)+4))+")",(lease.workspace_id,lease.run_id,*(metrics[k] for k in cols),Jsonb(metrics["breakdown"]),Jsonb(metrics)))
            self._terminal(c,lease,"succeeded")

    def _terminal(self,c,lease,status,code=None):
        c.execute("UPDATE runs SET status=%s,finished_at=clock_timestamp(),failure_code=%s,worker_id=NULL,lease_token=NULL,lease_until=NULL WHERE workspace_id=%s AND id=%s",(status,code,lease.workspace_id,lease.run_id))

    def finish_cancel(self,lease):
        with self.connect() as c:
            row=self._fence(c,lease)
            if row["status"]!="cancelling": raise Conflict("cancel not requested")
            self._terminal(c,lease,"cancelled")

    def fail(self,lease,code="execution_failed"):
        with self.connect() as c:
            self._fence(c,lease)
            self._terminal(c,lease,"failed",code)

    def reap(self):
        with self.connect() as c:
            result=c.execute("""UPDATE runs SET status='failed',failure_code='worker_lost',finished_at=clock_timestamp(),worker_id=NULL,lease_token=NULL,lease_until=NULL
                WHERE status IN ('running','cancelling') AND lease_until<=clock_timestamp()""")
            return result.rowcount
