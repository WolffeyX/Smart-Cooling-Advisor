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


@pytest.fixture(scope="module")
def utp_bank():
    from app.scenario import build_day_bank

    return build_day_bank(config.get_params("published_utp_data"))


def test_comparison_rows_carry_tank_level_at_21(bank):
    req = {**REQ, "tank_level_22_rth": 1500}
    r = recommend.build_response(bank, req, config.get_params("default"), round_values=False)
    for row in r["comparison"]:
        assert "tank_level_21_rth" in row
    assert r["comparison"][2]["tank_level_21_rth"] == r["hourly"][-1]["tank_level_rth"]
    assert r["comparison"][0]["tank_level_21_rth"] > r["comparison"][2]["tank_level_21_rth"]
    assert any("Single-day comparison (SIMULATED)" in a for a in r["assumptions"])


def test_message_ok_with_daytime_ec(bank):
    rec = run(bank)["recommendation"]
    assert rec["status"] == "ok" and rec["daytime_ec_hours"] > 0
    n = rec["daytime_ec_hours"]
    assert rec["message"].startswith(
        f"No cooling shortfall, but the tank runs out and electric chillers run {n} daytime hour"
    )


def test_message_capped_no_daytime_ec(bank):
    rec = run(bank, tank_capacity_rth=5000, forecast_max_temp_c=24, forecast_error_pct=30)[
        "recommendation"
    ]
    assert rec["status"] == "capped" and rec["daytime_ec_hours"] == 0
    assert rec["message"].startswith("Target capped at tank capacity (5,000 RTh)")
    assert "the tank still covers tomorrow." in rec["message"]


def test_message_unreachable_target(bank):
    rec = run(
        bank,
        tank_capacity_rth=25000,
        safety_margin_pct=60,
        tank_level_22_rth=0,
        forecast_max_temp_c=34,
    )["recommendation"]
    assert "can only charge" in rec["message"]


def test_message_shortfall(utp_bank):
    req = {**REQ, "forecast_max_temp_c": 34, "tank_capacity_rth": 5000}
    p = config.get_params("published_utp_data")
    r = recommend.build_response(utp_bank, req, p, round_values=False)
    rec = r["recommendation"]
    assert rec["status"] == "shortfall" and rec["shortfall_rth"] > 0
    assert rec["shortfall_rth"] == pytest.approx(sum(h["unmet_rt"] for h in r["hourly"]))
    assert "even with all electric chillers running" in rec["message"]


def test_semester_break_over_charge_is_flagged(bank):
    rec = run(bank, day_type="semester_break")["recommendation"]
    assert "unused" in rec["message"]
    assert rec["over_charged"] is True


@pytest.mark.parametrize("temp", [31.0, 34.0])
def test_weekday_not_flagged_over_charged(bank, temp):
    rec = run(bank, forecast_max_temp_c=temp)["recommendation"]
    assert "unused" not in rec["message"]
    assert rec["over_charged"] is False
