"""DayBank (historical days with out-of-sample forecasts) and scenario construction."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import DATA_DIR, DAY_TYPE_MULTIPLIERS
from app.explain import compute_explain_stats
from app.legacy import step5_plant
from app.model import (
    DailyForecasts,
    build_features,
    campus_load_frame,
    load_weather,
    train_forecasters,
)

WEEKDAY_TYPES = {"weekday", "exam_week", "semester_break"}
NEAR_TMAX_C = 1.0
FORECAST_KIND_OCT_DEC = "trained Jan–Sep, tested Oct–Dec"
FORECAST_KIND_LOMO = "leave-one-month-out (trained on Jan–Sep except this month)"


@dataclass
class DayBank:
    weather: pd.DataFrame
    load: pd.DataFrame
    daily: pd.DataFrame
    forecasts: DailyForecasts
    params: dict
    features: pd.DataFrame
    explain_stats: dict


def build_day_bank(params: dict, cache_dir: Path = DATA_DIR) -> DayBank:
    weather = load_weather()
    load = campus_load_frame(weather, params, cache_dir=cache_dir)
    total = load["total_rt"].values
    daily = step5_plant.daily_table(weather, total, params)
    X = build_features(daily, weather, total)
    forecasts = train_forecasters(daily, X)
    stats = compute_explain_stats(daily, X, forecasts, weather)
    return DayBank(
        weather=weather,
        load=load,
        daily=daily,
        forecasts=forecasts,
        params=params,
        features=X,
        explain_stats=stats,
    )


def select_day(bank: DayBank, day_type: str, tmax_c: float) -> pd.Timestamp:
    eligible = bank.forecasts.eligible
    dow = eligible.day_of_week
    cal = eligible[(dow >= 5) if day_type == "weekend" else (dow < 5)]
    tmax = bank.daily.loc[cal, "tmax"]
    dist = (tmax - tmax_c).abs()
    oct_dec = dist[cal.month >= 10]
    pool = oct_dec if len(oct_dec) and oct_dec.min() <= NEAR_TMAX_C else dist
    pool = pool.sort_index(kind="stable")  # ties -> earliest
    return pd.Timestamp(pool.idxmin())


@dataclass
class Scenario:
    source_date: str
    day_type: str
    source_tmax_c: float
    training_months: list[int]
    forecast_kind: str
    load_rt: np.ndarray
    academic_rt: np.ndarray
    evening_rt: np.ndarray
    base_rt: np.ndarray
    room_equivalents: int
    t_out: np.ndarray
    actual_need_rth: float
    ai_forecast_model_rth: float
    calendar_need_rth: float


def build_scenario(bank: DayBank, day_type: str, tmax_c: float, params: dict) -> Scenario:
    D = select_day(bank, day_type, tmax_c)
    m = DAY_TYPE_MULTIPLIERS[day_type]
    idx = pd.date_range(D - pd.Timedelta(hours=2), periods=24, freq="h")
    load = bank.load.set_index("time").loc[idx]
    weather = bank.weather.set_index("time").loc[idx]
    load_rt = (load["base_rt"] + m * load["room_rt"]).to_numpy(dtype=float)
    room = m * load["room_rt"].to_numpy(dtype=float)
    h = idx.hour.to_numpy()
    academic = np.where((h >= 8) & (h <= 17), room, 0.0)
    evening = np.where((h >= 18) & (h <= 21), room, 0.0)
    base = load_rt - academic - evening
    t_out = weather["temp"].to_numpy(dtype=float)
    actual = float(np.maximum(load_rt[10:24] - params["sac_available_rt"], 0).sum())
    fc = bank.forecasts
    return Scenario(
        source_date=D.strftime("%Y-%m-%d"),
        day_type=day_type,
        source_tmax_c=round(float(bank.daily.loc[D, "tmax"]), 1),
        training_months=list(fc.training_months[D]),
        forecast_kind=FORECAST_KIND_OCT_DEC if D.month >= 10 else FORECAST_KIND_LOMO,
        load_rt=load_rt,
        academic_rt=academic,
        evening_rt=evening,
        base_rt=base,
        room_equivalents=round(float(load["room_scale"].iloc[0])),
        t_out=t_out,
        actual_need_rth=actual,
        ai_forecast_model_rth=float(fc.ai[D]),
        calendar_need_rth=float(fc.calendar[D]),
    )
