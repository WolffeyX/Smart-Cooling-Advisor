import math

import pytest

from app import config, recommend

REQ = {
    "day_type": "weekday",
    "forecast_max_temp_c": 31.0,
    "safety_margin_pct": 10,
    "tank_capacity_rth": 10000,
    "tank_level_22_rth": 1500,
    "forecast_error_pct": 0,
}


def run(bank, **kw):
    return recommend.build_response(bank, {**REQ, **kw}, config.get_params("default"))


def test_always_full_target_is_capacity(bank):
    assert run(bank, tank_capacity_rth=12000)["comparison"][0]["charge_target_rth"] == 12000


def test_zero_error_zero_margin_target_equals_model_forecast(bank):
    r = run(bank, safety_margin_pct=0)
    rec = r["recommendation"]
    assert rec["charge_target_rth"] == pytest.approx(
        min(10000, rec["ai_forecast_model_rth"]), abs=0.1
    )


@pytest.mark.parametrize(
    "temp,margin,cap", [(31, 10, 10000), (34, 60, 5000), (29, 0, 25000), (34, 10, 10000)]
)
def test_capped_flag(bank, temp, margin, cap):
    rec = run(bank, forecast_max_temp_c=temp, safety_margin_pct=margin, tank_capacity_rth=cap)[
        "recommendation"
    ]
    assert rec["capped"] == (rec["ai_forecast_need_rth"] * (1 + margin / 100) > cap)


def test_error_slider_moves_forecast_not_actual(bank):
    a, b = run(bank)["recommendation"], run(bank, forecast_error_pct=-20)["recommendation"]
    assert b["actual_need_rth"] == a["actual_need_rth"]
    assert b["ai_forecast_need_rth"] == pytest.approx(0.8 * a["ai_forecast_model_rth"], abs=0.1)


def test_order_and_shape(bank):
    r = run(bank)
    assert [c["strategy"] for c in r["comparison"]] == [
        "always_full",
        "calendar_rule",
        "ai_forecast",
    ]
    assert r["comparison"][0]["vs_always_full_pct"] is None and len(r["hourly"]) == 24
    assert r["hourly"][0]["hour"] == "22:00" and r["hourly"][-1]["hour"] == "21:00"
    assert r["label"] == "SIMULATED"
    assert {"training_months", "forecast_kind", "source_date"} <= set(r["scenario"])
    assert len(r["assumptions"]) >= 7


def test_full_tank_semester_break_has_no_charging(bank):  # Review Focus 3
    r = run(bank, day_type="semester_break", tank_level_22_rth=10000)
    assert r["recommendation"]["electric_chillers"] == {"count": 0, "start": "—", "end": "—"}
    assert all(
        c["vs_always_full_pct"] is None or math.isfinite(c["vs_always_full_pct"])
        for c in r["comparison"]
    )


def test_vs_pct_handles_zero_baseline():
    assert recommend.vs_always_full_pct(0.0, 0.0) is None
    assert recommend.vs_always_full_pct(90.0, 100.0) == -10.0
