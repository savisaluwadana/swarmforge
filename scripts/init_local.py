"""Create an isolated local configuration without logging credentials."""
import argparse
import os
import secrets
import subprocess
from pathlib import Path

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default=".env")
    args=parser.parse_args()
    path=Path(args.output)
    if path.exists():raise SystemExit("Refusing to overwrite existing configuration: "+str(path))
    build=subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip()
    password=secrets.token_hex(24)
    values={"POSTGRES_PASSWORD":password,"DATABASE_URL":"postgresql://swarmforge:"+password+"@postgres:5432/swarmforge","ENGINE_VERSION":build,
            "AUTH_MODE":"local","LOCAL_DEMO_SUBJECT":"demo","LOCAL_DEMO_TOKEN":secrets.token_urlsafe(40),
            "LOCAL_MCP_TOKEN":secrets.token_urlsafe(40),"AGENT_APPROVAL_SECRET":secrets.token_urlsafe(40)}
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,"w") as out:
        for k,v in values.items():out.write(k+"="+v+"\n")
    print("Created local configuration; read credentials from",path,"privately. Model provider disabled.")
if __name__=="__main__":main()
