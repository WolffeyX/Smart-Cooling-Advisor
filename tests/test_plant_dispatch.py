import numpy as np
import pandas as pd

from app import config, model, plant
from app.legacy import step5_plant

P = config.get_params("default")


def flat(v):
    return np.full(24, float(v))


def test_charges_only_at_night_and_discharges_only_by_day():
    load = np.array([1500] * 10 + [3200] * 14, float)  # 22..07 night, 08..21 day
    r = plant.dispatch_day(load, flat(30), plant.HOURS, 1500.0, 9000.0, P)
    assert (r["charge_rt"][10:] == 0).all() and (r["tank_out_rt"][:10] == 0).all()
    assert r["charge_rt"][:10].sum() > 0 and r["tank_out_rt"][10:].sum() > 0


def test_level_change_is_charge_eff_minus_out_minus_standby():
    load = np.array([1500] * 10 + [3200] * 14, float)
    r = plant.dispatch_day(load, flat(30), plant.HOURS, 1500.0, 9000.0, P)
    prev = np.r_[1500.0, r["tank_level_rth"][:-1]]
    assert np.allclose(
        r["tank_level_rth"] - prev,
        r["charge_rt"] * 0.95 - r["tank_out_rt"] - r["standby_loss_rth"],
        atol=1e-6,
    )
    assert np.allclose(r["standby_loss_rth"], prev * 0.004)


def test_tank_out_capped_at_max_discharge_and_level():
    r = plant.dispatch_day(flat(6000), flat(30), plant.HOURS, 10000.0, 10000.0, P)
    assert r["tank_out_rt"].max() <= 2500 + 1e-9 and r["tank_level_rth"].min() >= -1e-9


def test_unmet_when_ec_capacity_exceeded():
    r = plant.dispatch_day(flat(5000), flat(30), plant.HOURS, 0.0, 0.0, P)  # 2800 > 1300 EC
    assert np.allclose(r["unmet_rt"][10:], 2800 - 1300) and (r["ec_count"] <= 4).all()


def test_regression_oct_dec_matches_step5_plant_results():
    w = model.load_weather()
    load = model.campus_load_frame(w, P)["total_rt"].values
    g = step5_plant.daily_table(w, load, P)
    f = step5_plant.forecasts(g)
    ref = pd.read_csv(config.PLANT_RESULTS_CSV).set_index("strategy")["EC_MWh"]
    test = (w["month"] >= 10).values
    for name in ["always_full", "calendar_rule", "AI_plus_dayahead_weather", "perfect"]:
        tgt = {pd.Timestamp(k): v for k, v in f[name].items()}
        res = plant.dispatch_year(w, load, tgt, P, use_margin=(name != "perfect"))
        got = step5_plant.plant_kpis(w, res, test, name)["EC_MWh"]
        assert abs(got / ref[name] - 1) <= 0.005, (name, got, ref[name])
