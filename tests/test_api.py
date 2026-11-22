import math
import time

import numpy as np
import pytest

from app import config, scenario


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "model_trained": True, "label": "SIMULATED"}


def test_recommend_shape(client):
    r = client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": 31})
    j = r.json()
    assert r.status_code == 200 and j["label"] == "SIMULATED" and len(j["hourly"]) == 24
    assert [c["strategy"] for c in j["comparison"]] == [
        "always_full",
        "calendar_rule",
        "ai_forecast",
    ]
    assert "training_months" in j["scenario"] and "forecast_kind" in j["scenario"]
    assert "ai_forecast_model_rth" in j["recommendation"]
    assert all("tank_level_21_rth" in c for c in j["comparison"])
    assert j["comparison"][0]["vs_always_full_pct"] is None


@pytest.mark.parametrize(
    "bad",
    [
        {"forecast_max_temp_c": 23.9},
        {"forecast_max_temp_c": 38.1},
        {"safety_margin_pct": 61},
        {"safety_margin_pct": -1},
        {"tank_capacity_rth": 4999},
        {"tank_capacity_rth": 25001},
        {"tank_level_22_rth": -1},
        {"forecast_error_pct": -31},
        {"forecast_error_pct": 31},
        {"day_type": "holiday"},
        {"tank_capacity_rth": 6000, "tank_level_22_rth": 7000},
    ],
)
def test_out_of_range_is_422(client, bad):
    body = {"day_type": "weekday", "forecast_max_temp_c": 31, **bad}
    assert client.post("/recommend", json=body).status_code == 422


def test_level_above_capacity_message(client):
    body = {
        "day_type": "weekday",
        "forecast_max_temp_c": 31,
        "tank_capacity_rth": 6000,
        "tank_level_22_rth": 7000,
    }
    r = client.post("/recommend", json=body)
    assert "tank_level_22_rth must be ≤ tank_capacity_rth" in r.text


def test_root_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200 and "SIMULATED" in r.text


@pytest.mark.slow
def _check_finite(node, path):
    if isinstance(node, dict):
        for k, v in node.items():
            _check_finite(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _check_finite(v, f"{path}[{i}]")
    elif node is None:
        assert path.endswith((".vs_always_full_pct", ".operator_plan", ".pct_saved")), (
            f"unexpected None at {path}"
        )
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        assert math.isfinite(node), f"non-finite at {path}"


def test_sweep_all_inputs_finite(client):
    for dt in ["weekday", "exam_week", "semester_break", "weekend"]:
        for t in np.arange(24, 38.01, 0.5):
            j = client.post(
                "/recommend", json={"day_type": dt, "forecast_max_temp_c": float(t)}
            ).json()
            _check_finite(j, "$")


def test_cold_start_under_60s(tmp_path):
    t = time.perf_counter()
    scenario.build_day_bank(config.get_params(), cache_dir=tmp_path)
    assert time.perf_counter() - t < 60


def test_three_vendored(client):
    r = client.get("/vendor/three/three.module.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert "REVISION = '170'" in r.text


@pytest.mark.parametrize("path", ["/plant3d.js", "/app.js"])
def test_js_served_as_javascript(client, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/javascript")
