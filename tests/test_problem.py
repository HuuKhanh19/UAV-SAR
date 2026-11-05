import numpy as np
import pytest
from pymoo.algorithms.moo.moead import MOEAD
from pymoo.algorithms.moo.nsga2 import NSGA2
from pymoo.decomposition.tchebicheff import Tchebicheff
from pymoo.optimize import minimize

from uav_sar.detector import match_boxes, wilson
from uav_sar.optimize import initial_population
from uav_sar.problem import Instance, SearchProblem, nondominated_indices


def tiny(deadline=100., budget=10.):
    return Instance(xy=np.array([[3., 0.], [0., 4.]]), pi=np.array([.2, .3]),
                    q=np.array([[.5, .8]]), bases=np.array([[0., 0.]]), speed=np.array([1.]),
                    fly_w=np.array([360.]), obs_w=np.array([720.]), budget=np.array([budget]),
                    deadline=deadline, tau=1., metadata={})


def test_hand_calculated_route_includes_return_and_separate_observation_power():
    i = tiny()
    r = i.evaluate_routes([[0, 1]])
    # Triangle legs 3+5+4=12 m; flight 12s, observation 2s.
    assert r["routes"][0]["distance_m"] == 12
    assert r["routes"][0]["return_time_s"] == 14
    assert r["energy_wh"] == pytest.approx(1.6)
    assert r["p_detect"] == pytest.approx(.34)
    assert r["feasible"]


def test_deadline_checks_return_not_only_arrival():
    i = tiny(deadline=5)
    r = i.evaluate_routes([[0]])  # Arrival+observation=4s, return=3s.
    assert not r["feasible"]
    routes, rejected = i.decode(np.array([0., 1., 0., 0., 0., 1.]))
    assert routes == [[]] and rejected == 1


def test_battery_repair_and_exact_deadline_boundary():
    assert tiny(deadline=7).evaluate_routes([[0]])["feasible"]
    assert tiny(budget=.8).evaluate_routes([[0]])["feasible"]
    i = tiny(budget=.79)
    routes, _ = i.decode(np.array([0., 1., 0., 0., 0., 1.]))
    assert routes == [[]]


def test_empty_and_no_duplicate_observations():
    r = tiny().evaluate_routes([[]])
    assert r["energy_wh"] == r["p_detect"] == 0 and r["feasible"]
    with pytest.raises(ValueError, match="more than once"):
        tiny().evaluate_routes([[0, 0]])


def test_cross_uav_uniqueness_and_assignment_probability():
    i = Instance(xy=np.array([[3., 0.], [0., 4.]]), pi=np.array([.2, .3]),
                 q=np.array([[.5, .8], [.1, .2]]), bases=np.zeros((2, 2)), speed=np.ones(2),
                 fly_w=np.ones(2)*360, obs_w=np.ones(2)*720, budget=np.ones(2)*10,
                 deadline=100, tau=1, metadata={})
    assert i.evaluate_routes([[0], [1]])["p_detect"] == pytest.approx(.16)
    with pytest.raises(ValueError, match="more than once"):
        i.evaluate_routes([[0], [0]])
    for x in np.random.default_rng(42).random((200, 6)):
        routes, _ = i.decode(x)
        assert i.evaluate_routes(routes)["feasible"]


def test_no_rescaling_missing_prior_mass():
    i = tiny()
    assert i.pi.sum() == .5
    assert i.probability_upper_bound == pytest.approx(.34)
    assert i.evaluate_routes([[1, 0]])["p_detect"] == pytest.approx(.34)


def test_skyline_ties_against_brute_force():
    f = np.random.default_rng(5).integers(0, 20, (200, 2))
    expected = {tuple(p) for p in f if not np.any(np.all(f <= p, axis=1) & np.any(f < p, axis=1))}
    assert {tuple(p) for p in f[nondominated_indices(f)]} == expected


def test_matching_counts_each_person_and_prediction_once():
    predictions = [[0, 0, 10, 10, .9], [0, 0, 10, 10, .8], [20, 20, 30, 30, .7]]
    gt = [[0, 0, 10, 10], [20, 20, 30, 30]]
    assert match_boxes(predictions, gt, .5).tolist() == [0, -1, 1]
    assert match_boxes(predictions, [], .5).tolist() == [-1, -1, -1]
    assert match_boxes([], gt, .5).tolist() == []
    assert match_boxes([[50, 50, 60, 60, .9]], gt, .5).tolist() == [-1]


def test_wilson_extremes():
    assert wilson(0, 100)[0] == pytest.approx(0)
    assert wilson(100, 100)[1] == pytest.approx(1)
    with pytest.raises(ValueError):
        wilson(0, 0)


@pytest.mark.parametrize("name", ["nsga2", "moead"])
def test_algorithms_equal_budget_reproducibility_and_exhaustive_tiny_front(name):
    archives = []
    for repeat in range(2):
        instance = tiny()
        problem = SearchProblem(instance)
        population = initial_population(instance, 12, 42)
        # Seed the exhaustive tiny front to check archive preservation independently of discovery luck.
        population[:4, :2] = [[.9, .9], [.1, .9], [.9, .1], [.1, .1]]
        if name == "nsga2":
            algorithm = NSGA2(pop_size=12, sampling=population, eliminate_duplicates=False)
        else:
            w = np.linspace(0, 1, 12)
            algorithm = MOEAD(ref_dirs=np.column_stack([w, 1-w]), sampling=population,
                              n_neighbors=4, decomposition=Tchebicheff())
        result = minimize(problem, algorithm, ("n_gen", 8), seed=42, verbose=False)
        assert result.algorithm.evaluator.n_eval == 96 == problem.evaluations
        exact = np.array([instance.objectives(instance.evaluate_routes([r])) for r in [[], [0], [1], [0, 1], [1, 0]]])
        front = exact[nondominated_indices(exact)]
        np.testing.assert_allclose(problem.archive_f, front, atol=1e-12)
        for x in problem.archive_x:
            assert instance.evaluate_routes(instance.decode(x)[0])["feasible"]
        archives.append(problem.archive_f.copy())
    np.testing.assert_array_equal(*archives)
