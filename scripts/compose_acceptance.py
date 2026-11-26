"""Verify security boundaries and restart-safe evidence on the real Compose stack."""
import os
import json
from pathlib import Path
from uuid import uuid4
import time
import httpx
from swarmforge.core.trace import semantic_digest

def main():
    base="http://127.0.0.1:8000"
    auth={"Authorization":"Bearer "+os.environ["LOCAL_DEMO_TOKEN"]}
    with httpx.Client(base_url=base,timeout=30,headers=auth) as c:
        me=c.get("/api/v1/me");me.raise_for_status()
        w=me.json()["workspaces"][0]["id"];p="/api/v1/workspaces/"+w
        assert c.get("/api/v1/me",headers={"Authorization":"Bearer invalid"}).status_code==401
        assert c.get("/api/v1/me",headers={"Authorization":"Bearer "+os.environ["LOCAL_MCP_TOKEN"]}).status_code==401
        assert c.get("/api/v1/workspaces/"+str(uuid4())+"/runs").status_code==404
        assert c.post("/mcp",headers={"Origin":"https://invalid.example"},json={}).status_code==403
        cfg=json.loads(Path("examples/two-robot-outage.json").read_text())
        r=c.post(p+"/scenarios",json={"name":"Compose release acceptance","config":cfg},headers={"Idempotency-Key":str(uuid4())});r.raise_for_status()
        sid=r.json()["scenario"]["id"]
        payload={"scenario_id":sid,"revision":1,"algorithm":"scoped_lease","seed":42,"mode":"scripted"}
        key=str(uuid4())
        r=c.post(p+"/runs",json=payload,headers={"Idempotency-Key":key});r.raise_for_status()
        rid=r.json()["id"]
        for _ in range(120):
            status=c.get(p+"/runs/"+rid);status.raise_for_status()
            if status.json()["status"] in ("succeeded","failed","cancelled"):break
            time.sleep(.25)
        assert status.json()["status"]=="succeeded",status.text
        r=c.get(p+"/runs/"+rid+"/export");r.raise_for_status()
        exp=r.json()
        assert semantic_digest(exp["events"])==exp["metrics"]["trace_hash"]
        again=c.post(p+"/runs",json=payload,headers={"Idempotency-Key":key});again.raise_for_status();assert again.json()["id"]==rid
        out=Path("artifacts/compose");out.mkdir(parents=True,exist_ok=True)
        (out/"run.json").write_text(json.dumps(exp,indent=2)+"\n")
        (out/"handle.json").write_text(json.dumps({"workspace":w,"run":rid,"trace_hash":exp["metrics"]["trace_hash"]})+"\n")
        print("Compose authentication, workspace isolation, execution, trace digest and idempotency verified")
if __name__=="__main__":main()
