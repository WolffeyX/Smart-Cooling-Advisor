"""Weather loading and the step1 heat-class classifier (thin wrappers over legacy code)."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
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
        return pd.read_csv(path, parse_dates=["time"])
    total, _ = step5_plant.campus_load(weather, params)
    base = params["base_load_rt"] * (1 + 0.03 * (weather["temp"].to_numpy() - 27))
    frame = pd.DataFrame({
        "time": weather["time"].to_numpy(),
        "total_rt": total,
        "base_rt": base,
        "room_rt": total - base,
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return frame
