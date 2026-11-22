"""Pure hour-by-hour plant dispatch (SAC -> tank -> electric chillers), step5 physics."""

import numpy as np
import pandas as pd

from app.legacy import step5_plant

HOURS = [22, 23, *range(22)]
HOUR_LABELS = [f"{h:02d}:00" for h in HOURS]

_KEYS = [
    "campus_load_rt",
    "sac_rt",
    "tank_out_rt",
    "ec_load_rt",
    "charge_rt",
    "ec_count",
    "ec_kw",
    "tank_level_rth",
    "unmet_rt",
    "standby_loss_rth",
]


def _hour_step(level, load, t_out, hour, target, params):
    """One hour of plant physics (design 6.6 steps 1-5). Returns (new_level, row)."""
    night = hour in params["night_hours"]
    # 1. standby loss
    standby = level * params["standby_loss_per_h"]
    level = level - standby
    # 2. shaved absorption chillers first
    sac = min(load, params["sac_available_rt"])
    rem = max(0.0, load - params["sac_available_rt"])
    tank_out = 0.0
    charge = 0.0
    # 3. day: discharge tank
    if not night and rem > 0:
        tank_out = min(rem, params["tes_max_discharge_rt"], level)
        level -= tank_out
        rem -= tank_out
    # 4. night: charge with spare EC capacity
    if night:
        tgt = min(params["tes_capacity_rth"], target)
        hours_left = (8 - hour) if hour < 8 else (32 - hour)
        needed = max(0.0, tgt - level) / params["charge_eff"]
        spare = max(0.0, params["n_ec"] * params["ec_unit_rt"] - rem)
        charge = min(needed / max(hours_left, 1), spare)
        level += charge * params["charge_eff"]
    # 5. electric chillers
    ec_total = rem + charge
    ec_kw, ec_count = step5_plant.ec_power_kw(ec_total, t_out, params)
    unmet = max(0.0, ec_total - params["n_ec"] * params["ec_unit_rt"])
    row = {
        "campus_load_rt": float(load),
        "sac_rt": sac,
        "tank_out_rt": tank_out,
        "ec_load_rt": rem - unmet,
        "charge_rt": charge,
        "ec_count": ec_count,
        "ec_kw": ec_kw,
        "tank_level_rth": level,
        "unmet_rt": unmet,
        "standby_loss_rth": standby,
        "_ec_day_rt": 0.0 if night else rem,
    }
    return level, row


def dispatch_day(load_rt, t_out, hours, tank_level_start, charge_target_rth, params):
    """24-hour dispatch. The charge target is final (margin already applied by caller)."""
    out = {k: np.zeros(len(hours)) for k in _KEYS}
    level = float(tank_level_start)
    for i, h in enumerate(hours):
        level, row = _hour_step(
            level, float(load_rt[i]), float(t_out[i]), h, float(charge_target_rth), params
        )
        for k in _KEYS:
            out[k][i] = row[k]
    return out


def dispatch_year(weather, load_rt, target_by_date, params, start_level=5000.0, use_margin=True):
    """Whole-year loop with step5 semantics (used for the regression test)."""
    n = len(weather)
    cols = ["ec_kw", "ec_n", "tes_out", "ec_day_rt", "unmet", "soc", "charge_rt"]
    out = {k: np.zeros(n) for k in cols}
    times = weather["time"]
    hours = times.dt.hour.values
    dates = times.dt.normalize()
    temps = weather["temp"].values
    cap = params["tes_capacity_rth"]
    level = float(start_level)
    for i in range(n):
        h = int(hours[i])
        target = 0.0
        if h in params["night_hours"]:
            day_for = dates.iloc[i] + pd.Timedelta(days=1) if h >= 22 else dates.iloc[i]
            tgt = target_by_date.get(day_for, cap)
            target = min(cap, tgt * (1 + params["margin"]) if use_margin else tgt)
        level, row = _hour_step(level, float(load_rt[i]), float(temps[i]), h, target, params)
        out["ec_kw"][i] = row["ec_kw"]
        out["ec_n"][i] = row["ec_count"]
        out["tes_out"][i] = row["tank_out_rt"]
        out["ec_day_rt"][i] = row["_ec_day_rt"]
        out["unmet"][i] = row["unmet_rt"]
        out["soc"][i] = level
        out["charge_rt"][i] = row["charge_rt"]
    return pd.DataFrame(out, index=weather.index)
