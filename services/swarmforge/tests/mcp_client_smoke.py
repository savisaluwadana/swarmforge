"""Official SDK client against running service; no mocked responses."""
import asyncio
import os
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

async def main():
    with httpx.Client() as c:
        r=c.get("http://127.0.0.1:8000/api/v1/me",headers={"Authorization":"Bearer "+os.environ["LOCAL_DEMO_TOKEN"]})
        r.raise_for_status()
        w=r.json()["workspaces"][0]["id"]
    async with streamablehttp_client("http://127.0.0.1:8000/mcp",headers={"Authorization":"Bearer "+os.environ["LOCAL_MCP_TOKEN"]}) as (read,write,_):
        async with ClientSession(read,write) as session:
            init=await session.initialize()
            tools=await session.list_tools()
            assert len(tools.tools)==13
            result=await session.call_tool("list_scenarios",{"workspace_id":w})
            assert not result.isError,result
            assert "items" in result.structuredContent,result
            print("Official MCP client negotiated",init.protocolVersion,"and successfully called list_scenarios")
if __name__=="__main__":asyncio.run(main())
