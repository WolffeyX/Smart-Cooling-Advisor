import numpy as np
import pandas as pd
import pytest

from app import model, recommend
from app.legacy import step5_plant
from app.scenario import select_day

REQ = {
    "day_type": "weekday",
    "forecast_max_temp_c": 31.0,
    "safety_margin_pct": 10,
    "tank_capacity_rth": 10000,
    "tank_level_22_rth": 1500,
    "forecast_error_pct": 0,
}
DAY_TYPES = ["weekday", "weekend", "exam_week", "semester_break"]


def _resp(bank, P, **kw):
    return recommend.build_response(bank, {**REQ, **kw}, P, round_values=False)


def _col(r, key):
    return np.array([h[key] for h in r["hourly"]])


@pytest.mark.parametrize("day_type", DAY_TYPES)
def test_blocks_sum_to_campus_load(bank, P, day_type):
    r = _resp(bank, P, day_type=day_type)
    for h in r["hourly"]:
        total = h["academic_rt"] + h["evening_rt"] + h["base_rt"]
        assert abs(total - h["campus_load_rt"]) < 1e-6


def test_academic_only_08_17_and_evening_only_18_21(bank, P):
    r = _resp(bank, P)
    ac, ev = _col(r, "academic_rt"), _col(r, "evening_rt")
    assert (ac[:10] == 0).all() and (ev[:10] == 0).all()
    assert (ev[10:20] == 0).all()
    assert (ac[20:24] == 0).all()


def test_weekend_has_no_academic_load(bank, P):
    r = _resp(bank, P, day_type="weekend")
    assert (_col(r, "academic_rt") == 0).all()


def test_semester_break_scales_blocks(bank, P):
    temp = 31.0
    assert select_day(bank, "weekday", temp) == select_day(bank, "semester_break", temp)
    wk = _resp(bank, P, day_type="weekday", forecast_max_temp_c=temp)
    sb = _resp(bank, P, day_type="semester_break", forecast_max_temp_c=temp)
    assert _col(sb, "academic_rt").sum() == pytest.approx(
        0.35 * _col(wk, "academic_rt").sum(), rel=1e-6
    )
    assert np.allclose(_col(sb, "base_rt"), _col(wk, "base_rt"))


def test_plant_echoes_capacity(bank, P):
    r = _resp(bank, P, tank_capacity_rth=12000)
    assert r["plant"]["tank_capacity_rth"] == 12000


def test_room_equivalents(bank, P):
    r = _resp(bank, P)
    n = r["plant"]["room_equivalents"]
    assert isinstance(n, int) and 1000 <= n <= 1500
    assert n == round(step5_plant.campus_load(bank.weather, P)[1])


def test_old_four_column_cache_is_rebuilt(tmp_path, P):
    w = model.load_weather()
    path = tmp_path / f"campus_load_2024_{model.load_hash(P)}.csv"
    pd.DataFrame({"time": w["time"], "total_rt": 1.0, "base_rt": 1.0, "room_rt": 0.0}).to_csv(
        path, index=False
    )
    fr = model.campus_load_frame(w, P, cache_dir=tmp_path)
    assert list(fr.columns) == model.LOAD_COLUMNS
    assert list(pd.read_csv(path, nrows=1).columns) == model.LOAD_COLUMNS
