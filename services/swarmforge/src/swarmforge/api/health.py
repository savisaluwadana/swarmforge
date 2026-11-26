"""Health endpoints only. No public mutation or identity bypass."""
import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import psycopg

app=FastAPI(title="SwarmForge R3",docs_url=None,redoc_url=None,openapi_url=None)


@app.get("/health/live")
def live():
    return {"status":"ok"}


@app.get("/health/ready")
def ready():
    try:
        with psycopg.connect(os.environ["DATABASE_URL"],connect_timeout=3) as c:
            versions={r[0] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
            if not {"001_initial.sql","002_full_metrics.sql"}<=versions:
                raise RuntimeError("schema not ready")
        return {"status":"ok"}
    except Exception:
        return JSONResponse(status_code=503,content={"code":"unavailable","message":"Database or schema unavailable","request_id":"readiness","details":[]})
