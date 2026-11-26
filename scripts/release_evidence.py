"""Summarize measured research suite without inventing missing values."""
import argparse
import hashlib
import json
from pathlib import Path
from statistics import mean

def main():
    p=argparse.ArgumentParser()
    p.add_argument("directory",type=Path)
    args=p.parse_args()
    root=args.directory
    result=json.loads((root/"summary.json").read_text())
    rows=result["runs"]
    lines=["# Measured research evidence","",f"Engine: `{result['engine_version']}`",
           f"Planned: {result['planned']}; successful: {result['succeeded']}; failed: {result['failed']}.","",
           "Execution success means the experiment and its audit completed; it does not mean the policy completed every task.","",
           "| Condition | Policy | Valid runs | Mean completion rate | Mean outage completions | Mean messages/completion |",
           "|---|---|---:|---:|---:|---:|"]
    def fmt(v):return "—" if v is None else f"{v:.3f}"
    for condition in dict.fromkeys(r["condition"] for r in rows):
        for algorithm in dict.fromkeys(r["algorithm"] for r in rows):
            group=[r for r in rows if r["condition"]==condition and r["algorithm"]==algorithm and r["status"]=="succeeded"]
            def metric(k):
                vals=[r["metrics"][k] for r in group if r["metrics"].get(k) is not None]
                return mean(vals) if vals else None
            lines.append(f"| {condition} | {algorithm} | {len(group)} | {fmt(metric('completion_rate'))} | {fmt(metric('outage_completions'))} | {fmt(metric('messages_per_completion'))} |")
    lines.extend(["","## Limitations",*[ "- "+s for s in result["limitations"]],"","See runs.csv, comparisons.csv and traces/ for every result including failures."])
    (root/"EVIDENCE.md").write_text("\n".join(lines)+"\n")
    checks=[]
    for file in sorted(root.rglob("*")):
        if file.is_file() and file.name!="SHA256SUMS":
            checks.append(hashlib.sha256(file.read_bytes()).hexdigest()+"  "+file.relative_to(root).as_posix())
    (root/"SHA256SUMS").write_text("\n".join(checks)+"\n")
    print("\n".join(lines))
    if result["planned"]!=len(rows) or any(not r.get("replay_verified") for r in rows) or result["failed"]:raise SystemExit("Research acceptance failed; inspect retained artifacts")
if __name__=="__main__":main()
