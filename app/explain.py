"""Random-forest explainer: real numbers from the real fitted forecasters (no leakage).

Permutation importance and held-out MAE are computed only on each model's held-out days
(Oct-Dec for "oct_dec", month m for "mN"), never on months the model was trained on.
"""

from itertools import pairwise

import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance

from app.model import FEATURE_PROVENANCE, DailyForecasts, train_classifier

N_REPEATS = 5
N_PATH_SPLITS = 5
N_BINS = 20

FEATURE_INFO: dict[str, tuple[str, str]] = {
    "need_today": ("Today's tank need", "RTh"),
    "load_today": ("Today's total campus load", "RT·h"),
    "tmean_today": ("Today's mean temperature", "°C"),
    "himax_today": ("Today's max heat index", "°C"),
    "rain_today": ("Today's rain", "mm"),
    "need_lastweek": ("Tank need 7 days ago", "RTh"),
    "dow_tomorrow": ("Day of week tomorrow (0 = Mon)", ""),
    "weekday_tomorrow": ("Tomorrow is a weekday (1/0)", ""),
    "month": ("Month", ""),
    "fc_tmax": ("Forecast max temperature tomorrow", "°C"),
    "fc_sw": ("Forecast solar radiation tomorrow", "W/m²·h"),
    "fc_rain": ("Forecast rain tomorrow", "mm"),
}


def _held_out_months(key: str) -> list[int]:
    return [10, 11, 12] if key == "oct_dec" else [int(key[1:])]


def compute_explain_stats(
    daily: pd.DataFrame, X: pd.DataFrame, forecasts: DailyForecasts, weather: pd.DataFrame
) -> dict:
    """Per-model held-out MAE (AI vs calendar rule), permutation and impurity importances."""
    ok = X.notna().all(axis=1)
    months = pd.Series(X.index.month, index=X.index)
    models: dict = {}
    for key, model in forecasts.models.items():
        held_months = _held_out_months(key)
        held = ok & months.isin(held_months)
        train_months = sorted(forecasts.training_months[X.index[held][0]])
        n_train = int((ok & months.isin(train_months)).sum())
        y = daily.loc[held, "need_rth"]
        rule = daily.loc[held, "dow"].map(forecasts.calendar_by_model[key])
        saved = model.n_jobs
        model.n_jobs = 1  # joblib spawn overhead dominates on ~30-90 rows
        try:
            perm = permutation_importance(
                model,
                X[held],
                y,
                scoring="neg_mean_absolute_error",
                n_repeats=N_REPEATS,
                random_state=0,
            )
        finally:
            model.n_jobs = saved
        names = list(X.columns)
        models[key] = {
            "held_out_months": held_months,
            "training_months": train_months,
            "n_training_days": n_train,
            # score = -MAE, so mean score drop == MAE increase in RTh (positive = shuffling hurts)
            "held_out_mae_ai_rth": float(np.mean(np.abs(forecasts.ai[held] - y))),
            "held_out_mae_rule_rth": float(np.mean(np.abs(rule - y))),
            "permutation": {
                n: (float(m), float(s))
                for n, m, s in zip(names, perm.importances_mean, perm.importances_std)
            },
            "impurity": {n: float(v) for n, v in zip(names, model.feature_importances_)},
        }
    return {"models": models, "classifier": train_classifier(weather), "n_repeats": N_REPEATS}


def _walk(tree, x: np.ndarray, feature_names: list[str]) -> list[dict]:
    """Every split node on x's path through one tree, in order (via sklearn's decision_path)."""
    t = tree.tree_
    nodes = tree.decision_path(x).indices
    splits = []
    for node, nxt in pairwise(nodes):
        f = int(t.feature[node])
        splits.append(
            {
                "feature": feature_names[f],
                "label": FEATURE_INFO[feature_names[f]][0],
                "threshold": float(t.threshold[node]),
                "value": float(x[0, f]),
                "direction": "≤" if nxt == t.children_left[node] else ">",
                "samples": int(t.n_node_samples[node]),
                "node_mean_rth": float(t.value[node][0][0]),
            }
        )
    return splits


def explain_day(bank, source_date: str) -> dict:
    """Spec 6.4 payload for one historical day. Raises KeyError if the day has no forecast."""
    try:
        D = pd.Timestamp(source_date)
    except ValueError as e:
        raise KeyError(source_date) from e
    fc = bank.forecasts
    if D not in fc.model_key_by_day:
        raise KeyError(source_date)
    key = fc.model_key_by_day[D]
    model = fc.models[key]
    stats = bank.explain_stats["models"][key]
    names = list(FEATURE_PROVENANCE)
    x = bank.features.loc[[D], names].to_numpy()

    preds = np.array([e.predict(x)[0] for e in model.estimators_])
    counts, edges = np.histogram(preds, bins=N_BINS)
    p10, med, p90 = np.percentile(preds, [10, 50, 90])

    tree = model.estimators_[0]
    all_splits = _walk(tree, x, names)
    cls = bank.explain_stats["classifier"]
    return {
        "source_date": D.strftime("%Y-%m-%d"),
        "model_key": key,
        "training_months": stats["training_months"],
        "n_training_days": stats["n_training_days"],
        "n_trees": len(model.estimators_),
        "min_samples_leaf": model.min_samples_leaf,
        "held_out_months": stats["held_out_months"],
        "held_out_mae_ai_rth": stats["held_out_mae_ai_rth"],
        "held_out_mae_rule_rth": stats["held_out_mae_rule_rth"],
        "features": [
            {
                "name": n,
                "label": FEATURE_INFO[n][0],
                "value": float(x[0, i]),
                "unit": FEATURE_INFO[n][1],
                "provenance": FEATURE_PROVENANCE[n],
            }
            for i, n in enumerate(names)
        ],
        "importance": [
            {
                "name": n,
                "permutation_mae_increase_rth": {
                    "mean": stats["permutation"][n][0],
                    "std": stats["permutation"][n][1],
                },
                "impurity": stats["impurity"][n],
            }
            for n in names
        ],
        "trees": {
            "mean": float(preds.mean()),
            "min": float(preds.min()),
            "p10": float(p10),
            "median": float(med),
            "p90": float(p90),
            "max": float(preds.max()),
            "histogram": {
                "edges": [float(e) for e in edges],
                "counts": [int(c) for c in counts],
            },
        },
        "path": {
            "tree_index": 0,
            "tree_prediction_rth": float(tree.predict(x)[0]),
            "depth": len(all_splits),
            "hidden_splits": max(len(all_splits) - N_PATH_SPLITS, 0),
            "splits": all_splits[:N_PATH_SPLITS],
        },
        "classifier": {
            "accuracy": cls["accuracy"],
            "train_months": sorted(cls["train_months"]),
            "test_months": sorted(cls["test_months"]),
            "label": "MEASURED",
        },
        "label": "SIMULATED",
    }
