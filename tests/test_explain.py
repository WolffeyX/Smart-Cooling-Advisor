import numpy as np
import pandas as pd
import pytest

from app.explain import FEATURE_INFO, N_REPEATS, _walk, explain_day
from app.model import FEATURE_PROVENANCE


def _ts(s):
    return pd.Timestamp(s)


def test_models_kept_and_predictions_unchanged(bank):
    fc = bank.forecasts
    assert set(fc.models) == {"oct_dec", *[f"m{i}" for i in range(1, 10)]}
    by_key: dict[str, list] = {}
    for D in fc.eligible:
        by_key.setdefault(fc.model_key_by_day[D], []).append(D)
    for k, days in by_key.items():
        preds = fc.models[k].predict(bank.features.loc[days])
        for D, pred in zip(days, preds, strict=True):
            assert pred == pytest.approx(fc.ai[D], abs=1e-9)
    assert fc.model_key_by_day[_ts("2024-10-23")] == "oct_dec"
    assert fc.model_key_by_day[_ts("2024-03-12")] == "m3"
    assert set(fc.calendar_by_model) == set(fc.models)


@pytest.mark.parametrize("day", ["2024-10-23", "2024-03-12"])
def test_tree_mean_equals_ai_forecast(bank, day):
    t = explain_day(bank, day)["trees"]
    assert abs(t["mean"] - bank.forecasts.ai[_ts(day)]) < 1e-6
    assert t["min"] <= t["p10"] <= t["median"] <= t["p90"] <= t["max"]
    assert sum(t["histogram"]["counts"]) == 400
    assert len(t["histogram"]["edges"]) == 21 and len(t["histogram"]["counts"]) == 20


@pytest.mark.parametrize("day", ["2024-10-23", "2024-03-12", "2024-10-09"])
def test_path_is_real(bank, day):
    r = explain_day(bank, day)
    p = r["path"]
    D = _ts(day)
    model = bank.forecasts.models[r["model_key"]]
    x = bank.features.loc[[D]]
    assert p["tree_index"] == 0
    assert len(p["splits"]) <= 5
    for s in p["splits"]:
        assert (s["direction"] == "≤") == (s["value"] <= s["threshold"])
        assert s["value"] == pytest.approx(float(x[s["feature"]].iloc[0]), rel=1e-6)
    assert p["depth"] == len(p["splits"]) + p["hidden_splits"]
    tree = model.estimators_[0]
    assert p["tree_prediction_rth"] == pytest.approx(float(tree.predict(x.to_numpy())[0]))
    samples = [s["samples"] for s in p["splits"]]
    assert samples == sorted(samples, reverse=True)
    # full walk agrees with sklearn's decision_path
    nodes = tree.decision_path(x.to_numpy()).indices
    n_split = sum(1 for n in nodes if tree.tree_.children_left[n] != -1)
    assert p["depth"] == n_split


def test_importance_shapes(bank):
    imp = explain_day(bank, "2024-10-23")["importance"]
    assert [i["name"] for i in imp] == list(FEATURE_PROVENANCE)
    assert sum(i["impurity"] for i in imp) == pytest.approx(1.0, abs=1e-6)
    assert all(i["permutation_mae_increase_rth"]["std"] >= 0 for i in imp)
    assert set(FEATURE_INFO) == set(FEATURE_PROVENANCE)


def test_never_trained_on_held_out(bank):
    od = explain_day(bank, "2024-10-23")
    assert od["held_out_months"] == [10, 11, 12]
    assert od["training_months"] == list(range(1, 10))
    m3 = explain_day(bank, "2024-03-12")
    assert m3["held_out_months"] == [3]
    assert 3 not in m3["training_months"]
    ok = bank.features.notna().all(axis=1)
    for r in (od, m3):
        n = int((ok & bank.features.index.month.isin(r["training_months"])).sum())
        assert r["n_training_days"] == n


def test_held_out_mae_matches_forecasts(bank):
    fc, daily = bank.forecasts, bank.daily
    d = fc.eligible[fc.eligible.month >= 10]
    r = explain_day(bank, "2024-10-23")
    assert r["held_out_mae_ai_rth"] == pytest.approx(
        float(np.mean(np.abs(fc.ai[d] - daily.loc[d, "need_rth"]))), rel=1e-9
    )
    assert r["held_out_mae_rule_rth"] == pytest.approx(
        float(np.mean(np.abs(fc.calendar[d] - daily.loc[d, "need_rth"]))), rel=1e-9
    )


def test_classifier_measured(bank):
    c = explain_day(bank, "2024-10-23")["classifier"]
    assert abs(c["accuracy"] - 0.788) < 0.005
    assert c["label"] == "MEASURED"


def test_ineligible_raises_keyerror(bank):
    for d in ("2024-01-03", "2023-06-01"):
        with pytest.raises(KeyError):
            explain_day(bank, d)


def test_api_ok(client):
    r = client.get("/explain", params={"source_date": "2024-10-23"})
    assert r.status_code == 200
    j = r.json()
    assert j["label"] == "SIMULATED"
    assert j["n_trees"] == 400 and j["min_samples_leaf"] == 3
    assert {f["name"]: f["provenance"] for f in j["features"]} == FEATURE_PROVENANCE
    assert all(f["label"] and "unit" in f for f in j["features"])


@pytest.mark.parametrize("d", ["2024-01-03", "2023-06-01"])
def test_api_404(client, d):
    r = client.get("/explain", params={"source_date": d})
    assert r.status_code == 404
    assert "no forecast for that day (eligible: 2024-01-08 to 2024-12-31)" == r.json()["detail"]


@pytest.mark.parametrize("d", ["2024-13-40", "abc"])
def test_api_422(client, d):
    assert client.get("/explain", params={"source_date": d}).status_code == 422


def test_api_missing_param_422(client):
    assert client.get("/explain").status_code == 422


def test_n_repeats():
    assert N_REPEATS == 5


def test_path_direction_consistent_on_every_day(bank):
    """direction == '≤' iff reported value <= threshold, on every eligible day (tree 0)."""
    fc = bank.forecasts
    names = list(FEATURE_PROVENANCE)
    for D in fc.eligible:
        tree = fc.models[fc.model_key_by_day[D]].estimators_[0]
        x = bank.features.loc[[D], names].to_numpy()
        splits = _walk(tree, x, names)
        nodes = tree.decision_path(x).indices
        assert len(splits) == sum(1 for n in nodes if tree.tree_.children_left[n] != -1)
        for s in splits:
            assert (s["direction"] == "≤") == (s["value"] <= s["threshold"]), (D, s)
