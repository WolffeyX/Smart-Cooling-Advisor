"""Operator charge-target override and operator_plan."""

import json

from app import recommend
from app.plant import HOURS, dispatch_day, summarise_day
from app.scenario import build_scenario

BODY = {"day_type": "weekday", "forecast_max_temp_c": 31}


def _post(client, **kw):
    r = client.post("/recommend", json={**BODY, **kw})
    assert r.status_code == 200, r.text
    return r


def _ai_row(j):
    return next(c for c in j["comparison"] if c["strategy"] == "ai_forecast")


def test_no_override_unchanged(client):
    a = _post(client)
    b = _post(client, charge_target_override_rth=None)
    assert a.content == b.content
    j = a.json()
    assert j["operator_plan"] is None
    assert j["hourly"][-1]["tank_level_rth"] == _ai_row(j)["tank_level_21_rth"]


def test_override_adds_operator_plan_and_hourly_follows_it(client, bank, P):
    base = _post(client).json()
    j = _post(client, charge_target_override_rth=9000).json()
    op = j["operator_plan"]
    assert op["charge_target_rth"] == 9000
    assert j["recommendation"] == base["recommendation"]
    assert j["comparison"] == base["comparison"]
    assert j["hourly"][-1]["tank_level_rth"] == op["tank_level_21_rth"]
    assert [h["academic_rt"] for h in j["hourly"]] == [h["academic_rt"] for h in base["hourly"]]
    p = {**P, "tes_capacity_rth": 10000.0}
    sc = build_scenario(bank, "weekday", 31.0, p)
    s = summarise_day(dispatch_day(sc.load_rt, sc.t_out, HOURS, 1500.0, 9000.0, p))
    assert op["ec_energy_kwh"] == round(s["ec_energy_kwh"], 1)
    assert op["status"] in ("ok", "shortfall")
    assert isinstance(op["message"], str) and op["message"]


def test_override_equal_to_ai_target_matches_ai_row(client):
    base = _post(client).json()
    ai = _ai_row(base)
    j = _post(client, charge_target_override_rth=base["recommendation"]["charge_target_rth"]).json()
    assert j["operator_plan"]["ec_energy_kwh"] == ai["ec_energy_kwh"]
    assert j["operator_plan"]["vs_always_full_pct"] == ai["vs_always_full_pct"]


def test_override_zero_on_hot_day_reports_daytime_ec(client):
    j = _post(client, forecast_max_temp_c=34, charge_target_override_rth=0).json()
    op = j["operator_plan"]
    assert op["daytime_ec_hours"] > 0
    assert "electric chillers" in op["message"]


def test_override_over_capacity_422(client):
    r = client.post(
        "/recommend",
        json={**BODY, "tank_capacity_rth": 8000, "charge_target_override_rth": 8001},
    )
    assert r.status_code == 422


def test_override_negative_422(client):
    r = client.post("/recommend", json={**BODY, "charge_target_override_rth": -1})
    assert r.status_code == 422


def test_build_response_direct_no_override(bank, P):
    req = {
        "day_type": "weekday",
        "forecast_max_temp_c": 31,
        "safety_margin_pct": 10,
        "tank_capacity_rth": 10000,
        "tank_level_22_rth": 1500,
        "forecast_error_pct": 0,
    }
    r = recommend.build_response(bank, req, P)
    assert r.get("operator_plan") is None
    json.dumps(r)
