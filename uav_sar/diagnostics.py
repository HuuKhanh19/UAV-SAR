"""Reproducible diagnostics and offline probes for a frozen SAR baseline run.

Probes are evidence about search weaknesses, not new budget-matched optimizers.
The baseline decoder, objectives, archives and input folders are never modified.
"""
import csv
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pymoo.core.population import Population
from pymoo.indicators.hv import HV
from pymoo.operators.mutation.pm import PM

from .io import read_json, sha256, write_json
from .optimize import initial_population
from .problem import Instance, SearchProblem, nondominated_indices


def route_key(routes):
    return tuple(tuple(route) for route in routes)


def distance_with_base(instance, k):
    d = np.zeros((instance.n + 1, instance.n + 1))
    d[:-1, :-1] = instance.distance
    d[-1, :-1] = d[:-1, -1] = instance.base_distance[k]
    return d


def two_opt(instance, routes):
    """Best-improvement 2-opt to a local optimum; preserve each UAV's cell set."""
    routes = [list(route) for route in routes]
    moves = 0
    for k, route in enumerate(routes):
        if len(route) < 3:
            continue
        d = distance_with_base(instance, k)
        left, right = np.triu_indices(len(route), 1)
        while True:
            path = np.array([instance.n, *route, instance.n])
            delta = (d[path[left], path[right + 1]] + d[path[left + 1], path[right + 2]]
                     - d[path[left], path[left + 1]] - d[path[right + 1], path[right + 2]])
            best = int(np.argmin(delta))
            if delta[best] >= -1e-9:
                break
            a, b = int(left[best]), int(right[best])
            route[a:b + 1] = route[a:b + 1][::-1]
            moves += 1
    return routes, moves


def greedy_insert(instance, routes=None, energy_cap=None):
    """Insert the feasible cell/UAV with largest marginal probability per Wh.

    Check every insertion position, individual batteries/deadlines and total cap.
    Existing observations stay on their original UAV. No optimality claim.
    """
    routes = [list(route) for route in routes] if routes is not None else [[] for _ in range(instance.k)]
    cap = float(instance.budget.sum()) if energy_cap is None else float(energy_cap)
    evaluation = instance.evaluate_routes(routes)
    if not np.isfinite(cap) or cap < 0 or not evaluation["feasible"] or evaluation["energy_wh"] > cap + 1e-9:
        raise ValueError("Greedy seed must be feasible within a finite nonnegative energy cap")
    distances = [distance_with_base(instance, k) for k in range(instance.k)]
    used = {j for route in routes for j in route}
    candidate_insertions = 0
    while len(used) < instance.n:
        available = np.array([j for j in range(instance.n) if j not in used])
        best = None
        for k, route in enumerate(routes):
            d = distances[k]
            path = np.array([instance.n, *route, instance.n])
            delta = (d[path[:-1, None], available] + d[available, path[1:, None]]
                     - d[path[:-1], path[1:]][:, None])
            candidate_insertions += int(delta.size)
            positions = np.argmin(delta, axis=0)
            extra_distance = np.maximum(0., delta[positions, np.arange(len(available))])
            extra_time = extra_distance / instance.speed[k] + instance.tau
            extra_energy = (extra_distance / instance.speed[k] * instance.fly_w[k]
                            + instance.obs_w[k] * instance.tau) / 3600
            gain = instance.pi[available] * instance.q[k, available]
            detail = evaluation["routes"][k]
            feasible = ((detail["return_time_s"] + extra_time <= instance.deadline + 1e-9)
                        & (detail["energy_wh"] + extra_energy <= instance.budget[k] + 1e-9)
                        & (evaluation["energy_wh"] + extra_energy <= cap + 1e-9) & (gain > 0))
            scores = np.where(feasible, gain / extra_energy, -np.inf)
            choice = int(np.argmax(scores))
            if np.isfinite(scores[choice]) and (best is None or scores[choice] > best[0]):
                best = (float(scores[choice]), k, int(available[choice]), int(positions[choice]))
        if best is None:
            break
        _, k, cell, position = best
        routes[k].insert(position, cell)
        used.add(cell)
        evaluation = instance.evaluate_routes(routes)
        if not evaluation["feasible"] or evaluation["energy_wh"] > cap + 1e-8:
            raise AssertionError("Insertion probe exceeded a resource limit")
    return routes, candidate_insertions


def population_metrics(instance, x):
    plans, assignments, values, selected, rejected, accepted = [], [], [], [], [], []
    for chromosome in x:
        routes, skipped = instance.decode(chromosome)
        evaluation = instance.evaluate_routes(routes)
        plans.append(route_key(routes))
        assignments.append(tuple(tuple(sorted(route)) for route in routes))
        values.append(instance.objectives(evaluation))
        selected.append(int(np.sum(chromosome[:instance.n] < .5)))
        rejected.append(skipped)
        accepted.append(evaluation["n_observations"])
    return {
        "size": len(x), "unique_genotypes": len(np.unique(x, axis=0)),
        "unique_routes": len(set(plans)), "unique_assignments": len(set(assignments)),
        "unique_objectives_12dp": len(np.unique(np.round(values, 12), axis=0)),
        "mean_selected": float(np.mean(selected)), "mean_rejected": float(np.mean(rejected)),
        "mean_observations": float(np.mean(accepted)),
        "rejected_selected_fraction": sum(rejected) / max(sum(selected), 1),
    }, np.asarray(values)


def mutation_probe(instance, x, eta, repeats, seed):
    """Isolated PM on saved parents; not the actual SBX+PM offspring trajectory."""
    if repeats < 1:
        raise ValueError("mutation repeats must be positive")
    parents = np.tile(x, (repeats, 1))
    state = np.random.get_state()
    try:
        np.random.seed(seed)
        offspring = PM(prob=1., prob_var=1 / (3 * instance.n), eta=eta).do(
            SearchProblem(instance), Population.new(X=parents.copy())).get("X")
    finally:
        np.random.set_state(state)
    changed_keys = np.count_nonzero(parents != offspring, axis=1)
    parent_results = []
    for chromosome in x:
        routes, _ = instance.decode(chromosome)
        parent_results.append((route_key(routes), np.array(instance.objectives(instance.evaluate_routes(routes)))))
    changed_plan = changed_objective = dominating = 0
    for index, child in enumerate(offspring):
        routes, _ = instance.decode(child)
        f = np.array(instance.objectives(instance.evaluate_routes(routes)))
        key, parent_f = parent_results[index % len(x)]
        changed_plan += int(route_key(routes) != key)
        changed_objective += int(not np.allclose(f, parent_f, rtol=0, atol=1e-12))
        dominating += int(np.all(f <= parent_f + 1e-12) and np.any(f < parent_f - 1e-12))
    trials = len(parents)
    changed_genotype = int(np.count_nonzero(changed_keys))
    return {"trials": trials, "mean_changed_keys": float(changed_keys.mean()),
            "genotype_changed_fraction": changed_genotype / trials,
            "plan_changed_fraction": changed_plan / trials,
            "objective_changed_fraction": changed_objective / trials,
            "dominates_parent_fraction": dominating / trials,
            "plan_unchanged_given_genotype_changed": (changed_genotype - changed_plan) / changed_genotype
            if changed_genotype else None}


def save_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def random_control(instance, seed, settings, evaluations, folder):
    """Independent stratified random plans; same initial population and budget."""
    folder.mkdir(parents=True, exist_ok=False)
    rng = np.random.default_rng(seed)
    problem = SearchProblem(instance)
    size = settings["population"]
    metric = HV(ref_point=np.array(settings["hv_reference"]))
    history = []
    start = time.perf_counter()
    while problem.evaluations < evaluations:
        batch_seed = seed if not history else int(rng.integers(0, 2**32 - 1))
        batch = initial_population(instance, size, batch_seed)[:evaluations - problem.evaluations]
        problem.evaluate(batch)
        history.append({"evaluations": problem.evaluations, "hypervolume": float(metric(problem.archive_f)),
                        "best_p_detect": float((1 - problem.archive_f[:, 0].min()) * instance.probability_upper_bound)})
    np.savez_compressed(folder / "archive.npz", X=problem.archive_x, F=problem.archive_f)
    save_csv(folder / "history.csv", history)
    summary = {"seed": seed, "evaluations": problem.evaluations, "elapsed_s": time.perf_counter() - start,
               "hypervolume": history[-1]["hypervolume"], "best_p_detect": history[-1]["best_p_detect"],
               "sampling": "independent batches of initial_population; density stratified from zero to one"}
    write_json(folder / "summary.json", summary)
    return summary, problem.archive_f, history


def load_runs(root):
    records = []
    for path in sorted(Path(root).glob("*/seed_*/summary.json")):
        summary = read_json(path)
        if summary["status"] != "completed":
            continue
        with np.load(path.parent / "archive.npz") as archive:
            x, f = archive["X"].copy(), archive["F"].copy()
        history = np.atleast_1d(np.genfromtxt(path.parent / "history.csv", delimiter=",", names=True))
        records.append((path.parent, summary, x, f, history))
    if not records:
        raise ValueError("No completed baseline runs found")
    return records


def _stats(rows, keys):
    return {key: {"mean": float(np.mean([r[key] for r in rows])),
                  "std": float(np.std([r[key] for r in rows], ddof=1)) if len(rows) > 1 else 0.}
            for key in keys}


def diagnose(results, output, extended_results=None, mutation_repeats=4, probe_seed=2026, include_random=True):
    root, output = Path(results), Path(output)
    if mutation_repeats < 1 or probe_seed < 0:
        raise ValueError("Require positive mutation repeats and a nonnegative probe seed")
    instance = Instance.load(root / "instance.json")
    records = load_runs(root)
    extended = {}
    if extended_results is not None:
        extended_root = Path(extended_results)
        if read_json(extended_root / "instance.json") != read_json(root / "instance.json"):
            raise ValueError("Budget comparison requires the exact same frozen instance")
        extended = {(s["algorithm"], s["seed"]): (s, f, h)
                    for _, s, _, f, h in load_runs(extended_root)}
        if set(extended) != {(s["algorithm"], s["seed"]) for _, s, _, _, _ in records}:
            raise ValueError("Extended runs must complete the same algorithm/seed pairs")
    settings = records[0][1]["settings"]
    for _, summary, _, _, _ in records:
        if summary["evaluations"] != records[0][1]["evaluations"] or summary["settings"] != settings:
            raise ValueError("Diagnosis expects a baseline cohort with the same settings and budget")
    output.mkdir(parents=True, exist_ok=False)
    hv = HV(ref_point=np.array(settings["hv_reference"]))
    run_rows, route_rows, probes, population_rows, mutation_rows, budget_rows, fronts, curves = [], [], [], [], [], [], {}, []
    input_hashes = {str(root / "instance.json"): sha256(root / "instance.json")}
    for folder, summary, archive_x, archive_f, history in records:
        algorithm, seed = summary["algorithm"], summary["seed"]
        identity = {"algorithm": algorithm, "seed": seed}
        for name in ("summary.json", "archive.npz", "history.csv", "final_population.npz"):
            path = folder / name
            input_hashes[str(path)] = sha256(path)
        with np.load(folder / "final_population.npz") as population:
            final_x, final_f = population["X"].copy(), population["F"].copy()
        for stage, x in (("initial", initial_population(instance, settings["population"], seed)), ("final", final_x)):
            metrics, f = population_metrics(instance, x)
            population_rows.append({**identity, "stage": stage, **metrics})
            if stage == "final" and not np.allclose(f, final_f, rtol=0, atol=1e-10):
                raise AssertionError("Saved population does not match the frozen evaluator")
        mutation_rows.append({**identity, **mutation_probe(instance, final_x, settings["mutation_eta"],
                              mutation_repeats, (probe_seed + seed + (0 if algorithm == "nsga2" else 10000)) % 2**32)})
        optimized_f, optimized_routes = [], []
        for solution_id, (x, f) in enumerate(zip(archive_x, archive_f)):
            routes, rejected = instance.decode(x)
            before = instance.evaluate_routes(routes)
            if not before["feasible"] or not np.allclose(instance.objectives(before), f, rtol=0, atol=1e-10):
                raise AssertionError("Saved archive does not match the frozen evaluator")
            improved, moves = two_opt(instance, routes)
            after = instance.evaluate_routes(improved)
            if (not after["feasible"] or not np.isclose(before["p_detect"], after["p_detect"], rtol=0, atol=1e-12)
                    or after["energy_wh"] > before["energy_wh"] + 1e-9):
                raise AssertionError("2-opt changed assignment/probability or increased energy")
            optimized_routes.append(improved)
            optimized_f.append(instance.objectives(after))
            for detail in before["routes"]:
                k, cells = detail["uav"], detail["cells"]
                covered = float(instance.pi[cells].sum())
                observation_energy = len(cells) * instance.tau * instance.obs_w[k] / 3600
                route_rows.append({**identity, "solution_id": solution_id, "uav": k,
                    "n_observations": len(cells), "covered_prior": covered,
                    "p_detect": float(np.dot(instance.pi[cells], instance.q[k, cells])),
                    "distance_m": detail["distance_m"], "time_utilization": detail["return_time_s"] / instance.deadline,
                    "battery_utilization": detail["energy_wh"] / instance.budget[k],
                    "energy_wh": detail["energy_wh"], "observation_energy_wh": observation_energy,
                    "flight_energy_wh": detail["energy_wh"] - observation_energy,
                    "two_opt_energy_wh": after["routes"][k]["energy_wh"]})
        optimized_f = np.asarray(optimized_f)
        optimized_front = optimized_f[nondominated_indices(optimized_f)]
        best = int(np.argmin(archive_f[:, 0]))
        original_routes, rejected = instance.decode(archive_x[best])
        before = instance.evaluate_routes(original_routes)
        after = instance.evaluate_routes(optimized_routes[best])
        filled_routes, insertion_checks = greedy_insert(instance, optimized_routes[best], before["energy_wh"])
        filled = instance.evaluate_routes(filled_routes)
        selected = np.array([j for route in original_routes for j in route], dtype=int)
        covered = float(instance.pi[selected].sum())
        detector_upper = float(np.dot(instance.pi[selected], instance.q[:, selected].max(axis=0)))
        halfway = np.flatnonzero(history["evaluations"] <= summary["evaluations"] / 2)
        half_hv = float(history["hypervolume"][halfway[-1] if len(halfway) else 0])
        row = {**identity, "evaluations": summary["evaluations"], "archive_size": len(archive_f),
               "archive_hv": float(hv(archive_f)), "final_population_hv": float(hv(final_f)),
               "archive_best_p": before["p_detect"],
               "final_population_best_p": float((1 - final_f[:, 0].min()) * instance.probability_upper_bound),
               "last_half_hv_gain": float(history["hypervolume"][-1] - half_hv),
               "pmax_solution_id": best, "pmax_observations": before["n_observations"],
               "pmax_selected": int(np.sum(archive_x[best, :instance.n] < .5)), "pmax_rejected": rejected,
               "pmax_covered_prior": covered, "pmax_conditional_detector_recall": before["p_detect"] / covered if covered else 0.,
               "pmax_same_cells_detector_upper": detector_upper,
               "pmax_energy_wh": before["energy_wh"], "pmax_two_opt_energy_wh": after["energy_wh"],
               "pmax_two_opt_energy_saving_fraction": 1 - after["energy_wh"] / before["energy_wh"] if before["energy_wh"] else 0.,
               "two_opt_archive_hv": float(hv(optimized_front)),
               "same_energy_refill_p": filled["p_detect"], "same_energy_refill_energy_wh": filled["energy_wh"],
               "same_energy_refill_observations": filled["n_observations"]}
        run_rows.append(row)
        probes.append({**identity, "solution_id": best, "original": before, "two_opt": after,
                       "two_opt_then_refill": filled, "refill_energy_cap_wh": before["energy_wh"],
                       "refill_candidate_insertions": insertion_checks})
        fronts.setdefault(algorithm, []).append(archive_f)
        fronts.setdefault(algorithm + " + offline 2-opt", []).append(optimized_front)
        curves.append((algorithm, history["evaluations"].tolist(), history["hypervolume"].tolist()))
        if extended:
            long, long_f, long_history = extended[algorithm, seed]
            unchanged = {k: v for k, v in settings.items() if k not in ("generations", "log_every")}
            long_settings = {k: v for k, v in long["settings"].items() if k not in ("generations", "log_every")}
            prefix = long_history[long_history["evaluations"] <= summary["evaluations"]]
            matches = (len(prefix) == len(history) and all(np.allclose(prefix[key], history[key], rtol=0, atol=1e-12)
                       for key in ("evaluations", "hypervolume", "best_p_detect")))
            if unchanged != long_settings or long["evaluations"] <= summary["evaluations"] or not matches:
                raise ValueError("Extended run changed settings or failed to reproduce the baseline history prefix")
            budget_rows.append({**identity, "baseline_evaluations": summary["evaluations"],
                "extended_evaluations": long["evaluations"], "baseline_p": before["p_detect"],
                "extended_p": long["best_p_detect"], "baseline_hv": row["archive_hv"],
                "extended_hv": float(hv(long_f)), "history_prefix_reproduced": matches})
            fronts.setdefault(algorithm + " extended", []).append(long_f)
            curves.append((algorithm + " extended", long_history["evaluations"].tolist(), long_history["hypervolume"].tolist()))
        print(f"[diagnose] {algorithm} seed={seed}: 2-opt saves {100 * row['pmax_two_opt_energy_saving_fraction']:.1f}% energy; "
              f"same-energy P {before['p_detect']:.4f} -> {filled['p_detect']:.4f}", flush=True)
    random_rows = []
    if include_random:
        for seed in sorted({s["seed"] for _, s, _, _, _ in records}):
            summary, f, history = random_control(instance, seed, settings, records[0][1]["evaluations"], output / "random" / f"seed_{seed}")
            random_rows.append(summary)
            fronts.setdefault("random", []).append(f)
            curves.append(("random", [r["evaluations"] for r in history], [r["hypervolume"] for r in history]))
            print(f"[diagnose] random seed={seed}: P={summary['best_p_detect']:.4f}, HV={summary['hypervolume']:.4f}", flush=True)
    controls = []
    start = time.perf_counter()
    for fraction in np.linspace(0, 1, 21):
        cap = float(fraction * instance.budget.sum())
        routes, checks = greedy_insert(instance, energy_cap=cap)
        controls.append({"energy_cap_wh": cap, "candidate_insertions": checks, **instance.evaluate_routes(routes)})
    greedy_seconds = time.perf_counter() - start
    greedy_f = np.array([instance.objectives(result) for result in controls])
    fronts["greedy insertion (probe)"] = [greedy_f[nondominated_indices(greedy_f)]]
    attainment = []
    for label, samples in fronts.items():
        for index, f in enumerate(samples):
            seeds = ([r["seed"] for r in random_rows] if label == "random" else
                     [s["seed"] for _, s, _, _, _ in records if s["algorithm"] == label.split()[0]])
            sample_seed = seeds[index] if seeds else None
            for fraction in (.2, .4, .6, .8, 1.):
                within = f[:, 1] <= fraction + 1e-12
                p = float((1 - f[within, 0].min()) * instance.probability_upper_bound) if within.any() else None
                attainment.append({"method": label, "seed": sample_seed, "energy_cap_wh": fraction * float(instance.budget.sum()), "best_p": p})
    for name, rows in (("run_diagnostics", run_rows), ("route_diagnostics", route_rows), ("population_diagnostics", population_rows),
                       ("mutation_probes", mutation_rows), ("budget_comparison", budget_rows), ("attainment", attainment)):
        save_csv(output / f"{name}.csv", rows)
    write_json(output / "probe_routes.json", probes)
    write_json(output / "greedy_controls.json", controls)
    keys = ["archive_best_p", "archive_hv", "final_population_hv", "pmax_covered_prior",
            "pmax_same_cells_detector_upper", "pmax_two_opt_energy_saving_fraction", "two_opt_archive_hv", "same_energy_refill_p"]
    report = {"baseline": {name: _stats([r for r in run_rows if r["algorithm"] == name], keys)
                           for name in sorted({r["algorithm"] for r in run_rows})},
              "random": _stats(random_rows, ["best_p_detect", "hypervolume"]) if random_rows else None,
              "greedy_probe": {"best_p": max(r["p_detect"] for r in controls), "hv": float(hv(greedy_f)),
                               "elapsed_s": greedy_seconds, "energy_caps": len(controls),
                               "candidate_insertions": sum(r["candidate_insertions"] for r in controls)},
              "extended": {name: _stats([r for r in budget_rows if r["algorithm"] == name], ["extended_p", "extended_hv"])
                           for name in sorted({r["algorithm"] for r in budget_rows})}}
    write_json(output / "summary.json", report)
    if extended_results:
        for path in sorted(Path(extended_results).glob("*/seed_*/*")):
            if path.name in ("summary.json", "history.csv", "archive.npz"):
                input_hashes[str(path)] = sha256(path)
        input_hashes[str(Path(extended_results) / "instance.json")] = sha256(Path(extended_results) / "instance.json")
    if any(sha256(path) != checksum for path, checksum in input_hashes.items()):
        raise AssertionError("An input file changed during diagnosis")
    write_json(output / "manifest.json", {"baseline_results": str(root), "extended_results": str(extended_results) if extended_results else None,
        "input_sha256": input_hashes, "source_sha256": {str(p): sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
        "probe_seed": probe_seed, "mutation_repeats": mutation_repeats, "random_control": include_random,
        "objective_tolerance": 1e-12, "probability_label": instance.probability_label,
        "notes": ["2-opt and insertion are offline probes with extra computation, not equal-budget algorithm comparisons.",
                  "Mutation is isolated PM on saved final parents, not measured offspring during evolution.",
                  "No claim of statistical generalization from seeds on a single instance.",
                  "HV normalization and reference are shared. Existing separately pooled IGD+ values are not compared across cohorts."]})
    plot_diagnostics(output, instance, fronts, curves, mutation_rows, run_rows)
    print(f"Diagnostics: {output / 'summary.json'}", flush=True)
    return report


def plot_diagnostics(output, instance, fronts, curves, mutations, rows):
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    colors = {"nsga2": "tab:blue", "moead": "tab:orange", "random": "gray"}
    for label, samples in fronts.items():
        if "offline" in label:
            continue
        union = np.vstack(samples)
        front = union[nondominated_indices(union)]
        color = colors.get(label.split()[0], "black")
        axes[0, 0].plot(front[:, 1] * instance.budget.sum(), (1 - front[:, 0]) * instance.probability_upper_bound * 100,
                        linestyle="--" if "extended" in label else "-", color=color, label=label, linewidth=1.4)
    axes[0, 0].set(xlabel="Planned energy (Wh)", ylabel="Detection probability (%)", title="Pooled fronts; greedy is an offline probe")
    seen = set()
    for label, evaluations, hypervolume in curves:
        if any("extended" in c[0] for c in curves) and label in ("nsga2", "moead"):
            continue
        axes[0, 1].plot(evaluations, hypervolume, color=colors.get(label.split()[0], "black"), alpha=.55,
                        label=label if label not in seen else None)
        seen.add(label)
    axes[0, 1].set(xlabel="Evaluations", ylabel="Hypervolume", title="Convergence (same instance and HV reference)")
    for index, name in enumerate(sorted({r["algorithm"] for r in mutations})):
        group = [r for r in mutations if r["algorithm"] == name]
        genetic = float(np.mean([r["genotype_changed_fraction"] for r in group]))
        plans = float(np.mean([r["plan_changed_fraction"] for r in group]))
        bottom = 0.
        for value, label, color in ((1-genetic, "No key change", "lightgray"),
                                     (genetic-plans, "Keys change, same routes", "tab:orange"),
                                     (plans, "Routes change", "tab:green")):
            axes[1, 0].bar(name, value * 100, bottom=bottom * 100, color=color, label=label if index == 0 else None)
            bottom += value
    axes[1, 0].set(ylabel="PM trials (%)", title="Isolated mutation on saved final populations", ylim=(0, 100))
    for name in sorted({r["algorithm"] for r in rows}):
        group = [r for r in rows if r["algorithm"] == name]
        axes[1, 1].scatter([r["archive_best_p"] * 100 for r in group], [r["same_energy_refill_p"] * 100 for r in group],
                           color=colors[name], label=name, s=40)
    limit = max(r["same_energy_refill_p"] for r in rows) * 105
    axes[1, 1].plot([0, limit], [0, limit], "k--", linewidth=1)
    axes[1, 1].set(xlabel="Original maximum P (%)", ylabel="P after 2-opt + insertion (%)",
                   title="Offline probe: cap energy at each original plan")
    for ax in axes.flat:
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output / "diagnostics.png", dpi=180)
    plt.close(fig)
