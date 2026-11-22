from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import model
from app.config import get_params
from app.legacy import step1_model, step5_plant


@pytest.fixture(scope="module")
def fx():
    P = get_params("default")
    w = model.load_weather()
    g = step5_plant.daily_table(w, model.campus_load_frame(w, P)["total_rt"].values, P)
    rt = model.campus_load_frame(w, P)["total_rt"].values
    X = model.build_features(g, w, rt)
    fc = model.train_forecasters(g, X)
    return SimpleNamespace(w=w, g=g, X=X, fc=fc, P=P, rt=rt)


def test_every_feature_has_provenance_and_none_is_same_day_observed(fx):
    assert list(fx.X.columns) == list(model.FEATURE_PROVENANCE)
    assert set(model.FEATURE_PROVENANCE.values()) <= {
        "observed_lag1", "observed_lag7", "calendar", "simulated_dayahead"}


def _rebuild(fx, w2, rt2):
    g2 = step5_plant.daily_table(w2, rt2, fx.P)
    return model.build_features(g2, w2, rt2)


def _perturb(fx, hours, day):
    w2 = fx.w.copy()
    rt2 = fx.rt.copy()
    sel = (w2["time"].dt.normalize() == day) & w2["time"].dt.hour.isin(hours)
    w2.loc[sel, ["temp", "rh", "rain"]] += 5
    rt2[sel.values] += 5
    return step1_model.add_features(w2.drop(columns=["hi", "cls", "hour", "month", "weekday", "target"])), rt2


def test_features_use_only_hours_before_22h_of_previous_day(fx):
    D = pd.Timestamp("2024-11-15")
    prev = D - pd.Timedelta(days=1)
    non_fc = [c for c in fx.X.columns if not c.startswith("fc_")]
    X2 = _rebuild(fx, *_perturb(fx, [22, 23], prev))
    assert np.allclose(fx.X.loc[D, non_fc], X2.loc[D, non_fc])
    # negative control: 21:00 is known at 22:00, so perturbing it must change a lag-1 feature
    X3 = _rebuild(fx, *_perturb(fx, [21], prev))
    lag1 = [c for c, k in model.FEATURE_PROVENANCE.items() if k == "observed_lag1"]
    assert not np.allclose(fx.X.loc[D, lag1], X3.loc[D, lag1])


def test_test_months_never_trained(fx):
    for day, months in fx.fc.training_months.items():
        assert not ({10, 11, 12} & set(months))
        if day.month <= 9:
            assert day.month not in months and len(months) == 8
        else:
            assert months == list(range(1, 10))


def test_oct_dec_close_to_step5(fx):
    f5 = step5_plant.forecasts(fx.g)["AI_plus_dayahead_weather"]
    od = fx.fc.ai.index[fx.fc.ai.index.month >= 10]
    mae = (fx.fc.ai[od] - f5[od]).abs().mean()
    assert mae < 0.10 * fx.g.loc[od, "need_rth"].mean()


def test_eligible_days(fx):
    assert fx.fc.eligible[0] == pd.Timestamp("2024-01-08")
    assert fx.fc.eligible[-1] == pd.Timestamp("2024-12-31")
    assert fx.fc.ai[fx.fc.eligible].notna().all()
    assert fx.fc.calendar[fx.fc.eligible].notna().all()


def test_jan_sep_forecast_is_out_of_sample(fx):
    d = pd.Timestamp("2024-05-14")
    g2 = fx.g.copy()
    g2.loc[g2.index.month == 5, "need_rth"] = 0.0
    fc2 = model.train_forecasters(g2, fx.X)
    assert fc2.ai[d] == pytest.approx(fx.fc.ai[d])
