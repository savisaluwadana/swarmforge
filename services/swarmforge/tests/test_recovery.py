import unittest
from uuid import uuid4
from test_core import fixture
from swarmforge.core.simulator import Simulation,build_manifest,simulate
from swarmforge.core.trace import semantic_digest
from swarmforge.network.emulator import Message
from swarmforge.policies.scoped import ScopeLedger
from swarmforge.domain.model import validate_config


class RecoveryTests(unittest.TestCase):
    def test_three_policy_replays(self):
        for algorithm in ("centralized_greedy","local_auction","scoped_lease"):
            for seed in range(5):
                c=fixture()
                c["network"]["default_drop_rate"]=0.1
                m=build_manifest(c,seed,algorithm=algorithm)
                a=Simulation(m,str(uuid4())).run()
                b=Simulation(m,str(uuid4())).run()
                self.assertEqual(a["metrics"]["trace_hash"],b["metrics"]["trace_hash"])
                self.assertEqual(semantic_digest(a["events"]),a["metrics"]["trace_hash"])
                for kind in ("task.picked","task.completed"):
                    ids=[e["payload"]["task_id"] for e in a["events"] if e["type"]==kind]
                    self.assertEqual(len(ids),len(set(ids)))
                metrics=a["metrics"]
                self.assertEqual(metrics["messages_sent"],metrics["messages_delivered"]+metrics["messages_dropped"]+metrics["messages_in_flight"])

    def test_peer_auction_completes(self):
        a=simulate(fixture(),42,algorithm="local_auction")
        self.assertEqual(a["metrics"]["completed"],2)
        self.assertTrue(any(e["type"]=="network.message_sent" and e["payload"]["kind"]=="peer_bid" for e in a["events"]))
        self.assertTrue(any(e["type"]=="task.assigned" and e["payload"]["issuer_id"]!="C" for e in a["events"]))

    def test_peer_partition_conflict_is_fenced(self):
        c=fixture()
        c["faults"]=[{"type":"partition","start_tick":0,"end_tick":None,"links":[{"from":"r1","to":"r2"},{"from":"r2","to":"r1"}]}]
        c["tasks"]=c["tasks"][:1]
        a=simulate(c,42,algorithm="local_auction")
        self.assertGreater(a["metrics"]["breakdown"]["assignment_conflicts"],0)
        self.assertEqual(sum(e["type"]=="task.assigned" for e in a["events"]),1)
        self.assertEqual(a["metrics"]["completed"],1)

    def test_scope_renewal_requires_delivered_request(self):
        c=fixture()
        c["scope_lease_ticks"]=8
        a=simulate(c,42,algorithm="scoped_lease")
        renew=[e for e in a["events"] if e["type"]=="authority.granted" and "scope_id" in e["payload"] and e["payload"]["epoch"]>1]
        self.assertTrue(renew)
        self.assertTrue(all(e["tick"]>=20 for e in renew))
        for e in renew:
            self.assertTrue(any(x["type"]=="network.message_delivered" and x["tick"]==e["tick"] and x["payload"]["receiver"]=="C" and x["payload"]["sender"]==e["payload"]["holder"] for x in a["events"]))

    def test_expired_token_fenced_after_renewal(self):
        c=fixture()
        s=ScopeLedger(c,validate_config(c))
        self.assertFalse(s.permits(40,"t1","r1","r1",1))
        fresh=s.renew("west",40,50)
        self.assertEqual(fresh.epoch,2)
        self.assertFalse(s.permits(41,"t1","r1","r1",1))
        self.assertTrue(s.permits(41,"t1","r1","r1",2))

    def test_release_evidence_exact_holder_epoch_and_expiry(self):
        c=fixture()
        s=Simulation(build_manifest(c,42,algorithm="scoped_lease"))
        t=s.tasks["t1"]
        t.released=True
        t.status="assigned"
        t.holder="r2"
        t.issuer="r1"
        t.epoch=1
        t.expires_tick=8
        def msg(sender,epoch,phase="unpicked"):
            return Message("test",sender,"r1","released_unpicked",{"task_id":"t1","epoch":epoch,"phase":phase},8,9)
        for tick,m in [(7,msg("r2",1)),(9,msg("r1",1)),(9,msg("r2",2)),(9,msg("r2",1,"picked"))]:
            s.reconcile_release(tick,"r1",m)
            self.assertEqual(t.status,"assigned")
        s.reconcile_release(9,"r1",msg("r2",1))
        self.assertEqual(t.status,"pending")
        self.assertEqual(t.epoch,1)
        s.reconcile_release(10,"r1",msg("r2",1))
        self.assertEqual(sum(e["type"]=="recovery.reconciled" for e in s.trace.events),1)

    def test_picked_or_stranded_not_released(self):
        s=Simulation(build_manifest(fixture(),42,algorithm="scoped_lease"))
        t=s.tasks["t1"]
        t.holder="r1"
        t.issuer="r1"
        t.epoch=1
        t.expires_tick=8
        for phase in ("picked","stranded","completed"):
            t.status=phase
            m=Message("test","r1","r1","released_unpicked",{"task_id":"t1","epoch":1,"phase":"unpicked"},8,8)
            s.reconcile_release(9,"r1",m)
            self.assertEqual(t.status,phase)
