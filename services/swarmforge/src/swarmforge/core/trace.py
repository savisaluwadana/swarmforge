import hashlib
import json
import math
from copy import deepcopy


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)):
        return [normalize(v) for v in value]
    if isinstance(value,float):
        if not math.isfinite(value):
            raise ValueError("non-finite number")
        if value == 0 or value.is_integer():
            return int(value)
    return value


def canonical(value) -> bytes:
    return json.dumps(normalize(value), sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def semantic_digest(events) -> str:
    h = hashlib.sha256()
    for e in events:
        normalized = {k:v for k,v in e.items() if k != "run_id"}
        if e["type"] == "run.finished":
            normalized["payload"] = {k:v for k,v in e["payload"].items() if k != "trace_hash"}
        h.update(canonical(normalized) + b"\n")
    return h.hexdigest()


class Trace:
    def __init__(self, run_id):
        self.run_id = run_id
        self.events = []
        self.tick = 0

    def emit(self, kind, **payload):
        self.events.append({"schema_version":1,"run_id":self.run_id,"seq":len(self.events)+1,
                            "tick":self.tick,"type":kind,"payload":deepcopy(payload)})
