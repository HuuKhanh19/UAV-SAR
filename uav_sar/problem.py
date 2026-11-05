"""Shared routing decoder and independently recomputed route evaluator."""
from dataclasses import dataclass

import numpy as np
from pymoo.core.problem import Problem

from .io import read_json


def nondominated_indices(f):
    """Exact, unique 2-D minimization skyline, O(n log n)."""
    f = np.asarray(f)
    if len(f) == 0:
        return np.array([], dtype=int)
    order = np.lexsort((f[:, 1], f[:, 0]))
    keep, best_energy = [], np.inf
    for i in order:
        if f[i, 1] < best_energy:
            keep.append(i)
            best_energy = f[i, 1]
    return np.asarray(keep, dtype=int)


@dataclass
class Instance:
    xy: np.ndarray
    pi: np.ndarray
    q: np.ndarray
    bases: np.ndarray
    speed: np.ndarray
    fly_w: np.ndarray
    obs_w: np.ndarray
    budget: np.ndarray
    deadline: float
    tau: float
    metadata: dict

    def __post_init__(self):
        self.n = len(self.pi)
        self.k = len(self.speed)
        self.prior_mode = self.metadata.get("prior_mode", self.metadata.get("config", {}).get("prior_mode", "preserve_mass"))
        for value in (self.xy, self.pi, self.q, self.bases, self.speed, self.fly_w, self.obs_w, self.budget):
            if not np.all(np.isfinite(value)):
                raise ValueError("Non-finite instance value")
        if self.n == 0 or self.k == 0 or self.xy.shape != (self.n, 2) or self.q.shape != (self.k, self.n):
            raise ValueError("Invalid instance dimensions")
        if self.bases.shape != (self.k, 2) or any(v.shape != (self.k,) for v in (self.speed, self.fly_w, self.obs_w, self.budget)):
            raise ValueError("Invalid fleet dimensions")
        if np.any(self.pi < 0) or self.pi.sum() > 1 + 1e-10 or np.any((self.q < 0) | (self.q > 1)):
            raise ValueError("Invalid probabilities")
        if self.prior_mode == "condition_on_crop" and not np.isclose(self.pi.sum(), 1., rtol=0, atol=1e-10):
            raise ValueError("Conditional mission prior must sum to one")
        if any(np.any(v <= 0) for v in (self.speed, self.fly_w, self.obs_w, self.budget)) or not np.isfinite([self.deadline, self.tau]).all() or self.deadline <= 0 or self.tau <= 0:
            raise ValueError("Time, speed, power and budgets must be positive")
        self.distance = np.linalg.norm(self.xy[:, None, :] - self.xy[None, :, :], axis=2)
        self.base_distance = np.linalg.norm(self.bases[:, None, :] - self.xy[None, :, :], axis=2)
        self.probability_upper_bound = float(np.dot(self.pi, self.q.max(axis=0)))
        if self.probability_upper_bound <= 0:
            raise ValueError("Detector produced zero usable probability: inspect calibration before optimizing")

    @property
    def probability_label(self):
        if self.prior_mode == "condition_on_crop":
            return "Detection probability | target in mission region"
        return "Detection probability (source prior)"

    @classmethod
    def load(cls, path):
        d = read_json(path)
        names = ["xy", "pi", "q", "bases", "speed", "fly_w", "obs_w", "budget"]
        return cls(**{n: np.asarray(d[n], dtype=float) for n in names},
                   deadline=d["deadline"], tau=d["tau"], metadata=d["metadata"])

    def decode(self, chromosome):
        """Selection, UAV assignment, random-key order; append only if return is feasible."""
        x = np.asarray(chromosome, dtype=float)
        if x.shape != (3 * self.n,) or not np.isfinite(x).all() or np.any((x < 0) | (x > 1)):
            raise ValueError("Chromosome must contain 3*N finite keys in [0,1]")
        selected = x[:self.n] < 0.5
        assignment = np.minimum((x[self.n:2*self.n] * self.k).astype(int), self.k-1)
        order = np.argsort(x[2*self.n:], kind="stable")
        routes = [[] for _ in range(self.k)]
        open_distance = np.zeros(self.k)
        rejected = 0
        for j in order:
            if not selected[j]:
                continue
            k = assignment[j]
            leg = self.distance[routes[k][-1], j] if routes[k] else self.base_distance[k, j]
            proposed_open = open_distance[k] + leg
            fly_s = (proposed_open + self.base_distance[k, j]) / self.speed[k]
            obs_s = (len(routes[k]) + 1) * self.tau
            energy = (fly_s * self.fly_w[k] + obs_s * self.obs_w[k]) / 3600
            if fly_s + obs_s <= self.deadline + 1e-9 and energy <= self.budget[k] + 1e-9:
                routes[k].append(int(j))
                open_distance[k] = proposed_open
            else:
                rejected += 1
        return routes, rejected

    def evaluate_routes(self, routes):
        """Recompute using coordinate geometry, including the return leg and observation phase."""
        if len(routes) != self.k:
            raise ValueError("Wrong number of routes")
        visited = [j for route in routes for j in route]
        if any(not isinstance(j, (int, np.integer)) or j < 0 or j >= self.n for j in visited):
            raise ValueError("Invalid cell index")
        if len(set(visited)) != len(visited):
            raise ValueError("An observation cell is visited more than once")
        details, probability = [], 0.0
        for k, route in enumerate(routes):
            points = np.vstack([self.bases[k], self.xy[route], self.bases[k]])
            distance = float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())
            fly_s = distance / self.speed[k]
            observe_s = len(route) * self.tau
            energy = (self.fly_w[k] * fly_s + self.obs_w[k] * observe_s) / 3600
            probability += float(np.dot(self.pi[route], self.q[k, route]))
            details.append({"uav": k, "cells": route, "distance_m": distance,
                            "return_time_s": fly_s + observe_s, "energy_wh": float(energy),
                            "feasible": bool(fly_s + observe_s <= self.deadline + 1e-8 and energy <= self.budget[k] + 1e-8)})
        return {"p_detect": probability, "energy_wh": sum(d["energy_wh"] for d in details),
                "n_observations": len(visited), "feasible": all(d["feasible"] for d in details), "routes": details}

    def objectives(self, evaluation):
        # Fixed instance-derived scaling, common to every algorithm and seed.
        return [1 - evaluation["p_detect"] / self.probability_upper_bound,
                evaluation["energy_wh"] / self.budget.sum()]


class SearchProblem(Problem):
    def __init__(self, instance):
        self.instance = instance
        self.archive_x = np.empty((0, 3*instance.n))
        self.archive_f = np.empty((0, 2))
        self.evaluations = 0
        self.repaired = 0
        super().__init__(n_var=3*instance.n, n_obj=2, xl=0.0, xu=1.0)

    def _evaluate(self, x, out, *args, **kwargs):
        values = []
        for chromosome in x:
            routes, rejected = self.instance.decode(chromosome)
            evaluation = self.instance.evaluate_routes(routes)
            if not evaluation["feasible"]:
                raise AssertionError("Shared decoder returned an infeasible route")
            values.append(self.instance.objectives(evaluation))
            self.evaluations += 1
            self.repaired += int(rejected > 0)
        out["F"] = np.asarray(values)
        all_f = np.vstack([self.archive_f, out["F"]])
        all_x = np.vstack([self.archive_x, x])
        keep = nondominated_indices(all_f)
        self.archive_f, self.archive_x = all_f[keep], all_x[keep]
