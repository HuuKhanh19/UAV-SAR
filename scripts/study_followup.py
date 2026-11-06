"""Development-only topology controls and a small reviewable study snapshot.

Run after the frozen online study. No search parameters are changed here.
"""
import argparse
import csv
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pymoo.core.population import Population
from pymoo.core.problem import Problem
from pymoo.operators.mutation.pm import PM

from uav_sar.diagnostics import population_metrics, save_csv
from uav_sar.io import read_json, sha256, write_json
from uav_sar.problem import Instance, SearchProblem
from uav_sar.route_operators import RouteMutation, encode_routes
from uav_sar.study import completed


def control_trials(instance, x, algorithm, seed, repeats=20):
    d, rows = 3 * instance.n, []
    original_plans = [instance.decode(parent)[0] for parent in x]
    canonical = np.array([encode_routes(instance, plan) for plan in original_plans])
    assert all(instance.decode(parent)[0] == plan for parent, plan in zip(canonical, original_plans))
    for variant, dimension in (("pm_original", d), ("pm_canonical", d), ("pm_dummy_1x", 2*d),
                                ("pm_dummy_3x", 4*d), ("route_mutation", d)):
        parents = np.tile(canonical if variant == "pm_canonical" else x, (repeats, 1))
        parents = np.pad(parents, ((0, 0), (0, dimension-d)), constant_values=.5)
        state = np.random.get_state()
        try:
            np.random.seed(2026 + seed)
            if variant == "route_mutation":
                children = RouteMutation().do(SearchProblem(instance), Population.new(X=parents.copy())).get("X")
            else:
                problem = Problem(n_var=dimension, n_obj=2, xl=0., xu=1.)
                children = PM(prob=1., prob_var=1/dimension, eta=20).do(problem, Population.new(X=parents.copy())).get("X")
        finally:
            np.random.set_state(state)
        categories = dict(membership=0, reassignment_same_cells=0, order_only=0, plan_changed=0)
        for index, child in enumerate(children):
            before, after = original_plans[index % len(x)], instance.decode(child[:d])[0]
            if before == after:
                continue
            categories["plan_changed"] += 1
            a = {(k, j) for k, route in enumerate(before) for j in route}
            b = {(k, j) for k, route in enumerate(after) for j in route}
            if {j for _, j in a} != {j for _, j in b}:
                categories["membership"] += 1
            elif a != b:
                categories["reassignment_same_cells"] += 1
            else:
                categories["order_only"] += 1
        assert sum(categories[k] for k in ("membership", "reassignment_same_cells", "order_only")) == categories["plan_changed"]
        rows.append({"algorithm": algorithm, "seed": seed, "variant": variant, "trials": len(parents), "dimension": dimension,
                     "mean_active_key_changes": float(np.count_nonzero(parents[:, :d] != children[:, :d], axis=1).mean()),
                     **{name+"_fraction": count/len(parents) for name, count in categories.items()}})
    return rows


def followup(output, repeats=20):
    output = Path(output)
    manifest, protocol = read_json(output / "manifest.json"), read_json(output / "protocol.json")
    if manifest["status"] != "completed" or repeats < 1:
        raise ValueError("Complete the online study first; repeats must be positive")
    baseline = Path(manifest["baseline_results"])
    instance = Instance.load(baseline / "instance.json")
    rows, hashes = [], {}
    for algorithm in ("nsga2", "moead"):
        for seed in protocol["development_seeds"]:
            path = baseline / algorithm / f"seed_{seed}" / "final_population.npz"
            hashes[str(path)] = sha256(path)
            with np.load(path) as population:
                x = population["X"].copy()
            rows.extend(control_trials(instance, x, algorithm, seed, repeats))
            print(f"[followup] {algorithm} seed={seed} complete", flush=True)
    save_csv(output / "exploratory_probes.csv", rows)
    write_json(output / "exploratory_probe_manifest.json", {
        "status": "exploratory_posthoc_development_only", "seed_base": 2026, "repeats": repeats,
        "active_dimensions": 3*instance.n, "inert_padding": [0, 3*instance.n, 9*instance.n],
        "input_sha256": hashes, "physical_problem_unchanged": True, "script_sha256": sha256(__file__),
        "explanation": "PM uses probability 1/total dimensions. Inert genes consume mutation opportunities. No validation tuning."})
    return rows


def export_snapshot(output, destination, rows):
    output, destination = Path(output), Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    manifest, protocol = read_json(output / "manifest.json"), read_json(output / "protocol.json")
    names = ["protocol.json", "manifest.json", "runs.csv", "summary.csv", "summary.json", "paired_effects.csv",
             "variation_probes.csv", "attainment.csv", "audit.json", "study.png", "exploratory_probes.csv", "exploratory_probe_manifest.json"]
    for path in [output / name for name in names] + list(output.glob("reference_*.csv")):
        shutil.copyfile(path, destination / path.name)
    baseline = Path(manifest["baseline_results"])
    write_json(destination / "environment.json", {key: value for key, value in read_json(output / "development" / "manifest.json").items()
                                                  if key in ("python", "platform", "pymoo", "numpy", "optimizer_actual")})
    representatives, populations = [], []
    for case in manifest["cases"]:
        source = baseline / "instance.json" if case["split"] == "development" else Path(case["instance"])
        target = destination / "inputs" / f"{case['name']}.json"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        records = completed(output / case["name"])
        if case["split"] == "development":
            records.update(completed(baseline))
        instance = Instance.load(source)
        for (name, run_seed), (folder, _) in records.items():
            if name.split("_")[0] not in ("nsga2", "moead"):
                continue
            with np.load(folder / "final_population.npz") as population:
                stats, _ = population_metrics(instance, population["X"])
            populations.append({"case": case["name"], "algorithm": name, "seed": run_seed,
                                "mean_active_cell_fraction": stats["mean_observations"] / instance.n, **stats})
        cap, seed = .8 * float(instance.budget.sum()), case["seeds"][0]
        for name in protocol["core_algorithms"]:
            folder, _ = records[name, seed]
            plans = read_json(folder / "routes.json")
            chosen = max((p for p in plans if p["energy_wh"] <= cap+1e-9), key=lambda p: (p["p_detect"], -p["energy_wh"]))
            representatives.append({"case": case["name"], "algorithm": name, "seed": seed,
                                    "energy_cap_wh": cap, "plan": chosen})
    write_json(destination / "representative_plans.json", representatives)
    save_csv(destination / "population_diagnostics.csv", populations)
    with (output / "runs.csv").open(encoding="utf-8") as stream:
        runs = list(csv.DictReader(stream))
    interaction = []
    for base in ("nsga2", "moead"):
        for seed in protocol["development_seeds"]:
            def score(suffix):
                return float(next(row["hypervolume"] for row in runs if row["case"] == "development"
                                  and row["algorithm"] == base+suffix and int(row["seed"]) == seed))
            interaction.append({"base": base, "seed": seed,
                "hv_interaction": score("_route")-score("_route_mutation")-score("_route_crossover")+score("")})
    save_csv(destination / "interaction_effects.csv", interaction)
    aggregates = []
    for algorithm in ("nsga2", "moead"):
        for variant in sorted({r["variant"] for r in rows}):
            group = [r for r in rows if r["algorithm"] == algorithm and r["variant"] == variant]
            aggregates.append({"algorithm": algorithm, "variant": variant,
                **{key: float(np.mean([r[key] for r in group])) for key in group[0] if key.endswith("_fraction") or key == "mean_active_key_changes"}})
    write_json(destination / "exploratory_summary.json", aggregates)
    plot_examples(destination, representatives)
    plot_controls(destination, aggregates)
    snapshot_hashes = {str(path.relative_to(destination)): sha256(path) for path in sorted(destination.rglob("*")) if path.is_file()}
    write_json(destination / "snapshot_manifest.json", {"source_results": str(output), "source_status": manifest["status"],
        "file_sha256": snapshot_hashes, "notes": "Small review snapshot; original archives/history remain in results. Offline controls are exploratory."})


def plot_examples(destination, representatives):
    instance = Instance.load(destination / "inputs" / "development.json")
    fig, axes = plt.subplots(2, 3, figsize=(14, 9))
    selected = [r for r in representatives if r["case"] == "development"]
    for ax, result in zip(axes.flat, selected):
        plan = result["plan"]
        ax.scatter(instance.xy[:, 0], instance.xy[:, 1], c=instance.pi, cmap="YlOrRd", s=12, alpha=.7)
        for k, route in enumerate(plan["routes"]):
            points = np.vstack([instance.bases[k], instance.xy[route["cells"]], instance.bases[k]])
            ax.plot(points[:, 0], points[:, 1], "o-", ms=2, lw=1, label=f"UAV {k+1}")
        ax.scatter(instance.bases[:, 0], instance.bases[:, 1], marker="*", s=90, color="black")
        ax.set(title=f"{result['algorithm']}: P={100*plan['p_detect']:.1f}%, E={plan['energy_wh']:.1f} Wh", aspect="equal")
        ax.grid(alpha=.2)
    fig.suptitle("Development seed 1; each plan chosen below 80% of total energy budget")
    fig.tight_layout()
    fig.savefig(destination / "representative_routes.png", dpi=160)
    plt.close(fig)


def plot_controls(destination, aggregates):
    variants = ["pm_original", "pm_canonical", "pm_dummy_1x", "pm_dummy_3x", "route_mutation"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, algorithm in zip(axes, ("nsga2", "moead")):
        bottom = np.zeros(len(variants))
        for key, label in (("membership_fraction", "Cell set"), ("reassignment_same_cells_fraction", "Assignment only"), ("order_only_fraction", "Order only")):
            values = [100*next(row[key] for row in aggregates if row["algorithm"] == algorithm and row["variant"] == variant) for variant in variants]
            ax.bar(np.arange(len(variants)), values, bottom=bottom, label=label)
            bottom += values
        ax.set(xticks=np.arange(len(variants)), xticklabels=["PM raw", "PM projected", "PM + D inert", "PM + 3D inert", "Route move"],
               ylabel="Trials changing the plan (%)", title=algorithm, ylim=(0, 100))
        ax.tick_params(axis="x", labelrotation=20)
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.suptitle("Exploratory controls: same physical parents, different transition kernels")
    fig.tight_layout()
    fig.savefig(destination / "exploratory_controls.png", dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", default="results/baseline_mechanism_study")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--snapshot", help="New directory for reviewable CSV/JSON/figures")
    args = parser.parse_args()
    rows = followup(args.study, args.repeats)
    if args.snapshot:
        export_snapshot(args.study, args.snapshot, rows)
