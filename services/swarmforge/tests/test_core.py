import copy
import json
from pathlib import Path
import random
import unittest
from uuid import uuid4
from swarmforge.core.simulator import Simulation,build_manifest,simulate
from swarmforge.core.trace import canonical,semantic_digest,Trace
from swarmforge.domain.model import InvalidScenario,Grid,validate_config
from swarmforge.motion.grid import plan,resolve
from swarmforge.network.emulator import Network

ROOT=Path(__file__).resolve().parents[3]

def fixture():
    return json.loads((ROOT/"examples/two-robot-outage.json").read_text())


class CoreTests(unittest.TestCase):
    def test_replay(self):
        m=build_manifest(fixture(),42)
        a=Simulation(m,str(uuid4())).run()
        b=Simulation(m,str(uuid4())).run()
        self.assertEqual(a["metrics"]["trace_hash"],b["metrics"]["trace_hash"])
        self.assertEqual(semantic_digest(a["events"]),a["metrics"]["trace_hash"])
        self.assertEqual([e["seq"] for e in a["events"]],list(range(1,len(a["events"])+1)))
        self.assertEqual([e["tick"] for e in a["events"]],sorted(e["tick"] for e in a["events"]))
        self.assertEqual(a["initial_snapshot"]["seq"],1)
        self.assertEqual(a["metrics"]["completed"],2)
        self.assertEqual(a["metrics"]["actual_collisions"],0)

    def test_outage_blocks_late_pickup(self):
        a=simulate(fixture())
        healthy=fixture()
        healthy["faults"]=[]
        b=simulate(healthy)
        def picked(result):
            return next(e["tick"] for e in result["events"] if e["type"]=="task.picked" and e["payload"]["task_id"]=="t2")
        self.assertGreaterEqual(picked(a),20)
        self.assertLess(picked(b),20)
        # A controller may reserve using a heartbeat that has not yet timed out.
        # No grant crosses the disconnected network; only a delivered grant permits execution.
        self.assertFalse(any(e["type"]=="network.message_delivered" and "C" in (e["payload"]["sender"],e["payload"]["receiver"]) and 5<=e["tick"]<20 for e in a["events"]))

    def test_crash_while_carrying(self):
        c=fixture()
        c["faults"]=[{"type":"robot_crash","robot_id":"r1","start_tick":4,"end_tick":None}]
        a=simulate(c)
        self.assertTrue(any(e["type"]=="task.stranded" and e["payload"]["task_id"]=="t1" for e in a["events"]))
        self.assertFalse(any(e["type"]=="task.completed" and e["payload"]["task_id"]=="t1" for e in a["events"]))
        self.assertFalse(any(e["type"]=="robot.moved" and e["payload"]["robot_id"]=="r1" and e["tick"]>=4 for e in a["events"]))

    def test_network_inflight_drop(self):
        t=Trace(str(uuid4()))
        net=Network({"default_delay_ticks":5,"default_drop_rate":0,"links":[]},{"C","r1"},3,t)
        net.send(0,"C","r1","grant",{})
        t.tick=1
        net.active["f"]={"type":"controller_outage"}
        net.invalidate_blocked()
        net.active.clear()
        t.tick=5
        self.assertFalse(net.deliver(5))
        self.assertEqual((net.sent,net.delivered,net.dropped),(1,0,1))

    def test_network_loss_and_direction(self):
        t=Trace(str(uuid4()))
        net=Network({"default_delay_ticks":1,"default_drop_rate":0,"links":[{"from":"C","to":"r1","drop_rate":1}]},{"C","r1"},0,t)
        net.send(0,"C","r1","a",{})
        net.send(0,"r1","C","b",{})
        t.tick=1
        inbox=net.deliver(1)
        self.assertEqual(len(inbox["C"]),1)
        self.assertNotIn("r1",inbox)

    def test_path_and_conflict(self):
        g=Grid(5,5,frozenset({(1,0)}))
        route=plan(g,(0,0),(2,0))
        self.assertEqual(route[-1],(2,0))
        self.assertNotIn((1,0),route)
        moves,reject=resolve(g,{"a":(0,2),"b":(2,2)},{"a":(1,2),"b":(1,2)})
        self.assertEqual(moves,{"a":(1,2)})
        self.assertEqual(reject,{"b":"vertex_conflict"})

    def test_property_random_motion(self):
        rng=random.Random(37)
        g=Grid(8,8,frozenset())
        for _ in range(300):
            pos=dict(zip(map(str,range(12)),rng.sample([(x,y) for x in range(8) for y in range(8)],12)))
            proposals={r:(p[0]+dx,p[1]+dy) for r,p in pos.items() for dx,dy in [rng.choice([(1,0),(-1,0),(0,1),(0,-1),(0,0)])]}
            moves,_=resolve(g,pos,proposals)
            new=pos|moves
            self.assertEqual(len(set(new.values())),len(new))
            for rid,p in moves.items():
                self.assertTrue(g.free(p))
                self.assertNotIn(p,pos.values())

    def test_validation_and_immutability(self):
        c=fixture()
        original=copy.deepcopy(c)
        simulate(c)
        self.assertEqual(c,original)
        c["robots"][1]["start"]=c["robots"][0]["start"]
        with self.assertRaises(InvalidScenario):
            validate_config(c)

    def test_unsupported_policy_fails_closed(self):
        m=build_manifest(fixture(),0)
        m["algorithm"]="unsupported"
        with self.assertRaises(NotImplementedError):
            Simulation(m)

    def test_canonical(self):
        self.assertEqual(canonical({"z":-0.0,"a":1.0}),b'{"a":1,"z":0}')
        with self.assertRaises(ValueError):
            canonical(float("nan"))

    def test_all_messages_accounted_for_and_no_duplicate_pickup(self):
        for seed in range(10):
            c=fixture()
            c["network"]["default_drop_rate"]=0.1
            a=simulate(c,seed)
            m=a["metrics"]
            self.assertEqual(m["messages_sent"],m["messages_delivered"]+m["messages_dropped"]+m["messages_in_flight"])
            for kind in ("task.picked","task.completed"):
                ids=[e["payload"]["task_id"] for e in a["events"] if e["type"]==kind]
                self.assertEqual(len(ids),len(set(ids)))
            self.assertLessEqual(m["completed"],m["released"])


if __name__=="__main__":
    unittest.main()
