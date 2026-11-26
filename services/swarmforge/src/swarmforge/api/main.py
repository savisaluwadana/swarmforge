"""Contract-first REST control plane; all simulations run in the separate worker."""
import csv
import io
import json
import os
import time
from pathlib import Path
from uuid import UUID,uuid4
from typing import Literal
from fastapi import FastAPI,Depends,Header,Query,Request,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,StreamingResponse,Response
from jsonschema import Draft202012Validator,FormatChecker,ValidationError
from referencing import Registry,Resource
from referencing.jsonschema import DRAFT202012
import psycopg
from swarmforge import __version__
from swarmforge.api.auth import Authenticator
from swarmforge.application.identity import NotFound,Forbidden,Conflict,QuotaExceeded
from swarmforge.application.views import run_view,revision_view
from swarmforge.persistence.control import ControlRepository
from swarmforge.persistence.repository import TERMINAL
from swarmforge.domain.model import validate_config,InvalidScenario
from swarmforge.core.trace import canonical


def csv_response(rows,name):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    buf=io.StringIO()
    writer=csv.DictWriter(buf,fieldnames=keys)
    writer.writeheader()
    for r in rows:
        writer.writerow({k:("'"+v if isinstance(v,str) and v[:1] in ("=","+","-","@","\t","\r") else v) for k,v in r.items()})
    return Response(buf.getvalue(),media_type="text/csv",headers={"Content-Disposition":f'attachment; filename="{name}.csv"'})


def create_app(repo,auth,contracts="contracts",provider=None,approval_secret=None,mcp_token=None):
    contract=json.loads((Path(contracts)/"openapi.json").read_text())
    registry=Registry().with_resource("urn:swarmforge:api",Resource.from_contents(contract,default_specification=DRAFT202012))
    def validate(name,value):
        Draft202012Validator({"$ref":"urn:swarmforge:api#/components/schemas/"+name},registry=registry,format_checker=FormatChecker()).validate(value)
        return value
    app=FastAPI(title="SwarmForge API",docs_url=None,redoc_url=None,openapi_url="/openapi.json")
    app.openapi=lambda:contract
    prefix="/api/v1/workspaces/{workspace_id}"
    def error(request,status,code,message,details=None,headers=None):
        return JSONResponse(status_code=status,content={"code":code,"message":str(message)[:1024] or code,"request_id":getattr(request.state,"request_id",str(uuid4())),"details":details or []},headers=headers)
    @app.middleware("http")
    async def request_boundary(request,call_next):
        request.state.request_id=str(uuid4())
        if request.method=="POST":
            # Bound actual bytes even for chunked requests.
            data=bytearray()
            async for chunk in request.stream():
                data.extend(chunk)
                if len(data)>262144:return error(request,422,"invalid_input","Request exceeds 256 KiB")
            request._body=bytes(data)
        response=await call_next(request)
        response.headers["X-Request-ID"]=request.state.request_id
        response.headers["Cache-Control"]="no-store"
        return response
    @app.exception_handler(HTTPException)
    async def http_error(request,exc):
        return error(request,exc.status_code,"unauthenticated" if exc.status_code==401 else "http_error",exc.detail,headers=exc.headers)
    @app.exception_handler(RequestValidationError)
    async def request_error(request,exc):
        return error(request,422,"invalid_input","Invalid request",[{"path":"/"+"/".join(map(str,e["loc"])),"message":e["msg"]} for e in exc.errors()[:100]])
    @app.exception_handler(ValidationError)
    async def schema_error(request,exc):
        return error(request,422,"invalid_input","Request does not match contract",[{"path":"/"+"/".join(map(str,exc.absolute_path)),"message":exc.message[:1024]}])
    for cls,status,code in [(NotFound,404,"not_found"),(Forbidden,403,"forbidden"),(Conflict,409,"conflict"),(QuotaExceeded,429,"quota_exceeded"),(ValueError,422,"invalid_input"),(psycopg.Error,503,"unavailable")]:
        def handler(status,code):
            async def handle(request,exc):
                return error(request,status,code,"Database unavailable" if status==503 else str(exc))
            return handle
        app.add_exception_handler(cls,handler(status,code))
    def principal(authorization:str|None=Header(default=None)):return auth.authenticate(authorization)
    def key(idempotency_key:str=Header(min_length=1,max_length=128)):return idempotency_key
    def page(limit:int=Query(50,ge=1,le=100),cursor:str|None=Query(None,max_length=512)):return limit,cursor

    @app.get("/health/live")
    def health_live():return {"status":"ok"}
    @app.get("/health/ready")
    def health_ready():
        try:
            with repo.connect() as c:
                v={r["version"] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
                if not {"001_initial.sql","002_full_metrics.sql","003_agent.sql"}<=v:raise RuntimeError()
            return {"status":"ok"}
        except Exception:raise HTTPException(503,"Database or schema unavailable")
    @app.get("/api/v1/me")
    def me(p=Depends(principal)):return repo.me(p)
    @app.get(prefix)
    def workspace(workspace_id:UUID,p=Depends(principal)):return repo.workspace(p,workspace_id)
    @app.get(prefix+"/scenarios")
    def list_scenarios(workspace_id:UUID,include_archived:bool=False,pg=Depends(page),p=Depends(principal)):
        return repo.list_scenarios(p,workspace_id,*pg,include_archived)
    @app.post(prefix+"/scenarios/validate")
    def validate_scenario(workspace_id:UUID,body:dict,p=Depends(principal)):
        repo.authorize_editor(p,workspace_id);validate("ScenarioConfig",body)
        try:validate_config(body)
        except InvalidScenario as e:
            path,_,message=str(e).partition(": ")
            return {"valid":False,"issues":[{"path":path,"message":message or str(e)}]}
        return {"valid":True,"issues":[]}
    @app.post(prefix+"/scenarios",status_code=201)
    def create_scenario(workspace_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        validate("CreateScenario",body)
        return repo.create_scenario(p,workspace_id,body["name"],body["config"],k)["response"]
    @app.get(prefix+"/scenarios/{scenario_id}")
    def get_scenario(workspace_id:UUID,scenario_id:UUID,p=Depends(principal)):return repo.scenario(p,workspace_id,scenario_id)
    @app.post(prefix+"/scenarios/{scenario_id}/archive")
    def archive(workspace_id:UUID,scenario_id:UUID,k=Depends(key),p=Depends(principal)):return repo.archive(p,workspace_id,scenario_id,k)
    @app.get(prefix+"/scenarios/{scenario_id}/revisions")
    def revisions(workspace_id:UUID,scenario_id:UUID,pg=Depends(page),p=Depends(principal)):return repo.list_revisions(p,workspace_id,scenario_id,*pg)
    @app.post(prefix+"/scenarios/{scenario_id}/revisions",status_code=201)
    def create_revision(workspace_id:UUID,scenario_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        validate("CreateRevision",body)
        return repo.create_revision(p,workspace_id,scenario_id,body["config"],k)["response"]
    @app.get(prefix+"/scenarios/{scenario_id}/revisions/{version}")
    def revision(workspace_id:UUID,scenario_id:UUID,version:int,p=Depends(principal)):
        return revision_view(repo.get_revision(p,workspace_id,scenario_id,version))
    @app.get(prefix+"/runs")
    def runs(workspace_id:UUID,status:Literal["queued","running","cancelling","succeeded","failed","cancelled"]|None=None,scenario_id:UUID|None=None,benchmark_id:UUID|None=None,pg=Depends(page),p=Depends(principal)):
        return repo.list_runs(p,workspace_id,*pg,status,scenario_id,benchmark_id)
    @app.post(prefix+"/runs",status_code=202)
    def create_run(workspace_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        validate("RunCreate",body)
        return repo.enqueue(p,workspace_id,UUID(body["scenario_id"]),body["revision"],body["algorithm"],body["seed"],k,body["mode"])["response"]
    @app.get(prefix+"/runs/{run_id}")
    def run(workspace_id:UUID,run_id:UUID,p=Depends(principal)):return run_view(repo.get_run(p,workspace_id,run_id))
    @app.post(prefix+"/runs/{run_id}/cancel",status_code=202)
    def cancel(workspace_id:UUID,run_id:UUID,k=Depends(key),p=Depends(principal)):return repo.cancel(p,workspace_id,run_id,k)["response"]
    @app.get(prefix+"/runs/{run_id}/manifest")
    def manifest(workspace_id:UUID,run_id:UUID,p=Depends(principal)):return repo.get_run(p,workspace_id,run_id)["manifest"]
    @app.get(prefix+"/runs/{run_id}/snapshot")
    def snapshot(workspace_id:UUID,run_id:UUID,at_seq:int|None=Query(None,ge=0,le=9007199254740991),p=Depends(principal)):return repo.get_snapshot(p,workspace_id,run_id,at_seq)
    @app.get(prefix+"/runs/{run_id}/events")
    def events(workspace_id:UUID,run_id:UUID,after_seq:int=Query(0,ge=0,le=9007199254740991),limit:int=Query(200,ge=1,le=1000),p=Depends(principal)):
        data=repo.read_events(p,workspace_id,run_id,after_seq,limit)
        end=data[-1]["seq"] if data else after_seq
        r=repo.get_run(p,workspace_id,run_id)
        return {"items":data,"next_after_seq":end,"has_more":end<r["last_seq"]}
    @app.get(prefix+"/runs/{run_id}/stream")
    def stream(workspace_id:UUID,run_id:UUID,after_seq:int=Query(0,ge=0,le=9007199254740991),last_event_id:str|None=Header(None),authorization:str|None=Header(None),p=Depends(principal)):
        if last_event_id is not None:
            if not last_event_id.isascii() or not last_event_id.isdigit() or len(last_event_id)>16:raise ValueError("invalid Last-Event-ID")
            after_seq=int(last_event_id)
        r=repo.get_run(p,workspace_id,run_id)
        if after_seq>r["last_seq"]:raise Conflict("reset_required")
        def frames():
            cursor=after_seq;start=last=time.monotonic()
            while time.monotonic()-start<60:
                try:
                    actor=auth.authenticate(authorization)
                    data=repo.read_events(actor,workspace_id,run_id,cursor,200)
                    r=repo.get_run(actor,workspace_id,run_id)
                except (HTTPException,NotFound,Forbidden,Conflict,psycopg.Error):
                    return
                for e in data:
                    cursor=e["seq"]
                    yield f"id: {cursor}\nevent: {e['type']}\ndata: "+canonical(e).decode()+"\n\n"
                if r["status"] in TERMINAL and cursor>=r["last_seq"]:
                    yield "event: stream.closed\ndata: "+json.dumps({"status":r["status"]})+"\n\n";return
                if time.monotonic()-last>=15:
                    yield ": heartbeat\n\n";last=time.monotonic()
                if not data:time.sleep(.25)
        return StreamingResponse(frames(),media_type="text/event-stream",headers={"X-Accel-Buffering":"no"})
    @app.post(prefix+"/runs/{run_id}/commands",status_code=202)
    def command(workspace_id:UUID,run_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        repo.authorize_editor(p,workspace_id);repo.get_run(p,workspace_id,run_id);validate("FaultCommand",body)
        if body["type"]=="robot_crash" and body["duration_ticks"] is not None:raise ValueError("robot crash must be permanent")
        return repo.queue_command(p,workspace_id,run_id,body,k)
    @app.get(prefix+"/runs/{run_id}/commands")
    def commands(workspace_id:UUID,run_id:UUID,pg=Depends(page),p=Depends(principal)):return repo.commands(p,workspace_id,run_id,*pg)
    @app.get(prefix+"/runs/{run_id}/metrics")
    def metrics(workspace_id:UUID,run_id:UUID,p=Depends(principal)):return repo.get_metrics(p,workspace_id,run_id)
    @app.get(prefix+"/runs/{run_id}/export")
    def export_run(workspace_id:UUID,run_id:UUID,format:Literal["json","csv"]="json",authorization:str|None=Header(None),p=Depends(principal)):
        head=repo.export_header(p,workspace_id,run_id)
        if format=="csv":
            return csv_response([{"run_id":str(run_id),"status":head["run"]["status"],**{k:v for k,v in (head["metrics"] or {}).items() if not isinstance(v,dict)}}],"run")
        def generate():
            # Freeze event upper bound at export start, page by committed seq.
            yield canonical(head)[:-1]+b',"events":['
            cursor=0;end=head["run"]["last_seq"]
            while cursor<end:
                actor=auth.authenticate(authorization)
                data=repo.read_events(actor,workspace_id,run_id,cursor,min(200,end-cursor))
                if not data:raise RuntimeError("export cursor gap")
                for e in data:
                    if cursor:yield b","
                    yield canonical(e);cursor=e["seq"]
            yield b"]}"
        return StreamingResponse(generate(),media_type="application/json",headers={"Content-Disposition":'attachment; filename="run.json"'})
    @app.get(prefix+"/benchmarks")
    def benchmarks(workspace_id:UUID,pg=Depends(page),p=Depends(principal)):return repo.list_benchmarks(p,workspace_id,*pg)
    @app.post(prefix+"/benchmarks",status_code=202)
    def create_benchmark(workspace_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        validate("BenchmarkCreate",body)
        return repo.create_benchmark(p,workspace_id,UUID(body["scenario_id"]),body["revision"],body["algorithms"],body["seeds"],k)
    @app.get(prefix+"/benchmarks/{benchmark_id}")
    def benchmark(workspace_id:UUID,benchmark_id:UUID,p=Depends(principal)):return repo.benchmark(p,workspace_id,benchmark_id)
    @app.get(prefix+"/benchmarks/{benchmark_id}/runs")
    def benchmark_runs(workspace_id:UUID,benchmark_id:UUID,pg=Depends(page),p=Depends(principal)):return repo.list_runs(p,workspace_id,*pg,bid=benchmark_id)
    @app.post(prefix+"/benchmarks/{benchmark_id}/cancel",status_code=202)
    def cancel_benchmark(workspace_id:UUID,benchmark_id:UUID,k=Depends(key),p=Depends(principal)):return repo.cancel_benchmark(p,workspace_id,benchmark_id,k)
    @app.get(prefix+"/benchmarks/{benchmark_id}/comparison")
    def comparison(workspace_id:UUID,benchmark_id:UUID,p=Depends(principal)):return repo.comparison(p,workspace_id,benchmark_id)
    @app.get(prefix+"/benchmarks/{benchmark_id}/export")
    def export_benchmark(workspace_id:UUID,benchmark_id:UUID,format:Literal["json","csv"]="json",p=Depends(principal)):
        result=repo.comparison(p,workspace_id,benchmark_id)
        if format=="json":return result
        return csv_response([{"run_id":r["run"]["id"],"algorithm":r["run"]["algorithm"],"seed":r["run"]["seed"],"status":r["run"]["status"],**{k:v for k,v in (r["metrics"] or {}).items() if not isinstance(v,dict)}} for r in result["runs"]],"benchmark")
    from swarmforge.agent.gateway import Gateway
    from swarmforge.agent.provider import Provider,start_session,get_session
    from swarmforge.agent.mcp import install
    import hmac
    gateway=Gateway(repo,contracts);model=provider or Provider()
    secret=approval_secret if approval_secret is not None else os.getenv("AGENT_APPROVAL_SECRET","")
    tool_token=mcp_token if mcp_token is not None else os.getenv("LOCAL_MCP_TOKEN","")
    def require_human(x_approval_secret:str|None=Header(None)):
        if len(secret)<32 or secret in (getattr(auth,"token",None),tool_token) or not x_approval_secret or not hmac.compare_digest(secret.encode(),x_approval_secret.encode()):
            raise Forbidden("separate approval credential required")
    @app.post(prefix+"/agent/plans",status_code=201)
    def agent_draft(workspace_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        return gateway.draft(p,workspace_id,body,k)
    @app.get(prefix+"/agent/plans/{plan_id}")
    def agent_get(workspace_id:UUID,plan_id:UUID,p=Depends(principal)):
        return gateway.get(p,workspace_id,plan_id)
    @app.post(prefix+"/agent/plans/{plan_id}/approve",dependencies=[Depends(require_human)])
    def agent_approve(workspace_id:UUID,plan_id:UUID,body:dict,p=Depends(principal)):
        validate("AgentDecision",body);return gateway.decide(p,workspace_id,plan_id,body["expected_plan_hash"],"approved")
    @app.post(prefix+"/agent/plans/{plan_id}/deny",dependencies=[Depends(require_human)])
    def agent_deny(workspace_id:UUID,plan_id:UUID,body:dict,p=Depends(principal)):
        validate("AgentDecision",body);return gateway.decide(p,workspace_id,plan_id,body["expected_plan_hash"],"denied")
    @app.post(prefix+"/agent/plans/{plan_id}/execute",status_code=202)
    def agent_execute(workspace_id:UUID,plan_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        validate("AgentDecision",body);return gateway.execute(p,workspace_id,plan_id,body["expected_plan_hash"],k)
    @app.post(prefix+"/agent/sessions",status_code=201)
    def agent_session(workspace_id:UUID,body:dict,k=Depends(key),p=Depends(principal)):
        return start_session(gateway,model,p,workspace_id,body,k)
    @app.get(prefix+"/agent/sessions/{session_id}")
    def agent_get_session(workspace_id:UUID,session_id:UUID,p=Depends(principal)):
        return get_session(gateway,p,workspace_id,session_id)
    @app.get(prefix+"/agent/reports/{benchmark_id}")
    def agent_report(workspace_id:UUID,benchmark_id:UUID,p=Depends(principal)):
        return gateway.report(p,workspace_id,benchmark_id)
    install(app,gateway,auth,tool_token,secret)
    return app


def from_env():
    repo=ControlRepository(os.environ["DATABASE_URL"],os.environ.get("ENGINE_VERSION",__version__),
                           max_active=int(os.getenv("MAX_ACTIVE_RUNS","4")),max_workspace_active=int(os.getenv("MAX_WORKSPACE_RUNS","2")),max_workspace_pending=int(os.getenv("MAX_WORKSPACE_PENDING","120")))
    return create_app(repo,Authenticator(repo))
