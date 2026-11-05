"""Regression checks for mission conditioning and SAREnv raster geometry."""
from dataclasses import replace

import numpy as np
import pytest
from pyproj import Transformer

from uav_sar.instance import build
from uav_sar.io import read_json, write_json
from uav_sar.problem import Instance


@pytest.fixture
def raster_inputs(tmp_path):
    # Synthetic unit-test data: 8 columns x 6 rows, 10 m x 20 m source pixels.
    folder = tmp_path / "SAREnv" / "sarenv_dataset" / "1"
    folder.mkdir(parents=True)
    cx, cy = Transformer.from_crs(4326, 32631, always_xy=True).transform(0., 0.)
    write_json(folder / "features.geojson", {
        "center_point": [0., 0.], "meter_per_bin": 10,
        "bounds": [cx-40, cy-60, cx+40, cy+60],
    })
    heat = np.ones((6, 8))
    heat[1, 2] = 2.
    np.save(folder / "heatmap.npy", heat / 49)
    write_json(tmp_path / "sources.json", {"unit_test_fixture": True})
    calibration = tmp_path / "calibration.json"
    write_json(calibration, {"source": "POP_detector_empirical", "imgsz": [320], "q_by_uav": [.75]})
    config = {"data_root": str(tmp_path), "scenario": "1", "crop_cells": 2, "block_pixels": 2,
              "prior_mode": "condition_on_crop", "deadline_s": 100., "observation_s": 1.,
              "uavs": [{"detector_imgsz": 320, "speed_mps": 10., "fly_w": 180.,
                        "observe_w": 200., "budget_wh": 10.}]}
    return config, calibration, tmp_path / "instance.json"


@pytest.mark.parametrize("mode", ["condition_on_crop", "preserve_mass"])
def test_build_uses_actual_pixel_edges_and_preserves_source_probability(raster_inputs, mode):
    config, calibration, output = raster_inputs
    config["prior_mode"] = mode
    build(config, calibration, output)
    data = read_json(output)
    instance = Instance.load(output)
    # Crop rows 1..4, columns 2..5. First block contains the extra probability.
    expected = np.array([5., 4., 4., 4.]) / (17 if mode == "condition_on_crop" else 49)
    np.testing.assert_allclose(instance.pi, expected)
    np.testing.assert_allclose(instance.xy, [[-10., -20.], [10., -20.], [-10., 20.], [10., 20.]])
    meta = data["metadata"]
    assert meta["crop_pixel_origin"] == [1, 2]
    assert meta["cell_size_xy_m"] == [20., 40.]
    assert meta["raw_crop_mass"] == pytest.approx(17/49)
    assert meta["raw_outside_probability"] == pytest.approx(32/49)
    assert meta["outside_probability"] == pytest.approx(0 if mode == "condition_on_crop" else 32/49)
    assert instance.pi.sum() == pytest.approx(1 if mode == "condition_on_crop" else 17/49)
    expected_label = "target in mission region" if mode == "condition_on_crop" else "source prior"
    assert expected_label in instance.probability_label
    # Frozen inputs cannot be silently replaced by a later build.
    before = output.read_bytes()
    with pytest.raises(FileExistsError):
        build(config, calibration, output)
    assert output.read_bytes() == before


def test_conditioning_scales_detection_but_not_routes_energy_or_normalized_objectives(raster_inputs):
    config, calibration, output = raster_inputs
    config["prior_mode"] = "preserve_mass"
    build(config, calibration, output)
    original = Instance.load(output)
    mass = float(original.pi.sum())
    conditional = replace(original, pi=original.pi/mass, metadata={"prior_mode": "condition_on_crop"})
    for route in [[], [0], [1, 3], [0, 1, 3, 2]]:
        old = original.evaluate_routes([route])
        new = conditional.evaluate_routes([route])
        assert new["p_detect"] == pytest.approx(old["p_detect"]/mass)
        assert new["routes"] == old["routes"]
        assert new["energy_wh"] == old["energy_wh"]
        np.testing.assert_allclose(conditional.objectives(new), original.objectives(old))
    assert conditional.probability_upper_bound == pytest.approx(.75)
    with pytest.raises(ValueError, match="sum to one"):
        replace(original, metadata={"prior_mode": "condition_on_crop"})
