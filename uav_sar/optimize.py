import csv
import platform
import subprocess
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pymoo
from pymoo.algorithms.moo.moead import MOEAD
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.core.callback import Callback
from pymoo.decomposition.tchebicheff import Tchebicheff
from pymoo.indicators.hv import HV
from pymoo.indicators.igd_plus import IGDPlus
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.optimize import minimize

from .io import read_json, sha256, write_json
from .problem import Instance, SearchProblem, nondominated_indices


def initial_population(instance, size, seed):
    rng = np.random.default_rng(seed)
    x = rng.random((size, 3 * instance.n))
    # Vary selection density to seed the full energy range. Identical for both algorithms.
    densities = np.linspace(0, 1, size)
    for i, density in enumerate(densities):
        chosen = rng.random(instance.n) < density
        x[i, :instance.n] = np.where(chosen, rng.uniform(0, .5, instance.n), rng.uniform(.5, 1, instance.n))
    return x


def write_front(problem, folder, label):
    instance = problem.instance
    solutions = []
    for i, (x, f) in enumerate(zip(problem.archive_x, problem.archive_f)):
        routes, _ = instance.decode(x)
        result = instance.evaluate_routes(routes)
        if not result["feasible"] or not np.allclose(f, instance.objectives(result), rtol=0, atol=1e-10):
            raise AssertionError("Saved solution verification failed")
        solutions.append({"solution_id": i, **result, "normalized_objectives": f.tolist()})
    write_json(folder / "routes.json", solutions)
    with (folder / "pareto.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["solution_id", "p_detect", "energy_wh", "n_observations", "feasible"])
        writer.writeheader()
        writer.writerows({k: result[k] for k in writer.fieldnames} for result in solutions)
    np.savez_compressed(folder / "archive.npz", X=problem.archive_x, F=problem.archive_f)
    if not solutions:
        return
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.scatter([s["energy_wh"] for s in solutions], [s["p_detect"] for s in solutions], s=15)
    ax.set(xlabel="Full planned energy (Wh)", ylabel=instance.probability_label, title=f"{label} - empirical non-dominated archive")
    ax.grid(alpha=.25)
    fig.tight_layout(); fig.savefig(folder / "pareto.png", dpi=180); plt.close(fig)
    index = int(np.argmin(np.linalg.norm(problem.archive_f, axis=1)))
    representative = solutions[index]
    fig, ax = plt.subplots(figsize=(7, 6))
    dots = ax.scatter(instance.xy[:, 0], instance.xy[:, 1], c=instance.pi, cmap="YlOrRd", s=25, alpha=.7)
    fig.colorbar(dots, ax=ax, label="Prior probability mass")
    for k, route in enumerate(representative["routes"]):
        points = np.vstack([instance.bases[k], instance.xy[route["cells"]], instance.bases[k]])
        ax.plot(points[:, 0], points[:, 1], "o-", ms=2, lw=1, label=f"UAV {k+1}")
    ax.scatter(instance.bases[:, 0], instance.bases[:, 1], marker="*", color="black", s=120, label="Base")
    ax.set(xlabel="East from base (m)", ylabel="North from base (m)", aspect="equal",
           title=f"{label}, solution {index}: P={representative['p_detect']:.5f}, E={representative['energy_wh']:.2f} Wh")
    ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(folder / "routes.png", dpi=180); plt.close(fig)


class Progress(Callback):
    def __init__(self, problem, folder, label, settings):
        super().__init__()
        self.problem, self.folder, self.label, self.settings = problem, folder, label, settings
        self.start = time.perf_counter()
        self.hv = HV(ref_point=np.array(settings["hv_reference"]))
        self.rows = []

    def notify(self, algorithm):
        p, i = self.problem, self.problem.instance
        f = p.archive_f
        row = {"generation": algorithm.n_gen, "evaluations": algorithm.evaluator.n_eval,
               "elapsed_s": time.perf_counter()-self.start, "archive_size": len(f),
               "hypervolume": float(self.hv(f)),
               "best_p_detect": float((1-f[:, 0].min()) * i.probability_upper_bound),
               "decoded_feasible_fraction": 1.0,
               "repair_fraction": p.repaired / max(p.evaluations, 1)}
        self.rows.append(row)
        with (self.folder / "history.csv").open("a", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(row))
            if len(self.rows) == 1:
                writer.writeheader()
            writer.writerow(row)
        if algorithm.n_gen == 1 or algorithm.n_gen % self.settings["log_every"] == 0 or algorithm.n_gen == self.settings["generations"]:
            print(f"[{self.label}] gen={algorithm.n_gen:4d}/{self.settings['generations']} eval={row['evaluations']:7d} "
                  f"archive={len(f):4d} Pmax={row['best_p_detect']:.6f} HV={row['hypervolume']:.6f} "
                  f"elapsed={row['elapsed_s']:.1f}s", flush=True)
            np.savez_compressed(self.folder / "checkpoint_archive.npz", X=p.archive_x, F=f)


def run_one(instance, name, seed, settings, folder):
    folder.mkdir(parents=True, exist_ok=False)
    problem = SearchProblem(instance)
    size = settings["population"]
    if size < 4 or settings["generations"] < 1 or settings["log_every"] < 1:
        raise ValueError("population >= 4, generations >= 1 and log_every >= 1 are required")
    common = {"sampling": initial_population(instance, size, seed),
              "crossover": SBX(prob=.9, eta=settings["sbx_eta"]),
              "mutation": PM(prob=1.0, prob_var=1/(3*instance.n), eta=settings["mutation_eta"])}
    if name == "nsga2":
        algorithm = NSGA2(pop_size=size, eliminate_duplicates=False, **common)
    elif name == "moead":
        w = np.linspace(0, 1, size)
        algorithm = MOEAD(ref_dirs=np.column_stack([w, 1-w]), n_neighbors=min(size, max(2, settings["neighbors"])),
                          decomposition=Tchebicheff(), prob_neighbor_mating=settings["neighbor_mating"], **common)
    else:
        raise ValueError(name)
    label = f"{name.upper()} seed={seed}"
    progress = Progress(problem, folder, label, settings)
    status = "completed"
    try:
        result = minimize(problem, algorithm, ("n_gen", settings["generations"]), seed=seed,
                          callback=progress, verbose=False, copy_algorithm=False, save_history=False)
        evaluations = result.algorithm.evaluator.n_eval
        if evaluations != size * settings["generations"]:
            raise AssertionError(f"Evaluation budget mismatch: {evaluations}")
        np.savez_compressed(folder / "final_population.npz", X=result.pop.get("X"), F=result.pop.get("F"))
    except KeyboardInterrupt:
        status, evaluations = "interrupted", problem.evaluations
    write_front(problem, folder, label)
    stats = {"algorithm": name, "seed": seed, "status": status, "evaluations": evaluations,
             "elapsed_s": time.perf_counter()-progress.start, "archive_size": len(problem.archive_f),
             "hypervolume": float(progress.hv(problem.archive_f)) if len(problem.archive_f) else 0,
             "best_p_detect": float((1-problem.archive_f[:, 0].min())*instance.probability_upper_bound) if len(problem.archive_f) else 0,
             "decoded_feasible_fraction": 1.0 if evaluations else None,
             "repair_fraction": problem.repaired/max(evaluations, 1), "settings": settings}
    write_json(folder / "summary.json", stats)
    print(f"[{label}] {status}: {folder}", flush=True)
    if status != "completed":
        raise KeyboardInterrupt
    return stats


def compare(output, instance):
    records = []
    for p in sorted(output.glob("*/seed_*/summary.json")):
        summary = read_json(p)
        if summary["status"] == "completed":
            f = np.load(p.parent / "archive.npz")["F"]
            records.append((p, summary, f))
    if not records:
        return
    union = np.vstack([f for _, _, f in records])
    reference = union[nondominated_indices(union)]
    np.savetxt(output / "empirical_reference.csv", reference, delimiter=",", header="normalized_miss,normalized_energy", comments="")
    metric = IGDPlus(reference)
    rows = []
    fig, (ax, curve) = plt.subplots(1, 2, figsize=(12, 4.5))
    colors = {"nsga2": "tab:blue", "moead": "tab:orange"}
    seen = set()
    for path, summary, f in records:
        summary["igd_plus_pooled_reference"] = float(metric(f))
        write_json(path, summary)
        row = {k: v for k, v in summary.items() if k != "settings"}
        rows.append(row)
        label = summary["algorithm"]
        ax.scatter(f[:, 1]*instance.budget.sum(), (1-f[:, 0])*instance.probability_upper_bound, s=10,
                   alpha=.5, c=colors[label], label=label if label not in seen else None)
        history = np.genfromtxt(path.parent / "history.csv", delimiter=",", names=True)
        curve.plot(np.atleast_1d(history["evaluations"]), np.atleast_1d(history["hypervolume"]),
                   c=colors[label], alpha=.6, label=label if label not in seen else None)
        seen.add(label)
    with (output / "summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    ax.set(xlabel="Full planned energy (Wh)", ylabel=instance.probability_label, title="Empirical archives, all seeds")
    curve.set(xlabel="Objective evaluations", ylabel="Normalized hypervolume", title="Convergence, all seeds")
    for a in (ax, curve):
        a.grid(alpha=.25); a.legend()
    fig.tight_layout(); fig.savefig(output / "comparison.png", dpi=180); plt.close(fig)


def run(config, instance_path, output, algorithms, seeds=None, population=None, generations=None):
    instance = Instance.load(instance_path)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    settings = dict(config["optimizer"])
    if population is not None: settings["population"] = population
    if generations is not None: settings["generations"] = generations
    seeds = seeds if seeds is not None else settings["seeds"]
    if not seeds or len(seeds) != len(set(seeds)):
        raise ValueError("Provide at least one distinct seed")
    write_json(output / "instance.json", read_json(instance_path))
    source_hashes = {str(p): sha256(p) for p in sorted(Path("uav_sar").glob("*.py"))}
    manifest = {"config": config, "optimizer_actual": settings, "seeds": seeds, "algorithms": algorithms,
                "prior": {"mode": instance.prior_mode, "label": instance.probability_label,
                          "mission_prior_mass": float(instance.pi.sum()),
                          "source_prior_mass_in_mission": instance.metadata.get("raw_crop_mass")},
                "instance_sha256": sha256(instance_path), "source_sha256": source_hashes,
                "python": sys.version, "executable": sys.executable, "platform": platform.platform(), "pymoo": pymoo.__version__,
                "normalization": {"probability_upper_bound": instance.probability_upper_bound, "energy_upper_bound_wh": float(instance.budget.sum())},
                "archive": "all evaluated feasible phenotypes for both algorithms", "igd_reference": "pooled empirical archive, not true Pareto front"}
    write_json(output / "manifest.json", manifest)
    (output / "pip-freeze.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True), encoding="utf-8")
    try:
        for seed in seeds:
            for name in algorithms:
                run_one(instance, name, seed, settings, output / name / f"seed_{seed}")
                compare(output, instance)
    except KeyboardInterrupt:
        compare(output, instance)
        print(f"Interrupted; completed seeds and current archive saved in {output}", flush=True)
        return
    print(f"Comparison: {output / 'summary.csv'}\nFigure: {output / 'comparison.png'}", flush=True)
