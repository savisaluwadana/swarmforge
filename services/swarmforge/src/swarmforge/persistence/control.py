"""Resource-facing repository, sharing the worker's durable queue."""
import base64
import json
from datetime import datetime
from uuid import UUID,uuid4
from statistics import mean,median
from psycopg.types.json import Jsonb
from swarmforge.persistence.repository import Repository,TERMINAL
from swarmforge.application.identity import Principal,NotFound,Conflict,QuotaExceeded
from swarmforge.application.views import wire,select,run_view,revision_view,scenario_view
from swarmforge.core.simulator import build_manifest
from swarmforge.core.trace import digest
from swarmforge.benchmark.runner import paired

METRICS=("completion_rate","throughput_tasks_per_minute","latency_p50_ticks","latency_p95_ticks","deadline_miss_rate","attempted_conflicts","messages_sent","messages_per_completion","stranded")


def cursor_encode(scope,stamp,rid):
    return base64.urlsafe_b64encode(json.dumps([scope,wire(stamp),str(rid)],separators=(",",":")).encode()).decode().rstrip("=")


def cursor_decode(cursor,scope,numeric=False):
    if not cursor: return None
    try:
        s,t,i=json.loads(base64.urlsafe_b64decode(cursor+"="*(-len(cursor)%4)))
        if s!=scope: raise ValueError()
        stamp=datetime.fromisoformat(t)
        if stamp.tzinfo is None: raise ValueError()
        return stamp,int(i) if numeric else UUID(i)
    except Exception as exc: raise ValueError("invalid or mismatched cursor") from exc


class ControlRepository(Repository):
    def principal(self,issuer,subject):
        with self.connect() as c:
            row=c.execute("SELECT id FROM users WHERE issuer=%s AND subject=%s",(issuer,subject)).fetchone()
            return Principal(row["id"]) if row else None

    def me(self,p):
        with self.connect() as c:
            u=c.execute("SELECT id,display_name FROM users WHERE id=%s",(p.user_id,)).fetchone()
            if not u: raise NotFound("identity")
            ws=c.execute("SELECT w.id,w.name,m.role FROM memberships m JOIN workspaces w ON w.id=m.workspace_id WHERE m.user_id=%s ORDER BY w.id LIMIT 1000",(p.user_id,)).fetchall()
            return wire({**u,"workspaces":ws})

    def workspace(self,p,w):
        with self.connect() as c:
            self._authorize(c,p,w)
            return wire(c.execute("SELECT w.id,w.name,m.role FROM workspaces w JOIN memberships m ON m.workspace_id=w.id WHERE w.id=%s AND m.user_id=%s",(w,p.user_id)).fetchone())

    def authorize_editor(self,p,w):
        with self.connect() as c: self._authorize(c,p,w,True)

    def scenario(self,p,w,sid):
        with self.connect() as c:
            self._authorize(c,p,w)
            return scenario_view(c,w,sid)

    def archive(self,p,w,sid,key):
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def change():
                scenario_view(c,w,sid)
                c.execute("UPDATE scenarios SET archived_at=coalesce(archived_at,clock_timestamp()) WHERE workspace_id=%s AND id=%s",(w,sid))
                self._audit(c,w,p.user_id,"scenario.archived","scenario",sid)
                return scenario_view(c,w,sid)
            return self._idem(c,p,w,"archive:"+str(sid),key,{},200,change)

    def _page(self,c,sql,args,scope,limit,cursor,view,idcol="id",numeric=False):
        bound=cursor_decode(cursor,scope,numeric)
        if bound:
            sql+=" AND (created_at,"+idcol+") < (%s,%s)"
            args+=list(bound)
        rows=c.execute(sql+" ORDER BY created_at DESC,"+idcol+" DESC LIMIT %s",(*args,limit+1)).fetchall()
        more=len(rows)>limit; rows=rows[:limit]
        return {"items":[view(r) for r in rows],"next_cursor":cursor_encode(scope,rows[-1]["created_at"],rows[-1][idcol]) if more else None}

    def list_scenarios(self,p,w,limit,cursor,archived):
        with self.connect() as c:
            self._authorize(c,p,w)
            return self._page(c,"SELECT * FROM scenarios WHERE workspace_id=%s"+("" if archived else " AND archived_at IS NULL"),[w],digest([str(w),"scenarios",archived]),limit,cursor,lambda r:scenario_view(c,w,r["id"]))

    def list_revisions(self,p,w,sid,limit,cursor):
        with self.connect() as c:
            self._authorize(c,p,w);scenario_view(c,w,sid)
            return self._page(c,"SELECT * FROM scenario_revisions WHERE workspace_id=%s AND scenario_id=%s",[w,sid],digest([str(w),str(sid),"revisions"]),limit,cursor,revision_view,"version",True)

    def list_runs(self,p,w,limit,cursor,status=None,sid=None,bid=None):
        with self.connect() as c:
            self._authorize(c,p,w)
            if bid:self._benchmark(c,w,bid)
            sql="SELECT * FROM runs WHERE workspace_id=%s";args=[w]
            for column,value in (("status",status),("scenario_id",sid),("benchmark_id",bid)):
                if value is not None: sql+=" AND "+column+"=%s";args.append(value)
            return self._page(c,sql,args,digest([str(w),"runs",status,str(sid),str(bid)]),limit,cursor,run_view)

    def _benchmark(self,c,w,bid):
        b=c.execute("SELECT * FROM benchmarks WHERE workspace_id=%s AND id=%s",(w,bid)).fetchone()
        if not b:raise NotFound("benchmark")
        return b

    def _benchmark_view(self,c,b):
        counts={r["status"]:r["n"] for r in c.execute("SELECT status,count(*) AS n FROM runs WHERE workspace_id=%s AND benchmark_id=%s GROUP BY status",(b["workspace_id"],b["id"])).fetchall()}
        total=sum(counts.values());ok=counts.get("succeeded",0);failed=counts.get("failed",0);cancelled=counts.get("cancelled",0);terminal=ok+failed+cancelled
        status=("failed" if failed else "cancelled" if cancelled else "succeeded") if terminal==total else "queued" if counts.get("queued",0)==total else "running"
        return {**select(b,"id scenario_id revision algorithms seeds engine_version created_at"),"status":status,"total_runs":total,"terminal_runs":terminal,"successful_runs":ok,"failed_runs":failed,"cancelled_runs":cancelled}

    def create_benchmark(self,p,w,sid,revision,algorithms,seeds,key):
        total=len(algorithms)*len(seeds)
        if not 2<=len(algorithms)<=3 or not 1<=len(seeds)<=60 or total>120 or len(set(algorithms))!=len(algorithms) or len(set(seeds))!=len(seeds):
            raise ValueError("invalid benchmark matrix")
        body={"scenario_id":str(sid),"revision":revision,"algorithms":algorithms,"seeds":seeds}
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def create():
                r=c.execute("SELECT r.config,r.config_hash,s.archived_at FROM scenario_revisions r JOIN scenarios s ON s.workspace_id=r.workspace_id AND s.id=r.scenario_id WHERE r.workspace_id=%s AND r.scenario_id=%s AND r.version=%s",(w,sid,revision)).fetchone()
                if not r:raise NotFound("revision")
                if r["archived_at"]:raise Conflict("archived scenario")
                n=c.execute("SELECT count(*) AS n FROM runs WHERE workspace_id=%s AND status IN ('queued','running','cancelling')",(w,)).fetchone()["n"]
                if n+total>self.max_workspace_pending:raise QuotaExceeded("workspace pending run limit")
                bid=uuid4()
                c.execute("INSERT INTO benchmarks(workspace_id,id,scenario_id,revision,algorithms,seeds,engine_version,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",(w,bid,sid,revision,Jsonb(algorithms),Jsonb(seeds),self.engine_version,p.user_id))
                for alg in algorithms:
                    for seed in seeds:
                        m=build_manifest(r["config"],seed,self.engine_version,str(sid),revision,alg)
                        if m["config_hash"]!=r["config_hash"]:raise Conflict("revision hash mismatch")
                        c.execute("INSERT INTO runs(workspace_id,scenario_id,revision,benchmark_id,algorithm,seed,mode,engine_version,manifest,manifest_hash,created_by) VALUES (%s,%s,%s,%s,%s,%s,'scripted',%s,%s,%s,%s)",(w,sid,revision,bid,alg,seed,self.engine_version,Jsonb(m),digest(m),p.user_id))
                self._audit(c,w,p.user_id,"benchmark.enqueued","benchmark",bid)
                return self._benchmark_view(c,self._benchmark(c,w,bid))
            return self._idem(c,p,w,"benchmark.create",key,body,202,create)

    def benchmark(self,p,w,bid):
        with self.connect() as c:
            self._authorize(c,p,w)
            return self._benchmark_view(c,self._benchmark(c,w,bid))

    def list_benchmarks(self,p,w,limit,cursor):
        with self.connect() as c:
            self._authorize(c,p,w)
            return self._page(c,"SELECT * FROM benchmarks WHERE workspace_id=%s",[w],digest([str(w),"benchmarks"]),limit,cursor,lambda b:self._benchmark_view(c,b))

    def cancel_benchmark(self,p,w,bid,key):
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def change():
                b=self._benchmark(c,w,bid)
                c.execute("UPDATE runs SET status='cancelled',finished_at=clock_timestamp() WHERE workspace_id=%s AND benchmark_id=%s AND status='queued'",(w,bid))
                c.execute("UPDATE runs SET status='cancelling' WHERE workspace_id=%s AND benchmark_id=%s AND status='running'",(w,bid))
                self._audit(c,w,p.user_id,"benchmark.cancel_requested","benchmark",bid)
                return self._benchmark_view(c,b)
            return self._idem(c,p,w,"benchmark.cancel:"+str(bid),key,{},202,change)

    def comparison(self,p,w,bid):
        with self.connect() as c:
            # One MVCC snapshot for status and metrics.
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self._authorize(c,p,w)
            b=self._benchmark_view(c,self._benchmark(c,w,bid))
            rows=c.execute("SELECT r.*,m.result_json FROM runs r LEFT JOIN run_metrics m ON m.workspace_id=r.workspace_id AND m.run_id=r.id WHERE r.workspace_id=%s AND r.benchmark_id=%s ORDER BY r.algorithm,r.seed",(w,bid)).fetchall()
            runs=[{"run":run_view(r),"metrics":r["result_json"]} for r in rows]
            summaries=[]; inputs=[]
            for r in runs:
                inputs.append({"condition":"benchmark","seed":r["run"]["seed"],"algorithm":r["run"]["algorithm"],"status":r["run"]["status"],"metrics":r["metrics"] or {}})
            for a in b["algorithms"]:
                group=[r for r in inputs if r["algorithm"]==a]
                values=[]
                for metric in METRICS:
                    v=[r["metrics"][metric] for r in group if r["status"]=="succeeded" and r["metrics"].get(metric) is not None]
                    values.append({"metric":metric,"n":len(v),"mean":mean(v) if v else None,"median":median(v) if v else None})
                summaries.append({"algorithm":a,"successful_runs":sum(r["status"]=="succeeded" for r in group),"failed_runs":sum(r["status"]=="failed" for r in group),"cancelled_runs":sum(r["status"]=="cancelled" for r in group),"metrics":values})
            baseline="centralized_greedy" if "centralized_greedy" in b["algorithms"] else b["algorithms"][0]
            comparisons=[]
            for candidate in b["algorithms"]:
                if candidate==baseline:continue
                for metric in METRICS:
                    r=paired(inputs,"benchmark",metric,candidate,baseline)
                    comparisons.append({k:v for k,v in r.items() if k not in ("condition","paired_differences")})
            return {"benchmark":b,"runs":runs,"summaries":summaries,"paired_comparisons":comparisons}

    def queue_command(self,p,w,rid,payload,key):
        with self.connect() as c:
            self._authorize(c,p,w,True)
            def create():
                r=self._get_run(c,w,rid,True)
                if r["status"]!="running" or r["mode"]!="interactive":raise Conflict("active interactive run required")
                if r["last_command_seq"]>=20:raise QuotaExceeded("interactive command limit")
                seq=r["last_command_seq"]+1
                row=c.execute("INSERT INTO run_commands(workspace_id,run_id,command_seq,actor_id,payload) VALUES (%s,%s,%s,%s,%s) RETURNING *",(w,rid,seq,p.user_id,Jsonb(payload))).fetchone()
                c.execute("UPDATE runs SET last_command_seq=%s WHERE workspace_id=%s AND id=%s",(seq,w,rid))
                self._audit(c,w,p.user_id,"run.command_queued","run",rid)
                return select(row,"command_seq status payload applied_tick rejection_reason created_at")
            return self._idem(c,p,w,"command:"+str(rid),key,payload,202,create)

    def commands(self,p,w,rid,limit,cursor):
        with self.connect() as c:
            self._authorize(c,p,w);self._get_run(c,w,rid)
            return self._page(c,"SELECT * FROM run_commands WHERE workspace_id=%s AND run_id=%s",[w,rid],digest([str(w),str(rid),"commands"]),limit,cursor,lambda r:select(r,"command_seq status payload applied_tick rejection_reason created_at"),"command_seq",True)

    def export_header(self,p,w,rid):
        with self.connect() as c:
            c.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self._authorize(c,p,w)
            r=self._get_run(c,w,rid)
            m=c.execute("SELECT result_json FROM run_metrics WHERE workspace_id=%s AND run_id=%s",(w,rid)).fetchone()
            return {"manifest":r["manifest"],"run":run_view(r),"metrics":m["result_json"] if m else None}
