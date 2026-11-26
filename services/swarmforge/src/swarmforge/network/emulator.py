from copy import deepcopy
from dataclasses import dataclass
from heapq import heappush, heappop
from hashlib import sha256
from collections import defaultdict
from swarmforge.core.trace import canonical


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    receiver: str
    kind: str
    body: dict
    sent_tick: int
    deliver_tick: int


class Network:
    def __init__(self, config, nodes, seed, trace):
        self.config = deepcopy(config)
        self.nodes = set(nodes)
        self.seed = seed
        self.trace = trace
        self.overrides = {(l["from"],l["to"]):l for l in config["links"]}
        self.active = {}
        self.dead = set()
        self.queue = []
        self.ordinals = defaultdict(int)
        self.counter = 0
        self.sent = self.delivered = self.dropped = 0

    def affected(self, f, a, b):
        if f["type"] == "controller_outage":
            return "C" in (a,b)
        return any(l["from"] == a and l["to"] == b for l in f.get("links",[]))

    def conditions(self,a,b):
        override = self.overrides.get((a,b),{})
        enabled = override.get("enabled",True) and a not in self.dead and b not in self.dead
        delay = override.get("delay_ticks",self.config["default_delay_ticks"])
        loss = override.get("drop_rate",self.config["default_drop_rate"])
        for f in self.active.values():
            if not self.affected(f,a,b):
                continue
            if f["type"] in ("controller_outage","partition"):
                enabled = False
            elif f["type"] == "latency":
                delay += f["extra_delay_ticks"]
            elif f["type"] == "packet_loss":
                loss = f["drop_rate"]
        return enabled,delay,loss

    def _drop(self,m,reason):
        self.dropped += 1
        self.trace.emit("network.message_dropped",message_id=m.id,sender=m.sender,receiver=m.receiver,reason=reason)

    def send(self,tick,sender,receiver,kind,body):
        if sender not in self.nodes or receiver not in self.nodes or sender == receiver:
            raise ValueError("invalid message endpoints")
        enabled,delay,loss = self.conditions(sender,receiver)
        self.counter += 1
        m = Message(f"m{self.counter}",sender,receiver,kind,deepcopy(body),tick,tick+delay)
        self.sent += 1
        self.trace.emit("network.message_sent",message_id=m.id,sender=sender,receiver=receiver,
                        kind=kind,deliver_tick=m.deliver_tick,bytes=len(canonical(m.__dict__)))
        key = (tick,sender,receiver,kind)
        ordinal = self.ordinals[key]
        self.ordinals[key] += 1
        draw = int.from_bytes(sha256(canonical([self.seed,"network",*key,ordinal])).digest()[:8],"big") / 2**64
        if not enabled:
            self._drop(m,"link_unavailable")
        elif draw < loss:
            self._drop(m,"packet_loss")
        else:
            heappush(self.queue,(m.deliver_tick,self.counter,m))
        return m.id

    def deliver(self,tick):
        inbox = defaultdict(list)
        while self.queue and self.queue[0][0] <= tick:
            _,_,m = heappop(self.queue)
            if not self.conditions(m.sender,m.receiver)[0]:
                self._drop(m,"link_unavailable_at_delivery")
                continue
            self.delivered += 1
            self.trace.emit("network.message_delivered",message_id=m.id,sender=m.sender,receiver=m.receiver)
            inbox[m.receiver].append(m)
        return inbox

    def invalidate_blocked(self):
        """Drop in-flight envelopes on a newly blocked link, even if it heals before delivery."""
        kept=[]
        for item in sorted(self.queue):
            m=item[2]
            if self.conditions(m.sender,m.receiver)[0]:
                kept.append(item)
            else:
                self._drop(m,"link_interrupted_in_flight")
        self.queue=[]
        for item in kept:
            heappush(self.queue,item)
