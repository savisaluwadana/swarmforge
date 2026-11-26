import unittest
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
from swarmforge.benchmark.scenarios import scenario,design
from swarmforge.benchmark.validate import audit,ContractValidator,EvidenceError
from swarmforge.benchmark.runner import paired,recovery,run_suite
from swarmforge.core.simulator import simulate
from swarmforge.core.trace import semantic_digest
from test_core import fixture,ROOT


class BenchmarkTests(unittest.TestCase):
    def test_frozen_design(self):
        self.assertEqual(len(design("smoke")),12)
        self.assertEqual(len(design("research")),72)
        a=scenario("healthy",11);b=scenario("short_outage",11)
        self.assertEqual(a["tasks"],b["tasks"])
        self.assertEqual(a["robots"],b["robots"])
        self.assertNotEqual(a["tasks"],scenario("healthy",29)["tasks"])

    def test_audit_three_policies(self):
        for alg in ("centralized_greedy","local_auction","scoped_lease"):
            result=simulate(fixture(),42,algorithm=alg)
            self.assertTrue(audit(result,ContractValidator(ROOT/"contracts"))["verified"])

    def test_counter_tamper_detected(self):
        r=simulate(fixture(),42)
        r["metrics"]["completed"]+=1
        with self.assertRaises(EvidenceError):audit(r)

    def test_latency_tamper_detected(self):
        r=simulate(fixture(),42)
        r["metrics"]["latency_p50_ticks"]+=1
        with self.assertRaises(EvidenceError):audit(r)

    def test_invalid_payload_detected(self):
        from jsonschema import ValidationError
        r=simulate(fixture(),42)
        e=next(e for e in r["events"] if e["type"]=="robot.moved")
        del e["payload"]["robot_id"]
        h=semantic_digest(r["events"])
        r["metrics"]["trace_hash"]=h;r["events"][-1]["payload"]["trace_hash"]=h
        with self.assertRaises(ValidationError):audit(r,ContractValidator(ROOT/"contracts"))

    def test_paired_missing_and_intervals(self):
        rows=[]
        for seed in range(6):
            rows.append({"condition":"a","seed":seed,"algorithm":"centralized_greedy","status":"succeeded","metrics":{"x":1}})
            rows.append({"condition":"a","seed":seed,"algorithm":"scoped_lease","status":"failed" if seed==5 else "succeeded","metrics":{"x":3}})
        p=paired(rows,"a","x","scoped_lease")
        self.assertEqual((p["matched_n"],p["missing_n"],p["ci95_low"],p["ci95_high"]),(5,1,2,2))

    def test_recovery_states(self):
        self.assertEqual(recovery([25],[25],20,50),(20,"recovered"))
        self.assertEqual(recovery([],[25],20,50),(None,"censored"))
        self.assertEqual(recovery([],[],20,50),(None,"undefined"))

    def test_failed_outcomes_are_preserved(self):
        def fail(m): raise RuntimeError("injected test failure")
        with TemporaryDirectory() as d:
            report=run_suite("smoke",d,ROOT/"contracts",runner=fail)
            self.assertEqual(report["failed"],12)
            self.assertEqual(len(list((Path(d)/"traces").glob("*.json"))),12)
            self.assertTrue((Path(d)/"runs.csv").exists())
