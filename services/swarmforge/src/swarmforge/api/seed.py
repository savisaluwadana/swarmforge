"""Explicit local-only identity provisioning, never exposed as an API route."""
import os
from swarmforge.persistence.control import ControlRepository


def main():
    if os.getenv("AUTH_MODE")!="local" or len(os.getenv("LOCAL_DEMO_TOKEN",""))<32:
        raise SystemExit("local mode with strong token required")
    repo=ControlRepository(os.environ["DATABASE_URL"],os.getenv("ENGINE_VERSION","0.3.0"))
    subject=os.getenv("LOCAL_DEMO_SUBJECT","demo")
    with repo.connect() as c:
        c.execute("SELECT pg_advisory_xact_lock(734182903)")
        u=c.execute("INSERT INTO users(issuer,subject,display_name) VALUES ('swarmforge-local',%s,'Local engineer') ON CONFLICT(issuer,subject) DO UPDATE SET display_name=excluded.display_name RETURNING id",(subject,)).fetchone()["id"]
        w=c.execute("SELECT workspace_id FROM memberships WHERE user_id=%s ORDER BY workspace_id LIMIT 1",(u,)).fetchone()
        if not w:
            wid=c.execute("INSERT INTO workspaces(name) VALUES ('Local reliability lab') RETURNING id").fetchone()["id"]
            c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES (%s,%s,'owner')",(wid,u))
        else:wid=w["workspace_id"]
    print("Local workspace:",wid)


if __name__=="__main__":main()
