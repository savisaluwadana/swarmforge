"""Worker bridges deterministic tick checkpoints to durable PostgreSQL batches."""
import argparse
import logging
import os
import socket
import threading
import time
from uuid import uuid4
from swarmforge import __version__
from swarmforge.application.identity import LeaseLost,CancelRequested
from swarmforge.benchmark.validate import ContractValidator,audit
from swarmforge.core.simulator import Simulation
from swarmforge.persistence.repository import Repository

LOG=logging.getLogger("swarmforge.worker")


class Worker:
    def __init__(self,repo,contracts="contracts",worker_id=None):
        self.repo=repo
        self.validator=ContractValidator(contracts)
        self.worker_id=worker_id or socket.gethostname()+":"+str(uuid4())

    def once(self):
        self.repo.reap()
        lease=self.repo.claim(self.worker_id)
        if lease is None: return False
        stop=threading.Event();lost=threading.Event();cancelled=threading.Event()
        def heartbeat():
            while not stop.wait(min(5,self.repo.lease_seconds/3)):
                try:
                    if self.repo.renew(lease)=="cancelling":
                        cancelled.set()
                except Exception:
                    lost.set()
                    return
        thread=threading.Thread(target=heartbeat,daemon=True)
        thread.start()
        seq=0;last=time.monotonic()
        interactive=lease.manifest["mode"]=="interactive"
        def commands(tick):
            if lost.is_set():raise LeaseLost()
            if cancelled.is_set():raise CancelRequested()
            return self.repo.pending_commands(lease)
        def checkpoint(snapshot,events):
            nonlocal seq,last
            if lost.is_set(): raise LeaseLost()
            if cancelled.is_set(): raise CancelRequested()
            # Initial checkpoint, then bounded tick batches; no DB in policy.
            if len(events)>seq and (seq==0 or len(events)-seq>=100 or time.monotonic()-last>=0.2 or any(e["type"].startswith("command.") for e in events[seq:])):
                batch=events[seq:]
                for e in batch: self.validator.event(e)
                self.validator.validate("Snapshot",snapshot)
                seq=self.repo.commit_batch(lease,batch,snapshot)
                last=time.monotonic()
            if interactive:
                # Pace interactive mode outside core; logical tick_ms still governs metrics.
                time.sleep(0.1)
        try:
            result=Simulation(lease.manifest,str(lease.run_id)).run(checkpoint,commands if interactive else None)
            audit(result,self.validator)
            if lost.is_set(): raise LeaseLost()
            if cancelled.is_set(): raise CancelRequested()
            self.repo.finish(lease,result["events"][seq:],result["final_snapshot"],result["metrics"])
            LOG.info("run succeeded id=%s",lease.run_id)
        except CancelRequested:
            try: self.repo.finish_cancel(lease)
            except LeaseLost: LOG.warning("cancel fenced id=%s",lease.run_id)
        except LeaseLost:
            LOG.warning("worker fenced id=%s",lease.run_id)
        except Exception as exc:
            # Preserve committed prefix, never publish fabricated terminal metrics.
            LOG.error("run failed id=%s error_type=%s",lease.run_id,type(exc).__name__)
            try: self.repo.fail(lease)
            except LeaseLost: LOG.warning("failure fenced id=%s",lease.run_id)
        finally:
            stop.set()
            thread.join(timeout=6)
        return True


def from_env():
    return Repository(os.environ["DATABASE_URL"],os.environ.get("ENGINE_VERSION",__version__),
                      max_active=int(os.environ.get("MAX_ACTIVE_RUNS","4")),
                      max_workspace_active=int(os.environ.get("MAX_WORKSPACE_RUNS","2")),
                      max_workspace_pending=int(os.environ.get("MAX_WORKSPACE_PENDING","120")),
                      lease_seconds=int(os.environ.get("RUN_LEASE_SECONDS","30")))


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--once",action="store_true")
    p.add_argument("--contracts",default="contracts")
    args=p.parse_args()
    logging.basicConfig(level=logging.INFO)
    worker=Worker(from_env(),args.contracts)
    if args.once:
        worker.once()
        return
    while True:
        try:
            if not worker.once(): time.sleep(0.5)
        except Exception as exc:
            LOG.error("worker loop unavailable error_type=%s",type(exc).__name__)
            time.sleep(2)


if __name__=="__main__":
    main()
