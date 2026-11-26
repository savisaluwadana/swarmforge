from __future__ import annotations

from dataclasses import dataclass
from collections import deque
import math
import re

Point = tuple[int, int]
ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DIRECTIONS = ((1, 0), (0, 1), (-1, 0), (0, -1))


class InvalidScenario(ValueError):
    """Invalid or unsupported scenario configuration."""


def require(ok: bool, path: str, message: str) -> None:
    if not ok:
        raise InvalidScenario(f"{path}: {message}")


def integer(value, lo: int, hi: int, path: str) -> int:
    require(type(value) is int and lo <= value <= hi, path, f"integer {lo}..{hi} required")
    return value


def ident(value, path: str) -> str:
    require(isinstance(value, str) and bool(ID.fullmatch(value)), path, "invalid identifier")
    return value


def probability(value, path: str) -> float:
    require(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1, path, "probability 0..1 required")
    return float(value)


def keys(value, required, optional=(), path="/"):
    require(isinstance(value, dict), path, "object required")
    require(set(required) <= value.keys() <= set(required) | set(optional), path, "missing or unknown fields")
    return value


def array(value, lo, hi, path):
    require(isinstance(value, list) and lo <= len(value) <= hi, path, f"array length {lo}..{hi} required")
    return value


def point(value, width, height, path) -> Point:
    keys(value, ("x", "y"), path=path)
    return integer(value["x"], 0, width-1, path+"/x"), integer(value["y"], 0, height-1, path+"/y")


def xy(p: Point) -> dict:
    return {"x": p[0], "y": p[1]}


def neighbors(p):
    return [(p[0]+dx, p[1]+dy) for dx, dy in DIRECTIONS]


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    obstacles: frozenset[Point]

    def free(self, p: Point) -> bool:
        return 0 <= p[0] < self.width and 0 <= p[1] < self.height and p not in self.obstacles

    def reachable(self, start: Point, end: Point) -> bool:
        todo = deque([start])
        seen = {start}
        while todo:
            p = todo.popleft()
            if p == end:
                return True
            for q in neighbors(p):
                if self.free(q) and q not in seen:
                    seen.add(q)
                    todo.append(q)
        return False


@dataclass(frozen=True)
class TaskSpec:
    id: str
    pickup: Point
    dropoff: Point
    release_tick: int
    priority: int
    due_tick: int | None


@dataclass
class Task:
    spec: TaskSpec
    released: bool = False
    status: str = "pending"
    holder: str | None = None
    epoch: int = 0
    expires_tick: int | None = None
    completed_tick: int | None = None


@dataclass
class Robot:
    id: str
    position: Point
    zone: str
    mode: str = "idle"
    task_id: str | None = None
    epoch: int = 0
    expires_tick: int = 0
    carrying: bool = False
    pickup: Point | None = None
    dropoff: Point | None = None
    waiting_ticks: int = 0


def validate_config(config: dict) -> Grid:
    """Validate v1 scenario syntax and core semantic constraints without mutating it."""
    c = keys(config, ("schema_version","width","height","obstacles","robots","zones","tasks","network","faults","duration_ticks","tick_ms","scope_lease_ticks"))
    integer(c["schema_version"],1,1,"/schema_version")
    w = integer(c["width"],2,100,"/width")
    h = integer(c["height"],2,100,"/height")
    duration = integer(c["duration_ticks"],1,10000,"/duration_ticks")
    integer(c["tick_ms"],100,60000,"/tick_ms")
    integer(c["scope_lease_ticks"],1,10000,"/scope_lease_ticks")
    obstacles = [point(p,w,h,"/obstacles") for p in array(c["obstacles"],0,10000,"/obstacles")]
    require(len(set(obstacles)) == len(obstacles),"/obstacles","duplicate obstacle")
    grid = Grid(w,h,frozenset(obstacles))
    robots = {}
    starts = set()
    for r in array(c["robots"],1,100,"/robots"):
        keys(r,("id","start","zone"),("capabilities",),"/robots")
        rid = ident(r["id"],"/robots/id")
        p = point(r["start"],w,h,"/robots/start")
        require(rid != "C" and rid not in robots,"/robots/id","duplicate or reserved ID")
        require(grid.free(p) and p not in starts,"/robots/start","blocked or duplicate start")
        ident(r["zone"],"/robots/zone")
        for cap in array(r.get("capabilities",[]),0,16,"/robots/capabilities"):
            ident(cap,"/robots/capabilities")
        robots[rid] = r
        starts.add(p)
    zones = {}
    covered = set()
    for z in array(c["zones"],1,100,"/zones"):
        keys(z,("id","min_x","max_x","min_y","max_y","leader"),path="/zones")
        zid = ident(z["id"],"/zones/id")
        require(zid not in zones,"/zones/id","duplicate zone")
        x0 = integer(z["min_x"],0,w-1,"/zones/min_x")
        x1 = integer(z["max_x"],x0,w-1,"/zones/max_x")
        y0 = integer(z["min_y"],0,h-1,"/zones/min_y")
        y1 = integer(z["max_y"],y0,h-1,"/zones/max_y")
        cells = {(x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)}
        require(not cells & covered,"/zones","overlapping zones")
        leader = ident(z["leader"],"/zones/leader")
        require(leader in robots and robots[leader]["zone"] == zid,"/zones/leader","leader must belong to zone")
        zones[zid] = cells
        covered |= cells
    for r in robots.values():
        require(r["zone"] in zones and point(r["start"],w,h,"/robots/start") in zones[r["zone"]],"/robots/zone","start outside declared zone")
    tids = set()
    for t in array(c["tasks"],0,1000,"/tasks"):
        keys(t,("id","pickup","dropoff","release_tick","priority"),("due_tick",),"/tasks")
        tid = ident(t["id"],"/tasks/id")
        require(tid not in tids,"/tasks/id","duplicate task/package ID")
        tids.add(tid)
        pickup = point(t["pickup"],w,h,"/tasks/pickup")
        dropoff = point(t["dropoff"],w,h,"/tasks/dropoff")
        require(grid.free(pickup) and grid.free(dropoff) and grid.reachable(pickup,dropoff),"/tasks","unreachable or blocked endpoints")
        release = integer(t["release_tick"],0,duration-1,"/tasks/release_tick")
        integer(t["priority"],0,9,"/tasks/priority")
        if t.get("due_tick") is not None:
            integer(t["due_tick"],release,10000,"/tasks/due_tick")
    nodes = set(robots) | {"C"}
    network = keys(c["network"],("default_delay_ticks","default_drop_rate","links"),path="/network")
    integer(network["default_delay_ticks"],1,100,"/network/default_delay_ticks")
    probability(network["default_drop_rate"],"/network/default_drop_rate")
    links = set()
    def pair(link, path):
        a,b = ident(link["from"],path),ident(link["to"],path)
        require(a in nodes and b in nodes and a != b,path,"unknown or self link")
        return a,b
    for link in array(network["links"],0,10200,"/network/links"):
        keys(link,("from","to"),("delay_ticks","drop_rate","enabled"),"/network/links")
        p = pair(link,"/network/links")
        require(p not in links,"/network/links","duplicate link")
        links.add(p)
        if "delay_ticks" in link:
            integer(link["delay_ticks"],1,100,"/network/links/delay_ticks")
        if "drop_rate" in link:
            probability(link["drop_rate"],"/network/links/drop_rate")
        if "enabled" in link:
            require(type(link["enabled"]) is bool,"/network/links/enabled","boolean required")
    seen_faults = []
    for f in array(c["faults"],0,100,"/faults"):
        require(isinstance(f,dict) and isinstance(f.get("type"),str),"/faults","fault object required")
        kind = f["type"]
        fields = {"controller_outage":(), "robot_crash":("robot_id",), "partition":("links",),
                  "latency":("links","extra_delay_ticks"),"packet_loss":("links","drop_rate")}
        require(kind in fields,"/faults/type","unknown fault")
        keys(f,("type","start_tick","end_tick")+fields[kind],path="/faults")
        start = integer(f["start_tick"],0,duration-1,"/faults/start_tick")
        end = duration if f["end_tick"] is None else integer(f["end_tick"],start+1,duration,"/faults/end_tick")
        if kind == "robot_crash":
            rid = ident(f["robot_id"],"/faults/robot_id")
            require(rid in robots and f["end_tick"] is None,"/faults","crash must target robot and be permanent")
            targets = {rid}
        elif kind == "controller_outage":
            targets = {("C",n) for n in robots} | {(n,"C") for n in robots}
        else:
            pairs = [pair(keys(l,("from","to"),path="/faults/links"),"/faults/links") for l in array(f["links"],1,10200,"/faults/links")]
            require(len(set(pairs)) == len(pairs),"/faults/links","duplicate fault target")
            targets = set(pairs)
        if kind == "latency":
            integer(f["extra_delay_ticks"],1,100,"/faults/extra_delay_ticks")
        if kind == "packet_loss":
            probability(f["drop_rate"],"/faults/drop_rate")
        category = "blocked" if kind in ("controller_outage","partition") else kind
        for prev_cat,a,b,prev_targets in seen_faults:
            require(not(category == prev_cat and start < b and a < end and targets & prev_targets),"/faults","overlapping effects")
        seen_faults.append((category,start,end,targets))
    return grid
