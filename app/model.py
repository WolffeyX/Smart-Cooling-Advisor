"""Weather loading and the step1 heat-class classifier (thin wrappers over legacy code)."""

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score

from app.config import DATA_DIR, WEATHER_CSV
from app.legacy import step1_model, step5_plant

heat_index_c = step1_model.heat_index_c
CLASSIFIER_FEATURES = step1_model.FEATURES


def load_weather() -> pd.DataFrame:
    """Hourly 2024 Seri Iskandar weather with heat index, class and calendar features."""
    return step1_model.add_features(step1_model.load_openmeteo(WEATHER_CSV))


def train_classifier(weather: pd.DataFrame) -> dict:
    """Train on Jan-Sep, score on Oct-Dec (class 3 h ahead), same RF settings as step1."""
    data = weather.dropna(subset=["target"]).copy()
    data["target"] = data["target"].astype(int)
    train = data[data["month"] <= 9]
    test = data[data["month"] >= 10]
    rf = RandomForestClassifier(n_estimators=300, min_samples_leaf=3,
                                random_state=step1_model.RANDOM_STATE, n_jobs=-1)
    rf.fit(train[CLASSIFIER_FEATURES], train["target"])
    pred = rf.predict(test[CLASSIFIER_FEATURES])
    return {
        "accuracy": float(accuracy_score(test["target"], pred)),
        "train_months": set(train["month"].unique().tolist()),
        "test_months": set(test["month"].unique().tolist()),
    }


LOAD_COLUMNS = ["time", "total_rt", "base_rt", "room_rt"]
LOAD_KEYS = ("base_load_rt", "target_peak_rt", "evening_factor", "noise_daily", "noise_hourly")


def load_hash(params: dict) -> str:
    """Short hash of the parameters that determine the synthetic campus load."""
    payload = json.dumps({k: params[k] for k in LOAD_KEYS}, sort_keys=True)
    return hashlib.sha1(payload.encode()).hexdigest()[:8]


def campus_load_frame(weather: pd.DataFrame, params: dict,
                      cache_dir: Path = DATA_DIR) -> pd.DataFrame:
    """Hourly campus load (time, total_rt, base_rt, room_rt), cached as CSV by load hash."""
    path = Path(cache_dir) / f"campus_load_2024_{load_hash(params)}.csv"
    if path.exists():
        try:
            cached = pd.read_csv(path, parse_dates=["time"])
            if list(cached.columns) == LOAD_COLUMNS and len(cached) == len(weather):
                return cached
        except (OSError, ValueError, pd.errors.ParserError, pd.errors.EmptyDataError):
            pass  # corrupt or partial cache: fall through and rebuild
    total, _ = step5_plant.campus_load(weather, params)
    base = params["base_load_rt"] * (1 + 0.03 * (weather["temp"].to_numpy() - 27))
    frame = pd.DataFrame({
        "time": weather["time"].to_numpy(),
        "total_rt": total,
        "base_rt": base,
        "room_rt": total - base,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        frame.to_csv(tmp, index=False)
        os.replace(tmp, path)  # atomic: readers never see a half-written file
    finally:
        tmp.unlink(missing_ok=True)
    return frame


# ---------------------------------------------------------------- daily forecasters (no leakage)
FEATURE_PROVENANCE: dict[str, str] = {
    "need_today": "observed_lag1",
    "load_today": "observed_lag1",
    "tmean_today": "observed_lag1",
    "himax_today": "observed_lag1",
    "rain_today": "observed_lag1",
    "need_lastweek": "observed_lag7",
    "dow_tomorrow": "calendar",
    "weekday_tomorrow": "calendar",
    "month": "calendar",
    "fc_tmax": "simulated_dayahead",
    "fc_sw": "simulated_dayahead",
    "fc_rain": "simulated_dayahead",
}
TRAINING_MONTHS_OCT_DEC = list(range(1, 10))


def _window_22h(values: np.ndarray, times: pd.Series, how: str) -> pd.Series:
    """24 h ending at 21:00 of each date (22:00 the day before .. 21:00), indexed by NEXT date."""
    r = pd.Series(np.asarray(values, dtype=float), index=pd.DatetimeIndex(times)).rolling(24)
    agg = getattr(r, how)()
    agg = agg[agg.index.hour == 21]
    agg.index = agg.index.normalize() + pd.Timedelta(days=1)
    return agg


def build_features(g: pd.DataFrame, weather: pd.DataFrame, total_rt: np.ndarray,
                   seed: int = 0) -> pd.DataFrame:
    """Features for forecasting day D at 22:00 on D-1 (mirrors step5 forecasts(), Xw set).

    Deviation from step5: load/tmean/himax/rain use the 24 h window 22:00 D-2..21:00 D-1, not the
    calendar day D-1, because the latter includes 22:00-23:00 readings after the decision time.

    Observed values are lagged (shift 1 / 7); the day-ahead weather forecast is the actual plus
    simulated NWP-like noise, drawn in step5's order (tmax, sw, rain) over the full length of g.
    """
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(index=g.index)
    X["need_today"] = g["need_rth"].shift(1)
    t = weather["time"]
    X["load_today"] = _window_22h(total_rt, t, "sum").reindex(g.index)
    X["tmean_today"] = _window_22h(weather["temp"].values, t, "mean").reindex(g.index)
    X["himax_today"] = _window_22h(weather["hi"].values, t, "max").reindex(g.index)
    X["rain_today"] = _window_22h(weather["rain"].values, t, "sum").reindex(g.index)
    X["need_lastweek"] = g["need_rth"].shift(7)
    X["dow_tomorrow"] = g["dow"]
    X["weekday_tomorrow"] = g["weekday"].astype(int)
    X["month"] = g["month"]
    X["fc_tmax"] = g["tmax"] + rng.normal(0, 1.0, len(g))
    X["fc_sw"] = g["sw"] * rng.normal(1.0, 0.15, len(g)).clip(0.5, 1.5)
    X["fc_rain"] = g["rain"] * rng.normal(1.0, 0.5, len(g)).clip(0, 3)
    return X[list(FEATURE_PROVENANCE)]


@dataclass
class DailyForecasts:
    ai: pd.Series
    calendar: pd.Series
    training_months: dict
    eligible: pd.DatetimeIndex


def _rf() -> RandomForestRegressor:
    return RandomForestRegressor(400, min_samples_leaf=3, random_state=42, n_jobs=-1)


def train_forecasters(g: pd.DataFrame, X: pd.DataFrame) -> DailyForecasts:
    """Out-of-sample forecasts for every feature-complete day.

    Oct-Dec: one model trained on Jan-Sep. Jan-Sep month m: a model trained on the other
    Jan-Sep months (leave-one-month-out), so no day is predicted by a model that saw its month.
    """
    ok = X.notna().all(axis=1)
    month = pd.Series(g.index.month, index=g.index)
    ai = pd.Series(np.nan, index=g.index)
    calendar = pd.Series(np.nan, index=g.index)
    training_months: dict = {}

    def fit_predict(train_months: list[int], target_mask: pd.Series) -> None:
        train = ok & month.isin(train_months)
        m = _rf().fit(X[train], g.loc[train, "need_rth"])
        ai[target_mask] = m.predict(X[target_mask])
        cal = g[train].groupby("dow")["need_rth"].mean()
        calendar[target_mask] = g.loc[target_mask, "dow"].map(cal)
        for day in g.index[target_mask]:
            training_months[day] = list(train_months)

    fit_predict(TRAINING_MONTHS_OCT_DEC, ok & (month >= 10))
    for m in range(1, 10):
        fit_predict([k for k in range(1, 10) if k != m], ok & (month == m))
    return DailyForecasts(ai=ai, calendar=calendar, training_months=training_months,
                          eligible=g.index[ok])
