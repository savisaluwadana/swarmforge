"""Official SDK stateless Streamable HTTP; local bearer preview only."""
from contextlib import asynccontextmanager
from contextvars import ContextVar
from urllib.parse import urlparse
import anyio
import hmac
from fastapi import HTTPException
from starlette.responses import JSONResponse
from starlette.routing import Route
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp import types
from swarmforge.application.identity import Forbidden,Conflict,NotFound,QuotaExceeded
from jsonschema import ValidationError

actor=ContextVar("mcp_actor",default=None)


def install(app,gateway,auth,mcp_token,approval_secret):
    server=Server("swarmforge")
    @server.list_tools()
    async def list_tools():
        return [types.Tool(name=t["name"],description=t["description"],inputSchema=t["inputSchema"],outputSchema=t["outputSchema"],annotations=types.ToolAnnotations(**t["annotations"])) for t in gateway.tools.values()]
    @server.call_tool()
    async def call_tool(name,arguments):
        p=actor.get()
        if p is None:raise ValueError("authentication required")
        try:return await anyio.to_thread.run_sync(gateway.call,p,name,arguments)
        except (Forbidden,Conflict,NotFound,QuotaExceeded,ValueError,ValidationError):
            raise ValueError("Tool rejected: invalid, unauthorized, unavailable or over budget")
    manager=StreamableHTTPSessionManager(app=server,json_response=True,stateless=True)
    old=app.router.lifespan_context
    @asynccontextmanager
    async def lifespan(a):
        async with old(a):
            async with manager.run():yield
    app.router.lifespan_context=lifespan
    class Endpoint:
        async def __call__(self,scope,receive,send):
            headers={k.decode().lower():v.decode() for k,v in scope["headers"]}
            host=headers.get("host","").split(":")[0];origin=headers.get("origin")
            if auth.mode!="local" or host not in ("127.0.0.1","localhost","testserver") or (origin and urlparse(origin).hostname not in ("127.0.0.1","localhost","testserver")):
                return await JSONResponse({"error":"MCP local access only"},status_code=403)(scope,receive,send)
            supplied=headers.get("authorization","")
            if len(mcp_token)<32 or mcp_token in (auth.token,approval_secret) or not hmac.compare_digest(supplied.encode(),("Bearer "+mcp_token).encode()):
                return await JSONResponse({"error":"MCP credential required"},status_code=401,headers={"WWW-Authenticate":"Bearer"})(scope,receive,send)
            p=await anyio.to_thread.run_sync(auth.repo.principal,"swarmforge-local",auth.subject)
            if not p:return await JSONResponse({"error":"authentication required"},status_code=401,headers={"WWW-Authenticate":"Bearer"})(scope,receive,send)
            token=actor.set(p)
            try:await manager.handle_request(scope,receive,send)
            finally:actor.reset(token)
    app.router.routes.append(Route("/mcp",Endpoint(),methods=["GET","POST","DELETE"]))
