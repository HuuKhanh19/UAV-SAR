import argparse
import time
from pathlib import Path

from .io import read_json


def main():
    parser = argparse.ArgumentParser(description="Multi-UAV SAR: POP + SAREnv, NSGA-II and MOEA/D")
    parser.add_argument("command", choices=["download", "prepare", "train", "calibrate", "instance", "run", "pipeline", "diagnose"])
    parser.add_argument("--config", default="configs/pilot.json")
    parser.add_argument("--device", default="0", help="GPU index, or cpu")
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--name", help="Unique detector training run name")
    parser.add_argument("--weights", help="Checkpoint with training_manifest.json")
    parser.add_argument("--calibration", default="data/calibration.json")
    parser.add_argument("--instance", default="data/instance_mission.json")
    parser.add_argument("--output", help="Output file (calibrate/instance) or new directory (run/pipeline/diagnose)")
    parser.add_argument("--algorithms", nargs="+", choices=["nsga2", "moead"], default=["nsga2", "moead"])
    parser.add_argument("--seeds", nargs="+", type=int)
    parser.add_argument("--population", type=int)
    parser.add_argument("--generations", type=int)
    parser.add_argument("--results", default="results/baseline_mission_100pct", help="Frozen baseline run to diagnose")
    parser.add_argument("--extended-results", help="Completed runs with the same settings and seeds but a larger evaluation budget")
    parser.add_argument("--mutation-repeats", type=int, default=4, help="Independent PM trials per saved final individual")
    parser.add_argument("--probe-seed", type=int, default=2026)
    parser.add_argument("--skip-random", action="store_true", help="Skip the equal-evaluation stratified random-search control")
    args = parser.parse_args()
    config = read_json(args.config)
    # Set this before importing Ultralytics, including direct python invocations.
    import os
    settings_folder = Path(config["data_root"]) / "ultralytics_settings"
    settings_folder.mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(settings_folder.resolve())
    if args.command == "download":
        from .datasets import fetch
        fetch(config)
    elif args.command == "prepare":
        from .detector import prepare
        prepare(config)
    elif args.command == "train":
        from .detector import train
        train(config, args.epochs, args.device, args.name)
    elif args.command == "calibrate":
        from .detector import calibrate
        calibrate(config, args.output or args.calibration, args.weights, args.device)
    elif args.command == "instance":
        from .instance import build
        build(config, args.calibration, args.output or args.instance)
    elif args.command == "run":
        from .optimize import run
        run(config, args.instance, args.output or f"results/run_{time.strftime('%Y%m%d_%H%M%S')}",
            args.algorithms, args.seeds, args.population, args.generations)
    elif args.command == "diagnose":
        from .diagnostics import diagnose
        diagnose(args.results, args.output or f"results/diagnostics_{time.strftime('%Y%m%d_%H%M%S')}",
                 args.extended_results, args.mutation_repeats, args.probe_seed, not args.skip_random)
    else:
        from .datasets import fetch
        from .detector import prepare, train, calibrate
        from .instance import build
        from .optimize import run
        output = Path(args.output or f"results/pipeline_{time.strftime('%Y%m%d_%H%M%S')}")
        if output.exists():
            raise FileExistsError(output)
        # Intermediate data uses a sibling directory so run() can create an exclusive result directory.
        intermediate = output.with_name(output.name + "_inputs")
        intermediate.mkdir(parents=True, exist_ok=False)
        fetch(config)
        prepare(config)
        weights = train(config, args.epochs, args.device, args.name)
        calibration = intermediate / "calibration.json"
        instance = intermediate / "instance.json"
        calibrate(config, calibration, weights, args.device)
        build(config, calibration, instance)
        run(config, instance, output, args.algorithms, args.seeds, args.population, args.generations)
