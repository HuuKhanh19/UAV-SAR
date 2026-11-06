"""Routing decisions shared by non-EA controls and EA operator ablations."""
import numpy as np
from pymoo.core.crossover import Crossover
from pymoo.core.mutation import Mutation
from pymoo.operators.mutation.pm import PM


MOVES = ("insert", "delete", "relocate", "swap", "reverse")


def integer(rng, high):
    return int(rng.integers(high) if hasattr(rng, "integers") else rng.randint(high))


def encode_routes(instance, routes):
    """Canonical 3N keys. Exact round trip for feasible, unique routing plans.

    For infeasible proposals the unchanged shared decoder supplies repair.
    Canonicalization is a deliberate part of the operator and has its own control.
    """
    if len(routes) != instance.k:
        raise ValueError("Wrong number of routes")
    cells = [j for route in routes for j in route]
    if len(cells) != len(set(cells)) or any(j < 0 or j >= instance.n for j in cells):
        raise ValueError("Routes must contain distinct valid cell IDs")
    x = np.full(3 * instance.n, .75)
    order = 0
    for k, route in enumerate(routes):
        for j in route:
            x[j] = .25
            x[instance.n + j] = (k + .5) / instance.k
            x[2 * instance.n + j] = (order + .5) / max(len(cells), 1)
            order += 1
    return x


def insertion_position(instance, route, k, cell, rng, cheapest=True):
    if not cheapest:
        return integer(rng, len(route) + 1), 0
    if not route:
        return 0, 1
    delta = np.empty(len(route) + 1)
    delta[0] = instance.base_distance[k, cell] + instance.distance[cell, route[0]] - instance.base_distance[k, route[0]]
    delta[-1] = instance.distance[route[-1], cell] + instance.base_distance[k, cell] - instance.base_distance[k, route[-1]]
    if len(route) > 1:
        delta[1:-1] = (instance.distance[np.array(route[:-1]), cell]
                       + instance.distance[cell, np.array(route[1:])]
                       - instance.distance[np.array(route[:-1]), np.array(route[1:])])
    return int(np.argmin(delta)), len(delta)


def route_move(instance, routes, rng, operator=None, cheapest=True):
    """One proposal, no hidden fitness evaluations or feasibility retries.

    Cheapest insertion scans positions on the already chosen UAV; the cell and
    UAV are sampled uniformly. Every position scan is counted as internal work.
    Resource feasibility is decided by the caller's counted evaluator/decoder.
    """
    child = [list(route) for route in routes]
    visited = [(k, p, j) for k, route in enumerate(child) for p, j in enumerate(route)]
    available = np.setdiff1d(np.arange(instance.n), [j for _, _, j in visited], assume_unique=True)
    applicable = (["insert"] if len(available) else []) + (["delete", "relocate"] if visited else [])
    if len(visited) >= 2:
        applicable.append("swap")
    if any(len(route) >= 3 for route in child):
        applicable.append("reverse")
    if operator is None:
        operator = applicable[integer(rng, len(applicable))]
    if operator not in MOVES:
        raise ValueError(operator)
    if operator not in applicable:
        return child, {"operator": operator, "position_checks": 0, "applicable": False}
    checks = 0
    if operator == "insert":
        cell, k = int(available[integer(rng, len(available))]), integer(rng, instance.k)
        position, checks = insertion_position(instance, child[k], k, cell, rng, cheapest)
        child[k].insert(position, cell)
    elif operator == "delete":
        k, position, _ = visited[integer(rng, len(visited))]
        child[k].pop(position)
    elif operator == "relocate":
        old_k, position, cell = visited[integer(rng, len(visited))]
        child[old_k].pop(position)
        k = integer(rng, instance.k)
        position, checks = insertion_position(instance, child[k], k, cell, rng, cheapest)
        child[k].insert(position, cell)
    elif operator == "swap":
        a, b = rng.choice(len(visited), 2, replace=False)
        k1, p1, j1 = visited[int(a)]
        k2, p2, j2 = visited[int(b)]
        child[k1][p1], child[k2][p2] = j2, j1
    else:
        eligible = [k for k, route in enumerate(child) if len(route) >= 3]
        k = eligible[integer(rng, len(eligible))]
        a, b = sorted(rng.choice(len(child[k]), 2, replace=False).tolist())
        child[k][a:b + 1] = child[k][a:b + 1][::-1]
    return child, {"operator": operator, "position_checks": checks, "applicable": True}


def route_crossover(instance, parent_a, parent_b, rng):
    """Preserve random route prefixes from A, append unused cells in B's order."""
    child = [route[:integer(rng, len(route) + 1)] for route in parent_a]
    used = {j for route in child for j in route}
    for k, route in enumerate(parent_b):
        for j in route:
            if j not in used:
                child[k].append(j)
                used.add(j)
    return child


class RouteMutation(Mutation):
    def __init__(self):
        super().__init__(prob=1.)
        self.position_checks = self.proposals = 0

    def _do(self, problem, x, **kwargs):
        children = []
        for chromosome in x:
            routes, _ = problem.instance.decode(chromosome)
            child, meta = route_move(problem.instance, routes, np.random)
            self.position_checks += meta["position_checks"]
            self.proposals += 1
            children.append(encode_routes(problem.instance, child))
        return np.array(children)


class CanonicalPM(PM):
    """Control for projecting repaired random keys, without route-aware moves."""
    def _do(self, problem, x, **kwargs):
        children = super()._do(problem, x, **kwargs)
        return np.array([encode_routes(problem.instance, problem.instance.decode(child)[0]) for child in children])


class RouteCrossover(Crossover):
    def __init__(self):
        super().__init__(2, 2, prob=.9)

    def _do(self, problem, x, **kwargs):
        children = np.empty_like(x)
        for mating in range(x.shape[1]):
            a, _ = problem.instance.decode(x[0, mating])
            b, _ = problem.instance.decode(x[1, mating])
            children[0, mating] = encode_routes(problem.instance, route_crossover(problem.instance, a, b, np.random))
            children[1, mating] = encode_routes(problem.instance, route_crossover(problem.instance, b, a, np.random))
        return children
