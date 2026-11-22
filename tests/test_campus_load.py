import os

import numpy as np
import pandas as pd

from app import config, model
from app.legacy import step5_plant


def test_load_matches_step5_and_writes_cache(tmp_path):
    w = model.load_weather()
    p = config.get_params("default")
    fr = model.campus_load_frame(w, p, cache_dir=tmp_path)
    expected, _ = step5_plant.campus_load(w, p)
    assert len(fr) == 8784 and np.allclose(fr["total_rt"], expected)
    assert np.allclose(fr["base_rt"] + fr["room_rt"], fr["total_rt"])
    assert (tmp_path / f"campus_load_2024_{model.load_hash(p)}.csv").exists()


def test_cache_is_reused(tmp_path, monkeypatch):
    w = model.load_weather()
    p = config.get_params("default")
    first = model.campus_load_frame(w, p, cache_dir=tmp_path)

    def boom(*a, **k):
        raise AssertionError("rebuilt")

    monkeypatch.setattr(model.step5_plant, "campus_load", boom)
    fr = model.campus_load_frame(w, p, cache_dir=tmp_path)
    assert len(fr) == 8784
    pd.testing.assert_frame_equal(fr, first)


def test_truncated_cache_is_rebuilt(tmp_path):
    w = model.load_weather()
    p = config.get_params("default")
    first = model.campus_load_frame(w, p, cache_dir=tmp_path)
    path = tmp_path / f"campus_load_2024_{model.load_hash(p)}.csv"
    lines = path.read_text().splitlines()[:11]
    path.write_text(os.linesep.join(lines) + os.linesep)
    fr = model.campus_load_frame(w, p, cache_dir=tmp_path)
    assert len(fr) == 8784
    assert len(pd.read_csv(path)) == 8784
    pd.testing.assert_frame_equal(fr, first)


def test_hash_changes_with_load_params_not_plant_params():
    p = config.get_params("default")
    assert model.load_hash(p) != model.load_hash({**p, "target_peak_rt": 3600.0})
    assert model.load_hash(p) == model.load_hash(config.get_params("published_utp_data"))


def test_room_part_zero_on_weekend_daytime():
    w = model.load_weather()
    fr = model.campus_load_frame(w, config.get_params("default"))
    assert np.allclose(fr.loc[~w["weekday"].values, "room_rt"], 0, atol=1e-6)
