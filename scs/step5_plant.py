"""
Smart Cooling Advisor - Step 5: PLANT-LEVEL proof of concept (SIMULATED).

Plant modelled on UTP's Gas District Cooling (GDC) equipment as published:
  2 x 1,250 RT steam absorption chillers (SAC, driven by gas-turbine waste heat)
  4 x   325 RT electric chillers (EC) - designed to charge the TES at night
  1 x 10,000 RTh chilled-water thermal energy storage (TES)
Published issue: SAC + TES were not enough, so ECs also ran in the daytime at partial load.

Decision tested: every night at 22:00, how much should the ECs charge the TES for tomorrow?
Fair comparison: always-full / calendar rule / persistence / AI forecast / perfect forecast.

Campus load is SYNTHETIC: our room model (step2) scaled to many rooms + a 24/7 base load,
driven by the real 2024 Seri Iskandar weather. Every assumption is in PLANT below.
Run: python step5_plant.py
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
import step2_simulate as sim

RT = 3.517  # kW per refrigeration ton

PLANT = dict(
    sac_available_rt=2200.0,     # 2 x 1250 RT, derated ~12% (steam limits, ageing) - assumed
    ec_unit_rt=325.0, n_ec=4,
    tes_capacity_rth=10000.0,
    tes_max_discharge_rt=2500.0, # assumed
    charge_eff=0.95,             # assumed
    standby_loss_per_h=0.004,    # 0.4%/h of stored energy (~85% over a day incl. charge losses) - assumed
    night_hours=list(range(22, 24)) + list(range(0, 8)),   # 10 h charging window
    kw_per_rt_full=0.60,         # water-cooled centrifugal chiller at full load (typical 0.55-0.65)
    kw_per_rt_aux=0.15,          # chilled/condenser water pumps + cooling towers (assumed)
    plr_penalty=0.8,             # kW/RT x (1 + 0.8*(1-PLR)^2)  partial-load penalty (assumed)
    temp_coeff=0.015,            # +1.5% kW/RT per degC outdoor above 30 degC (condenser side, assumed)
    base_load_rt=350.0,          # 24/7 loads: data centre, labs, library (assumed)
    target_peak_rt=3300.0,       # calibrate synthetic campus so the 95th-pct weekday peak ~ this (assumed)
    evening_factor=0.3,          # 18:00-22:00 weekday load as share of room load (library, evening classes)
    margin=0.10,                 # charge forecast + 10% safety margin
    noise_daily=0.0,             # random day-to-day occupancy/event variation (std, fraction)
    noise_hourly=0.0,            # random hour-to-hour variation (std, fraction)
)


# ---------------------------------------------------------------- 1. synthetic campus load
def campus_load(df, P=PLANT):
    room = sim.simulate(df, "S1_fixed_24C")            # one 60 m2 room at 25-ish degC, weekdays 08-18
    room_kw = (room["q_sens"] + room["q_lat"]) / 1000.0
    # evening partial occupancy: 18:00-22:00 weekdays at evening_factor x that day's 17:00 room load
    evening = (df["weekday"] & df["hour"].between(18, 21)).values
    at17 = room_kw.where(df["hour"] == 17).groupby(df["time"].dt.date).transform("max").fillna(0)
    room_kw = room_kw.where(~evening, at17 * P["evening_factor"])
    # weather-sensitive base load (outdoor air for 24/7 spaces)
    base_rt = P["base_load_rt"] * (1 + 0.03 * (df["temp"] - 27))
    wk_peak = room_kw[df["weekday"]].groupby(df.loc[df["weekday"], "time"].dt.date).max()
    scale = (P["target_peak_rt"] - P["base_load_rt"]) * RT / wk_peak.quantile(0.95)
    load_rt = base_rt + room_kw * scale / RT
    if P.get("noise_daily", 0) or P.get("noise_hourly", 0):
        rng = np.random.default_rng(123)
        days = df["time"].dt.date
        dn = pd.Series(rng.normal(1, P["noise_daily"], days.nunique()), index=sorted(days.unique()))
        load_rt = load_rt * days.map(dn).values * rng.normal(1, P["noise_hourly"], len(df))
        load_rt = load_rt.clip(lower=0)
    return load_rt.values, scale / 1.0


def kw_per_rt(plr, t_out, P=PLANT):
    plr = np.clip(plr, 0.2, 1.0)
    return (P["kw_per_rt_full"] * (1 + P["plr_penalty"] * (1 - plr) ** 2)
            * (1 + P["temp_coeff"] * (t_out - 30.0)) + P["kw_per_rt_aux"])


def ec_power_kw(load_rt, t_out, P=PLANT):
    """Electric power to make load_rt with the fewest ECs (staging), each sharing equally."""
    if load_rt <= 0:
        return 0.0, 0
    n = int(np.ceil(load_rt / P["ec_unit_rt"]))
    n = min(n, P["n_ec"])
    made = min(load_rt, n * P["ec_unit_rt"])
    plr = made / (n * P["ec_unit_rt"])
    return made * kw_per_rt(plr, t_out, P), n


# ---------------------------------------------------------------- 2. daily table + forecasting
def daily_table(df, load_rt, P=PLANT):
    d = df[["time", "temp", "rh", "sw_rad", "rain", "hi", "weekday", "month"]].copy()
    d["load_rt"] = load_rt
    d["date"] = d["time"].dt.date
    d["day_need"] = np.where(~d["time"].dt.hour.isin(P["night_hours"]),
                             np.clip(d["load_rt"] - P["sac_available_rt"], 0, None), 0.0)
    g = d.groupby("date").agg(need_rth=("day_need", "sum"), load_rth=("load_rt", "sum"),
                              tmean=("temp", "mean"), tmax=("temp", "max"), himax=("hi", "max"),
                              sw=("sw_rad", "sum"), rain=("rain", "sum"),
                              weekday=("weekday", "first"), month=("month", "first"))
    g.index = pd.to_datetime(g.index)
    g["dow"] = g.index.dayofweek
    return g


def forecasts(g, seed=0):
    """Forecast of TOMORROW's TES need, made at 22:00 today. Train Jan-Sep, apply all year (test = Oct-Dec)."""
    rng = np.random.default_rng(seed)
    f = pd.DataFrame(index=g.index)
    f["actual"] = g["need_rth"]
    # features known at 22:00 the day before
    X = pd.DataFrame(index=g.index)
    X["need_today"] = g["need_rth"].shift(1)
    X["load_today"] = g["load_rth"].shift(1)
    X["tmean_today"] = g["tmean"].shift(1)
    X["himax_today"] = g["himax"].shift(1)
    X["rain_today"] = g["rain"].shift(1)
    X["need_lastweek"] = g["need_rth"].shift(7)
    X["dow_tomorrow"] = g["dow"]
    X["weekday_tomorrow"] = g["weekday"].astype(int)
    X["month"] = g["month"]
    # a realistic day-ahead weather forecast for tomorrow: actual + forecast error (assumed NWP-like error)
    Xw = X.copy()
    Xw["fc_tmax"] = g["tmax"] + rng.normal(0, 1.0, len(g))
    Xw["fc_sw"] = g["sw"] * rng.normal(1.0, 0.15, len(g)).clip(0.5, 1.5)
    Xw["fc_rain"] = (g["rain"] * rng.normal(1.0, 0.5, len(g)).clip(0, 3))
    ok = X.notna().all(axis=1)
    train = ok & (g.index.month <= 9)
    for name, XX in [("AI_calendar_weather_today", X), ("AI_plus_dayahead_weather", Xw)]:
        m = RandomForestRegressor(400, min_samples_leaf=3, random_state=42, n_jobs=-1)
        m.fit(XX[train], g.loc[train, "need_rth"])
        f[name] = np.nan
        f.loc[ok, name] = m.predict(XX[ok])
    f["persistence"] = g["need_rth"].shift(1)
    cal = g[g.index.month <= 9].groupby("dow")["need_rth"].mean()
    f["calendar_rule"] = g["dow"].map(cal)
    f["always_full"] = 1e9
    f["perfect"] = g["need_rth"]
    return f.bfill()


# ---------------------------------------------------------------- 3. plant dispatch, hour by hour
def dispatch(df, load_rt, target_by_date, P=PLANT, use_margin=True):
    soc = 5000.0
    out = {k: np.zeros(len(df)) for k in ["ec_kw", "ec_n", "tes_out", "ec_day_rt", "unmet", "soc", "charge_rt"]}
    times = df["time"]
    hours = times.dt.hour.values
    T = df["temp"].values
    dates = times.dt.normalize()
    for i in range(len(df)):
        h = hours[i]
        soc *= (1 - P["standby_loss_per_h"])
        load = load_rt[i]
        night = h in P["night_hours"]
        # --- serve the campus load first: SAC, then TES (daytime only), then ECs
        rem = max(0.0, load - P["sac_available_rt"])
        tes_out = 0.0
        if not night and rem > 0:
            tes_out = min(rem, P["tes_max_discharge_rt"], soc)
            soc -= tes_out
            rem -= tes_out
        # --- charging at night with whatever EC capacity is left (decision for the coming day)
        charge = 0.0
        if night:
            day_for = (dates.iloc[i] + pd.Timedelta(days=1)) if h >= 22 else dates.iloc[i]
            tgt = target_by_date.get(day_for, P["tes_capacity_rth"])
            tgt = min(P["tes_capacity_rth"], tgt * (1 + P["margin"]) if use_margin else tgt)
            hours_left = (8 - h) if h < 8 else (8 + 24 - h)
            needed = max(0.0, tgt - soc) / P["charge_eff"]
            spare = max(0.0, P["n_ec"] * P["ec_unit_rt"] - rem)
            charge = min(needed / max(hours_left, 1), spare)
            soc += charge * P["charge_eff"]
        ec_rt_total = rem + charge
        kw, n = ec_power_kw(ec_rt_total, T[i], P)
        unmet = max(0.0, ec_rt_total - P["n_ec"] * P["ec_unit_rt"])
        out["ec_kw"][i] = kw; out["ec_n"][i] = n; out["tes_out"][i] = tes_out
        out["ec_day_rt"][i] = 0 if night else rem; out["unmet"][i] = unmet
        out["soc"][i] = soc; out["charge_rt"][i] = charge
    return pd.DataFrame(out, index=df.index)


def plant_kpis(df, res, mask, label):
    r, d = res[mask], df[mask]
    day = ~d["time"].dt.hour.isin(PLANT["night_hours"])
    return {
        "strategy": label,
        "EC_MWh": round(r["ec_kw"].sum() / 1000, 1),
        "EC_day_MWh": round(r.loc[day, "ec_kw"].sum() / 1000, 1),
        "EC_day_run_hours": int((r.loc[day, "ec_n"] > 0).sum()),
        "EC_day_peak_kW": round(r.loc[day, "ec_kw"].max(), 0),
        "mean_day_EC_kW_14_18": round(r.loc[day & d["time"].dt.hour.between(14, 17), "ec_kw"].mean(), 1),
        "TES_charged_MWh_th": round(r["charge_rt"].sum() * RT / 1000, 1),
        "unmet_RTh": round(r["unmet"].sum(), 1),
    }


def forecast_skill(f, test_idx):
    from sklearn.metrics import mean_absolute_error
    rows = []
    for c in ["AI_calendar_weather_today", "AI_plus_dayahead_weather", "persistence", "calendar_rule"]:
        rows.append({"forecast": c, "MAE_RTh": round(mean_absolute_error(f.loc[test_idx, "actual"], f.loc[test_idx, c]), 0),
                     "MAPE_weekdays_%": round(100 * (np.abs(f.loc[test_idx, c] - f.loc[test_idx, "actual"]) /
                                                      f.loc[test_idx, "actual"].replace(0, np.nan)).dropna().mean(), 1)})
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    load_rt, scale = campus_load(df)
    g = daily_table(df, load_rt)
    f = forecasts(g)
    test_days = f.index[f.index.month >= 10]
    test = (df["month"] >= 10).values
    pd.set_option("display.width", 250)

    wk = g[g["weekday"]]
    print(f"\nSYNTHETIC CAMPUS (scaled to ~{scale:.0f} reference rooms): weekday peak 95th pct "
          f"{pd.Series(load_rt)[df['weekday'].values].groupby(df.loc[df['weekday'], 'time'].dt.date.values).max().quantile(0.95):.0f} RT, "
          f"weekday daytime TES need mean {wk['need_rth'].mean():.0f} RTh (max {wk['need_rth'].max():.0f}), "
          f"weekend mean {g.loc[~g['weekday'], 'need_rth'].mean():.0f} RTh")
    print("\nFORECAST SKILL for tomorrow's TES need, Oct-Dec (SIMULATED load, real weather)")
    print(forecast_skill(f, test_days).to_string(index=False))

    rows = []
    for name in ["always_full", "calendar_rule", "persistence", "AI_calendar_weather_today",
                 "AI_plus_dayahead_weather", "perfect"]:
        tgt = {pd.Timestamp(k): v for k, v in f[name].items()}
        res = dispatch(df, load_rt, tgt, use_margin=(name != "perfect"))
        rows.append(plant_kpis(df, res, test, name))
    out = pd.DataFrame(rows)
    base = out.loc[out["strategy"] == "always_full", "EC_MWh"].iloc[0]
    out["EC_vs_always_full_%"] = (100 * (out["EC_MWh"] / base - 1)).round(1)
    print("\nPLANT DISPATCH, Oct-Dec 2024 (SIMULATED)")
    print(out.to_string(index=False))
    out.to_csv("data/plant_results.csv", index=False)
    return out


if __name__ == "__main__":
    main()
