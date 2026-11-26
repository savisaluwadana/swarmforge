from heapq import heappush, heappop
from swarmforge.domain.model import Grid, Point, neighbors, xy


def distance(a: Point,b: Point) -> int:
    return abs(a[0]-b[0])+abs(a[1]-b[1])


def plan(grid: Grid, start: Point, goal: Point, horizon=32, reservations=frozenset()) -> list[Point]:
    """Deterministic bounded space-time A*. Return best partial path if goal out of horizon."""
    if not grid.free(start) or not grid.free(goal):
        return []
    root = (start,0)
    heap = [(distance(start,goal),distance(start,goal),0,root)]
    parent = {root:None}
    seq = 0
    best = root
    while heap:
        _,_,_,state = heappop(heap)
        p,t = state
        if (distance(p,goal),t,p) < (distance(best[0],goal),best[1],best[0]):
            best = state
        if p == goal:
            best = state
            break
        if t >= horizon:
            continue
        for q in neighbors(p)+[p]:
            nxt = (q,t+1)
            if not grid.free(q) or nxt in reservations or nxt in parent:
                continue
            parent[nxt] = state
            seq += 1
            h = distance(q,goal)
            heappush(heap,(t+1+h,h,seq,nxt))
    result = []
    while parent[best] is not None:
        result.append(best[0])
        best = parent[best]
    return list(reversed(result))


def resolve(grid: Grid, positions: dict[str,Point], proposals: dict[str,Point]):
    """Common conservative physical gate: never enter a cell occupied at tick start."""
    occupied = set(positions.values())
    accepted, rejected, claimed = {}, {}, set()
    for rid,q in sorted(proposals.items()):
        p = positions[rid]
        if q == p:
            continue
        if not grid.free(q) or distance(p,q) != 1:
            rejected[rid] = "invalid_step"
        elif q in occupied:
            rejected[rid] = "occupied"
        elif q in claimed:
            rejected[rid] = "vertex_conflict"
        else:
            accepted[rid] = q
            claimed.add(q)
    return accepted,rejected
