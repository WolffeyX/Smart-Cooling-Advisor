import pytest

from app import config
from app.recommend import impact_line

BODY = {"day_type": "weekday", "forecast_max_temp_c": 31}


def _by(j):
    return {c["strategy"]: c["ec_energy_kwh"] for c in j["comparison"]}


def test_impact_matches_comparison(client):
    j = client.post("/recommend", json=BODY).json()
    e = _by(j)
    imp = j["impact"]
    for key, base in (("vs_always_full", "always_full"), ("vs_calendar_rule", "calendar_rule")):
        line = imp[key]
        assert line["kwh_saved"] == pytest.approx(e[base] - e["ai_forecast"], abs=0.1)
        assert line["co2_kg_saved"] == pytest.approx(line["kwh_saved"] * 0.740, abs=0.1)
    assert imp["grid_kg_per_kwh"] == 0.740
    assert "Peninsular" in imp["grid_source"]
    assert imp["label"] == "SIMULATED"


def test_impact_negative_when_ai_worse(client):
    # weekday 33.2 C selects 2024-10-23, where the weekday/weekend rule beats the AI
    j = client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": 33.2}).json()
    assert j["scenario"]["source_date"] == "2024-10-23"
    line = j["impact"]["vs_calendar_rule"]
    assert line["kwh_saved"] < 0
    assert line["co2_kg_saved"] < 0
    assert line["pct_saved"] < 0


def test_impact_ignores_override(client):
    a = client.post("/recommend", json=BODY).json()["impact"]
    b = client.post("/recommend", json={**BODY, "charge_target_override_rth": 9000}).json()
    assert b["operator_plan"] is not None
    assert b["impact"] == a


def test_pct_none_when_baseline_zero():
    line = impact_line(0.0, 0.0)
    assert line["pct_saved"] is None
    assert line["kwh_saved"] == 0.0
    assert impact_line(100.0, 90.0)["pct_saved"] == 10.0


def test_grid_constants():
    assert config.GRID_EMISSION_KG_PER_KWH == 0.740
    assert "Peninsular Malaysia 2024" in config.GRID_EMISSION_SOURCE


def test_ec_out_rt_is_load_plus_charge(client):
    j = client.post("/recommend", json=BODY).json()
    for r in j["hourly"]:
        assert r["ec_out_rt"] == pytest.approx(r["ec_load_rt"] + r["charge_rt"], abs=0.1)
        if r["ec_count"] == 0:
            assert r["ec_out_rt"] == 0
    assert any(r["ec_out_rt"] > 0 for r in j["hourly"])


def _levels(j):
    return {c["strategy"]: round(c["tank_level_21_rth"]) for c in j["comparison"]}


@pytest.mark.parametrize("temp", [31, 33.2])
def test_impact_note_has_21h_levels(client, temp):
    j = client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": temp}).json()
    note = j["impact"]["note"]
    lv = _levels(j)
    assert "SIMULATED" in note
    for k in ("always_full", "calendar_rule", "ai_forecast"):
        assert f"{lv[k]:,}" in note
    assert "overstates" not in note
    assert "flatters the AI" not in note


def test_impact_note_neutral_on_oct23(client):
    j = client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": 33.2}).json()
    assert j["scenario"]["source_date"] == "2024-10-23"
    assert "favours the plan that leaves less" in j["impact"]["note"]
