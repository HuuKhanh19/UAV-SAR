"""Explicit SAR adaptations of MOSA and sampled Pareto ILS.

MOSA uses fixed-weight Tchebycheff annealing chains, not AMOSA's dominance
acceptance rule. PILS samples finite neighborhoods; it does not certify local
optimality of a complete neighborhood. Every attempted plan consumes budget.
"""
import csv
import time

import numpy as np
from pymoo.indicators.hv import HV

from .io import write_json
from .route_operators import MOVES, encode_routes, integer, route_move


def dominates(a, b):
    return bool(np.all(a <= b) and np.any(a < b))


def signature(routes):
    return tuple(tuple(route) for route in routes)


class RouteLedger:
    """Exact unique objective archive of every evaluated feasible routing plan."""
    def __init__(self, instance):
        self.instance = instance
        self.archive_f = np.empty((0, 2))
        self.plans = []
        self.evaluations = self.feasible = self.position_checks = 0
        self.moves = {move: 0 for move in MOVES}

    def evaluate(self, routes, meta=None):
        evaluation = self.instance.evaluate_routes(routes)
        self.evaluations += 1
        if meta:
            self.position_checks += meta["position_checks"]
            self.moves[meta["operator"]] += 1
        if not evaluation["feasible"] or any(r["return_time_s"] > self.instance.deadline + 1e-9
                or r["energy_wh"] > self.instance.budget[r["uav"]] + 1e-9 for r in evaluation["routes"]):
            return None
        self.feasible += 1
        f = np.asarray(self.instance.objectives(evaluation))
        # Reject dominated/equal objectives, preserving one representative.
        if not len(self.archive_f) or not np.any(np.all(self.archive_f <= f, axis=1)):
            keep = ~np.all(f <= self.archive_f, axis=1)
            self.plans = [plan for plan, retained in zip(self.plans, keep) if retained]
            self.plans.append([list(route) for route in routes])
            self.archive_f = np.vstack([self.archive_f[keep], f])
        return f

    @property
    def archive_x(self):
        return np.array([encode_routes(self.instance, routes) for routes in self.plans])


def run_direct(instance, name, seed, settings, folder):
    from .optimize import initial_population, write_front
    folder.mkdir(parents=True, exist_ok=False)
    size, generations = settings["population"], settings["generations"]
    if size < 4 or generations < 1 or settings["log_every"] < 1:
        raise ValueError("population >= 4, generations >= 1 and log_every >= 1 required")
    options = {"directions": 21, "temperature_start": .02, "temperature_end": .0002,
               "neighbors_per_operator": 8, "perturbation_moves": 5}
    options.update(settings.get("local_search", {}))
    if (options["directions"] < 2 or options["temperature_start"] <= 0 or options["temperature_end"] <= 0
            or options["neighbors_per_operator"] < 1 or options["perturbation_moves"] < 1):
        raise ValueError("Invalid local-search settings")
    budget = size * generations
    rng, ledger = np.random.default_rng(seed), RouteLedger(instance)
    metric = HV(ref_point=np.array(settings["hv_reference"]))
    history, accepted, improving, perturbations = [], 0, 0, 0
    start = time.perf_counter()

    def log():
        if ledger.evaluations % size:
            return
        generation = ledger.evaluations // size
        row = {"generation": generation, "evaluations": ledger.evaluations,
               "elapsed_s": time.perf_counter() - start, "archive_size": len(ledger.archive_f),
               "hypervolume": float(metric(ledger.archive_f)),
               "best_p_detect": float((1 - ledger.archive_f[:, 0].min()) * instance.probability_upper_bound),
               "candidate_feasible_fraction": ledger.feasible / ledger.evaluations,
               "insertion_position_checks": ledger.position_checks}
        history.append(row)
        if generation == 1 or generation % settings["log_every"] == 0 or ledger.evaluations == budget:
            print(f"[{name.upper()} seed={seed}] eval={ledger.evaluations}/{budget} "
                  f"Pmax={row['best_p_detect']:.6f} HV={row['hypervolume']:.6f}", flush=True)

    initial, initial_f = [], []
    for x in initial_population(instance, size, seed):
        routes, _ = instance.decode(x)
        initial.append(routes)
        initial_f.append(ledger.evaluate(routes))
    log()
    if name == "mosa":
        w = np.linspace(0, 1, options["directions"])
        weights = np.column_stack([w, 1 - w])
        initial_f = np.array(initial_f)
        best = [int(np.argmin(np.max(weight * initial_f, axis=1))) for weight in weights]
        current, values = [initial[index] for index in best], initial_f[best].copy()
        while ledger.evaluations < budget:
            chain = (ledger.evaluations - size) % len(weights)
            child, meta = route_move(instance, current[chain], rng)
            f = ledger.evaluate(child, meta)
            fraction = (ledger.evaluations - size) / max(budget - size, 1)
            temperature = options["temperature_start"] * (options["temperature_end"] / options["temperature_start"]) ** fraction
            if f is not None:
                delta = float(np.max(weights[chain] * f) - np.max(weights[chain] * values[chain]))
                if delta <= 0 or rng.random() < np.exp(-delta / temperature):
                    current[chain], values[chain] = child, f
                    accepted += 1
                    improving += int(delta < 0)
            log()
    elif name == "pils":
        explored = set()
        index = integer(rng, len(ledger.plans))
        current, value = ledger.plans[index], ledger.archive_f[index]
        # These state reads reuse already-evaluated plans; no proposal is scored free.
        order, operator_index, attempts = rng.permutation(len(MOVES)), 0, 0
        while ledger.evaluations < budget:
            if operator_index == len(MOVES):
                explored.add(signature(current))
                unvisited = [i for i, plan in enumerate(ledger.plans) if signature(plan) not in explored]
                if unvisited:
                    index = unvisited[integer(rng, len(unvisited))]
                    current, value = ledger.plans[index], ledger.archive_f[index]
                else:
                    index = integer(rng, len(ledger.plans))
                    current, value = ledger.plans[index], ledger.archive_f[index]
                    perturbations += 1
                    for _ in range(options["perturbation_moves"]):
                        if ledger.evaluations >= budget:
                            break
                        child, meta = route_move(instance, current, rng, cheapest=False)
                        f = ledger.evaluate(child, meta)
                        if f is not None:
                            current, value = child, f
                            accepted += 1
                        log()
                order, operator_index, attempts = rng.permutation(len(MOVES)), 0, 0
                if ledger.evaluations >= budget:
                    break
            child, meta = route_move(instance, current, rng, operator=MOVES[int(order[operator_index])])
            f = ledger.evaluate(child, meta)
            attempts += 1
            if f is not None and dominates(f, value):
                current, value = child, f
                accepted += 1
                improving += 1
                order, operator_index, attempts = rng.permutation(len(MOVES)), 0, 0
            elif attempts == options["neighbors_per_operator"]:
                operator_index += 1
                attempts = 0
            log()
    else:
        raise ValueError(name)
    search_elapsed = time.perf_counter() - start
    if ledger.evaluations != budget:
        raise AssertionError("Evaluation budget mismatch")
    order = np.argsort(ledger.archive_f[:, 0])
    ledger.archive_f = ledger.archive_f[order]
    ledger.plans = [ledger.plans[int(index)] for index in order]
    with (folder / "history.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    write_front(ledger, folder, f"{name.upper()} seed={seed}")
    np.savez_compressed(folder / "final_population.npz", X=ledger.archive_x, F=ledger.archive_f)
    stats = {"algorithm": name, "seed": seed, "status": "completed", "evaluations": ledger.evaluations,
             "elapsed_s": time.perf_counter() - start, "search_elapsed_s": search_elapsed,
             "archive_size": len(ledger.archive_f), "hypervolume": float(metric(ledger.archive_f)),
             "best_p_detect": float((1 - ledger.archive_f[:, 0].min()) * instance.probability_upper_bound),
             "decoded_feasible_fraction": None, "candidate_feasible_fraction": ledger.feasible / ledger.evaluations,
             "repair_fraction": 0., "settings": settings, "local_search_actual": options,
             "insertion_position_checks": ledger.position_checks, "accepted_moves": accepted,
             "improving_moves": improving, "perturbations": perturbations,
             "move_attempts": ledger.moves,
             "implementation": "MOSA-TCH (21 annealing chains, fixed ideal 0)" if name == "mosa" else "Sampled Pareto ILS (archive, 5 neighborhoods, perturbation)",
             "final_population_semantics": "archive snapshot, not an EA population"}
    write_json(folder / "summary.json", stats)
    return stats
