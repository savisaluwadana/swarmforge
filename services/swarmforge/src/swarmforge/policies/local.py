"""Simplified peer auction baseline; no claim of distributed consensus."""
from swarmforge.motion.grid import distance
from swarmforge.policies.centralized import GrantProposal


class PeerAuction:
    """Local knowledge only. A peer can propose itself, never another robot."""
    def __init__(self,rid,peers):
        self.rid=rid
        self.peers=tuple(sorted(p for p in peers if p!=rid))
        self.pending={}
        self.bids={}
        self.done=set()
        self.claims={}

    def release(self,spec):
        self.pending[spec.id]=spec

    def observe(self,tick,inbox):
        for m in inbox:
            if m.sender not in self.peers:
                continue
            b=m.body
            if m.kind=="peer_bid" and b["round"]==tick//4*4 and tick%4!=0:
                self.bids.setdefault(b["task_id"],{})[m.sender]=b["score"]
            elif m.kind=="peer_claim" and b["expires_tick"]>tick:
                self.claims[b["task_id"]]=max(self.claims.get(b["task_id"],0),b["expires_tick"])
            elif m.kind=="peer_completed":
                self.done.add(b["task_id"])
                self.pending.pop(b["task_id"],None)

    def step(self,tick,robot,network):
        if tick%4==0:
            self.bids={}
        if robot.mode!="idle" or robot.task_id is not None:
            return None
        if tick%4==0:
            for tid,s in sorted(self.pending.items()):
                if tid in self.done or self.claims.get(tid,0)>tick:
                    continue
                estimate=distance(robot.position,s.pickup)+distance(s.pickup,s.dropoff)
                penalty=max(0,tick+estimate-s.due_tick) if s.due_tick is not None else 0
                score=estimate+penalty-2*s.priority
                self.bids.setdefault(tid,{})[self.rid]=score
                for peer in self.peers:
                    network.send(tick,self.rid,peer,"peer_bid",{"task_id":tid,"round":tick,"score":score})
        if tick%4==3:
            wins=[]
            for tid,bids in sorted(self.bids.items()):
                if tid not in self.pending or self.claims.get(tid,0)>tick or self.rid not in bids:
                    continue
                score,winner=min((score,rid) for rid,score in bids.items())
                if winner==self.rid:
                    wins.append((score,tid))
            if wins:
                return GrantProposal(min(wins)[1],self.rid)
        return None

    def announce(self,tick,network,kind,body):
        for peer in self.peers:
            network.send(tick,self.rid,peer,kind,body)
