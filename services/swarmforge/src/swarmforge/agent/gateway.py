import json
from pathlib import Path
from uuid import UUID,uuid4
from datetime import datetime,timezone
from jsonschema import Draft202012Validator,FormatChecker
from referencing import Registry,Resource
from referencing.jsonschema import DRAFT202012
from psycopg.types.json import Jsonb
from swarmforge.application.identity import NotFound,Forbidden,Conflict,QuotaExceeded
from swarmforge.application.views import wire,run_view,revision_view
from swarmforge.core.trace import digest,canonical
from swarmforge.domain.model import validate_config,InvalidScenario


class Gateway:
    def __init__(self,repo,contracts):
        self.repo=repo
        root=Path(contracts)
        self.tools={t["name"]:t for t in json.loads((root/"agent-tools.json").read_text())["tools"]}
        self.registry=Registry().with_resource("urn:agent",Resource.from_contents(json.loads((root/"openapi.json").read_text()),default_specification=DRAFT202012))

    def schema(self,name,value):
        Draft202012Validator({"$ref":"urn:agent#/components/schemas/"+name},registry=self.registry,format_checker=FormatChecker()).validate(value)

    def _row(self,c,w,pid,lock=False):
        r=c.execute("SELECT * FROM agent_plans WHERE workspace_id=%s AND id=%s"+(" FOR UPDATE" if lock else ""),(w,pid)).fetchone()
        if not r:raise NotFound("plan")
        return r

    def _view(self,r):
        status=r["status"]
        if status in ("draft","approved") and r["expires_at"]<=datetime.now(timezone.utc):status="expired"
        return wire({"id":r["id"],"actor_id":r["actor_id"],"plan":r["plan_json"],"plan_hash":r["plan_hash"],"status":status,"created_at":r["created_at"],"expires_at":r["expires_at"],"execution":r["execution"],"approval_url":"/agent/"+str(r["id"])})

    def get(self,p,w,pid):
        with self.repo.connect() as c:
            self.repo._authorize(c,p,w)
            return self._view(self._row(c,w,pid))

    def draft(self,p,w,body,key):
        self.schema("AgentDraft",body)
        count=len(body["cases"])*len(body["algorithms"])*len(body["seeds"])
        if count>12 or len(canonical(body))>220000:raise QuotaExceeded("plan budget exceeded")
        with self.repo.connect() as c:
            self.repo._authorize(c,p,w,True)
            def create():
                n=c.execute("SELECT count(*) AS n FROM agent_plans WHERE workspace_id=%s AND status IN ('draft','approved') AND expires_at>clock_timestamp()",(w,)).fetchone()["n"]
                if n>=30:raise QuotaExceeded("active plan limit")
                cases=[]
                for case in body["cases"]:
                    sid=case.get("scenario_id");rev=case.get("revision")
                    if sid:
                        r=c.execute("SELECT r.config,r.config_hash,s.archived_at FROM scenario_revisions r JOIN scenarios s ON s.workspace_id=r.workspace_id AND s.id=r.scenario_id WHERE r.workspace_id=%s AND r.scenario_id=%s AND r.version=%s",(w,UUID(sid),rev)).fetchone()
                        if not r:raise NotFound("revision")
                        if r["archived_at"]:raise Conflict("archived scenario")
                        config=r["config"]
                        if digest(config)!=r["config_hash"]:raise Conflict("revision hash mismatch")
                    else:config=case["scenario_config"]
                    self.schema("ScenarioConfig",config);validate_config(config)
                    if len(config["robots"])>100 or config["duration_ticks"]>10000:raise QuotaExceeded("scenario limits")
                    cases.append({"label":case["label"],"scenario_id":sid,"revision":rev,"config":config,"config_hash":digest(config)})
                data={"objective":body["objective"],"cases":cases,"algorithms":body["algorithms"],"seeds":body["seeds"],"run_count":count,"engine_version":self.repo.engine_version}
                if len(canonical(data))>220000:raise QuotaExceeded("resolved plan too large")
                row=c.execute("INSERT INTO agent_plans(workspace_id,actor_id,plan_json,plan_hash,engine_version,expires_at) VALUES (%s,%s,%s,%s,%s,clock_timestamp()+interval '30 minutes') RETURNING *",(w,p.user_id,Jsonb(data),digest(data),self.repo.engine_version)).fetchone()
                self.repo._audit(c,w,p.user_id,"agent.plan_drafted","agent_plan",row["id"])
                return self._view(row)
            return self.repo._idem(c,p,w,"agent.draft",key,body,201,create)

    def decide(self,p,w,pid,expected,decision):
        with self.repo.connect() as c:
            self.repo._authorize(c,p,w,True)
            r=self._row(c,w,pid,True)
            if r["actor_id"]!=p.user_id:raise Forbidden("plan owner required")
            if r["status"]!="draft" or r["expires_at"]<=datetime.now(timezone.utc) or r["plan_hash"]!=expected or digest(r["plan_json"])!=expected or r["engine_version"]!=self.repo.engine_version:raise Conflict("plan not eligible for decision")
            c.execute("INSERT INTO agent_approvals(workspace_id,plan_id,approver_id,approved_hash,decision) VALUES (%s,%s,%s,%s,%s)",(w,pid,p.user_id,expected,decision))
            row=c.execute("UPDATE agent_plans SET status=%s WHERE workspace_id=%s AND id=%s RETURNING *",(decision,w,pid)).fetchone()
            self.repo._audit(c,w,p.user_id,"agent."+decision,"agent_plan",pid)
            return self._view(row)

    def execute(self,p,w,pid,expected,key):
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError("idempotency key required")
        with self.repo.connect() as c:
            self.repo._authorize(c,p,w,True)
            r=self._row(c,w,pid,True);data=r["plan_json"]
            if r["actor_id"]!=p.user_id:raise Forbidden("plan owner required")
            if r["plan_hash"]!=expected or digest(data)!=expected:raise Conflict("plan hash mismatch")
            if r["status"]=="executed":return r["execution"]
            if r["status"]!="approved" or r["expires_at"]<=datetime.now(timezone.utc) or r["engine_version"]!=self.repo.engine_version:raise Conflict("valid approval required")
            a=c.execute("SELECT * FROM agent_approvals WHERE workspace_id=%s AND plan_id=%s FOR UPDATE",(w,pid)).fetchone()
            if not a or a["decision"]!="approved" or a["approver_id"]!=p.user_id or a["approved_hash"]!=expected or a["consumed_at"]:raise Conflict("valid approval required")
            count=len(data["cases"])*len(data["algorithms"])*len(data["seeds"])
            n=c.execute("SELECT count(*) AS n FROM runs WHERE workspace_id=%s AND status IN ('queued','running','cancelling')",(w,)).fetchone()["n"]
            if count!=data["run_count"] or count>12 or n+count>self.repo.max_workspace_pending:raise QuotaExceeded("run limit")
            result={"plan_id":str(pid),"run_ids":[],"benchmark_ids":[]}
            for case in data["cases"]:
                config=case["config"];h=case["config_hash"];rev=case["revision"]
                if digest(config)!=h:raise Conflict("config hash mismatch")
                if case["scenario_id"]:
                    sid=UUID(case["scenario_id"])
                    current=c.execute("SELECT r.config_hash,s.archived_at FROM scenario_revisions r JOIN scenarios s ON s.workspace_id=r.workspace_id AND s.id=r.scenario_id WHERE r.workspace_id=%s AND r.scenario_id=%s AND r.version=%s",(w,sid,rev)).fetchone()
                    if not current or current["archived_at"] or current["config_hash"]!=h:raise Conflict("revision unavailable or changed")
                else:
                    sid=uuid4();rev=1
                    c.execute("INSERT INTO scenarios(workspace_id,id,name,created_by) VALUES (%s,%s,%s,%s)",(w,sid,case["label"],p.user_id))
                    self.repo._insert_revision(c,p,w,sid,rev,config)
                created=self.repo._enqueue_case(c,p,w,sid,rev,data["algorithms"],data["seeds"],config,h)
                result["run_ids"].extend(created["run_ids"])
                if created["benchmark_id"]:result["benchmark_ids"].append(created["benchmark_id"])
            c.execute("UPDATE agent_approvals SET consumed_at=clock_timestamp() WHERE workspace_id=%s AND plan_id=%s",(w,pid))
            c.execute("UPDATE agent_plans SET status='executed',execution=%s WHERE workspace_id=%s AND id=%s",(Jsonb(result),w,pid))
            self.repo._audit(c,w,p.user_id,"agent.executed","agent_plan",pid)
            return result

    def report(self,p,w,bid):
        comparison=self.repo.comparison(p,w,bid);facts=[]
        for r in comparison["runs"]:
            if r["run"]["status"]!="succeeded" or not r["metrics"]:continue
            for key in ("completed","released","latency_p50_ticks","latency_p95_ticks","completion_rate","messages_sent","actual_collisions","stranded"):
                facts.append({"run_id":r["run"]["id"],"manifest_hash":r["run"]["manifest_hash"],"metric":key,"value":r["metrics"].get(key)})
        return {"benchmark_id":str(bid),"comparison":comparison,"facts":facts,"limitations":["Synthetic simulation only, not physical safety evidence.","Failed or cancelled runs excluded from numeric comparisons; inspect missing counts.","Latency conditional on completed tasks; no claim of superiority."]}

    def call(self,p,name,args):
        t=self.tools.get(name)
        if not t:raise Forbidden("tool not allowlisted")
        if len(canonical(args))>220000:raise ValueError("tool input too large")
        Draft202012Validator(t["inputSchema"],format_checker=FormatChecker()).validate(args)
        w=UUID(args["workspace_id"]);r=self.repo
        with r.connect() as c:
            r._authorize(c,p,w)
            c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",(str(w)+":agent-rate",))
            n=c.execute("SELECT count(*) AS n FROM agent_tool_audit WHERE workspace_id=%s AND actor_id=%s AND created_at>clock_timestamp()-interval '1 minute'",(w,p.user_id)).fetchone()["n"]
            if n>=60:raise QuotaExceeded("agent rate limit")
            aid=c.execute("INSERT INTO agent_tool_audit(workspace_id,actor_id,tool,request_hash,outcome) VALUES (%s,%s,%s,%s,'started') RETURNING id",(w,p.user_id,name,digest(args))).fetchone()["id"]
        result=None;outcome="failed";a={k:v for k,v in args.items() if k!="workspace_id"}
        try:
            if name=="list_scenarios":result=r.list_scenarios(p,w,a.get("limit",20),a.get("cursor"),False)
            elif name=="get_scenario":result=revision_view(r.get_revision(p,w,UUID(a["scenario_id"]),a["revision"]))
            elif name=="validate_scenario":
                try:validate_config(a["scenario_config"]);result={"valid":True,"issues":[]}
                except InvalidScenario as exc:result={"valid":False,"issues":[{"path":"/","message":str(exc)[:512]}]}
            elif name=="create_experiment_plan":result=self.draft(p,w,{k:v for k,v in a.items() if k!="idempotency_key"},a["idempotency_key"])
            elif name=="get_experiment_plan":result=self.get(p,w,UUID(a["plan_id"]))
            elif name=="execute_approved_plan":result=self.execute(p,w,UUID(a["plan_id"]),a["expected_plan_hash"],a["idempotency_key"])
            elif name=="get_run_status":result=run_view(r.get_run(p,w,UUID(a["run_id"])))
            elif name=="get_run_metrics":result=r.get_metrics(p,w,UUID(a["run_id"]))
            elif name=="get_run_manifest":result=r.get_run(p,w,UUID(a["run_id"]))["manifest"]
            elif name=="get_run_events":
                rid=UUID(a["run_id"]);after=a.get("after_seq",0);items=r.read_events(p,w,rid,after,a.get("limit",100));end=items[-1]["seq"] if items else after
                result={"items":items,"next_after_seq":end,"has_more":end<r.get_run(p,w,rid)["last_seq"]}
            elif name=="get_benchmark_status":result=r.benchmark(p,w,UUID(a["benchmark_id"]))
            elif name=="compare_benchmark":result=r.comparison(p,w,UUID(a["benchmark_id"]))
            elif name=="get_evidence_report":result=self.report(p,w,UUID(a["benchmark_id"]))
            Draft202012Validator(t["outputSchema"],format_checker=FormatChecker()).validate(result)
            if len(canonical(result))>262144:raise QuotaExceeded("tool output too large; inspect smaller pages or web export")
            outcome="succeeded"
            return result
        finally:
            with r.connect() as c:c.execute("UPDATE agent_tool_audit SET outcome=%s,result_hash=%s WHERE workspace_id=%s AND id=%s",(outcome,digest(result) if outcome=="succeeded" else None,w,aid))
