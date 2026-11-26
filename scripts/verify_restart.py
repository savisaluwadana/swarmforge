import json
import os
from pathlib import Path
import httpx
from swarmforge.core.trace import semantic_digest

h=json.loads(Path("artifacts/compose/handle.json").read_text())
with httpx.Client(base_url="http://127.0.0.1:8000",headers={"Authorization":"Bearer "+os.environ["LOCAL_DEMO_TOKEN"]},timeout=15) as c:
    r=c.get("/api/v1/workspaces/"+h["workspace"]+"/runs/"+h["run"]+"/export")
    r.raise_for_status();exp=r.json()
    assert exp["metrics"]["trace_hash"]==h["trace_hash"]==semantic_digest(exp["events"])
print("Committed evidence survived API/worker/PostgreSQL restart")
