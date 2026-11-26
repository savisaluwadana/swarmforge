"""Matched benchmark suite. Preserve all run outcomes and raw trace artifacts."""
import csv
import json
import platform
import random
from pathlib import Path
from statistics import mean,median
from swarmforge import __version__
from swarmforge.core.simulator import Simulation,build_manifest
from swarmforge.core.trace import canonical,digest
from swarmforge.benchmark.scenarios import design,scenario,POLICIES
from swarmforge.benchmark.validate import ContractValidator,audit


METRICS=("completion_rate","throughput_tasks_per_minute","latency_p50_ticks","latency_p95_ticks",
         "deadline_miss_rate","attempted_conflicts","stale_rejections","messages_per_completion",
         "estimated_message_bytes","utilization","stranded","outage_completions","recovery_ticks")


def write_json(path,value):
    path.write_bytes(canonical(value)+b"\n")


def paired(rows,condition,metric,candidate,baseline="centralized_greedy"):
    seeds=sorted({r["seed"] for r in rows if r["condition"]==condition})
    index={(r["seed"],r["algorithm"]):r for r in rows if r["condition"]==condition and r["status"]=="succeeded"}
    diffs=[]
    for seed in seeds:
        a=index.get((seed,candidate),{}).get("metrics",{}).get(metric)
        b=index.get((seed,baseline),{}).get("metrics",{}).get(metric)
        if a is not None and b is not None:
            diffs.append(a-b)
    ci=[None,None]
    if len(diffs)>=5:
        rng=random.Random(int(digest([condition,metric,candidate,baseline])[:16],16))
        values=sorted(mean(rng.choices(diffs,k=len(diffs))) for _ in range(1000))
        ci=[values[24],values[974]]
    return {"condition":condition,"metric":metric,"candidate":candidate,"baseline":baseline,
            "matched_n":len(diffs),"missing_n":len(seeds)-len(diffs),
            "mean_difference":mean(diffs) if diffs else None,"median_difference":median(diffs) if diffs else None,
            "ci95_low":ci[0],"ci95_high":ci[1],"paired_differences":diffs}


def recovery(ticks,healthy,heal,duration):
    if heal is None or heal+20>duration:
        return None,"undefined"
    had_reference=False
    for end in range(heal+20,duration+1):
        start=end-20
        reference=sum(start<=t<end for t in healthy)
        if not reference: continue
        had_reference=True
        actual=sum(start<=t<end for t in ticks)
        if 10*actual>=9*reference:
            return end-heal,"recovered"
    return None,"censored" if had_reference else "undefined"


def run_suite(suite,output,contracts,engine_version=__version__,runner=None,replay=True):
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    traces=output/"traces"; traces.mkdir(exist_ok=True)
    validator=ContractValidator(contracts)
    plan=design(suite)
    write_json(output/"design.json",{"suite":suite,"matrix":[{"condition":c,"seed":s,"algorithm":a} for c,s,a in plan],
              "engine_version":engine_version,"workload_source":"common_predeclared_local_release_v1",
              "synthetic":True,"runtime":platform.python_version(),"platform":platform.platform()})
    rows=[]
    run=runner or (lambda m:Simulation(m).run())
    for condition,seed,algorithm in plan:
        config=scenario(condition,seed)
        manifest=build_manifest(config,seed,engine_version,algorithm=algorithm)
        name=f"{condition}-{seed}-{algorithm}.json"; path=traces/name
        row={"condition":condition,"seed":seed,"algorithm":algorithm,"manifest_hash":digest(manifest),"config_hash":manifest["config_hash"],"artifact":"traces/"+name}
        result=None;sim=None
        try:
            if runner is None:
                sim=Simulation(manifest)
                result=sim.run()
            else:
                result=run(manifest)
            write_json(path,result)
            evidence=audit(result,validator)
            if replay:
                again=run(manifest)
                check_hash=again["metrics"]["trace_hash"]
                if check_hash!=result["metrics"]["trace_hash"]:
                    raise ValueError("replay digest mismatch")
            row.update(status="succeeded",trace_hash=result["metrics"]["trace_hash"],replay_verified=replay,
                       metrics={**result["metrics"],"estimated_message_bytes":evidence["estimated_message_bytes"],"utilization":evidence["utilization"]},
                       evidence=evidence)
            faults=config["faults"]
            if faults:
                f=faults[0];start=f["start_tick"];end=f["end_tick"]
                row["metrics"]["outage_completions"]=sum(start<=t<(end if end is not None else config["duration_ticks"]) for t in evidence["completion_ticks"])
                row["metrics"]["first_post_heal_completion_ticks"]=next((t-end for t in evidence["completion_ticks"] if end is not None and t>=end),None)
        except Exception as exc:
            row.update(status="failed",error=f"{type(exc).__name__}: {exc}",replay_verified=False)
            write_json(path,{"manifest":manifest,"error":row["error"],"partial_result":result,
                            "partial_events":sim.trace.events if sim is not None and result is None else []})
        rows.append(row)
        print(f"{condition} seed={seed} {algorithm}: {row['status']}"+(f" ({row['error']})" if row["status"]=="failed" else ""),flush=True)
    healthy={(r["seed"],r["algorithm"]):r for r in rows if r["condition"]=="healthy" and r["status"]=="succeeded"}
    for r in rows:
        if r["status"]!="succeeded" or r["condition"]=="healthy": continue
        baseline=healthy.get((r["seed"],r["algorithm"]))
        f=scenario(r["condition"],r["seed"])["faults"][0]
        # The skew/cross-zone control changes task placement and has no matched healthy workload.
        if r["condition"]=="skew_cross_zone":
            value,status=None,"missing_matched_workload"
        else:
            value,status=recovery(r["evidence"]["completion_ticks"],baseline["evidence"]["completion_ticks"],f["end_tick"],100) if baseline else (None,"missing_baseline")
        r["metrics"]["recovery_ticks"]=value;r["metrics"]["recovery_status"]=status
    conditions=list(dict.fromkeys(r["condition"] for r in rows))
    aggregates=[]
    for condition in conditions:
        for algorithm in POLICIES:
            group=[r for r in rows if r["condition"]==condition and r["algorithm"]==algorithm]
            for metric in METRICS:
                values=[r["metrics"][metric] for r in group if r["status"]=="succeeded" and r["metrics"].get(metric) is not None]
                aggregates.append({"condition":condition,"algorithm":algorithm,"metric":metric,"n":len(values),"missing_n":len(group)-len(values),"mean":mean(values) if values else None,"median":median(values) if values else None})
    comparisons=[paired(rows,c,m,a) for c in conditions for m in METRICS for a in POLICIES[1:]]
    report={"suite":suite,"engine_version":engine_version,"planned":len(plan),"succeeded":sum(r["status"]=="succeeded" for r in rows),
            "failed":sum(r["status"]=="failed" for r in rows),"runs":rows,"aggregates":aggregates,"comparisons":comparisons,
            "limitations":["Synthetic grid model with replicated predeclared task input; no physical safety or novelty claim.",
            "Latency is conditional on completed tasks; survivor bias possible. Small paired samples descriptive only.",
            "Recovery uses full 20-tick post-heal windows; zero healthy reference is undefined; unrecovered nonzero reference is censored.",
            "Peer arbitration uses modeled shared execution gate; controller-only source ablation not implemented."]}
    write_json(output/"summary.json",report)
    for filename,data,columns in (
        ("runs.csv",[{**{k:v for k,v in r.items() if k not in ("metrics","evidence")},**{k:r.get("metrics",{}).get(k) for k in METRICS}} for r in rows],
         ["condition","seed","algorithm","status","manifest_hash","config_hash","trace_hash","replay_verified","artifact","error",*METRICS]),
        ("aggregates.csv",aggregates,["condition","algorithm","metric","n","missing_n","mean","median"]),
        ("comparisons.csv",comparisons,["condition","metric","candidate","baseline","matched_n","missing_n","mean_difference","median_difference","ci95_low","ci95_high"])):
        with (output/filename).open("w",newline="") as f:
            w=csv.DictWriter(f,fieldnames=columns,extrasaction="ignore");w.writeheader();w.writerows(data)
    print(json.dumps({k:report[k] for k in ("suite","planned","succeeded","failed")}),flush=True)
    return report
