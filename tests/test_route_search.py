import csv
from itertools import permutations

import numpy as np
import pytest

from uav_sar.io import read_json, write_json
from uav_sar.local_search import RouteLedger, run_direct
from uav_sar.optimize import run_one
from uav_sar.problem import Instance
from uav_sar.route_operators import MOVES, encode_routes, route_crossover, route_move
from uav_sar.study import run_study
from uav_sar.study_analysis import variation_probe


@pytest.fixture
def instance():
    return Instance(xy=np.array([[3., 0.], [3., 4.], [0., 4.], [-3., 0.]]),
                    pi=np.array([.4, .3, .2, .1]), q=np.array([[.6, .7, .8, .9], [.9, .8, .7, .6]]),
                    bases=np.zeros((2, 2)), speed=np.array([1., 2.]), fly_w=np.array([360., 720.]),
                    obs_w=np.array([720., 720.]), budget=np.array([10., 10.]),
                    deadline=100., tau=1., metadata={"prior_mode": "condition_on_crop"})


def settings():
    return {"population": 12, "generations": 8, "log_every": 100, "hv_reference": [1.1, 1.1],
            "sbx_eta": 15, "mutation_eta": 20, "neighbors": 4, "neighbor_mating": .9}


def test_route_encoder_lossless_for_assignments_and_orders(instance):
    for ordering in permutations(range(4)):
        for split in range(5):
            routes = [list(ordering[:split]), list(ordering[split:])]
            x = encode_routes(instance, routes)
            assert instance.decode(x) == (routes, 0)
    assert instance.decode(encode_routes(instance, [[], []])) == ([[], []], 0)
    with pytest.raises(ValueError):
        encode_routes(instance, [[0], [0]])


@pytest.mark.parametrize("move", MOVES)
def test_route_moves_preserve_unique_indices_and_do_not_modify_parent(instance, move):
    rng = np.random.default_rng(2)
    parent = [[0, 1, 2], []]
    for _ in range(30):
        child, meta = route_move(instance, parent, rng, operator=move)
        cells = [j for route in child for j in route]
        assert len(cells) == len(set(cells)) and set(cells) <= set(range(4))
        assert parent == [[0, 1, 2], []]
        assert meta["operator"] == move and meta["position_checks"] >= 0
        if move in ("relocate", "swap", "reverse"):
            assert set(cells) == {0, 1, 2}


def test_route_crossover_respects_parent_union_and_global_uniqueness(instance):
    a, b = [[0, 1], [2]], [[2, 3], [0]]
    child = route_crossover(instance, a, b, np.random.default_rng(42))
    cells = [j for route in child for j in route]
    assert len(cells) == len(set(cells)) and set(cells) <= {0, 1, 2, 3}
    assert a == [[0, 1], [2]] and b == [[2, 3], [0]]
    assert instance.decode(encode_routes(instance, child))[0] == child


@pytest.mark.parametrize("name", ["mosa", "pils"])
def test_direct_algorithms_budget_reproducibility_and_monotone_archive(instance, name, tmp_path):
    fronts = []
    for repeat in range(2):
        folder = tmp_path / str(repeat)
        summary = run_direct(instance, name, 42, settings(), folder)
        assert summary["evaluations"] == 96
        assert sum(summary["move_attempts"].values()) == 84
        with np.load(folder / "archive.npz") as archive:
            fronts.append(archive["F"].copy())
            for x, f in zip(archive["X"], archive["F"]):
                result = instance.evaluate_routes(instance.decode(x)[0])
                assert result["feasible"]
                np.testing.assert_allclose(instance.objectives(result), f, rtol=0, atol=1e-12)
        history = list(csv.DictReader((folder / "history.csv").open()))
        hv = [float(row["hypervolume"]) for row in history]
        assert len(history) == 8 and np.all(np.diff(hv) >= -1e-12)
    np.testing.assert_array_equal(*fronts)


def test_infeasible_proposals_are_counted_and_excluded_from_archive(instance, tmp_path):
    instance.deadline = .1
    for name in ("mosa", "pils"):
        summary = run_direct(instance, name, 42, settings(), tmp_path / name)
        assert summary["evaluations"] == 96 and summary["candidate_feasible_fraction"] < 1
        results = read_json(tmp_path / name / "routes.json")
        assert len(results) == 1 and results[0]["n_observations"] == 0


@pytest.mark.parametrize("base", ["nsga2", "moead"])
@pytest.mark.parametrize("variant", ["route_mutation", "route_crossover", "route", "canonical"])
def test_ea_ablation_keeps_budget_and_feasibility(instance, base, variant, tmp_path):
    name = f"{base}_{variant}"
    summary = run_one(instance, name, 42, settings(), tmp_path / name)
    assert summary["evaluations"] == 96
    for result in read_json(tmp_path / name / "routes.json"):
        assert result["feasible"]


def test_variation_probes_reproducible_and_preserve_rng(instance):
    from uav_sar.optimize import initial_population
    x = initial_population(instance, 12, 42)
    state = np.random.get_state()
    result = variation_probe(instance, x, 2026, 2)
    after = np.random.get_state()
    assert state[0] == after[0] and state[2:] == after[2:]
    np.testing.assert_array_equal(state[1], after[1])
    assert result == variation_probe(instance, x, 2026, 2)
    assert all(value is None or 0 <= value <= 1 for value in result.values())


def test_inert_padding_probe_preserves_physical_parents_and_classifies_changes(instance):
    from scripts.study_followup import control_trials
    from uav_sar.optimize import initial_population
    x = initial_population(instance, 12, 42)
    original = x.copy()
    rows = control_trials(instance, x, "nsga2", 42, repeats=2)
    assert len(rows) == 5 and all(row["trials"] == 24 for row in rows)
    assert [row["dimension"] for row in rows] == [12, 12, 24, 48, 12]
    for row in rows:
        assert row["membership_fraction"] + row["reassignment_same_cells_fraction"] + row["order_only_fraction"] == pytest.approx(row["plan_changed_fraction"])
    np.testing.assert_array_equal(x, original)
    assert rows == control_trials(instance, x, "nsga2", 42, repeats=2)


def test_frozen_study_pipeline_and_changed_protocol_rejection(instance, tmp_path):
    baseline = tmp_path / "baseline"
    baseline.mkdir()
    data = {name: getattr(instance, name).tolist() for name in ("xy", "pi", "q", "bases", "speed", "fly_w", "obs_w", "budget")}
    data.update(deadline=instance.deadline, tau=instance.tau, metadata={**instance.metadata, "calibration": {"source": "unit_test"}})
    write_json(baseline / "instance.json", data)
    actual = settings()
    actual["seeds"] = [42]
    for name in ("nsga2", "moead", "mosa", "pils"):
        run_one(instance, name, 42, actual, baseline / name / "seed_42")
    protocol = read_json("configs/baseline-study.json")
    protocol.update(evaluations_per_run=96, population=12, development_seeds=[42],
                    validation_cases=[], probe_repeats=1)
    path = tmp_path / "protocol.json"
    write_json(path, protocol)
    output = tmp_path / "study"
    run_study({"optimizer": actual}, path, baseline, output)
    assert read_json(output / "manifest.json")["status"] == "completed"
    assert read_json(output / "audit.json")["plans_independently_checked"] > 0
    assert len(read_json(output / "summary.json")) == 12
    protocol["evaluations_per_run"] = 108
    write_json(path, protocol)
    with pytest.raises(ValueError, match="protocol differs"):
        run_study({"optimizer": actual}, path, baseline, output)
