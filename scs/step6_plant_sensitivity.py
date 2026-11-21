"""Step 6: plant-level sensitivity + hot-season test (SIMULATED). Run: python step6_plant_sensitivity.py"""
import numpy as np, pandas as pd
from sklearn.ensemble import RandomForestRegressor
import step5_plant as pl

def run_case(df, P, months_test, label):
    load_rt, _ = pl.campus_load(df, P)
    g = pl.daily_table(df, load_rt, P)
    f = pl.forecasts(g)
    # refit AI models excluding the test months (honest out-of-sample for any season)
    rng = np.random.default_rng(0)
    X = pd.DataFrame(index=g.index)
    X["need_today"] = g["need_rth"].shift(1); X["load_today"] = g["load_rth"].shift(1)
    X["tmean_today"] = g["tmean"].shift(1); X["himax_today"] = g["himax"].shift(1)
    X["rain_today"] = g["rain"].shift(1); X["need_lastweek"] = g["need_rth"].shift(7)
    X["dow_tomorrow"] = g["dow"]; X["weekday_tomorrow"] = g["weekday"].astype(int); X["month"] = g["month"]
    X["fc_tmax"] = g["tmax"] + rng.normal(0, 1.0, len(g)); X["fc_sw"] = g["sw"] * rng.normal(1, .15, len(g)).clip(.5, 1.5)
    X["fc_rain"] = g["rain"] * rng.normal(1, .5, len(g)).clip(0, 3)
    ok = X.notna().all(axis=1); tm = g.index.month.isin(months_test)
    m = RandomForestRegressor(400, min_samples_leaf=3, random_state=42, n_jobs=-1).fit(X[ok & ~tm], g.loc[ok & ~tm, "need_rth"])
    f["AI"] = np.nan; f.loc[ok, "AI"] = m.predict(X[ok]); f["AI"] = f["AI"].bfill()
    cal = g[~tm].groupby("dow")["need_rth"].mean(); f["calendar_rule"] = g["dow"].map(cal)
    mask = df["month"].isin(months_test).values
    res = {}
    for name in ["always_full", "calendar_rule", "AI", "perfect"]:
        tgt = {pd.Timestamp(k): v for k, v in f[name].items()}
        r = pl.dispatch(df, load_rt, tgt, P, use_margin=(name != "perfect"))
        res[name] = pl.plant_kpis(df, r, mask, name)
    b = res["always_full"]["EC_MWh"]
    row = {"case": label}
    for k in ["calendar_rule", "AI", "perfect"]:
        row[f"{k}_vs_full_%"] = round(100 * (res[k]["EC_MWh"] / b - 1), 1)
    row["AI_day_EC_hours"] = res["AI"]["EC_day_run_hours"]; row["full_day_EC_hours"] = res["always_full"]["EC_day_run_hours"]
    row["cal_day_EC_hours"] = res["calendar_rule"]["EC_day_run_hours"]
    row["unmet_full/cal/AI/perfect"] = "/".join(str(int(res[k]["unmet_RTh"])) for k in ["always_full","calendar_rule","AI","perfect"])
    gain_ai = res["calendar_rule"]["EC_MWh"] - res["AI"]["EC_MWh"]; gain_pf = res["calendar_rule"]["EC_MWh"] - res["perfect"]["EC_MWh"]
    row["AI_beyond_calendar_MWh"] = round(gain_ai, 1)
    row["capture_vs_perfect_%"] = round(100 * gain_ai / gain_pf, 0) if gain_pf > 0 else np.nan
    return row

def main():
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    B = dict(pl.PLANT)
    cases = [
        ("Base, Oct-Dec", {}, [10, 11, 12]),
        ("Base, HOT season Apr-Jul", {}, [4, 5, 6, 7]),
        ("Low standby loss 0.2%/h, Oct-Dec", {"standby_loss_per_h": 0.002}, [10, 11, 12]),
        ("High standby loss 0.8%/h, Oct-Dec", {"standby_loss_per_h": 0.008}, [10, 11, 12]),
        ("Weaker SAC 2000 RT, Oct-Dec", {"sac_available_rt": 2000.0}, [10, 11, 12]),
        ("Weaker SAC 2000 RT, Apr-Jul", {"sac_available_rt": 2000.0}, [4, 5, 6, 7]),
        ("Stronger SAC 2400 RT, Oct-Dec", {"sac_available_rt": 2400.0}, [10, 11, 12]),
        ("Bigger campus peak 3600 RT, Apr-Jul", {"target_peak_rt": 3600.0}, [4, 5, 6, 7]),
        ("No safety margin, Oct-Dec", {"margin": 0.0}, [10, 11, 12]),
        ("NOISY load (daily 10%, hourly 5%), Oct-Dec", {"noise_daily": 0.10, "noise_hourly": 0.05}, [10, 11, 12]),
        ("NOISY load (daily 20%, hourly 5%), Oct-Dec", {"noise_daily": 0.20, "noise_hourly": 0.05}, [10, 11, 12]),
        ("NOISY load (daily 10%), Apr-Jul", {"noise_daily": 0.10, "noise_hourly": 0.05}, [4, 5, 6, 7]),
    ]
    rows = []
    for label, ch, months in cases:
        P = {**B, **ch}
        pl.PLANT.update(P)
        rows.append(run_case(df, P, months, label))
        pl.PLANT.clear(); pl.PLANT.update(B)
    out = pd.DataFrame(rows); pd.set_option("display.width", 250)
    print(out.to_string(index=False)); out.to_csv("data/plant_sensitivity.csv", index=False)

if __name__ == "__main__":
    main()
