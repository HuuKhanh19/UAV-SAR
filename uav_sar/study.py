"""Frozen development/validation protocol for baseline and mechanism research."""
from copy import deepcopy
import platform
import subprocess
import sys
from pathlib import Path

import numpy as np
import pymoo

from .instance import build
from .io import read_json, sha256, write_json
from .optimize import compare, run_one
from .problem import Instance


def completed(folder):
    return { (s["algorithm"], s["seed"]): (path.parent, s)
             for path in Path(folder).glob("*/seed_*/summary.json")
             if (s := read_json(path)).get("status") == "completed" }


def run_cohort(config, instance_path, output, algorithms, seeds, settings):
    output = Path(output)
    if not output.exists():
        output.mkdir(parents=True)
        write_json(output / "instance.json", read_json(instance_path))
        write_json(output / "manifest.json", {
            "optimizer_actual": settings, "algorithms": algorithms, "seeds": seeds,
            "instance_sha256": sha256(instance_path), "python": sys.version,
            "platform": platform.platform(), "pymoo": pymoo.__version__, "numpy": np.__version__,
            "source_sha256": {str(p): sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))},
            "archive": "all evaluated feasible plans; unique objective pairs",
            "constraint_policy": "EA decoder repair; direct methods count and reject infeasible proposals"})
        (output / "pip-freeze.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True), encoding="utf-8")
    else:
        manifest = read_json(output / "manifest.json")
        if (manifest["optimizer_actual"] != settings or manifest["algorithms"] != algorithms or manifest["seeds"] != seeds
                or read_json(output / "instance.json") != read_json(instance_path)):
            raise ValueError(f"Existing cohort differs from protocol: {output}")
        current = {str(p): sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
        if manifest["source_sha256"] != current:
            raise ValueError("Cannot resume a cohort after source changes; use a new output directory")
    instance = Instance.load(instance_path)
    done = completed(output)
    for seed in seeds:
        for name in algorithms:
            key = name, seed
            if key in done:
                if done[key][1]["evaluations"] != settings["population"] * settings["generations"] or done[key][1]["settings"] != settings:
                    raise ValueError(f"Completed run differs from protocol: {key}")
                continue
            run_one(instance, name, seed, settings, output / name / f"seed_{seed}")
    compare(output, instance)


def run_study(config, protocol_path, baseline_results, output):
    protocol = read_json(protocol_path)
    baseline_results, output = Path(baseline_results), Path(output)
    size, evaluations = protocol["population"], protocol["evaluations_per_run"]
    if size < 4 or evaluations < size or evaluations % size:
        raise ValueError("Study evaluation budget must be a positive multiple of population >= 4")
    if output.exists():
        if read_json(output / "protocol.json") != protocol:
            raise ValueError("Existing study protocol differs")
    else:
        output.mkdir(parents=True)
        write_json(output / "protocol.json", protocol)
    expected = {(name, seed) for name in ("nsga2", "moead", "mosa", "pils") for seed in protocol["development_seeds"]}
    baseline_runs = completed(baseline_results)
    if set(baseline_runs) != expected:
        raise ValueError("Complete the four-baseline development cohort with the specified seeds first")
    data = read_json(baseline_results / "instance.json")
    settings = deepcopy(config["optimizer"])
    settings.update(population=size, generations=evaluations // size, local_search=protocol["local_search"])
    # Default local-search settings and explicitly specified defaults are equivalent.
    for _, summary in baseline_runs.values():
        actual = deepcopy(summary["settings"])
        actual.setdefault("local_search", protocol["local_search"])
        if actual != settings or summary["evaluations"] != evaluations:
            raise ValueError("Development baseline settings differ from the locked study")
        if summary.get("local_search_actual", protocol["local_search"]) != protocol["local_search"]:
            raise ValueError("Local-search baseline settings differ")
    sources = {str(path): sha256(path) for path in sorted(Path(__file__).parent.glob("*.py"))}
    write_json(output / "manifest.json", {"status": "running", "protocol_sha256": sha256(output / "protocol.json"),
        "source_sha256": sources, "baseline_results": str(baseline_results),
        "baseline_instance_sha256": sha256(baseline_results / "instance.json"),
        "normalization": "instance-derived; compare metrics within each instance",
        "validation_policy": "No parameter changes after inspecting validation outcomes"})
    write_json(output / "calibration.json", data["metadata"]["calibration"])
    cases = [{"name": "development", "split": "development", "instance": str(baseline_results / "instance.json"),
              "seeds": protocol["development_seeds"], "baseline_source": str(baseline_results)}]
    variants = [name for name in protocol["core_algorithms"] if name not in ("nsga2", "moead", "mosa", "pils")]
    variants += protocol["development_ablations"]
    run_cohort(config, baseline_results / "instance.json", output / "development", variants, protocol["development_seeds"], settings)
    for spec in protocol["validation_cases"]:
        cfg = deepcopy(config)
        cfg.update(scenario=spec["scenario"], crop_cells=spec["crop_cells"])
        cfg["deadline_s"] *= spec["resource_factor"]
        for uav in cfg["uavs"]:
            uav["budget_wh"] *= spec["resource_factor"]
        instance_path = output / "inputs" / f"{spec['name']}.json"
        if not instance_path.exists():
            build(cfg, output / "calibration.json", instance_path)
        run_cohort(config, instance_path, output / spec["name"], protocol["core_algorithms"], protocol["validation_seeds"], settings)
        cases.append({"name": spec["name"], "split": "validation", "instance": str(instance_path),
                      "seeds": protocol["validation_seeds"], "specification": spec})
    from .study_analysis import analyze_study
    analyze_study(output, cases, protocol)
    if any(sha256(path) != checksum for path, checksum in sources.items()):
        raise AssertionError("Source changed during the frozen study")
    manifest = read_json(output / "manifest.json")
    manifest.update(status="completed", cases=cases)
    write_json(output / "manifest.json", manifest)
