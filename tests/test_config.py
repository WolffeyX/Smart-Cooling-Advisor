from app import config
from app.legacy import step5_plant


def test_default_preset_equals_step5_plant():
    assert config.get_params("default") == step5_plant.PLANT


def test_get_params_returns_fresh_copy():
    p = config.get_params("default")
    p["sac_available_rt"] = 1.0
    p["night_hours"].append(99)
    assert config.get_params("default")["sac_available_rt"] == 2200.0
    assert 99 not in config.get_params("default")["night_hours"]
    assert step5_plant.PLANT["sac_available_rt"] == 2200.0


def test_published_preset_values():
    p = config.get_params("published_utp_data")
    assert (
        p["standby_loss_per_h"],
        p["kw_per_rt_full"],
        p["kw_per_rt_aux"],
        p["sac_available_rt"],
    ) == (0.0005, 0.82, 0.24, 1800.0)
    assert config.PRESET_LABELS["published_utp_data"] == "ASSUMPTION"


def test_env_var_selects_preset(monkeypatch):
    monkeypatch.setenv("SCA_PARAMS_PRESET", "published_utp_data")
    assert config.get_params()["sac_available_rt"] == 1800.0


def test_unknown_preset_raises():
    import pytest

    with pytest.raises(ValueError):
        config.get_params("nope")


def test_multipliers():
    assert config.DAY_TYPE_MULTIPLIERS == {
        "weekday": 1.0,
        "weekend": 1.0,
        "exam_week": 0.9,
        "semester_break": 0.35,
    }
