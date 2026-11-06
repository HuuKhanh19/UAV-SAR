"""Paired, per-instance analysis; no cross-instance IGD/HV pooling."""
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from pymoo.core.population import Population
from pymoo.indicators.hv import HV
from pymoo.indicators.igd_plus import IGDPlus
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM

from .diagnostics import save_csv, two_opt
from .io import read_json, sha256, write_json
from .problem import Instance, SearchProblem, nondominated_indices
from .route_operators import CanonicalPM, RouteCrossover, RouteMutation
from .study import completed


def edges(instance, routes):
    return {(k, min(a, b), max(a, b)) for k, route in enumerate(routes)
            for a, b in zip([instance.n, *route], [*route, instance.n]) if route}


def variation_probe(instance, x, seed, repeats=4):
    problem, rows = SearchProblem(instance), {}
    parent_keys = [tuple(tuple(route) for route in instance.decode(row)[0]) for row in x]
    parents = np.tile(x, (repeats, 1))
    state = np.random.get_state()
    try:
        for label, mutation in (("pm", PM(prob=1., prob_var=1/(3*instance.n), eta=20)),
                                ("canonical_pm", CanonicalPM(prob=1., prob_var=1/(3*instance.n), eta=20)),
                                ("route_mutation", RouteMutation())):
            np.random.seed(seed)
            children = mutation.do(problem, Population.new(X=parents.copy())).get("X")
            changed = sum(tuple(tuple(route) for route in instance.decode(child)[0]) != parent_keys[index % len(x)]
                          for index, child in enumerate(children))
            rows[label + "_plan_change"] = changed / len(children)
        pairs = np.random.default_rng(seed).integers(len(x), size=(len(x) * repeats // 2, 2))
        parent_edges = [edges(instance, instance.decode(row)[0]) for row in x]
        for label, crossover in (("sbx", SBX(prob=.9, eta=15)), ("route_crossover", RouteCrossover())):
            np.random.seed(seed)
            children = crossover.do(problem, Population.new(X=x.copy()), parents=pairs).get("X")
            retention, common_retention = [], []
            for index, child in enumerate(children):
                a, b = pairs[index % len(pairs)]
                union, common = parent_edges[a] | parent_edges[b], parent_edges[a] & parent_edges[b]
                child_edges = edges(instance, instance.decode(child)[0])
                if child_edges:
                    retention.append(len(child_edges & union) / len(child_edges))
                if common:
                    common_retention.append(len(child_edges & common) / len(common))
            rows[label + "_parent_edge_retention"] = float(np.mean(retention)) if retention else 1.
            rows[label + "_common_edge_retention"] = float(np.mean(common_retention)) if common_retention else None
    finally:
        np.random.set_state(state)
    return rows


def audit_plan(instance, result):
    """Independent scalar geometry and fsum; do not call evaluate_routes."""
    cells, probability, energy = [], 0., 0.
    for route in result["routes"]:
        k, selected = route["uav"], route["cells"]
        if not 0 <= k < instance.k or any(not isinstance(j, int) or not 0 <= j < instance.n for j in selected):
            raise AssertionError("Invalid UAV/cell ID")
        cells.extend(selected)
        points = [instance.bases[k], *instance.xy[selected], instance.bases[k]]
        distance = math.fsum(math.dist(a, b) for a, b in zip(points, points[1:]))
        flight, observation = distance / instance.speed[k], len(selected) * instance.tau
        wh = (flight * instance.fly_w[k] + observation * instance.obs_w[k]) / 3600
        if flight + observation > instance.deadline + 1e-8 or wh > instance.budget[k] + 1e-8:
            raise AssertionError("Saved plan violates physical constraints")
        if abs(distance-route["distance_m"]) > 1e-8 or abs(flight+observation-route["return_time_s"]) > 1e-8 or abs(wh-route["energy_wh"]) > 1e-8:
            raise AssertionError("Saved route metrics differ from independent geometry")
        probability += math.fsum(instance.pi[j] * instance.q[k, j] for j in selected)
        energy += wh
    if len(cells) != len(set(cells)) or len(cells) != result["n_observations"]:
        raise AssertionError("Duplicate/missing observations")
    if abs(probability-result["p_detect"]) > 1e-12 or abs(energy-result["energy_wh"]) > 1e-8:
        raise AssertionError("Saved objectives differ from independent calculation")


def analyze_study(output, cases, protocol):
    output = Path(output)
    rows, probes, attainment, case_fronts, hashes = [], [], [], {}, {}
    audit_count = 0
    metric = HV(ref_point=np.array([1.1, 1.1]))
    for case in cases:
        root = output / case["name"]
        instance = Instance.load(case["instance"])
        records = completed(root)
        if case.get("baseline_source"):
            baseline = completed(case["baseline_source"])
            if set(baseline) & set(records):
                raise AssertionError("Duplicate method/seed in combined development cohort")
            records.update(baseline)
        expected_algorithms = protocol["core_algorithms"] + (protocol["development_ablations"] if case["split"] == "development" else [])
        if set(records) != {(name, seed) for name in expected_algorithms for seed in case["seeds"]}:
            raise AssertionError("Incomplete or unexpected method/seed cohort")
        loaded = []
        for (name, seed), (folder, summary) in sorted(records.items()):
            with np.load(folder / "archive.npz") as archive:
                f = archive["F"].copy()
            history = np.atleast_1d(np.genfromtxt(folder / "history.csv", delimiter=",", names=True))
            loaded.append((name, seed, folder, summary, f, history))
            for file in ("summary.json", "archive.npz", "history.csv", "routes.json", "final_population.npz"):
                hashes[str(folder / file)] = sha256(folder / file)
        union = np.vstack([f for _, _, _, _, f, _ in loaded])
        reference = union[nondominated_indices(union)]
        np.savetxt(output / f"reference_{case['name']}.csv", reference, delimiter=",", header="normalized_miss,normalized_energy", comments="")
        igd = IGDPlus(reference)
        common_time = min(float(summary["search_elapsed_s"]) for _, _, _, summary, _, _ in loaded)
        if any(history["elapsed_s"][0] > common_time for _, _, _, _, _, history in loaded):
            raise AssertionError("Common time is earlier than a method's initialization checkpoint")
        initial = {}
        for name, seed, folder, summary, f, history in loaded:
            if summary["evaluations"] != protocol["evaluations_per_run"]:
                raise AssertionError("Evaluation budget mismatch")
            first = float(history["hypervolume"][0])
            if seed in initial and abs(initial[seed] - first) > 1e-12:
                raise AssertionError("Methods did not start with equivalent initial archives")
            initial[seed] = first
            plans = read_json(folder / "routes.json")
            if len(plans) != len(f):
                raise AssertionError("Archive lengths differ")
            for plan, value in zip(plans, f):
                audit_plan(instance, plan)
                expected = [1-plan["p_detect"]/instance.probability_upper_bound, plan["energy_wh"]/instance.budget.sum()]
                np.testing.assert_allclose(expected, value, rtol=0, atol=1e-10)
                audit_count += 1
            best = plans[int(np.argmin(f[:, 0]))]
            optimized, _ = two_opt(instance, [route["cells"] for route in best["routes"]])
            improved = instance.evaluate_routes(optimized)
            checkpoint = np.flatnonzero(history["elapsed_s"] <= common_time)[-1]
            row = {"case": case["name"], "split": case["split"], "algorithm": name, "seed": seed,
                "n_cells": instance.n, "evaluations": summary["evaluations"], "hypervolume": float(metric(f)),
                "igd_plus_common_reference": float(igd(f)), "pmax": best["p_detect"],
                "search_elapsed_s": summary["search_elapsed_s"], "archive_size": len(f),
                "common_time_s": common_time, "time_matched_hv": float(history["hypervolume"][checkpoint]),
                "time_matched_evaluations": int(history["evaluations"][checkpoint]),
                "insertion_position_checks": summary["insertion_position_checks"],
                "candidate_feasible_fraction": summary.get("candidate_feasible_fraction", 1.),
                "pmax_energy_wh": best["energy_wh"], "pmax_observations": best["n_observations"],
                "pmax_covered_prior": float(sum(instance.pi[route["cells"]].sum() for route in best["routes"])),
                "pmax_two_opt_energy_saving": 1-improved["energy_wh"]/best["energy_wh"] if best["energy_wh"] else 0.}
            rows.append(row)
            for fraction in (.2, .4, .6, .8, 1.):
                selected = f[:, 1] <= fraction + 1e-12
                attainment.append({"case": case["name"], "algorithm": name, "seed": seed, "energy_fraction": fraction,
                    "energy_cap_wh": fraction * float(instance.budget.sum()),
                    "best_p": float((1-f[selected, 0].min())*instance.probability_upper_bound) if selected.any() else None})
            if name in ("nsga2", "moead"):
                with np.load(folder / "final_population.npz") as population:
                    x = population["X"].copy()
                probe = variation_probe(instance, x, protocol["probe_seed"] + seed, protocol["probe_repeats"])
                probes.append({"case": case["name"], "algorithm": name, "seed": seed, **probe})
            case_fronts.setdefault(case["name"], {}).setdefault(name, []).append(f)
        print(f"[study analysis] {case['name']}: {len(loaded)} runs audited", flush=True)
    aggregates = []
    for case in cases:
        names = sorted({row["algorithm"] for row in rows if row["case"] == case["name"]})
        for name in names:
            group = [row for row in rows if row["case"] == case["name"] and row["algorithm"] == name]
            aggregate = {"case": case["name"], "split": case["split"], "algorithm": name, "seeds": len(group)}
            for key in ("hypervolume", "igd_plus_common_reference", "pmax", "search_elapsed_s", "time_matched_hv", "pmax_two_opt_energy_saving"):
                values = [row[key] for row in group]
                aggregate[key + "_mean"] = float(np.mean(values))
                aggregate[key + "_std"] = float(np.std(values, ddof=1)) if len(values) > 1 else 0.
            aggregates.append(aggregate)
    effects = []
    for case in cases:
        for base in ("nsga2", "moead"):
            for variant in ("route", "route_mutation", "route_crossover", "canonical"):
                for seed in case["seeds"]:
                    before = next(row for row in rows if (row["case"], row["algorithm"], row["seed"]) == (case["name"], base, seed))
                    after = next((row for row in rows if (row["case"], row["algorithm"], row["seed"]) == (case["name"], f"{base}_{variant}", seed)), None)
                    if after:
                        effects.append({"case": case["name"], "split": case["split"], "base": base, "variant": variant, "seed": seed,
                            "hv_delta": after["hypervolume"]-before["hypervolume"],
                            "hv_relative_gain": after["hypervolume"]/before["hypervolume"]-1,
                            "pmax_delta": after["pmax"]-before["pmax"],
                            "time_matched_hv_delta": after["time_matched_hv"]-before["time_matched_hv"]})
    for name, values in (("runs", rows), ("summary", aggregates), ("variation_probes", probes), ("paired_effects", effects), ("attainment", attainment)):
        save_csv(output / f"{name}.csv", values)
    write_json(output / "summary.json", aggregates)
    write_json(output / "audit.json", {"status": "passed", "plans_independently_checked": audit_count,
        "initial_hv_matched_by_seed": True, "all_budgets_matched": True,
        "input_sha256": hashes, "method": "math.dist/fsum; per-UAV constraints; unique cells; NPZ objective agreement"})
    if any(sha256(path) != checksum for path, checksum in hashes.items()):
        raise AssertionError("Input changed during analysis")
    plot_study(output, rows, aggregates, effects, probes, case_fronts, cases)


def plot_study(output, rows, aggregates, effects, probes, fronts, cases):
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    names = ["nsga2", "moead", "mosa", "pils", "nsga2_route", "moead_route"]
    instance = Instance.load(cases[0]["instance"])
    for name in names:
        f = np.vstack(fronts["development"][name])
        f = f[nondominated_indices(f)]
        axes[0, 0].plot(f[:, 1]*instance.budget.sum(), (1-f[:, 0])*instance.probability_upper_bound*100, label=name)
    axes[0, 0].set(xlabel="Energy (Wh)", ylabel="Detection probability (%)", title="Development: pooled empirical fronts")
    validations = [case["name"] for case in cases if case["split"] == "validation"]
    x = np.arange(len(validations))
    for offset, base in ((-.18, "nsga2"), (.18, "moead")):
        gain = [np.mean([r["hv_relative_gain"] for r in effects if r["case"] == case and r["base"] == base and r["variant"] == "route"]) * 100 for case in validations]
        axes[0, 1].bar(x+offset, gain, width=.35, label=base+" + route operators")
    axes[0, 1].set(xticks=x, xticklabels=validations, ylabel="Mean paired HV gain (%)", title="Validation: parameters frozen")
    axes[0, 1].tick_params(axis="x", labelrotation=20)
    for offset, key, label in ((-.25, "pm_plan_change", "PM"), (0., "canonical_pm_plan_change", "PM + projection"), (.25, "route_mutation_plan_change", "Route mutation")):
        values = [100 * np.mean([row[key] for row in probes if row["case"] == case["name"]]) for case in cases]
        axes[1, 0].bar(np.arange(len(cases))+offset, values, width=.24, label=label)
    axes[1, 0].set(xticks=np.arange(len(cases)), xticklabels=[case["name"] for case in cases], ylabel="Plans changed (%)", title="Paired probes on original EA final parents")
    axes[1, 0].tick_params(axis="x", labelrotation=20)
    variants = ["", "_canonical", "_route_mutation", "_route_crossover", "_route"]
    for offset, base in ((-.18, "nsga2"), (.18, "moead")):
        group = [next(row for row in aggregates if row["case"] == "development" and row["algorithm"] == base+variant) for variant in variants]
        axes[1, 1].bar(np.arange(len(variants))+offset, [r["hypervolume_mean"] for r in group],
                       yerr=[r["hypervolume_std"] for r in group], width=.35, capsize=3, label=base)
    axes[1, 1].set(xticks=np.arange(len(variants)), xticklabels=["Original", "Projection", "Mutation", "Crossover", "Both"], ylabel="HV (mean +/- SD)", title="Development ablation, same evaluation budget")
    for ax in axes.flat:
        ax.grid(alpha=.2)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(output / "study.png", dpi=180)
    plt.close(fig)
