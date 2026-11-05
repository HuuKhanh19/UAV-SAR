"""POP scene split, detector training, and held-out person-level recall calibration."""
import collections
import csv
import os
import shutil
import time
from pathlib import Path

import numpy as np

from .io import read_json, sha256, write_json


def pop_folder(config):
    path = Path(config["data_root"]) / "POP" / "POP"
    if not (path / "train" / "Annotations" / "train.json").exists():
        raise FileNotFoundError("POP is missing; run 'download' first")
    return path


def prepare(config):
    original = pop_folder(config)
    prepared = Path(config["data_root"]) / "pop_yolo"
    lists = collections.defaultdict(list)
    scenes = collections.defaultdict(set)
    annotations_hash = {}
    image_hash_groups = collections.defaultdict(set)
    counts = collections.Counter()
    for official in ("train", "val", "test"):
        source_json = original / official / "Annotations" / f"{official}.json"
        annotations_hash[official] = sha256(source_json)
        data = read_json(source_json)
        if data["categories"] != [{"name": "person", "id": 1}]:
            raise ValueError("Unexpected POP categories; review label conversion")
        by_image = collections.defaultdict(list)
        for annotation in data["annotations"]:
            if annotation["category_id"] != 1 or annotation.get("iscrowd", 0):
                raise ValueError("Unsupported class or crowd annotation")
            by_image[annotation["image_id"]].append(annotation)
        for image in data["images"]:
            name = Path(image["file_name"]).name
            scene = name.split("_")[0]
            split = "tune" if official == "train" and scene in ("F11", "F12") else ("calibration" if official == "val" else official)
            scenes[split].add(scene)
            source = original / official / "JPEGImages" / name
            dest = prepared / "images" / split / name
            label = prepared / "labels" / split / (Path(name).stem + ".txt")
            dest.parent.mkdir(parents=True, exist_ok=True)
            label.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                try:
                    os.link(source, dest)
                except OSError:
                    shutil.copy2(source, dest)
            image_hash_groups[sha256(source)].add(split)
            w, h = image["width"], image["height"]
            rows = []
            for a in by_image[image["id"]]:
                x, y, bw, bh = a["bbox"]
                x1, y1, x2, y2 = max(0, x), max(0, y), min(w, x+bw), min(h, y+bh)
                if x2 <= x1 or y2 <= y1:
                    raise ValueError(f"Invalid POP bounding box: {name}, annotation {a['id']}")
                if (x1, y1, x2, y2) != (x, y, x+bw, y+bh):
                    counts["clipped_boxes"] += 1
                rows.append(f"0 {(x1+x2)/2/w:.9f} {(y1+y2)/2/h:.9f} {(x2-x1)/w:.9f} {(y2-y1)/h:.9f}")
                counts[f"{split}_boxes"] += 1
            label.write_text("\n".join(rows), encoding="utf-8")
            lists[split].append(dest.resolve().as_posix())
            counts[f"{split}_images"] += 1
    split_names = list(scenes)
    for i, a in enumerate(split_names):
        for b in split_names[i+1:]:
            if scenes[a] & scenes[b]:
                raise ValueError(f"Scene overlap: {a}, {b}")
    duplicates = sum(len(groups) > 1 for groups in image_hash_groups.values())
    if duplicates:
        raise ValueError(f"Found {duplicates} exact image duplicates across splits")
    for split, paths in lists.items():
        (prepared / f"{split}.txt").write_text("\n".join(sorted(paths)) + "\n", encoding="utf-8")
    import yaml
    spec = {"path": prepared.resolve().as_posix(), "train": "train.txt", "val": "tune.txt", "test": "test.txt", "names": {0: "person"}}
    (prepared / "pop.yaml").write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    manifest = {"counts": dict(counts), "scenes": {k: sorted(v) for k, v in scenes.items()},
                "annotation_sha256": annotations_hash, "exact_duplicates_across_splits": duplicates,
                "protocol": "F1-F10 train; F11-F12 checkpoint selection; F13-F16 q calibration; T1-T3 untouched test",
                "note": "Scene disjointness and byte duplicates checked; near-duplicate/participant overlap not independently verified."}
    write_json(prepared / "split_manifest.json", manifest)
    print(f"Prepared scene-separated POP: {dict(counts)}", flush=True)
    return prepared


def train(config, epochs=None, device="0", name=None):
    import torch
    from ultralytics import YOLO
    root = Path(config["data_root"])
    prepared = root / "pop_yolo"
    if not (prepared / "split_manifest.json").exists():
        prepare(config)
    if device != "cpu" and not torch.cuda.is_available():
        raise RuntimeError("CUDA unavailable. Use the project environment or pass --device cpu.")
    settings = config["detector"]
    epochs = settings["epochs"] if epochs is None else epochs
    if epochs < 1:
        raise ValueError("epochs must be positive")
    name = name or time.strftime("pop_%Y%m%d_%H%M%S")
    folder = root / "detector_runs" / name
    if folder.exists():
        raise FileExistsError(f"Training output already exists: {folder}; choose another --name")
    models = root / "models"
    models.mkdir(parents=True, exist_ok=True)
    # Ultralytics resolves this official model asset into the specified directory.
    model = YOLO(str(models / settings["initial_weights"]))
    model.train(data=str(prepared / "pop.yaml"), epochs=epochs, imgsz=settings["imgsz"],
                batch=settings["batch"], device=device, workers=0, seed=settings["seed"], deterministic=True,
                project=str(root / "detector_runs"), name=name, exist_ok=False, pretrained=True,
                amp=False, cache=False, patience=epochs+1, plots=True, save=True, verbose=False)
    best = Path(model.trainer.best)
    manifest = {"weights": str(best.resolve()), "weights_sha256": sha256(best), "epochs": epochs,
                "settings": settings, "split_manifest": read_json(prepared / "split_manifest.json"),
                "initial_weights_sha256": sha256(models / settings["initial_weights"]),
                "device": device, "torch": torch.__version__, "numpy": np.__version__, "training_output": str(folder),
                "actual_args_file": str(folder / "args.yaml"), "actual_args_sha256": sha256(folder / "args.yaml")}
    write_json(folder / "training_manifest.json", manifest)
    write_json(root / "detector_current.json", manifest)
    print(f"Trained detector: {best}", flush=True)
    return best


def match_boxes(predictions, ground_truth, threshold):
    """Confidence-ordered one-to-one matching; return matched GT per prediction (-1=FP)."""
    pred = np.asarray(predictions, dtype=float).reshape(-1, 5)
    gt = np.asarray(ground_truth, dtype=float).reshape(-1, 4)
    assignments = np.full(len(pred), -1, dtype=int)
    used = set()
    for i in np.argsort(-pred[:, 4], kind="stable"):
        if not len(gt):
            break
        a = pred[i, :4]
        intersection = np.maximum(0, np.minimum(a[2:], gt[:, 2:]) - np.maximum(a[:2], gt[:, :2])).prod(axis=1)
        union = np.maximum(0, a[2:]-a[:2]).prod() + np.maximum(0, gt[:, 2:]-gt[:, :2]).prod(axis=1) - intersection
        iou = intersection / np.maximum(union, 1e-12)
        if used:
            iou[list(used)] = -1
        j = int(np.argmax(iou))
        if iou[j] >= threshold:
            assignments[i] = j
            used.add(j)
    return assignments


def wilson(success, total):
    if total <= 0:
        raise ValueError("Cannot estimate q without labeled people")
    z, p = 1.959963984540054, success/total
    den = 1 + z*z/total
    center = (p + z*z/(2*total))/den
    radius = z*np.sqrt(p*(1-p)/total + z*z/(4*total*total))/den
    return [float(max(0, center-radius)), float(min(1, center+radius))]


def calibrate(config, output, weights=None, device="0"):
    import torch
    import ultralytics
    from ultralytics import YOLO
    root, original = Path(config["data_root"]), pop_folder(config)
    split_manifest = read_json(root / "pop_yolo" / "split_manifest.json")
    training = read_json(root / "detector_current.json") if weights is None else None
    weights = Path(training["weights"] if weights is None else weights)
    if not weights.exists():
        raise FileNotFoundError(weights)
    # Explicit checkpoints must carry this project's scene-split training provenance.
    if training is None:
        training = read_json(weights.parent.parent / "training_manifest.json")
    if sha256(weights) != training["weights_sha256"]:
        raise ValueError("Checkpoint checksum does not match its training manifest")
    if training["split_manifest"] != split_manifest:
        raise ValueError("Training and calibration split manifests differ")
    source_json = original / "val" / "Annotations" / "val.json"
    if sha256(source_json) != split_manifest["annotation_sha256"]["val"]:
        raise ValueError("POP calibration annotations changed")
    data = read_json(source_json)
    by_image = collections.defaultdict(list)
    for annotation in data["annotations"]:
        x, y, w, h = annotation["bbox"]
        by_image[annotation["image_id"]].append([x, y, x+w, y+h])
    images = sorted(data["images"], key=lambda x: x["file_name"])
    sources = [str(original / "val" / "JPEGImages" / x["file_name"]) for x in images]
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Calibration already exists: {output}; select a new --output")
    output.parent.mkdir(parents=True, exist_ok=True)
    evidence = output.parent / (output.stem + "_evidence")
    evidence.mkdir(exist_ok=False)
    # A list of strings is treated by Ultralytics as an in-memory image batch.
    # A text source instead streams files in bounded batches of 16.
    source_list = evidence / "images.txt"
    source_list.write_text("\n".join(Path(p).resolve().as_posix() for p in sources) + "\n", encoding="utf-8")
    model = YOLO(str(weights))
    sizes = [u["detector_imgsz"] for u in config["uavs"]]
    settings = config["detector"]
    estimates = []
    for k, size in enumerate(sizes):
        rows, per_scene = [], collections.defaultdict(lambda: [0, 0])
        predictions = model.predict(source=str(source_list), imgsz=size, conf=settings["confidence"], iou=settings["nms_iou"],
                                    classes=[0], device=device, batch=16, stream=True, verbose=False, save=False)
        with (evidence / f"predictions_uav{k+1}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            writer.writerow(["file", "x1", "y1", "x2", "y2", "confidence", "matched_gt_index"])
            processed = 0
            for image, prediction in zip(images, predictions, strict=True):
                if Path(prediction.path).name != image["file_name"]:
                    raise AssertionError("Detector returned images in an unexpected order")
                boxes = prediction.boxes
                pred = np.column_stack([boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy()])
                gt = np.asarray(by_image[image["id"]], dtype=float).reshape(-1, 4)
                if len(gt):
                    gt[:, [0, 2]] = np.clip(gt[:, [0, 2]], 0, image["width"])
                    gt[:, [1, 3]] = np.clip(gt[:, [1, 3]], 0, image["height"])
                matches = match_boxes(pred, gt, settings["match_iou"])
                tp = int((matches >= 0).sum())
                scene = image["file_name"].split("_")[0]
                per_scene[scene][0] += tp; per_scene[scene][1] += len(gt)
                rows.append({"file": image["file_name"], "scene": scene,
                             "altitude_m": float(Path(image["file_name"]).stem.split("_")[-1]),
                             "n_gt": len(gt), "n_detected": tp, "false_positives": len(pred)-tp})
                for p, match in zip(pred, matches):
                    writer.writerow([image["file_name"], *p.tolist(), int(match)])
                processed += 1
                if processed % 200 == 0 or processed == len(images):
                    print(f"[POP q] UAV={k+1} imgsz={size} images={processed}/{len(images)}", flush=True)
        with (evidence / f"counts_uav{k+1}.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
        success, total = sum(r["n_detected"] for r in rows), sum(r["n_gt"] for r in rows)
        counts = np.asarray(list(per_scene.values()))
        rng = np.random.default_rng(2026)
        bootstrap = counts[rng.integers(len(counts), size=(2000, len(counts)))].sum(axis=1)
        ratios = bootstrap[:, 0] / bootstrap[:, 1]
        estimates.append({"imgsz": size, "q": success/total, "detected": success, "n_gt": total,
                          "n_images": len(rows), "false_positives": sum(r["false_positives"] for r in rows),
                          "wilson_95_iid_approximation": wilson(success, total),
                          "scene_bootstrap_95": np.quantile(ratios, [.025, .975]).tolist(),
                          "by_scene": {s: {"detected": v[0], "n_gt": v[1], "q": v[0]/v[1]} for s, v in per_scene.items()}})
        print(f"[POP q] UAV={k+1}: {success}/{total} -> q={success/total:.6f}", flush=True)
    manifest = {"source": "POP_detector_empirical", "q_by_uav": [e["q"] for e in estimates], "imgsz": sizes,
                "estimates": estimates, "weights": str(weights.resolve()), "weights_sha256": sha256(weights),
                "training": training, "annotation_sha256": sha256(source_json), "split": "official val: F13-F16",
                "detector_settings": settings, "ultralytics": ultralytics.__version__, "torch": torch.__version__,
                "uncertainty_note": "Wilson assumes independent trials; neighboring frames are correlated. Scene bootstrap has only four groups; not a precision guarantee.",
                "sampling_note": "Recall is conditional on annotated/visible people, not on fully invisible/unlabelled victims.",
                "evidence": {p.name: sha256(p) for p in evidence.glob("*.csv")}}
    write_json(output, manifest)
    print(f"Saved empirical q: {output}", flush=True)
