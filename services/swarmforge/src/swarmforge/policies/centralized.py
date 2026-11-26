from dataclasses import dataclass
from swarmforge.domain.model import TaskSpec
from swarmforge.motion.grid import distance


@dataclass(frozen=True)
class GrantProposal:
    task_id: str
    robot_id: str


class CentralizedGreedy:
    """Controller-local policy. Receives only task announcements and delivered messages."""
    def __init__(self):
        self.pending: dict[str,TaskSpec] = {}
        self.status = {}
        self.reservations = {}
        self.completed = set()

    def release(self,spec):
        self.pending[spec.id] = spec

    def receive(self,tick,inbox):
        for msg in inbox:
            if msg.kind == "status":
                self.status[msg.sender] = (tick,msg.body)
            elif msg.kind == "completed" and self.reservations.get(msg.body["task_id"]) == msg.sender:
                self.completed.add(msg.body["task_id"])
                self.pending.pop(msg.body["task_id"],None)
                self.reservations.pop(msg.body["task_id"],None)

    def choose(self,tick):
        busy = set(self.reservations.values())
        candidates = []
        for rid,(seen,body) in sorted(self.status.items()):
            if tick-seen > 3 or body["mode"] != "idle" or rid in busy:
                continue
            for tid,spec in sorted(self.pending.items()):
                if tid in self.reservations or tid in self.completed:
                    continue
                estimate = distance(tuple(body["position"]),spec.pickup)+distance(spec.pickup,spec.dropoff)
                penalty = max(0,tick+estimate-spec.due_tick) if spec.due_tick is not None else 0
                candidates.append((estimate+penalty-2*spec.priority,tid,rid))
        used_tasks,used_robots = set(),set()
        result=[]
        for _,tid,rid in sorted(candidates):
            if tid in used_tasks or rid in used_robots:
                continue
            used_tasks.add(tid)
            used_robots.add(rid)
            result.append(GrantProposal(tid,rid))
        return result

    def reserve(self,proposal):
        self.reservations[proposal.task_id] = proposal.robot_id
