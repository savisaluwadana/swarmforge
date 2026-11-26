"""Validate canonical contract plus independently reconstruct safety evidence."""
from collections import Counter
from itertools import groupby
from pathlib import Path
import json
from swarmforge.core.trace import digest,semantic_digest
from swarmforge.domain.model import validate_config


class EvidenceError(ValueError):
    pass


def check(ok,message):
    if not ok:
        raise EvidenceError(message)


class ContractValidator:
    def __init__(self,contracts):
        from jsonschema import Draft202012Validator, FormatChecker
        from referencing import Registry, Resource
        from referencing.jsonschema import DRAFT202012
        root=Path(contracts)
        api=json.loads((root/"openapi.json").read_text())
        payloads=json.loads((root/"event-payloads.json").read_text())["$defs"]
        schemas=api["components"]["schemas"]
        doc={"$schema":"https://json-schema.org/draft/2020-12/schema","components":{"schemas":schemas}}
        uri="urn:swarmforge:openapi"
        registry=Registry().with_resource(uri,Resource.from_contents(doc,default_specification=DRAFT202012))
        self.validators={name:Draft202012Validator({"$ref":uri+"#/components/schemas/"+name},registry=registry,format_checker=FormatChecker()) for name in ("Manifest","Event","Metrics","Snapshot")}
        check(set(payloads)==set(schemas["Event"]["properties"]["type"]["enum"]),"payload schema coverage mismatch")
        self.payloads={k:Draft202012Validator(v) for k,v in payloads.items()}

    def validate(self,name,value):
        self.validators[name].validate(value)

    def event(self,e):
        self.validate("Event",e)
        self.payloads[e["type"]].validate(e["payload"])


def audit(result,contract=None):
    m=result["manifest"]; events=result["events"]; metrics=result["metrics"]
    c=m["config"]; grid=validate_config(c); duration=c["duration_ticks"]
    if contract:
        for name,value in (("Manifest",m),("Metrics",metrics),("Snapshot",result["initial_snapshot"]),("Snapshot",result["final_snapshot"])):
            contract.validate(name,value)
    check(digest(c)==m["config_hash"],"config hash mismatch")
    check(bool(events) and events[0]["type"]=="run.started" and events[-1]["type"]=="run.finished","trace boundaries")
    check(events[0]["payload"]["manifest_hash"]==digest(m),"manifest hash mismatch")
    h=semantic_digest(events)
    check(h==metrics["trace_hash"]==events[-1]["payload"]["trace_hash"],"trace hash mismatch")
    check(events[-1]["tick"]==duration and events[-1]["payload"]["status"]=="succeeded","incomplete trace")
    run=metrics["run_id"]; last=-1
    positions={r["id"]:(r["start"]["x"],r["start"]["y"]) for r in c["robots"]}
    failed=set(); carrying={}; releases={}; assignments={}; picked=set(); completed={}; stranded=set(); messages={}; final_messages=set()
    counts=Counter(); completion_ticks=[]; bytes_sent=0; duplicates=0; collisions=0; active_ticks=0; available_ticks=0
    task_specs={t["id"]:t for t in c["tasks"]}
    disabled={(l["from"],l["to"]) for l in c["network"]["links"] if l.get("enabled") is False}
    def blocked(sender,receiver,tick):
        if (sender,receiver) in disabled or sender in failed or receiver in failed:
            return True
        for f in c["faults"]:
            if f["start_tick"]<=tick and (f["end_tick"] is None or tick<f["end_tick"]):
                if f["type"]=="controller_outage" and "C" in (sender,receiver):
                    return True
                if f["type"]=="partition" and any((l["from"],l["to"])==(sender,receiver) for l in f["links"]):
                    return True
        return False
    expected_seq=0
    # Account activity in every simulated tick, including ticks without semantic events.
    prev_tick=-1
    for tick,group in groupby(events,key=lambda e:e["tick"]):
        if prev_tick>=0:
            gap=max(0,min(tick,duration)-min(prev_tick+1,duration))
            available_ticks+=gap*(len(positions)-len(failed))
            active_ticks+=gap*sum(r not in failed for r in carrying)
        moved=set(); before=dict(positions)
        for e in group:
            expected_seq+=1
            check(e["seq"]==expected_seq and e["run_id"]==run and last<=tick<=duration,"event sequence/run/tick")
            last=tick
            if contract: contract.event(e)
            p=e["payload"]; k=e["type"]; counts[k]+=1
            if k=="robot.failed":
                failed.add(p["robot_id"])
            elif k=="robot.moved":
                rid=p["robot_id"]; a=(p["from"]["x"],p["from"]["y"]); b=(p["to"]["x"],p["to"]["y"])
                check(rid not in failed and rid not in moved and positions[rid]==a and grid.free(b) and abs(a[0]-b[0])+abs(a[1]-b[1])==1,"illegal movement")
                collisions+=int(b in positions.values() or b in before.values())
                positions[rid]=b; moved.add(rid)
            elif k=="task.released":
                tid=p["task_id"]
                check(tid not in releases and task_specs[tid]["release_tick"]==tick,"invalid release")
                releases[tid]=tick
            elif k=="task.assigned":
                tid=p["task_id"]
                duplicates+=int(tid in assignments or tid in picked or tid in completed)
                check(tid in releases and p["expires_tick"]>tick,"assignment before release or expiry")
                assignments[tid]=(p["robot_id"],p["epoch"],p["expires_tick"])
            elif k in ("task.picked","task.completed"):
                tid=p["task_id"]; rid=p["robot_id"]
                grant=assignments.get(tid)
                check(grant and grant[:2]==(rid,p["epoch"]) and tick<grant[2] and rid not in failed,"action without live task grant")
                endpoint=task_specs[tid]["pickup" if k=="task.picked" else "dropoff"]
                check(positions[rid]==(endpoint["x"],endpoint["y"]),"action at wrong location")
                if k=="task.picked":
                    duplicates+=int(tid in picked or rid in carrying)
                    picked.add(tid);carrying[rid]=tid
                else:
                    duplicates+=int(tid in completed)
                    check(tid in picked and carrying.get(rid)==tid and tid not in stranded,"invalid completion")
                    completed[tid]=tick;completion_ticks.append(tick);carrying.pop(rid)
            elif k=="task.released_assignment":
                tid=p["task_id"]; g=assignments.get(tid)
                check(g and g[:2]==(p["robot_id"],p["epoch"]) and tick>=g[2] and tid not in picked,"unsafe release")
                assignments.pop(tid)
            elif k=="task.stranded":
                tid=p["task_id"]
                check(tid in picked and tid not in completed,"invalid stranded state")
                stranded.add(tid)
            elif k=="network.message_sent":
                mid=p["message_id"];check(mid not in messages and p["deliver_tick"]>tick,"invalid message send")
                messages[mid]=(p["sender"],p["receiver"],p["deliver_tick"])
                bytes_sent+=p["bytes"]
            elif k in ("network.message_delivered","network.message_dropped"):
                mid=p["message_id"]
                check(mid in messages and mid not in final_messages,"unknown/duplicate message outcome")
                sender,receiver,due=messages[mid]
                check((sender,receiver)==(p["sender"],p["receiver"]),"message endpoints changed")
                if k=="network.message_delivered":
                    check(tick==due and not blocked(sender,receiver,tick),"delivery across blocked link or wrong tick")
                final_messages.add(mid)
        if tick<duration:
            available_ticks+=len(positions)-len(failed)
            active_ticks+=len((moved|set(carrying))-failed)
        prev_tick=tick
    derived={"released":len(releases),"completed":len(completed),"stranded":len(stranded),
             "messages_sent":len(messages),"messages_delivered":counts["network.message_delivered"],
             "messages_dropped":counts["network.message_dropped"],"messages_in_flight":len(messages)-len(final_messages),
             "accepted_duplicates":duplicates,"actual_collisions":collisions,"stale_rejections":counts["authority.rejected"]}
    for k,v in derived.items():
        check(metrics[k]==v,f"metric mismatch: {k} expected {v}, got {metrics[k]}")
    check(duplicates==0 and collisions==0,"trace safety violation")
    check(len(releases)==len(task_specs),"missing scheduled releases")
    check(result["final_snapshot"]["seq"]==len(events),"snapshot cursor mismatch")
    check({r["id"]:(r["position"]["x"],r["position"]["y"]) for r in result["final_snapshot"]["robots"]}==positions,"snapshot position mismatch")
    return {"verified":True,"event_count":len(events),"derived":derived,"estimated_message_bytes":bytes_sent,
            "utilization":active_ticks/available_ticks if available_ticks else None,
            "activity_definition":"robot moved this tick or held a picked package at end of tick, excluding failed robots",
            "completion_ticks":completion_ticks}
