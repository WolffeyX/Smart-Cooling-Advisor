import pytest

from app import config, recommend

BASE = {
    "day_type": "weekday",
    "forecast_max_temp_c": 31.0,
    "safety_margin_pct": 10,
    "tank_capacity_rth": 10000,
    "tank_level_22_rth": 1500,
    "forecast_error_pct": 0,
}

SCENARIOS = [
    {"forecast_max_temp_c": 34},
    {"forecast_max_temp_c": 29},
    {"day_type": "weekend", "forecast_max_temp_c": 30},
    {"day_type": "semester_break"},
    {"tank_capacity_rth": 5000},
    {"tank_capacity_rth": 25000},
    {"safety_margin_pct": 0},
    {"safety_margin_pct": 60},
    {"day_type": "exam_week", "forecast_max_temp_c": 32},
    {"forecast_error_pct": -30},
    {"forecast_error_pct": 30},
]


@pytest.mark.parametrize("kw", SCENARIOS, ids=lambda k: ",".join(f"{a}={b}" for a, b in k.items()))
def test_energy_balance(bank, kw):
    req = {**BASE, **kw}
    p = config.get_params("default")
    cap = req["tank_capacity_rth"]
    r = recommend.build_response(bank, req, p, round_values=False)
    for i, h in enumerate(r["hourly"]):
        assert h["sac_rt"] + h["tank_out_rt"] + h["ec_load_rt"] + h["unmet_rt"] == pytest.approx(
            h["campus_load_rt"], abs=1e-6
        )
        assert h["ec_load_rt"] + h["charge_rt"] <= 4 * 325 + 1e-6
        assert -1e-9 <= h["tank_level_rth"] <= cap + 1e-6
        night = i < 10
        if night:
            assert h["tank_out_rt"] == 0
        else:
            assert h["charge_rt"] == 0
        prev = req["tank_level_22_rth"] if i == 0 else r["hourly"][i - 1]["tank_level_rth"]
        assert h["tank_level_rth"] - prev == pytest.approx(
            h["charge_rt"] * 0.95 - h["tank_out_rt"] - prev * 0.004, abs=1e-6
        )
    rec = r["recommendation"]
    assert rec["shortfall_rth"] == pytest.approx(sum(h["unmet_rt"] for h in r["hourly"]), abs=0.1)
