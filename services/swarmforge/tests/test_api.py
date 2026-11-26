"""Contract and real-worker integration over ASGI; no mocked simulation data."""
import os
import json
import unittest
from uuid import uuid4
from test_core import fixture,ROOT
import test_persistence

DSN=os.getenv("SWARMFORGE_TEST_DATABASE_URL")


@unittest.skipUnless(DSN,"dedicated PostgreSQL required")
class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reuse the isolated-schema migration setup, not the test cases.
        test_persistence.PersistenceTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        test_persistence.PersistenceTests.tearDownClass.__func__(cls)

    def setUp(self):
        from swarmforge.persistence.control import ControlRepository
        from swarmforge.api.auth import Authenticator
        from swarmforge.api.main import create_app
        from fastapi.testclient import TestClient
        from swarmforge.application.identity import Principal
        self.repo=ControlRepository(self.dsn,"api-integration",max_workspace_active=2)
        self.w=uuid4();self.other=uuid4();self.user=uuid4();self.viewer=uuid4()
        with self.repo.connect() as c:
            c.execute("TRUNCATE workspaces,users CASCADE")
            for u,s in ((self.user,"owner"),(self.viewer,"viewer")):
                c.execute("INSERT INTO users(id,issuer,subject) VALUES (%s,'swarmforge-local',%s)",(u,s))
            for w in (self.w,self.other):c.execute("INSERT INTO workspaces(id,name) VALUES (%s,'test')",(w,))
            for u,role in ((self.user,"owner"),(self.viewer,"viewer")):
                c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES (%s,%s,%s)",(self.w,u,role))
        self.token="a"*40
        self.auth=Authenticator(self.repo,mode="local",token=self.token,subject="owner")
        self.app=create_app(self.repo,self.auth,ROOT/"contracts")
        self.client=TestClient(self.app,headers={"Authorization":"Bearer "+self.token})
        self.viewer_client=TestClient(create_app(self.repo,Authenticator(self.repo,mode="local",token="b"*40,subject="viewer"),ROOT/"contracts"),headers={"Authorization":"Bearer "+"b"*40})
        self.prefix="/api/v1/workspaces/"+str(self.w)
        self.contract=json.loads((ROOT/"contracts/openapi.json").read_text())

    def assert_schema(self,name,data):
        from jsonschema import Draft202012Validator,FormatChecker
        from referencing import Registry,Resource
        from referencing.jsonschema import DRAFT202012
        r=Registry().with_resource("urn:test:contract",Resource.from_contents(self.contract,default_specification=DRAFT202012))
        Draft202012Validator({"$ref":"urn:test:contract#/components/schemas/"+name},registry=r,format_checker=FormatChecker()).validate(data)
        return data

    def post(self,path,body=None,key=None,status=202):
        r=self.client.post(self.prefix+path,json=body,headers={"Idempotency-Key":key or str(uuid4())})
        self.assertEqual(r.status_code,status,r.text[:1000])
        return r.json()

    def scenario(self):
        return self.assert_schema("CreatedScenario",self.post("/scenarios",{"name":"warehouse","config":fixture()},status=201))["scenario"]["id"]

    def test_contract_routes_and_auth(self):
        paths={(r.path,m.lower()) for r in self.app.routes for m in (r.methods or [])}
        for path,ops in self.contract["paths"].items():
            for method in ops:self.assertIn((path,method),paths)
        self.assertEqual(self.client.get("/health/ready").status_code,200)
        self.assert_schema("Me",self.client.get("/api/v1/me").json())
        self.assertEqual(self.client.get("/api/v1/me",headers={"Authorization":"Bearer wrong"}).status_code,401)
        self.assertEqual(self.client.get("/api/v1/workspaces/"+str(self.other)).status_code,404)
        self.assertEqual(self.viewer_client.post(self.prefix+"/scenarios",json={"name":"x","config":fixture()},headers={"Idempotency-Key":"a"}).status_code,403)

    def test_scenario_pagination_revision_archive(self):
        sid=self.scenario();self.scenario()
        a=self.assert_schema("ScenarioPage",self.client.get(self.prefix+"/scenarios?limit=1").json())
        b=self.assert_schema("ScenarioPage",self.client.get(self.prefix+"/scenarios",params={"limit":1,"cursor":a["next_cursor"]}).json())
        self.assertNotEqual(a["items"][0]["id"],b["items"][0]["id"])
        cfg=fixture();cfg["duration_ticks"]=60
        self.assert_schema("Revision",self.post(f"/scenarios/{sid}/revisions",{"config":cfg},status=201))
        self.assertEqual(self.client.get(self.prefix+f"/scenarios/{sid}/revisions/1").json()["config"]["duration_ticks"],50)
        self.assert_schema("RevisionPage",self.client.get(self.prefix+f"/scenarios/{sid}/revisions").json())
        self.assert_schema("Scenario",self.post(f"/scenarios/{sid}/archive",status=200))
        self.assertEqual(len(self.client.get(self.prefix+"/scenarios").json()["items"]),1)

    def test_run_worker_sse_export_idempotency(self):
        from swarmforge.worker.main import Worker
        sid=self.scenario()
        body={"scenario_id":sid,"revision":1,"algorithm":"scoped_lease","seed":42,"mode":"scripted"}
        a=self.assert_schema("Run",self.post("/runs",body,key="run"))
        rid=a["id"]
        self.assertEqual(self.client.get(self.prefix+f"/runs/{rid}/snapshot").status_code,409)
        self.assertTrue(Worker(self.repo,ROOT/"contracts").once())
        self.assertEqual(a,self.post("/runs",body,key="run"))
        r=self.assert_schema("Run",self.client.get(self.prefix+f"/runs/{rid}").json())
        self.assertEqual(r["status"],"succeeded")
        m=self.assert_schema("Metrics",self.client.get(self.prefix+f"/runs/{rid}/metrics").json())
        self.assertEqual(m["completed"],2)
        self.assert_schema("Manifest",self.client.get(self.prefix+f"/runs/{rid}/manifest").json())
        self.assert_schema("Snapshot",self.client.get(self.prefix+f"/runs/{rid}/snapshot").json())
        page=self.assert_schema("EventPage",self.client.get(self.prefix+f"/runs/{rid}/events?limit=2").json())
        self.assertEqual(page["next_after_seq"],2)
        stream=self.client.get(self.prefix+f"/runs/{rid}/stream",headers={"Last-Event-ID":"2"})
        self.assertEqual(stream.status_code,200)
        self.assertTrue(stream.text.startswith("id: 3\n"))
        self.assertIn("event: stream.closed",stream.text)
        exp=self.assert_schema("RunExport",self.client.get(self.prefix+f"/runs/{rid}/export").json())
        from swarmforge.core.trace import semantic_digest
        self.assertEqual(semantic_digest(exp["events"]),m["trace_hash"])
        self.assertEqual(self.client.get(self.prefix+f"/runs/{rid}/stream?after_seq=999999").status_code,409)
        self.assertEqual(self.client.post(self.prefix+f"/runs/{rid}/commands",json={"type":"controller_outage","duration_ticks":5},headers={"Idempotency-Key":"cmd"}).status_code,409)
        self.assert_schema("CommandPage",self.client.get(self.prefix+f"/runs/{rid}/commands").json())

    def test_benchmark_fanout_comparison_and_cancel(self):
        from swarmforge.worker.main import Worker
        sid=self.scenario()
        body={"scenario_id":sid,"revision":1,"algorithms":["centralized_greedy","scoped_lease"],"seeds":[11,29]}
        b=self.assert_schema("Benchmark",self.post("/benchmarks",body,key="b"))
        self.assertEqual(b["total_runs"],4)
        self.assertEqual(b,self.post("/benchmarks",body,key="b"))
        worker=Worker(self.repo,ROOT/"contracts")
        for _ in range(4):self.assertTrue(worker.once())
        bid=b["id"]
        result=self.assert_schema("BenchmarkComparison",self.client.get(self.prefix+f"/benchmarks/{bid}/comparison").json())
        self.assertEqual(result["benchmark"]["successful_runs"],4)
        self.assertEqual(len(result["runs"]),4)
        self.assertEqual(self.client.get(self.prefix+f"/benchmarks/{bid}/export?format=csv").status_code,200)
        self.assert_schema("RunPage",self.client.get(self.prefix+f"/benchmarks/{bid}/runs").json())
        b2=self.post("/benchmarks",body)
        cancelled=self.assert_schema("Benchmark",self.post(f"/benchmarks/{b2['id']}/cancel"))
        self.assertEqual(cancelled["cancelled_runs"],4)

    def test_interactive_command_and_evidence(self):
        from swarmforge.worker.main import Worker
        from concurrent.futures import ThreadPoolExecutor
        import time
        sid=self.scenario()
        r=self.assert_schema("Run",self.post("/runs",{"scenario_id":sid,"revision":1,"algorithm":"centralized_greedy","seed":42,"mode":"interactive"}))
        rid=r["id"];path=f"/runs/{rid}"
        with ThreadPoolExecutor(max_workers=1) as pool:
            f=pool.submit(Worker(self.repo,ROOT/"contracts").once)
            for _ in range(100):
                if self.client.get(self.prefix+path).json()["status"]=="running":break
                time.sleep(.025)
            cmd=self.assert_schema("Command",self.post(path+"/commands",{"type":"packet_loss","duration_ticks":4,"links":[{"from":"r1","to":"C"}],"drop_rate":1},key="fault"))
            self.assertEqual(cmd,self.post(path+"/commands",{"type":"packet_loss","duration_ticks":4,"links":[{"from":"r1","to":"C"}],"drop_rate":1},key="fault"))
            self.assertTrue(f.result(timeout=30))
        r=self.client.get(self.prefix+path).json()
        self.assertEqual(r["status"],"succeeded",r)
        commands=self.assert_schema("CommandPage",self.client.get(self.prefix+path+"/commands").json())
        self.assertEqual(commands["items"][0]["status"],"applied")
        exp=self.assert_schema("RunExport",self.client.get(self.prefix+path+"/export").json())
        applied=[e for e in exp["events"] if e["type"]=="command.applied"]
        self.assertEqual(len(applied),1)
        self.assertEqual(applied[0]["tick"],commands["items"][0]["applied_tick"])
        self.assertEqual(len(exp["manifest"]["config"]["faults"]),len(fixture()["faults"]))
        self.assertTrue(any(e["type"]=="network.fault_started" and e["payload"]["fault_id"]==applied[0]["payload"]["fault_id"] for e in exp["events"]))

    def test_validation_and_oversize(self):
        self.assertEqual(self.client.post(self.prefix+"/scenarios",json={"name":"x"},headers={"Idempotency-Key":"a"}).status_code,422)
        r=self.client.post(self.prefix+"/scenarios",content=b"x"*262145,headers={"Content-Type":"application/json","Idempotency-Key":"a"})
        self.assertEqual(r.status_code,422)
