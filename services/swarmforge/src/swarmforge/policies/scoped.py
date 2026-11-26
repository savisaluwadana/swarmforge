"""Fixed, non-overlapping scope delegation and leader-local auction.

A zone receives its predeclared task releases from its local workload source,
not from instantaneous global state. Remote bids and grants travel via Network.
"""
from dataclasses import dataclass
from swarmforge.domain.model import Grid
from swarmforge.motion.grid import distance
from swarmforge.policies.centralized import GrantProposal


@dataclass(frozen=True)
class ScopeGrant:
    zone: str
    leader: str
    epoch: int
    expires_tick: int
    members: tuple[str, ...]


class ScopeLedger:
    """Execution-side gate; never selects a task or reveals remote task state."""
    def __init__(self, config, grid):
        self.grants = {}
        self.grids = {}
        self.task_zone = {}
        self.lease_ticks=config["scope_lease_ticks"]
        expires = min(config["duration_ticks"], self.lease_ticks)
        for z in sorted(config["zones"], key=lambda z:z["id"]):
            zone = z["id"]
            members = tuple(sorted(r["id"] for r in config["robots"] if r["zone"] == zone))
            self.grants[zone] = ScopeGrant(zone,z["leader"],1,expires,members)
            outside = {(x,y) for x in range(grid.width) for y in range(grid.height)
                       if not (z["min_x"] <= x <= z["max_x"] and z["min_y"] <= y <= z["max_y"])}
            self.grids[zone] = Grid(grid.width,grid.height,grid.obstacles | frozenset(outside))
        for t in config["tasks"]:
            p = (t["pickup"]["x"],t["pickup"]["y"])
            q = (t["dropoff"]["x"],t["dropoff"]["y"])
            for zone,g in self.grids.items():
                if g.free(p) and g.free(q) and g.reachable(p,q):
                    self.task_zone[t["id"]] = zone
                    break

    def renew(self,zone,tick,duration):
        old=self.grants[zone]
        if tick<old.expires_tick or tick>=duration:
            raise ValueError("scope renewal outside allowed interval")
        fresh=ScopeGrant(zone,old.leader,old.epoch+1,min(duration,tick+self.lease_ticks),old.members)
        self.grants[zone]=fresh
        return fresh

    def permits(self,tick,task_id,issuer,holder,scope_epoch):
        zone = self.task_zone.get(task_id)
        if zone is None:
            return issuer == "C" and scope_epoch is None
        s = self.grants[zone]
        return (issuer == s.leader and holder in s.members and scope_epoch == s.epoch
                and 0 <= tick < s.expires_tick)


class ZoneAuction:
    """Each leader has local inbox, scope token, task releases, bids and reservations."""
    def __init__(self,scope,grid):
        self.scope = scope
        self.grid = grid
        self.token = None
        self.pending = {}
        self.rounds = {}
        self.reservations = {}
        self.completed = set()

    def release(self,spec):
        self.pending[spec.id] = spec

    def active(self,tick):
        return self.token is not None and tick < self.token["expires_tick"]

    def receive(self,tick,inbox):
        for m in inbox:
            b = m.body
            if m.kind == "scope" and m.sender == "C" and b["scope_id"] == self.scope.zone:
                if (self.token is None or b["epoch"]>=self.token["epoch"]) and tick < b["expires_tick"]:
                    if self.token is None or b["epoch"]>self.token["epoch"]:
                        self.rounds.clear()
                    self.token = b
            elif m.kind == "bid":
                rnd = self.rounds.get(b["task_id"])
                if (rnd and m.sender in self.scope.members and b["round"] == rnd["start"]
                        and tick <= rnd["start"]+3):
                    rnd["bids"][m.sender] = b["score"]
            elif m.kind == "completed" and self.reservations.get(b["task_id"]) == m.sender:
                self.completed.add(b["task_id"])
                self.pending.pop(b["task_id"],None)
                self.reservations.pop(b["task_id"],None)

    def score(self,tick,robot,spec):
        if (robot.mode != "idle" or robot.task_id is not None
                or not self.grid.free(robot.position)
                or not self.grid.reachable(robot.position,spec.pickup)):
            return None
        estimate = distance(robot.position,spec.pickup)+distance(spec.pickup,spec.dropoff)
        penalty = max(0,tick+estimate-spec.due_tick) if spec.due_tick is not None else 0
        return estimate+penalty-2*spec.priority

    def decide(self,tick,leader,network):
        if not self.active(tick):
            return []
        busy = set(self.reservations.values())
        candidates=[]
        for tid,rnd in sorted(list(self.rounds.items())):
            if tick < rnd["start"]+3:
                continue
            if tid not in self.reservations:
                for rid,score in rnd["bids"].items():
                    if rid not in busy:
                        candidates.append((score,tid,rid))
            del self.rounds[tid]
        proposals=[]
        used=set()
        for _,tid,rid in sorted(candidates):
            if tid in used or rid in busy:
                continue
            proposals.append(GrantProposal(tid,rid))
            used.add(tid)
            busy.add(rid)
        for tid,spec in sorted(self.pending.items()):
            if tid in self.reservations or tid in self.rounds or tid in used:
                continue
            if tick+3 >= self.token["expires_tick"]:
                continue
            rnd={"start":tick,"bids":{}}
            score=self.score(tick,leader,spec)
            if score is not None:
                rnd["bids"][leader.id]=score
            self.rounds[tid]=rnd
            body={"task_id":tid,"pickup":spec.pickup,"dropoff":spec.dropoff,
                  "priority":spec.priority,"due_tick":spec.due_tick,"round":tick,
                  "scope_id":self.scope.zone}
            for rid in self.scope.members:
                if rid != leader.id:
                    network.send(tick,leader.id,rid,"auction",body)
        return proposals
