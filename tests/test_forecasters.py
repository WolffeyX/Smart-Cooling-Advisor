from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from app import model
from app.config import get_params
from app.legacy import step5_plant


@pytest.fixture(scope="module")
def fx():
    P = get_params("default")
    w = model.load_weather()
    g = step5_plant.daily_table(w, model.campus_load_frame(w, P)["total_rt"].values, P)
    X = model.build_features(g)
    fc = model.train_forecasters(g, X)
    return SimpleNamespace(w=w, g=g, X=X, fc=fc)


def test_every_feature_has_provenance_and_none_is_same_day_observed(fx):
    assert list(fx.X.columns) == list(model.FEATURE_PROVENANCE)
    assert set(model.FEATURE_PROVENANCE.values()) <= {
        "observed_lag1", "observed_lag7", "calendar", "simulated_dayahead"}


def test_observed_features_use_only_previous_days(fx):
    g2 = fx.g.copy()
    d = pd.Timestamp("2024-11-15")
    g2.loc[d:, ["need_rth", "load_rth", "tmean", "himax", "rain"]] *= 3
    X2 = model.build_features(g2)
    lag = [c for c, k in model.FEATURE_PROVENANCE.items() if k.startswith("observed")]
    assert np.allclose(fx.X.loc[d, lag], X2.loc[d, lag])


def test_oct_dec_forecast_equals_step5_and_test_months_never_trained(fx):
    f5 = step5_plant.forecasts(fx.g)["AI_plus_dayahead_weather"]
    od = fx.fc.ai.index[fx.fc.ai.index.month >= 10]
    assert np.allclose(fx.fc.ai[od], f5[od])
    for day, months in fx.fc.training_months.items():
        assert not ({10, 11, 12} & set(months))
        if day.month <= 9:
            assert day.month not in months and len(months) == 8
        else:
            assert months == list(range(1, 10))


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
