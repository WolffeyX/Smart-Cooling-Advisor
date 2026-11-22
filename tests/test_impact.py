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
