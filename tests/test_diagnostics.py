from itertools import permutations

import numpy as np
import pytest

from uav_sar.diagnostics import greedy_insert, mutation_probe, random_control, two_opt
from uav_sar.optimize import initial_population
from uav_sar.problem import Instance


def small(xy=None, deadline=100.):
    xy = np.array(xy if xy is not None else [[1., 1.], [1., -1.], [-1., 1.], [-1., -1.]])
    n = len(xy)
    return Instance(xy=xy, pi=np.full(n, 1/n), q=np.linspace(.5, .8, n)[None, :],
                    bases=np.zeros((1, 2)), speed=np.ones(1), fly_w=np.array([360.]),
                    obs_w=np.array([720.]), budget=np.array([20.]), deadline=deadline,
                    tau=1., metadata={"prior_mode": "condition_on_crop"})


def test_two_opt_uncrosses_tour_without_changing_reward_or_input():
    instance = small()
    routes = [[0, 3, 1, 2]]
    before = instance.evaluate_routes(routes)
    improved, moves = two_opt(instance, routes)
    after = instance.evaluate_routes(improved)
    exact_energy = min(instance.evaluate_routes([list(order)])["energy_wh"] for order in permutations(range(4)))
    assert moves > 0 and routes == [[0, 3, 1, 2]]
    assert set(improved[0]) == set(routes[0])
    assert after["p_detect"] == pytest.approx(before["p_detect"])
    assert after["energy_wh"] < before["energy_wh"]
    assert after["energy_wh"] == pytest.approx(exact_energy)
    assert after["feasible"]
    assert two_opt(instance, improved)[1] == 0
    assert two_opt(instance, [[]]) == ([[]], 0)


def test_insertion_uses_middle_position_and_honors_return_deadline_and_cap():
    instance = small([[3., 0.], [3., 4.], [3., 2.]], deadline=15.)
    original = [[0, 1]]
    assert not instance.evaluate_routes([[0, 1, 2]])["feasible"]
    routes, checks = greedy_insert(instance, original, energy_cap=1.8)
    assert routes == [[0, 2, 1]] and original == [[0, 1]] and checks > 0
    result = instance.evaluate_routes(routes)
    assert result["feasible"] and result["energy_wh"] == pytest.approx(1.8)
    assert greedy_insert(instance, original, energy_cap=1.79)[0] == original
    assert greedy_insert(instance, energy_cap=0.)[0] == [[]]
    with pytest.raises(ValueError, match="energy cap"):
        greedy_insert(instance, original, energy_cap=1.)


def test_insertion_does_not_assign_to_infeasible_high_recall_uav():
    instance = Instance(xy=np.array([[3., 0.]]), pi=np.array([1.]), q=np.array([[1.], [.5]]),
                        bases=np.zeros((2, 2)), speed=np.ones(2), fly_w=np.full(2, 360.),
                        obs_w=np.full(2, 720.), budget=np.array([.79, 1.]), deadline=7., tau=1., metadata={})
    routes, _ = greedy_insert(instance)
    assert routes == [[], [0]]
    assert instance.evaluate_routes(routes)["p_detect"] == .5


def test_mutation_probe_is_reproducible_and_restores_global_rng():
    instance = small()
    x = initial_population(instance, 12, 42)
    original = x.copy()
    state = np.random.get_state()
    first = mutation_probe(instance, x, 20, 5, 2026)
    after = np.random.get_state()
    assert state[0] == after[0] and state[2:] == after[2:]
    np.testing.assert_array_equal(state[1], after[1])
    np.testing.assert_array_equal(x, original)
    assert first == mutation_probe(instance, x, 20, 5, 2026)
    assert 0 <= first["plan_changed_fraction"] <= first["genotype_changed_fraction"] <= 1
    assert first["trials"] == 60


def test_random_control_reproducibility_budget_and_feasible_archive(tmp_path):
    instance = small()
    settings = {"population": 12, "hv_reference": [1.1, 1.1]}
    a, f_a, history_a = random_control(instance, 2, settings, 37, tmp_path / "a")
    b, f_b, history_b = random_control(instance, 2, settings, 37, tmp_path / "b")
    assert a["evaluations"] == b["evaluations"] == 37
    np.testing.assert_array_equal(f_a, f_b)
    assert history_a == history_b
    with np.load(tmp_path / "a" / "archive.npz") as archive:
        for x in archive["X"]:
            assert instance.evaluate_routes(instance.decode(x)[0])["feasible"]
