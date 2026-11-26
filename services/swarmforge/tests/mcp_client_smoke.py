"""Official SDK client against actual HTTP API + durable worker."""
import asyncio
import os
import json
from pathlib import Path
from uuid import uuid4
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    base="http://127.0.0.1:8000"
    with httpx.Client(base_url=base,headers={"Authorization":"Bearer "+os.environ["LOCAL_DEMO_TOKEN"]}) as rest:
        me=rest.get("/api/v1/me");me.raise_for_status();w=me.json()["workspaces"][0]["id"]
        prefix="/api/v1/workspaces/"+w
        config=json.loads(Path("examples/two-robot-outage.json").read_text())
        r=rest.post(prefix+"/scenarios",json={"name":"SDK acceptance fixture","config":config},headers={"Idempotency-Key":str(uuid4())});r.raise_for_status()
        sid=r.json()["scenario"]["id"]
        async with streamablehttp_client(base+"/mcp",headers={"Authorization":"Bearer "+os.environ["LOCAL_MCP_TOKEN"]}) as (read,write,_):
            async with ClientSession(read,write) as session:
                init=await session.initialize()
                tools=await session.list_tools();assert len(tools.tools)==13
                async def call(name,args,success=True):
                    result=await session.call_tool(name,{"workspace_id":w,**args})
                    assert bool(result.isError)!=success,result
                    return result.structuredContent
                plan=await call("create_experiment_plan",{"objective":"Compare outage policies","cases":[{"label":"outage","scenario_id":sid,"revision":1}],"algorithms":["centralized_greedy","scoped_lease"],"seeds":[42],"idempotency_key":str(uuid4())})
                args={"plan_id":plan["id"],"expected_plan_hash":plan["plan_hash"],"idempotency_key":str(uuid4())}
                await call("execute_approved_plan",args,False)
                approval=rest.post(prefix+"/agent/plans/"+plan["id"]+"/approve",json={"expected_plan_hash":plan["plan_hash"]},headers={"X-Approval-Secret":os.environ["AGENT_APPROVAL_SECRET"]})
                approval.raise_for_status()
                execution=await call("execute_approved_plan",args)
                assert len(execution["run_ids"])==2
                bid=execution["benchmark_ids"][0]
                for _ in range(30):
                    status=await call("get_benchmark_status",{"benchmark_id":bid})
                    if status["status"] in ("succeeded","failed","cancelled"):break
                    await asyncio.sleep(.5)
                assert status["status"]=="succeeded",status
                report=await call("get_evidence_report",{"benchmark_id":bid})
                assert report["facts"] and report["observations"],report
                print("Official SDK negotiated",init.protocolVersion,"; 13 tools; approved 2-run experiment succeeded; real evidence retrieved")
if __name__=="__main__":asyncio.run(main())
