import copy
import unittest
from uuid import uuid4
from test_core import fixture
from swarmforge.core.simulator import Simulation,build_manifest,simulate
from swarmforge.core.trace import semantic_digest
from swarmforge.domain.model import validate_config
from swarmforge.policies.scoped import ScopeLedger


class ScopedTests(unittest.TestCase):
    def run_scoped(self,c,seed=42):
        return simulate(c,seed,algorithm="scoped_lease")

    def test_local_work_during_outage(self):
        c=fixture()
        central=simulate(c,42)
        scoped=self.run_scoped(c)
        def pickup(result):
            return next(e["tick"] for e in result["events"] if e["type"]=="task.picked" and e["payload"]["task_id"]=="t2")
        self.assertGreaterEqual(pickup(central),20)
        self.assertTrue(5<=pickup(scoped)<20)
        self.assertEqual(scoped["metrics"]["completed"],2)
        self.assertFalse(any(e["type"]=="network.message_delivered" and "C" in (e["payload"]["sender"],e["payload"]["receiver"]) and 5<=e["tick"]<20 for e in scoped["events"]))

    def test_initial_scope_message_must_arrive(self):
        c=fixture()
        c["faults"]=[{"type":"controller_outage","start_tick":0,"end_tick":None}]
        r=self.run_scoped(c)
        self.assertEqual(r["metrics"]["completed"],0)
        self.assertFalse(any(e["type"]=="task.assigned" for e in r["events"]))

    def test_expired_scope_fences_actions(self):
        c=fixture()
        c["scope_lease_ticks"]=8
        r=self.run_scoped(c)
        self.assertFalse(any(e["tick"]>=8 and e["type"] in ("task.picked","task.completed","robot.moved") for e in r["events"]))
        self.assertTrue(any(e["type"]=="authority.expired" for e in r["events"]))
        self.assertEqual(r["metrics"]["completed"],0)

    def test_scope_gate_wrong_issuer_member_epoch_and_expiry(self):
        c=fixture()
        ledger=ScopeLedger(c,validate_config(c))
        self.assertTrue(ledger.permits(5,"t1","r1","r1",1))
        for issuer,holder,epoch,tick in [("C","r1",1,5),("r2","r1",1,5),("r1","r2",1,5),("r1","r1",2,5),("r1","r1",1,40)]:
            self.assertFalse(ledger.permits(tick,"t1",issuer,holder,epoch))

    def test_cross_zone_requires_controller(self):
        c=fixture()
        c["tasks"][0]["dropoff"]={"x":7,"y":4}
        ledger=ScopeLedger(c,validate_config(c))
        self.assertNotIn("t1",ledger.task_zone)
        self.assertTrue(ledger.permits(5,"t1","C","r1",None))
        self.assertFalse(ledger.permits(5,"t1","r1","r1",1))

    def test_remote_bid_and_grant(self):
        c=fixture()
        c["robots"].append({"id":"r3","start":{"x":3,"y":4},"zone":"west"})
        c["tasks"][0]["pickup"]={"x":3,"y":4}
        c["tasks"][0]["dropoff"]={"x":4,"y":4}
        c["faults"]=[]
        r=self.run_scoped(c)
        self.assertTrue(any(e["type"]=="network.message_sent" and e["payload"]["kind"]=="bid" and e["payload"]["sender"]=="r3" for e in r["events"]))
        self.assertTrue(any(e["type"]=="task.completed" and e["payload"]["task_id"]=="t1" and e["payload"]["robot_id"]=="r3" for e in r["events"]))

    def test_leader_crash_prevents_new_assignments(self):
        c=fixture()
        c["faults"]=[{"type":"robot_crash","start_tick":4,"end_tick":None,"robot_id":"r2"}]
        r=self.run_scoped(c)
        self.assertFalse(any(e["type"]=="task.assigned" and e["payload"]["task_id"]=="t2" for e in r["events"]))

    def test_determinism_loss_and_invariants(self):
        c=fixture()
        c["network"]["default_drop_rate"]=0.1
        for seed in range(10):
            m=build_manifest(c,seed,algorithm="scoped_lease")
            a=Simulation(m,str(uuid4())).run()
            b=Simulation(m,str(uuid4())).run()
            self.assertEqual(a["metrics"]["trace_hash"],b["metrics"]["trace_hash"])
            self.assertEqual(semantic_digest(a["events"]),a["metrics"]["trace_hash"])
            x=a["metrics"]
            self.assertEqual(x["messages_sent"],x["messages_delivered"]+x["messages_dropped"]+x["messages_in_flight"])
            for kind in ("task.picked","task.completed"):
                ids=[e["payload"]["task_id"] for e in a["events"] if e["type"]==kind]
                self.assertEqual(len(ids),len(set(ids)))
