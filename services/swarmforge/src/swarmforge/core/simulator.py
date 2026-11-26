from copy import deepcopy
from hashlib import sha256
from statistics import median
from uuid import UUID, uuid5, NAMESPACE_URL
from swarmforge import __version__
from swarmforge.domain.model import Robot,Task,TaskSpec,validate_config,xy,integer
from swarmforge.core.trace import Trace,digest,semantic_digest
from swarmforge.motion.grid import plan,resolve
from swarmforge.network.emulator import Network
from swarmforge.policies.centralized import CentralizedGreedy


def build_manifest(config, seed, engine_version=__version__, scenario_id=None, revision=1):
    validate_config(config)
    integer(seed,0,2147483647,"/seed")
    integer(revision,1,2147483647,"/revision")
    config = deepcopy(config)
    ch = digest(config)
    sid = str(UUID(scenario_id)) if scenario_id else str(uuid5(NAMESPACE_URL,"swarmforge:scenario:"+ch))
    return {"schema_version":1,"engine_version":engine_version,
            "dependency_lock_hash":sha256(b"swarmforge-core-runtime:stdlib-only:v1").hexdigest(),
            "scenario_id":sid,"revision":revision,"config_hash":ch,"config":config,
            "algorithm":"centralized_greedy","policy_parameters":{"heartbeat_timeout_ticks":3,"path_horizon":32,"grant_expiry":"run_end"},
            "seed":seed,"mode":"scripted"}


class Simulation:
    def __init__(self, manifest, run_id=None):
        self.manifest = deepcopy(manifest)
        if manifest["algorithm"] != "centralized_greedy" or manifest["mode"] != "scripted":
            raise NotImplementedError("milestone 1 supports scripted centralized_greedy only")
        config = self.manifest["config"]
        expected = build_manifest(config,manifest["seed"],manifest["engine_version"],manifest["scenario_id"],manifest["revision"])
        if self.manifest != expected:
            raise ValueError("manifest does not match supported configuration and policy")
        self.grid = validate_config(config)
        self.duration = config["duration_ticks"]
        self.run_id = str(UUID(run_id)) if run_id else str(uuid5(NAMESPACE_URL,"swarmforge:run:"+digest(manifest)))
        self.trace = Trace(self.run_id)
        self.robots = {r["id"]:Robot(r["id"],(r["start"]["x"],r["start"]["y"]),r["zone"]) for r in config["robots"]}
        self.tasks = {t["id"]:Task(TaskSpec(t["id"],(t["pickup"]["x"],t["pickup"]["y"]),(t["dropoff"]["x"],t["dropoff"]["y"]),t["release_tick"],t["priority"],t.get("due_tick"))) for t in config["tasks"]}
        self.network = Network(config["network"],set(self.robots)|{"C"},manifest["seed"],self.trace)
        self.policy = CentralizedGreedy()
        self.grant_payloads = {}
        self.acked = set()
        self.conflicts = self.stale = 0
        self.started = False

    def reject(self,r,tid,epoch,reason):
        self.stale += 1
        self.trace.emit("authority.rejected",task_id=tid,robot_id=r.id,epoch=epoch,reason=reason)

    def apply_faults(self,tick):
        for i,f in enumerate(self.manifest["config"]["faults"]):
            fid=f"f{i+1}"
            targets=[f["robot_id"]] if f["type"]=="robot_crash" else ["C"] if f["type"]=="controller_outage" else f["links"]
            if f["end_tick"] == tick:
                self.network.active.pop(fid,None)
                self.trace.emit("network.fault_ended",fault_id=fid,fault_type=f["type"],targets=targets)
        for i,f in enumerate(self.manifest["config"]["faults"]):
            if f["start_tick"] != tick:
                continue
            fid=f"f{i+1}"
            kind=f["type"]
            targets=[f["robot_id"]] if kind=="robot_crash" else ["C"] if kind=="controller_outage" else f["links"]
            self.trace.emit("network.fault_started",fault_id=fid,fault_type=kind,targets=targets,end_tick=f["end_tick"])
            if kind=="robot_crash":
                r=self.robots[f["robot_id"]]
                r.mode="failed"
                self.network.dead.add(r.id)
                self.trace.emit("robot.failed",robot_id=r.id,reason="crash_stop")
                if r.task_id is not None and r.carrying:
                    t=self.tasks[r.task_id]
                    t.status="stranded"
                    self.trace.emit("task.stranded",task_id=t.spec.id,robot_id=r.id,reason="crash_carrying")
            else:
                self.network.active[fid]=f
            self.network.invalidate_blocked()

    def grant(self,tick,proposal):
        # Gate validates only; it does not choose tasks/robots or return remote status.
        task=self.tasks[proposal.task_id]
        if not task.released or task.status != "pending":
            self.reject(self.robots[proposal.robot_id],proposal.task_id,task.epoch,"task_not_pending")
            return
        task.status="assigned"
        task.holder=proposal.robot_id
        task.epoch+=1
        task.expires_tick=self.duration
        self.policy.reserve(proposal)
        body={"task_id":task.spec.id,"epoch":task.epoch,"expires_tick":self.duration,
              "pickup":task.spec.pickup,"dropoff":task.spec.dropoff}
        self.grant_payloads[task.spec.id]=(proposal.robot_id,body)
        self.trace.emit("authority.granted",task_id=task.spec.id,holder=proposal.robot_id,epoch=task.epoch,expires_tick=self.duration,issuer_id="C")
        self.trace.emit("task.assigned",task_id=task.spec.id,robot_id=proposal.robot_id,epoch=task.epoch,expires_tick=self.duration,issuer_id="C")
        self.network.send(tick,"C",proposal.robot_id,"grant",body)

    def robot_receive(self,tick,r,inbox):
        for msg in inbox:
            if msg.kind != "grant" or msg.sender != "C":
                continue
            b=msg.body
            if tick >= b["expires_tick"]:
                self.reject(r,b["task_id"],b["epoch"],"expired")
                continue
            if r.task_id==b["task_id"] and r.epoch==b["epoch"]:
                self.network.send(tick,r.id,"C","ack",{"task_id":r.task_id,"epoch":r.epoch})
                continue
            if r.mode!="idle":
                self.reject(r,b["task_id"],b["epoch"],"robot_busy")
                continue
            # A completed task can have a delayed duplicate grant. Local tombstones reject it.
            if (r.id,b["task_id"],b["epoch"]) in self.local_completed:
                self.network.send(tick,r.id,"C","completed",{"task_id":b["task_id"],"epoch":b["epoch"]})
                continue
            r.task_id=b["task_id"]
            r.epoch=b["epoch"]
            r.expires_tick=b["expires_tick"]
            r.pickup=tuple(b["pickup"])
            r.dropoff=tuple(b["dropoff"])
            r.mode="moving_to_pickup"
            self.network.send(tick,r.id,"C","ack",{"task_id":r.task_id,"epoch":r.epoch})

    def authorized(self,tick,r):
        t=self.tasks[r.task_id]
        valid=(t.holder==r.id and t.epoch==r.epoch and t.expires_tick is not None and
               tick<t.expires_tick and t.status==("picked" if r.carrying else "assigned"))
        if not valid:
            self.reject(r,r.task_id,r.epoch,"invalid_authority")
        return valid

    def move_and_act(self,tick):
        proposals={}
        valid=[]
        for rid,r in sorted(self.robots.items()):
            if r.mode=="failed" or r.task_id is None or not self.authorized(tick,r):
                continue
            valid.append(rid)
            goal=r.dropoff if r.carrying else r.pickup
            if r.position!=goal:
                path=plan(self.grid,r.position,goal)
                if path:
                    proposals[rid]=path[0]
        moves,rejected=resolve(self.grid,{rid:r.position for rid,r in self.robots.items()},proposals)
        for rid,q in moves.items():
            r=self.robots[rid]
            old=r.position
            r.position=q
            r.waiting_ticks=0
            self.trace.emit("robot.moved",robot_id=rid,**{"from":xy(old),"to":xy(q)})
        for rid,reason in rejected.items():
            self.conflicts+=1
            self.trace.emit("motion.conflict",robot_id=rid,target=xy(proposals[rid]),reason=reason)
        for rid in valid:
            r=self.robots[rid]
            t=self.tasks[r.task_id]
            if not r.carrying and r.position==r.pickup:
                t.status="picked"
                r.carrying=True
                r.mode="moving_to_dropoff"
                r.waiting_ticks=0
                self.trace.emit("task.picked",task_id=t.spec.id,robot_id=rid,epoch=r.epoch)
            elif r.carrying and r.position==r.dropoff:
                t.status="completed"
                t.completed_tick=tick
                self.trace.emit("task.completed",task_id=t.spec.id,robot_id=rid,epoch=r.epoch)
                self.local_completed.add((rid,t.spec.id,r.epoch))
                self.network.send(tick,rid,"C","completed",{"task_id":t.spec.id,"epoch":r.epoch})
                r.mode="idle"
                r.task_id=None
                r.carrying=False
                r.waiting_ticks=0
            elif rid not in moves:
                r.waiting_ticks+=1
                if r.waiting_ticks==20:
                    self.trace.emit("motion.deadlock_suspected",robot_id=rid,waiting_ticks=r.waiting_ticks)
        if len({r.position for r in self.robots.values()}) != len(self.robots):
            raise RuntimeError("I4: vertex collision")

    def run(self):
        if self.started:
            raise RuntimeError("simulation already executed")
        self.started=True
        self.local_completed=set()
        self.trace.emit("run.started",manifest_hash=digest(self.manifest),engine_version=self.manifest["engine_version"])
        initial=self.snapshot()
        for tick in range(self.duration):
            self.trace.tick=tick
            self.apply_faults(tick)
            inbox=self.network.deliver(tick)
            for t in sorted(self.tasks.values(),key=lambda t:t.spec.id):
                if t.spec.release_tick==tick:
                    t.released=True
                    self.policy.release(t.spec)
                    self.trace.emit("task.released",task_id=t.spec.id)
            self.policy.receive(tick,inbox.get("C",[]))
            for m in inbox.get("C",[]):
                grant=self.grant_payloads.get(m.body.get("task_id"))
                if m.kind in ("ack","completed") and grant and grant[0]==m.sender and grant[1]["epoch"]==m.body.get("epoch"):
                    self.acked.add(m.body["task_id"])
            for p in self.policy.choose(tick):
                self.grant(tick,p)
            for tid,(rid,body) in sorted(self.grant_payloads.items()):
                if tid not in self.acked and tick%3==0 and tick>0:
                    self.network.send(tick,"C",rid,"grant",body)
            for rid,r in sorted(self.robots.items()):
                if r.mode=="failed":
                    continue
                self.robot_receive(tick,r,inbox.get(rid,[]))
                self.network.send(tick,rid,"C","status",{"position":r.position,"mode":r.mode})
                # Repeat completion evidence; controller deduplicates. Conservative milestone.
                for robot_id,tid,epoch in sorted(self.local_completed):
                    if robot_id==rid and tick%3==0:
                        self.network.send(tick,rid,"C","completed",{"task_id":tid,"epoch":epoch})
            self.move_and_act(tick)
            if tick%10==0:
                self.trace.emit("run.progress",completed=sum(t.status=="completed" for t in self.tasks.values()),released=sum(t.released for t in self.tasks.values()),duration_ticks=self.duration)
        self.trace.tick=self.duration
        self.trace.emit("run.finished",status="succeeded",trace_hash="")
        h=semantic_digest(self.trace.events)
        self.trace.events[-1]["payload"]["trace_hash"]=h
        return {"manifest":deepcopy(self.manifest),"events":self.trace.events,"initial_snapshot":initial,
                "final_snapshot":self.snapshot(),"metrics":self.metrics(h)}

    def snapshot(self):
        return {"run_id":self.run_id,"seq":len(self.trace.events),"tick":self.trace.tick,
                "robots":[{"id":r.id,"position":xy(r.position),"mode":r.mode,"task_id":r.task_id,"zone":r.zone} for r in sorted(self.robots.values(),key=lambda r:r.id)],
                "tasks":[{"id":t.spec.id,"status":t.status,"holder":t.holder,"epoch":t.epoch,"expires_tick":t.expires_tick,"released":t.released,"deferred":False} for t in sorted(self.tasks.values(),key=lambda t:t.spec.id)],
                "network":{"active_faults":sorted(self.network.active),"failed_nodes":sorted(self.network.dead)},"metrics":{},"authority":[]}

    def metrics(self,h):
        released=sum(t.released for t in self.tasks.values())
        done=[t for t in self.tasks.values() if t.status=="completed"]
        n=len(done)
        lat=sorted(t.completed_tick-t.spec.release_tick for t in done)
        due=[t for t in self.tasks.values() if t.released and t.spec.due_tick is not None and t.spec.due_tick<=self.duration]
        misses=sum(t.completed_tick is None or t.completed_tick>t.spec.due_tick for t in due)
        return {"run_id":self.run_id,"complete":True,"released":released,"completed":n,
                "stranded":sum(t.status=="stranded" for t in self.tasks.values()),"duration_ticks":self.duration,
                "completion_rate":n/released if released else None,"throughput_tasks_per_minute":n*60000/(self.duration*self.manifest["config"]["tick_ms"]),
                "latency_p50_ticks":median(lat) if lat else None,"latency_p95_ticks":lat[(95*len(lat)+99)//100-1] if lat else None,
                "deadline_miss_rate":misses/len(due) if due else None,"attempted_conflicts":self.conflicts,
                "accepted_duplicates":0,"actual_collisions":0,"stale_rejections":self.stale,"messages_sent":self.network.sent,
                "messages_delivered":self.network.delivered,"messages_dropped":self.network.dropped,"messages_in_flight":len(self.network.queue),
                "messages_per_completion":self.network.sent/n if n else None,"trace_hash":h,
                "breakdown":{"unfinished":released-n,"model":"conservative_grid_crash_stop","limitations":["no safe reassignment yet","centralized baseline only"]}}


def simulate(config,seed=0,engine_version=__version__):
    return Simulation(build_manifest(config,seed,engine_version)).run()
