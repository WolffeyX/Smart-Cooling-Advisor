import numpy as np
import pytest

from app import model

F2C = lambda f: (f - 32) * 5 / 9


@pytest.mark.parametrize("t_f,rh,nws_table_f", [(90, 70, 106), (96, 50, 108), (86, 90, 105)])
def test_heat_index_matches_nws(t_f, rh, nws_table_f):
    hi_f = model.heat_index_c(np.array([F2C(t_f)]), np.array([rh]))[0] * 9 / 5 + 32
    assert abs(hi_f - nws_table_f) <= 0.5  # NWS heat-index table values (degF)


def test_classifier_trained_jan_sep_scores_oct_dec():
    r = model.train_classifier(model.load_weather())
    assert r["train_months"] == set(range(1, 10)) and r["test_months"] == {10, 11, 12}
    assert abs(r["accuracy"] - 0.788) <= 0.005


def test_no_classifier_feature_uses_t_plus_3_or_later():
    w = model.load_weather()
    assert len(w) == 8784
    assert "target" not in model.CLASSIFIER_FEATURES and "cls_ahead" not in model.CLASSIFIER_FEATURES
    # every feature at row t equals a value computed from row t alone: perturb rows t+1.. and recompute
    w2 = w.copy()
    w2.loc[100:, ["temp", "rh", "cloud", "sw_rad", "wind", "rain"]] += 5.0
    from app.legacy import step1_model as s1
    cols = ["time", "temp", "rh", "cloud", "sw_rad", "wind", "rain"]
    f1 = s1.add_features(w[cols])
    f2 = s1.add_features(w2[cols])
    assert (f1.loc[:99, model.CLASSIFIER_FEATURES].values == f2.loc[:99, model.CLASSIFIER_FEATURES].values).all()
    assert (f1["target"].iloc[:97] == f1["cls"].shift(-3).iloc[:97]).all()  # target is exactly t+3
