"""Bounded capacity characterization, not a combined maximum-load guarantee."""
import json
import resource
import time
import os
from pathlib import Path
from swarmforge.core.simulator import Simulation,build_manifest
from swarmforge.benchmark.validate import ContractValidator,audit

def case(n,ticks):
    width=24 if n>1 else 6
    height=24 if n>1 else 6
    return {"schema_version":1,"width":width,"height":height,"obstacles":[],
            "robots":[{"id":f"r{i:03}","start":{"x":2*(i%10),"y":2*(i//10)},"zone":"z"} for i in range(n)],
            "zones":[{"id":"z","min_x":0,"max_x":width-1,"min_y":0,"max_y":height-1,"leader":"r000"}],
            "tasks":[{"id":"t0","pickup":{"x":0,"y":1},"dropoff":{"x":1,"y":1},"release_tick":0,"priority":1}],
            "network":{"default_delay_ticks":1,"default_drop_rate":0,"links":[]},"faults":[],
            "duration_ticks":ticks,"tick_ms":1000,"scope_lease_ticks":40}

def main():
    rows=[];validator=ContractValidator("contracts")
    out=Path("artifacts/scale");out.mkdir(parents=True,exist_ok=True)
    for n,ticks in [(100,20),(1,10000)]:
        for alg in ("centralized_greedy","local_auction","scoped_lease"):
            start=time.monotonic()
            row={"robots":n,"ticks":ticks,"algorithm":alg}
            try:
                m=build_manifest(case(n,ticks),42,os.environ.get("GITHUB_SHA","local"),algorithm=alg)
                result=Simulation(m).run()
                audit(result,validator)
                row.update(status="succeeded",trace_hash=result["metrics"]["trace_hash"],events=len(result["events"]),completed=result["metrics"]["completed"],actual_collisions=result["metrics"]["actual_collisions"],accepted_duplicates=result["metrics"]["accepted_duplicates"])
            except Exception as e:row.update(status="failed",error=type(e).__name__+": "+str(e))
            row.update(wall_seconds=round(time.monotonic()-start,3),process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
            rows.append(row);print(json.dumps(row),flush=True)
            (out/"results.json").write_text(json.dumps(rows,indent=2)+"\n")
    if any(r["status"]!="succeeded" or r["actual_collisions"] or r["accepted_duplicates"] for r in rows):raise SystemExit(1)
if __name__=="__main__":main()
