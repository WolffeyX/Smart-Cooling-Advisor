"""
Smart Cooling Advisor - Step 1: heat index, labels, 3-hours-ahead model and baselines.

Input : data/seri_iskandar_2024_openmeteo.csv  (Open-Meteo hourly, 2024, Seri Iskandar)
Output: data/predictions.csv  (one row per hour with actual and predicted classes)
        printed metrics table

Run   : python step1_model.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, recall_score

HORIZON = 3              # hours ahead
CLASSES = ["Low", "Medium", "High"]
RANDOM_STATE = 42


# ---------------------------------------------------------------- data
def load_openmeteo(path):
    df = pd.read_csv(path, skiprows=3)          # first 3 lines are location metadata
    df.columns = ["time", "temp", "rh", "cloud", "sw_rad", "wind", "rain"]
    df["time"] = pd.to_datetime(df["time"])
    return df


def heat_index_c(t_c, rh):
    """US National Weather Service heat index (Rothfusz + adjustments). Input/Output in degC."""
    t = t_c * 9 / 5 + 32
    simple = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + rh * 0.094)
    hi = np.where((simple + t) / 2 < 80, simple, np.nan)
    roth = (-42.379 + 2.04901523 * t + 10.14333127 * rh - 0.22475541 * t * rh
            - 6.83783e-3 * t ** 2 - 5.481717e-2 * rh ** 2 + 1.22874e-3 * t ** 2 * rh
            + 8.5282e-4 * t * rh ** 2 - 1.99e-6 * t ** 2 * rh ** 2)
    adj_low = ((13 - rh) / 4) * np.sqrt(np.clip((17 - np.abs(t - 95.0)) / 17, 0, None))
    roth = np.where((rh < 13) & (t >= 80) & (t <= 112), roth - adj_low, roth)
    adj_high = ((rh - 85) / 10) * ((87 - t) / 5)
    roth = np.where((rh > 85) & (t >= 80) & (t <= 87), roth + adj_high, roth)
    hi = np.where(np.isnan(hi), roth, hi)
    return (hi - 32) * 5 / 9


def to_class(hi):
    return np.select([hi >= 32, hi >= 27], [2, 1], default=0)   # 0 Low, 1 Medium, 2 High


def add_features(df):
    df = df.copy()
    df["hi"] = heat_index_c(df["temp"].values, df["rh"].values)
    df["cls"] = to_class(df["hi"].values)
    df["hour"] = df["time"].dt.hour
    df["month"] = df["time"].dt.month
    df["weekday"] = df["time"].dt.dayofweek < 5
    df["target"] = df["cls"].shift(-HORIZON)          # class 3 hours later
    return df


FEATURES = ["temp", "rh", "cloud", "sw_rad", "wind", "rain", "hi", "hour", "month"]


# ---------------------------------------------------------------- evaluation helpers
def report(name, y_true, y_pred):
    rec = recall_score(y_true, y_pred, labels=[0, 1, 2], average=None, zero_division=0)
    return {"model": name, "accuracy": accuracy_score(y_true, y_pred),
            "recall_Low": rec[0], "recall_Medium": rec[1], "recall_High": rec[2]}


def main(path="data/seri_iskandar_2024_openmeteo.csv"):
    df = add_features(load_openmeteo(path))
    data = df.dropna(subset=["target"]).copy()
    data["target"] = data["target"].astype(int)

    train = data[data["month"] <= 9]
    test = data[data["month"] >= 10]

    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3,
                                random_state=RANDOM_STATE, n_jobs=-1)
    rf.fit(train[FEATURES], train["target"])
    pred_rf = rf.predict(test[FEATURES])

    # Baseline 1: most common class for that clock hour (learned on training months)
    hour_mode = train.groupby("hour")["target"].agg(lambda s: s.mode().iloc[0])
    pred_hour = test["hour"].map(hour_mode).values

    # Baseline 2: persistence = the class 3 hours later equals the class now
    pred_persist = test["cls"].values

    # Baseline 3: persistence for that hour yesterday (class at t+3 = class at t+3-24)
    yday = df.set_index("time")["cls"]
    t_target = test["time"] + pd.Timedelta(hours=HORIZON)
    pred_yday = yday.reindex(t_target - pd.Timedelta(hours=24)).values

    rows = [report("Random forest (ours)", test["target"], pred_rf),
            report("Hour-of-day rule", test["target"], pred_hour),
            report("Persistence (same as now)", test["target"], pred_persist),
            report("Same hour yesterday", test["target"], pred_yday.astype(int))]
    print("\nTEST PERIOD Oct-Dec 2024, predicting the class 3 hours ahead (MEASURED on real data)")
    print(pd.DataFrame(rows).round(3).to_string(index=False))

    print("\nConfusion matrix, random forest (rows = actual Low/Med/High, cols = predicted)")
    print(confusion_matrix(test["target"], pred_rf, labels=[0, 1, 2]))

    imp = pd.Series(rf.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print("\nFeature importance\n", imp.round(3).to_string())

    # Office-hours view (weekdays 08-18) - where the decisions matter
    office = test["weekday"] & test["hour"].between(8, 17)
    print("\nOffice hours only:")
    print(pd.DataFrame([report("Random forest", test["target"][office], pred_rf[office.values]),
                        report("Persistence", test["target"][office], pred_persist[office.values])]).round(3).to_string(index=False))

    # Predictions for the whole year, for the energy simulation.
    # Test months (Oct-Dec) use the honest train-on-Jan-Sep model.
    # Other months use leave-one-month-out (model trained on the other 11 months) - labelled as such.
    data["pred"] = np.nan
    data.loc[test.index, "pred"] = pred_rf
    for m in range(1, 10):
        tr = data[data["month"] != m]
        te = data[data["month"] == m]
        mdl = RandomForestClassifier(n_estimators=200, min_samples_leaf=3,
                                     random_state=RANDOM_STATE, n_jobs=-1).fit(tr[FEATURES], tr["target"])
        data.loc[te.index, "pred"] = mdl.predict(te[FEATURES])

    out = df[["time", "temp", "rh", "cloud", "sw_rad", "wind", "rain", "hi", "cls", "hour", "month", "weekday"]].copy()
    # pred_for_t = prediction ABOUT hour t, made 3 hours earlier (what the controller knows at hour t)
    pred_about = pd.Series(data["pred"].values, index=data["time"] + pd.Timedelta(hours=HORIZON))
    out["pred_for_t"] = out["time"].map(pred_about)
    # pred_ahead = prediction made AT hour t about hour t+3
    out["pred_ahead"] = out["time"].map(pd.Series(data["pred"].values, index=data["time"]))
    out["cls_ahead"] = out["cls"].shift(-HORIZON)
    out.to_csv("data/predictions.csv", index=False)

    # Descriptive stats (to cross-check against the team's report)
    print("\nWhole year class share:", (df["cls"].value_counts(normalize=True).sort_index() * 100).round(1).to_dict())
    off = df["weekday"] & df["hour"].between(8, 17)
    print("Weekday 08-18 class share:", (df.loc[off, "cls"].value_counts(normalize=True).sort_index() * 100).round(1).to_dict())
    print("Heat index mean/min/max:", round(df["hi"].mean(), 1), round(df["hi"].min(), 1), round(df["hi"].max(), 1))


if __name__ == "__main__":
    main()
