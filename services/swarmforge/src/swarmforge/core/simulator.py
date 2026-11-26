from copy import deepcopy
from hashlib import sha256
from statistics import median
from uuid import UUID, uuid5, NAMESPACE_URL
from swarmforge import __version__
from swarmforge.domain.model import Robot,Task,TaskSpec,validate_config,xy,integer,InvalidScenario
from swarmforge.core.trace import Trace,digest,semantic_digest
from swarmforge.motion.grid import plan,resolve
from swarmforge.network.emulator import Network, Message
from swarmforge.policies.scoped import ScopeLedger, ZoneAuction
from swarmforge.policies.centralized import CentralizedGreedy
from swarmforge.policies.local import PeerAuction


def build_manifest(config, seed, engine_version=__version__, scenario_id=None, revision=1, algorithm="centralized_greedy", mode="scripted"):
    if algorithm not in ("centralized_greedy","local_auction","scoped_lease"):
        raise NotImplementedError("unsupported algorithm: "+str(algorithm))
    validate_config(config)
    if mode not in ("scripted","interactive") or (mode=="interactive" and config["duration_ticks"]>300):
        raise ValueError("interactive mode limited to 300 logical ticks")
    integer(seed,0,2147483647,"/seed")
    integer(revision,1,2147483647,"/revision")
    config = deepcopy(config)
    ch = digest(config)
    sid = str(UUID(scenario_id)) if scenario_id else str(uuid5(NAMESPACE_URL,"swarmforge:scenario:"+ch))
    return {"schema_version":1,"engine_version":engine_version,
            "dependency_lock_hash":sha256(b"swarmforge-core-runtime:stdlib-only:v1").hexdigest(),
            "scenario_id":sid,"revision":revision,"config_hash":ch,"config":config,
            "algorithm":algorithm,"policy_parameters":{"heartbeat_timeout_ticks":3,"path_horizon":32,"grant_expiry":"scope_expiry" if algorithm=="scoped_lease" else "run_end","auction_ticks":3 if algorithm!="centralized_greedy" else 0,"workload_source":"common_predeclared_local_release_v1"},
            "seed":seed,"mode":mode}


class Simulation:
    def __init__(self, manifest, run_id=None):
        self.manifest = deepcopy(manifest)
        if manifest["algorithm"] not in ("centralized_greedy","local_auction","scoped_lease") or manifest["mode"] not in ("scripted","interactive"):
            raise NotImplementedError("unsupported policy or mode")
        config = self.manifest["config"]
        expected = build_manifest(config,manifest["seed"],manifest["engine_version"],manifest["scenario_id"],manifest["revision"],manifest["algorithm"],manifest["mode"])
        if self.manifest != expected:
            raise ValueError("manifest does not match supported configuration and policy")
        self.grid = validate_config(config)
        self.duration = config["duration_ticks"]
        self.faults=deepcopy(config["faults"])
        self.command_seen=set()
        self.run_id = str(UUID(run_id)) if run_id else str(uuid5(NAMESPACE_URL,"swarmforge:run:"+digest(manifest)))
        self.trace = Trace(self.run_id)
        self.robots = {r["id"]:Robot(r["id"],(r["start"]["x"],r["start"]["y"]),r["zone"]) for r in config["robots"]}
        self.tasks = {t["id"]:Task(TaskSpec(t["id"],(t["pickup"]["x"],t["pickup"]["y"]),(t["dropoff"]["x"],t["dropoff"]["y"]),t["release_tick"],t["priority"],t.get("due_tick"))) for t in config["tasks"]}
        self.network = Network(config["network"],set(self.robots)|{"C"},manifest["seed"],self.trace)
        self.policy = CentralizedGreedy()
        self.scopes = ScopeLedger(config,self.grid) if manifest["algorithm"]=="scoped_lease" else None
        self.auctions = {z:ZoneAuction(s,self.scopes.grids[z]) for z,s in self.scopes.grants.items()} if self.scopes else {}
        self.expired_scopes = set()
        self.peers={rid:PeerAuction(rid,self.robots) for rid in self.robots} if manifest["algorithm"]=="local_auction" else {}
        self.release_evidence=set()
        self.released_grants=set()
        self.assignment_conflicts=0
        self.completion_issuers = {}
        self.grant_payloads = {}
        self.acked = set()
        self.conflicts = self.stale = 0
        self.started = False

    def reject(self,r,tid,epoch,reason):
        self.stale += 1
        self.trace.emit("authority.rejected",task_id=tid,robot_id=r.id,epoch=epoch,reason=reason)

    def apply_commands(self,tick,commands):
        for command in sorted(commands,key=lambda c:c["command_seq"]):
            seq=command["command_seq"]
            if seq in self.command_seen:continue
            self.command_seen.add(seq)
            try:
                if self.manifest["mode"]!="interactive":raise ValueError("scripted run")
                body=deepcopy(command["payload"])
                length=body.pop("duration_ticks")
                if length is not None and (type(length) is not int or length<=0):
                    raise ValueError("invalid duration")
                if body["type"]=="robot_crash" and length is not None:
                    raise ValueError("robot crash must be permanent")
                body["start_tick"]=tick
                body["end_tick"]=None if length is None else min(self.duration,tick+length)
                candidate={**self.manifest["config"],"faults":[*self.faults,body]}
                validate_config(candidate)
                self.faults.append(body)
                self.trace.emit("command.applied",command_seq=seq,fault_id=f"f{len(self.faults)}",applied_tick=tick,fault=body)
            except (InvalidScenario,ValueError,KeyError,TypeError) as exc:
                self.trace.emit("command.rejected",command_seq=seq,reason=str(exc)[:512])

    def apply_faults(self,tick):
        for i,f in enumerate(self.faults):
            fid=f"f{i+1}"
            targets=[f["robot_id"]] if f["type"]=="robot_crash" else ["C"] if f["type"]=="controller_outage" else f["links"]
            if f["end_tick"] == tick:
                self.network.active.pop(fid,None)
                self.trace.emit("network.fault_ended",fault_id=fid,fault_type=f["type"],targets=targets)
        for i,f in enumerate(self.faults):
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

    def send(self,tick,sender,receiver,kind,body):
        # A same-process leader/robot delivery is local, not a network message.
        if sender == receiver:
            msg=Message("local",sender,receiver,kind,deepcopy(body),tick,tick)
            if kind=="grant":
                self.robot_receive(tick,self.robots[receiver],[msg])
            elif kind=="completed":
                if self.peers:
                    self.peers[receiver].done.add(body["task_id"])
                    self.peers[receiver].pending.pop(body["task_id"],None)
                    self.peers[receiver].announce(tick,self.network,"peer_completed",body)
                else:
                    self.auctions[self.robots[receiver].zone].receive(tick,[msg])
                self.acked.add(body["task_id"])
            elif kind=="released_unpicked":
                self.reconcile_release(tick,receiver,msg)
            elif kind=="ack":
                self.acked.add(body["task_id"])
        else:
            self.network.send(tick,sender,receiver,kind,body)

    def grant(self,tick,proposal,issuer="C",auction=None):
        # Gate validates only; it does not choose tasks/robots or return remote status.
        task=self.tasks[proposal.task_id]
        if not task.released or task.status != "pending":
            self.assignment_conflicts+=1
            self.reject(self.robots[proposal.robot_id],proposal.task_id,task.epoch,"task_not_pending")
            return False
        if self.peers and issuer!=proposal.robot_id:
            raise ValueError("peer policy may propose only itself")
        scope_epoch=auction.token["epoch"] if auction else None
        expires=auction.token["expires_tick"] if auction else self.duration
        if self.scopes and not self.scopes.permits(tick,task.spec.id,issuer,proposal.robot_id,scope_epoch):
            self.reject(self.robots[proposal.robot_id],proposal.task_id,task.epoch,"scope_violation")
            return False
        task.status="assigned"
        task.deferred=False
        task.holder=proposal.robot_id
        task.epoch+=1
        task.expires_tick=expires
        task.issuer=issuer
        task.scope_epoch=scope_epoch
        if auction:
            auction.reservations[proposal.task_id]=proposal.robot_id
        elif not self.peers:
            self.policy.reserve(proposal)
        body={"task_id":task.spec.id,"epoch":task.epoch,"expires_tick":expires,
              "pickup":task.spec.pickup,"dropoff":task.spec.dropoff,
              "scope_id":auction.scope.zone if auction else None}
        self.grant_payloads[task.spec.id]=(proposal.robot_id,body,issuer)
        self.trace.emit("authority.granted",task_id=task.spec.id,holder=proposal.robot_id,epoch=task.epoch,expires_tick=expires,issuer_id=issuer)
        self.trace.emit("task.assigned",task_id=task.spec.id,robot_id=proposal.robot_id,epoch=task.epoch,expires_tick=expires,issuer_id=issuer)
        self.send(tick,issuer,proposal.robot_id,"grant",body)
        return True

    def robot_receive(self,tick,r,inbox):
        for msg in inbox:
            if msg.kind != "grant":
                continue
            b=msg.body
            if msg.sender != "C" and not (self.peers and msg.sender==r.id) and (not self.scopes or b.get("scope_id") != r.zone or self.scopes.grants[r.zone].leader != msg.sender):
                self.reject(r,b["task_id"],b["epoch"],"unauthorized_issuer")
                continue
            if tick >= b["expires_tick"] or (r.id,b["task_id"],b["epoch"],msg.sender) in self.release_evidence:
                self.reject(r,b["task_id"],b["epoch"],"expired")
                continue
            if r.task_id==b["task_id"] and r.epoch==b["epoch"]:
                self.send(tick,r.id,msg.sender,"ack",{"task_id":r.task_id,"epoch":r.epoch})
                continue
            if r.mode!="idle":
                self.reject(r,b["task_id"],b["epoch"],"robot_busy")
                continue
            # A completed task can have a delayed duplicate grant. Local tombstones reject it.
            if (r.id,b["task_id"],b["epoch"]) in self.local_completed:
                self.send(tick,r.id,msg.sender,"completed",{"task_id":b["task_id"],"epoch":b["epoch"]})
                continue
            r.task_id=b["task_id"]
            r.epoch=b["epoch"]
            r.expires_tick=b["expires_tick"]
            r.issuer=msg.sender
            r.scope_id=b.get("scope_id")
            r.pickup=tuple(b["pickup"])
            r.dropoff=tuple(b["dropoff"])
            r.mode="moving_to_pickup"
            self.send(tick,r.id,msg.sender,"ack",{"task_id":r.task_id,"epoch":r.epoch})

    def authorized(self,tick,r):
        t=self.tasks[r.task_id]
        valid=(t.holder==r.id and t.epoch==r.epoch and t.expires_tick is not None and
               tick<t.expires_tick and t.status==("picked" if r.carrying else "assigned"))
        if valid and self.scopes:
            valid=self.scopes.permits(tick,t.spec.id,r.issuer,r.id,t.scope_epoch)
            if valid and r.scope_id is not None:
                valid=self.scopes.grids[r.scope_id].free(r.position)
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
                local_grid=self.scopes.grids[r.scope_id] if r.scope_id is not None else self.grid
                path=plan(local_grid,r.position,goal)
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
                self.completion_issuers[(rid,t.spec.id,r.epoch)]=r.issuer
                self.send(tick,rid,r.issuer,"completed",{"task_id":t.spec.id,"epoch":r.epoch})
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

    def reconcile_release(self,tick,receiver,msg):
        """Gate accepts only exact delivered holder evidence after expiry."""
        b=msg.body
        t=self.tasks.get(b["task_id"])
        if not t or (msg.sender,b["task_id"],b["epoch"],receiver) in self.released_grants:
            return
        if (t.status!="assigned" or t.holder!=msg.sender or t.issuer!=receiver
                or t.epoch!=b["epoch"] or t.expires_tick is None or tick<t.expires_tick
                or b.get("phase")!="unpicked"):
            self.trace.emit("recovery.unresolved",task_id=b["task_id"],reason="release_evidence_mismatch")
            return
        old_epoch=t.epoch
        t.status="pending"
        t.holder=None
        t.expires_tick=None
        t.deferred=True
        self.grant_payloads.pop(t.spec.id,None)
        self.acked.discard(t.spec.id)
        self.released_grants.add((msg.sender,t.spec.id,old_epoch,receiver))
        if self.scopes and t.spec.id in self.scopes.task_zone:
            a=self.auctions[self.scopes.task_zone[t.spec.id]]
            a.reservations.pop(t.spec.id,None)
            a.rounds.pop(t.spec.id,None)
        else:
            self.policy.reservations.pop(t.spec.id,None)
        self.trace.emit("task.released_assignment",task_id=t.spec.id,robot_id=msg.sender,epoch=old_epoch,reason="delivered_expired_unpicked")
        self.trace.emit("recovery.reconciled",task_id=t.spec.id,epoch=old_epoch,outcome="released_unpicked")

    def expire_robot_grants(self,tick):
        for rid,r in sorted(self.robots.items()):
            if r.mode=="failed":
                continue
            if r.task_id is not None and tick>=r.expires_tick and not r.carrying:
                self.release_evidence.add((rid,r.task_id,r.epoch,r.issuer))
                r.task_id=None
                r.scope_id=None
                r.mode="idle"
                r.waiting_ticks=0
            for owner,tid,epoch,issuer in sorted(self.release_evidence):
                if owner==rid and tick%3==0:
                    self.send(tick,rid,issuer,"released_unpicked",{"task_id":tid,"epoch":epoch,"phase":"unpicked"})

    def peer_tick(self,tick,inbox):
        for rid,a in sorted(self.peers.items()):
            r=self.robots[rid]
            if r.mode=="failed":
                continue
            a.observe(tick,inbox.get(rid,[]))
            p=a.step(tick,r,self.network)
            if p and self.grant(tick,p,rid):
                a.claims[p.task_id]=self.duration
                a.announce(tick,self.network,"peer_claim",{"task_id":p.task_id,"expires_tick":self.duration})

    def expire_scopes(self,tick):
        if not self.scopes:
            return
        for zone,s in sorted(self.scopes.grants.items()):
            if tick < s.expires_tick or zone in self.expired_scopes:
                continue
            self.expired_scopes.add(zone)
            self.trace.emit("authority.expired",scope_id=zone,holder=s.leader,epoch=s.epoch)
            for t in sorted(self.tasks.values(),key=lambda t:t.spec.id):
                if self.scopes.task_zone.get(t.spec.id)!=zone or t.status in ("completed","stranded"):
                    continue
                if t.status=="picked":
                    t.status="stranded"
                    self.trace.emit("task.stranded",task_id=t.spec.id,robot_id=t.holder,reason="scope_expired_carrying")
                if t.holder is not None:
                    self.trace.emit("authority.expired",task_id=t.spec.id,holder=t.holder,epoch=t.epoch)
                if t.released:
                    t.deferred=True
                    self.trace.emit("task.deferred",task_id=t.spec.id,reason="scope_expired_uncertain")
                    if t.holder is not None:
                        self.trace.emit("recovery.unresolved",task_id=t.spec.id,reason="scope_expired_requires_holder_evidence")
                # A robot with an expired local grant cannot move or act. Do not reuse it
                # without reconciled state in this milestone.

    def scoped_tick(self,tick,inbox):
        if not self.scopes:
            return
        # Only a delivered request can authorize a fresh term after expiry.
        for m in inbox.get("C",[]):
            if m.kind=="scope_request":
                zone=m.body["scope_id"]
                s=self.scopes.grants.get(zone)
                if s and m.sender==s.leader and tick>=s.expires_tick and tick<self.duration:
                    fresh=self.scopes.renew(zone,tick,self.duration)
                    self.expired_scopes.discard(zone)
                    self.trace.emit("authority.granted",scope_id=zone,holder=fresh.leader,epoch=fresh.epoch,expires_tick=fresh.expires_tick,issuer_id="C")
        for zone,s in sorted(self.scopes.grants.items()):
            if tick == 0:
                self.trace.emit("authority.granted",scope_id=zone,holder=s.leader,epoch=s.epoch,expires_tick=s.expires_tick,issuer_id="C")
            if tick%3 == 0 and tick < s.expires_tick:
                self.network.send(tick,"C",s.leader,"scope",{"scope_id":zone,"epoch":s.epoch,"expires_tick":s.expires_tick})
            leader=self.robots[s.leader]
            if leader.mode=="failed":
                continue
            auction=self.auctions[zone]
            auction.receive(tick,inbox.get(s.leader,[]))
            if not auction.active(tick) and tick%3==0:
                self.network.send(tick,s.leader,"C","scope_request",{"scope_id":zone})
            for p in auction.decide(tick,leader,self.network):
                self.grant(tick,p,s.leader,auction)
        # Each robot responds using its own current state and received announcement only.
        for rid,r in sorted(self.robots.items()):
            if r.mode=="failed":
                continue
            auction=self.auctions[r.zone]
            for m in inbox.get(rid,[]):
                b=m.body
                if m.kind!="auction" or m.sender!=auction.scope.leader or b["scope_id"]!=r.zone or tick>b["round"]+3:
                    continue
                spec=TaskSpec(b["task_id"],tuple(b["pickup"]),tuple(b["dropoff"]),tick,b["priority"],b["due_tick"])
                score=auction.score(tick,r,spec)
                if score is not None:
                    self.network.send(tick,rid,m.sender,"bid",{"task_id":b["task_id"],"round":b["round"],"score":score})

    def run(self, checkpoint=None, command_source=None):
        """Optional observer receives state and trace at completed tick boundaries.

        Observer is outside policy logic; it may abort execution, never mutate inputs.
        No wall clock or persistence dependencies enter the core.
        """
        if self.started:
            raise RuntimeError("simulation already executed")
        if self.manifest["mode"]=="interactive" and command_source is None:
            raise ValueError("interactive execution requires an explicit command source")
        if self.manifest["mode"]=="scripted" and command_source is not None:
            raise ValueError("scripted execution cannot accept commands")
        self.started=True
        self.local_completed=set()
        self.trace.emit("run.started",manifest_hash=digest(self.manifest),engine_version=self.manifest["engine_version"])
        initial=self.snapshot()
        if checkpoint is not None:
            checkpoint(initial,self.trace.events)
        for tick in range(self.duration):
            self.trace.tick=tick
            if command_source is not None:
                self.apply_commands(tick,command_source(tick))
            self.apply_faults(tick)
            self.expire_scopes(tick)
            self.expire_robot_grants(tick)
            inbox=self.network.deliver(tick)
            for receiver,messages in sorted(inbox.items()):
                for m in messages:
                    if m.kind=="released_unpicked":
                        self.reconcile_release(tick,receiver,m)
            for t in sorted(self.tasks.values(),key=lambda t:t.spec.id):
                if t.spec.release_tick==tick:
                    t.released=True
                    zone=self.scopes.task_zone.get(t.spec.id) if self.scopes else None
                    # All policies have the same predeclared release schedule at each node.
                    # The policy chooses which eligible local source to consume.
                    if self.peers:
                        for a in self.peers.values():
                            a.release(t.spec)
                    elif zone is None:
                        self.policy.release(t.spec)
                    else:
                        self.auctions[zone].release(t.spec)
                        if zone in self.expired_scopes:
                            t.deferred=True
                    self.trace.emit("task.released",task_id=t.spec.id)
                    if t.deferred:
                        self.trace.emit("task.deferred",task_id=t.spec.id,reason="scope_expired")
            self.policy.receive(tick,inbox.get("C",[]))
            for receiver,messages in sorted(inbox.items()):
                for m in messages:
                    grant=self.grant_payloads.get(m.body.get("task_id"))
                    if m.kind in ("ack","completed") and grant and grant[0]==m.sender and grant[2]==receiver and grant[1]["epoch"]==m.body.get("epoch"):
                        self.acked.add(m.body["task_id"])
            for p in self.policy.choose(tick):
                self.grant(tick,p)
            self.scoped_tick(tick,inbox)
            self.peer_tick(tick,inbox)
            for tid,(rid,body,issuer) in sorted(self.grant_payloads.items()):
                if tid not in self.acked and tick%3==0 and tick>0 and tick<body["expires_tick"] and (issuer=="C" or self.robots[issuer].mode!="failed"):
                    self.send(tick,issuer,rid,"grant",body)
            for rid,r in sorted(self.robots.items()):
                if r.mode=="failed":
                    continue
                self.robot_receive(tick,r,inbox.get(rid,[]))
                self.network.send(tick,rid,"C","status",{"position":r.position,"mode":r.mode})
                # Repeat completion evidence; controller deduplicates. Conservative milestone.
                for robot_id,tid,epoch in sorted(self.local_completed):
                    if robot_id==rid and tick%3==0:
                        self.send(tick,rid,self.completion_issuers[(rid,tid,epoch)],"completed",{"task_id":tid,"epoch":epoch})
            self.move_and_act(tick)
            if tick%10==0:
                self.trace.emit("run.progress",completed=sum(t.status=="completed" for t in self.tasks.values()),released=sum(t.released for t in self.tasks.values()),duration_ticks=self.duration)
            if checkpoint is not None:
                checkpoint(self.snapshot(),self.trace.events)
        self.trace.tick=self.duration
        self.expire_scopes(self.duration)
        self.trace.emit("run.finished",status="succeeded",trace_hash="")
        h=semantic_digest(self.trace.events)
        self.trace.events[-1]["payload"]["trace_hash"]=h
        return {"manifest":deepcopy(self.manifest),"events":self.trace.events,"initial_snapshot":initial,
                "final_snapshot":self.snapshot(),"metrics":self.metrics(h)}

    def snapshot(self):
        return {"run_id":self.run_id,"seq":len(self.trace.events),"tick":self.trace.tick,
                "robots":[{"id":r.id,"position":xy(r.position),"mode":r.mode,"task_id":r.task_id,"zone":r.zone} for r in sorted(self.robots.values(),key=lambda r:r.id)],
                "tasks":[{"id":t.spec.id,"status":t.status,"holder":t.holder,"epoch":t.epoch,"expires_tick":t.expires_tick,"released":t.released,"deferred":t.deferred} for t in sorted(self.tasks.values(),key=lambda t:t.spec.id)],
                "network":{"active_faults":sorted(self.network.active),"failed_nodes":sorted(self.network.dead)},"metrics":{},"authority":[{"scope_id":z,"holder":s.leader,"epoch":s.epoch,"expires_tick":s.expires_tick} for z,s in sorted(self.scopes.grants.items()) if z not in self.expired_scopes] if self.scopes and self.started and len(self.trace.events)>1 else []}

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
                "deadline_miss_rate":misses/len(due) if due else None,"attempted_conflicts":self.conflicts+self.assignment_conflicts,
                "accepted_duplicates":0,"actual_collisions":0,"stale_rejections":self.stale,"messages_sent":self.network.sent,
                "messages_delivered":self.network.delivered,"messages_dropped":self.network.dropped,"messages_in_flight":len(self.network.queue),
                "messages_per_completion":self.network.sent/n if n else None,"trace_hash":h,
                "breakdown":{"unfinished":released-n,"motion_conflicts":self.conflicts,"assignment_conflicts":self.assignment_conflicts,"model":"conservative_grid_crash_stop","workload_source":"common_predeclared_local_release_v1","limitations":["fixed leader renewal after expiry; lost holder evidence remains deferred","peer conflicts fenced by modeled gate; not consensus","static task schedule available to all participants"]}}


def simulate(config,seed=0,engine_version=__version__,algorithm="centralized_greedy"):
    return Simulation(build_manifest(config,seed,engine_version,algorithm=algorithm)).run()
