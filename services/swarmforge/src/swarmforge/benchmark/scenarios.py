"""Frozen experimental design. Exogenous workload randomness is separate from network."""
import random

POLICIES=("centralized_greedy","local_auction","scoped_lease")
SMOKE={"healthy":(11,29),"short_outage":(11,29)}
RESEARCH={"healthy":(11,29,47,71,101),"short_outage":(11,29,47,71,101),
          "long_outage":(11,29),"partition":(11,29),"robot_crash":(11,29),
          "loss":(11,29),"latency":(11,29),"skew_cross_zone":(11,29),
          "lost_delegation":(11,29)}


def scenario(condition,seed):
    if condition not in RESEARCH:
        raise ValueError("unknown condition")
    rng=random.Random(seed)
    robots=[{"id":f"r{i:02}","start":{"x":2 if i<5 else 14,"y":2+2*(i%5)},
             "zone":"west" if i<5 else "east"} for i in range(10)]
    zones=[{"id":"west","min_x":0,"max_x":11,"min_y":0,"max_y":11,"leader":"r00"},
           {"id":"east","min_x":12,"max_x":23,"min_y":0,"max_y":11,"leader":"r05"}]
    tasks=[]
    for i in range(20):
        west=i%2==0 or condition=="skew_cross_zone" and i<16
        x=1 if west else 13
        y=1+2*(i%5)
        tasks.append({"id":f"t{i:02}","pickup":{"x":x,"y":y},
                      "dropoff":{"x":x+3+(12 if condition=="skew_cross_zone" and i%5==0 and west else 0),"y":y},
                      "release_tick":i*3+rng.randrange(3),"priority":rng.randrange(1,6),
                      "due_tick":i*3+35})
    links=[{"from":a["id"],"to":b["id"]} for a in robots for b in robots if a["zone"]!=b["zone"]]
    faults=[]
    if condition in ("short_outage","long_outage","lost_delegation","skew_cross_zone"):
        faults=[{"type":"controller_outage","start_tick":0 if condition=="lost_delegation" else 15,
                 "end_tick":None if condition=="lost_delegation" else 65 if condition=="long_outage" else 30}]
    elif condition=="partition":
        faults=[{"type":"partition","start_tick":15,"end_tick":30,"links":links}]
    elif condition=="robot_crash":
        faults=[{"type":"robot_crash","start_tick":20,"end_tick":None,"robot_id":"r00"}]
    elif condition in ("loss","latency"):
        faults=[{"type":"packet_loss" if condition=="loss" else "latency","start_tick":15,"end_tick":30,"links":links,
                 **({"drop_rate":0.35} if condition=="loss" else {"extra_delay_ticks":4})}]
    return {"schema_version":1,"width":24,"height":12,"obstacles":[{"x":6,"y":y} for y in (2,4,6,8,10)],
            "robots":robots,"zones":zones,"tasks":tasks,"network":{"default_delay_ticks":1,"default_drop_rate":0,"links":[]},
            "faults":faults,"duration_ticks":100,"tick_ms":1000,"scope_lease_ticks":40}


def design(suite):
    matrix=SMOKE if suite=="smoke" else RESEARCH if suite=="research" else None
    if matrix is None:
        raise ValueError("unknown benchmark suite")
    return [(condition,seed,algorithm) for condition,seeds in matrix.items() for seed in seeds for algorithm in POLICIES]
