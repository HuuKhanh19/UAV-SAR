from pathlib import Path

import numpy as np
from pyproj import Transformer

from .io import read_json, sha256, write_json


def build(config, calibration_path, output):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Frozen instance already exists: {output}; choose a new --output")
    root = Path(config["data_root"])
    folder = root / "SAREnv" / "sarenv_dataset" / config["scenario"]
    meta = read_json(folder / "features.geojson")
    heat = np.load(folder / "heatmap.npy", allow_pickle=False)
    if heat.ndim != 2 or not heat.size or not np.isfinite(heat).all() or np.any(heat < 0) or heat.sum() > 1 + 1e-8:
        raise ValueError("Invalid SAREnv probability heatmap")
    calibration = read_json(calibration_path)
    if calibration.get("source") != "POP_detector_empirical":
        raise ValueError("An empirical POP detector calibration is required")
    expected_sizes = [u["detector_imgsz"] for u in config["uavs"]]
    if calibration["imgsz"] != expected_sizes:
        raise ValueError("UAV detector resolutions differ from the calibrated configurations")
    lon, lat = meta["center_point"]
    epsg = (32600 if lat >= 0 else 32700) + int((lon + 180) // 6) + 1
    cx, cy = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
    nominal_pixel = float(meta["meter_per_bin"])
    minx, miny, maxx, maxy = meta["bounds"]
    # SAREnv constructs pixel edges with linspace over these bounds. Integer
    # truncation of the bin count can make the actual X/Y spacing differ.
    pixel_x = (maxx - minx) / heat.shape[1]
    pixel_y = (maxy - miny) / heat.shape[0]
    if not np.isfinite([pixel_x, pixel_y]).all() or min(pixel_x, pixel_y) <= 0:
        raise ValueError("Invalid SAREnv raster bounds")
    block, cells = config["block_pixels"], config["crop_cells"]
    span = block * cells
    if min(block, cells) < 1 or span > min(heat.shape):
        raise ValueError("Crop does not fit the SAREnv heatmap")
    col = int(round((cx - minx) / pixel_x)) - span // 2
    row = int(round((cy - miny) / pixel_y)) - span // 2
    col, row = max(0, min(col, heat.shape[1]-span)), max(0, min(row, heat.shape[0]-span))
    crop = heat[row:row+span, col:col+span]
    mass = crop.reshape(cells, block, cells, block).sum(axis=(1, 3))
    xx, yy = np.meshgrid(minx + (col + (np.arange(cells)+0.5)*block)*pixel_x,
                         miny + (row + (np.arange(cells)+0.5)*block)*pixel_y)
    xy = np.column_stack([xx.ravel()-cx, yy.ravel()-cy])
    pi = mass.ravel()
    raw_mass = float(pi.sum())
    if raw_mass <= 0:
        raise ValueError("Selected crop has no probability mass")
    if config["prior_mode"] == "condition_on_crop":
        pi = pi / raw_mass
        outside_probability = 0.0
    elif config["prior_mode"] != "preserve_mass":
        raise ValueError("Unknown prior_mode")
    else:
        outside_probability = float(max(0, 1-raw_mass))
    fleet = config["uavs"]
    # Exchangeability transfer: all cells share POP's validation condition mixture.
    # Different UAV rows reflect measured inference resolutions, not invented sensors.
    q = np.repeat(np.asarray(calibration["q_by_uav"])[:, None], len(pi), axis=1)
    metadata = {"status": "pilot", "scenario": config["scenario"], "config": config,
                "source_manifest": read_json(root / "sources.json"),
                "heatmap_sha256": sha256(folder / "heatmap.npy"),
                "calibration": calibration, "calibration_sha256": sha256(calibration_path),
                "prior_mode": config["prior_mode"],
                "probability_semantics": ("conditional_on_target_in_mission_region"
                                          if config["prior_mode"] == "condition_on_crop" else "source_prior"),
                "raw_crop_mass": raw_mass,
                "raw_outside_probability": float(max(0, 1-raw_mass)),
                "outside_probability": outside_probability,
                "grid_shape": [cells, cells],
                "cell_size_m": nominal_pixel * block,  # Nominal size, retained for existing readers.
                "cell_size_xy_m": [pixel_x * block, pixel_y * block],
                "source_pixel_size_xy_m": [pixel_x, pixel_y],
                "grid_geometry": "pixel edges from bounds and heatmap shape; cell_size_m is nominal",
                "crop_pixel_origin": [row, col], "utm_epsg": epsg,
                "mapping": "q[k,j]=person-level recall for UAV k resolution, constant over cells; POP condition-mixture transfer assumption",
                "observation": "one designated detector frame in a fixed hover dwell; no independent multi-frame assumption",
                "physical_model": "2D Euclidean flight, common base at SAREnv center, time zero launch; no collision/no-fly/communication model"}
    data = {"xy": xy.tolist(), "pi": pi.tolist(), "q": q.tolist(), "bases": [[0., 0.]] * len(fleet),
            "speed": [u["speed_mps"] for u in fleet], "fly_w": [u["fly_w"] for u in fleet],
            "obs_w": [u["observe_w"] for u in fleet], "budget": [u["budget_wh"] for u in fleet],
            "deadline": config["deadline_s"], "tau": config["observation_s"], "metadata": metadata}
    from .problem import Instance
    # Validate before committing the frozen input file.
    Instance(**{k: np.asarray(data[k]) for k in ("xy", "pi", "q", "bases", "speed", "fly_w", "obs_w", "budget")},
             deadline=data["deadline"], tau=data["tau"], metadata=metadata)
    write_json(output, data)
    print(f"Frozen instance: N={len(pi)}, K={len(fleet)}, prior mass={pi.sum():.6f}, q={calibration['q_by_uav']}", flush=True)
    print(f"Saved {output}", flush=True)
