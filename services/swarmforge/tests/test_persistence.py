"""Real PostgreSQL integration tests. Enabled only with SWARMFORGE_TEST_DATABASE_URL."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID,uuid4
from test_core import fixture,ROOT

DSN=os.environ.get("SWARMFORGE_TEST_DATABASE_URL")


@unittest.skipUnless(DSN,"requires dedicated PostgreSQL test database")
class PersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import psycopg
        from psycopg import sql
        from psycopg.conninfo import make_conninfo
        from swarmforge.persistence.migrate import migrate
        cls.schema="test_"+uuid4().hex
        with psycopg.connect(DSN) as c:
            c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.dsn=make_conninfo(DSN,options="-c search_path="+cls.schema)
        migrate(cls.dsn,ROOT/"db")
        migrate(cls.dsn,ROOT/"db")

    @classmethod
    def tearDownClass(cls):
        import psycopg
        from psycopg import sql
        with psycopg.connect(DSN) as c:
            c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def setUp(self):
        from swarmforge.persistence.repository import Repository
        from swarmforge.application.identity import Principal
        self.repo=Repository(self.dsn,"integration-build",max_active=2,max_workspace_active=1)
        self.w=uuid4();self.other=uuid4()
        self.p=Principal(uuid4());self.viewer=Principal(uuid4());self.outside=Principal(uuid4())
        with self.repo.connect() as c:
            # Tests share only schema, never active jobs.
            c.execute("TRUNCATE workspaces,users CASCADE")
            for p in (self.p,self.viewer,self.outside):
                c.execute("INSERT INTO users(id,issuer,subject) VALUES (%s,'test',%s)",(p.user_id,str(p.user_id)))
            for w in (self.w,self.other):
                c.execute("INSERT INTO workspaces(id,name) VALUES (%s,'test')",(w,))
            for w,p,role in ((self.w,self.p,"owner"),(self.w,self.viewer,"viewer"),(self.other,self.outside,"owner"),(self.other,self.p,"owner")):
                c.execute("INSERT INTO memberships(workspace_id,user_id,role) VALUES (%s,%s,%s)",(w,p.user_id,role))
        self.sid=UUID(self.repo.create_scenario(self.p,self.w,"fixture",fixture(),"scenario")["scenario_id"])

    def enqueue(self,key="run"):
        return UUID(self.repo.enqueue(self.p,self.w,self.sid,1,"centralized_greedy",42,key)["run_id"])

    def test_migration_and_immutable_revision(self):
        c=fixture();c["duration_ticks"]=60
        new=self.repo.create_revision(self.p,self.w,self.sid,c,"rev")
        self.assertEqual(new["revision"],2)
        self.assertEqual(self.repo.get_revision(self.p,self.w,self.sid,1)["config"]["duration_ticks"],50)
        self.assertEqual(self.repo.get_revision(self.p,self.w,self.sid,2)["config"]["duration_ticks"],60)

    def test_idempotency_and_conflict(self):
        from swarmforge.application.identity import Conflict
        a=self.enqueue();b=self.enqueue()
        self.assertEqual(a,b)
        with self.assertRaises(Conflict):
            self.repo.enqueue(self.p,self.w,self.sid,1,"scoped_lease",42,"run")

    def test_concurrent_idempotency(self):
        with ThreadPoolExecutor(max_workers=4) as ex:
            ids=list(ex.map(lambda _:self.enqueue(),range(4)))
        self.assertEqual(len(set(ids)),1)

    def test_workspace_and_roles(self):
        from swarmforge.application.identity import Forbidden,NotFound
        rid=self.enqueue()
        with self.assertRaises(NotFound): self.repo.get_run(self.outside,self.w,rid)
        with self.assertRaises(NotFound): self.repo.get_run(self.p,self.other,rid)
        with self.assertRaises(NotFound): self.repo.read_events(self.p,self.other,rid)
        with self.assertRaises(Forbidden): self.repo.cancel(self.viewer,self.w,rid,"cancel")
        self.assertEqual(self.repo.get_run(self.viewer,self.w,rid)["status"],"queued")
        self.assertNotIn("lease_token",self.repo.get_run(self.viewer,self.w,rid))

    def test_claim_concurrency_and_workspace_quota(self):
        self.enqueue("1");self.enqueue("2")
        with ThreadPoolExecutor(max_workers=4) as ex:
            leases=list(ex.map(lambda i:self.repo.claim(str(i)),range(4)))
        self.assertEqual(sum(x is not None for x in leases),1)

    def test_stale_lease_cannot_append(self):
        from swarmforge.application.identity import LeaseLost
        rid=self.enqueue();lease=self.repo.claim("worker")
        with self.repo.connect() as c:
            c.execute("UPDATE runs SET lease_until=clock_timestamp()-interval '1 second' WHERE id=%s",(rid,))
        with self.assertRaises(LeaseLost): self.repo.commit_batch(lease,[],None)
        self.assertEqual(self.repo.reap(),1)
        with self.assertRaises(LeaseLost): self.repo.renew(lease)
        self.assertEqual(self.repo.get_run(self.p,self.w,rid)["failure_code"],"worker_lost")
        self.assertIsNone(self.repo.claim("new"))

    def test_cancel_queued_and_running(self):
        from swarmforge.application.identity import CancelRequested,Conflict
        rid=self.enqueue()
        self.assertEqual(self.repo.cancel(self.p,self.w,rid,"c")["status"],"cancelled")
        other=self.enqueue("other");lease=self.repo.claim("worker")
        self.assertEqual(lease.run_id,other)
        self.assertEqual(self.repo.cancel(self.p,self.w,other,"c")["status"],"cancelling")
        with self.assertRaises(CancelRequested): self.repo.commit_batch(lease,[],None)
        self.repo.finish_cancel(lease)
        self.assertEqual(self.repo.get_run(self.p,self.w,other)["status"],"cancelled")
        with self.assertRaises(Conflict): self.repo.get_metrics(self.p,self.w,other)

    def test_batch_gap_rolls_back(self):
        from swarmforge.application.identity import Conflict
        rid=self.enqueue();lease=self.repo.claim("worker")
        from swarmforge.core.simulator import Simulation
        result=Simulation(lease.manifest,str(rid)).run()
        with self.assertRaises(Conflict): self.repo.commit_batch(lease,result["events"][1:2],None)
        self.assertEqual(self.repo.get_run(self.p,self.w,rid)["last_seq"],0)
        self.assertEqual(self.repo.read_events(self.p,self.w,rid),[])

    def test_worker_real_result_and_restart_read(self):
        from swarmforge.worker.main import Worker
        from swarmforge.persistence.repository import Repository
        from swarmforge.core.trace import semantic_digest
        rid=self.enqueue()
        self.assertTrue(Worker(self.repo,ROOT/"contracts").once())
        restarted=Repository(self.dsn,"integration-build")
        row=restarted.get_run(self.p,self.w,rid)
        self.assertEqual(row["status"],"succeeded")
        metrics=restarted.get_metrics(self.p,self.w,rid)
        events=restarted.read_events(self.p,self.w,rid,0,1000)
        self.assertEqual(metrics["completed"],2)
        self.assertEqual(semantic_digest(events),metrics["trace_hash"])
        self.assertEqual(row["last_seq"],len(events))
        self.assertEqual(restarted.get_snapshot(self.p,self.w,rid)["seq"],len(events))
        self.assertEqual(restarted.get_snapshot(self.p,self.w,rid,1)["seq"],1)
        self.assertEqual(restarted.read_events(self.p,self.w,rid,1,2),events[1:3])
        self.assertFalse(Worker(restarted,ROOT/"contracts").once())
