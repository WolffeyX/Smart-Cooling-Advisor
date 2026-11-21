"""
Smart Cooling Advisor - Step 2: energy simulation of ONE reference room with a real AC unit.

Everything here is SIMULATED: results depend on the assumptions in PARAMS below.
Change PARAMS (or the sensitivity list at the bottom) and re-run to see how conclusions move.

Input : data/predictions.csv  (from step1_model.py)
Output: printed results tables, data/sim_hourly_<strategy>.csv
Run   : python step2_simulate.py
"""
import numpy as np
import pandas as pd

# ---------------------------------------------------------------- assumptions
PARAMS = dict(
    # Room: 60 m2 tutorial room, 3 m high, mid-floor, one external wall with windows
    floor_area=60.0, height=3.0,
    ua_envelope=101.0,        # W/K  windows 6 m2 x 5.7 + ext wall 18 m2 x 2.5 + corridor wall 22.5 m2 x 2.0 x 0.5
    ach_base=0.5,             # air changes/h, infiltration (doors closed)
    ach_occupied_extra=0.5,   # extra air changes/h while occupied (door opening)
    c_air=0.82e6,             # J/K  room air (0.22 MJ/K) + furniture (0.6 MJ/K)
    c_mass=12.0e6,            # J/K  effective concrete mass (slabs ~5 cm active depth)
    h_mass=500.0,             # W/K  air <-> mass surface coupling
    window_area=6.0, shgc=0.5, f_vertical=0.3,   # solar: GHI x area x SHGC x vertical factor
    occupants=30, sens_per_person=75.0, lat_per_person=55.0,   # W
    lights_w=600.0, equip_w=300.0,
    occ_start=8, occ_end=18,  # occupied 08:00-18:00 on weekdays
    # AC: 2 x Daikin FTKF50C (2.0 HP inverter) - datasheet: 5.28 kW (1.52-5.42) cooling, 1,880 W (380-1,950) input
    n_units=2, cap_rated=5.28e3, cap_max=5.42e3, cap_min=1.52e3,
    p_rated=1880.0, p_min=380.0,
    cop_out_slope=0.025,      # COP +2.5% per degC cooler outdoor than 35 degC (assumed)
    cop_in_slope=0.02,        # COP -2% per degC indoor setpoint below 27 degC (assumed)
    cd_cycling=0.25,          # cycling degradation below minimum capacity (EN 14825 default)
    indoor_rh=0.55,           # target indoor RH for latent load
    latent=True,
    # Comfort & money
    comfort_max=26.0,         # MS 1525 design range upper bound (degC)
    tariff_rm_kwh=0.5068,     # LV non-domestic general: energy 27.03 + capacity 8.83 + network 14.82 sen/kWh
    md_rm_kw=89.27,           # MV general: capacity 29.43 + network 59.84 RM/kW of monthly max demand
    co2_kg_kwh=0.740,         # Peninsular grid emission factor 2024 (provisional), Energy Commission
    dt=300,                   # s, simulation step (5 min)
)

SETPOINT = {0: 26.0, 1: 25.0, 2: 24.0}   # Low / Medium / High -> setpoint (degC)
PRECOOL_SETPOINT = 23.0
SAFETY_TEMP = 26.5                        # indoor override: AC switches on if room passes this while occupied


# ---------------------------------------------------------------- helpers
def humidity_ratio(t_c, rh_frac, p=101325.0):
    pws = 610.94 * np.exp(17.625 * t_c / (t_c + 243.04))
    pw = rh_frac * pws
    return 0.622 * pw / (p - pw)


def cop(q_total, t_out, t_set, P):
    """Electrical COP of the installed units at this load and conditions."""
    cop_rated = P["cap_rated"] / P["p_rated"]
    cop_min_ratio = (P["cap_min"] / P["p_min"]) / cop_rated
    plr = q_total / (P["n_units"] * P["cap_rated"])
    plr_min = P["cap_min"] / P["cap_rated"]
    f_out = np.clip(1 + P["cop_out_slope"] * (35.0 - t_out), 0.6, 1.4)
    f_in = np.clip(1 + P["cop_in_slope"] * (t_set - 27.0), 0.6, 1.2)
    if plr >= plr_min:
        f_plr = 1 + (cop_min_ratio - 1) * (1 - plr) / (1 - plr_min)
    else:
        f_plr = cop_min_ratio * (1 - P["cd_cycling"] * (1 - plr / plr_min))
    return cop_rated * f_out * f_in * f_plr


# ---------------------------------------------------------------- control strategies
def schedule(df, strategy, P):
    """Return (ac_on, setpoint) per hour. Decisions use only info available at that hour."""
    occ = df["weekday"] & (df["hour"] >= P["occ_start"]) & (df["hour"] < P["occ_end"])
    on = occ.copy()
    sp = pd.Series(np.nan, index=df.index)

    if strategy == "S0_habit_16C":
        sp[:] = 16.0
    elif strategy == "S1_fixed_24C":
        sp[:] = 24.0
    elif strategy in ("SR_reactive_now", "S2_AI_forecast", "S3_perfect", "S2_AI_no_precool", "S2_AI_setpoint_only"):
        if strategy == "SR_reactive_now":        # no AI: use the class measured NOW
            cls_t, cls_ahead = df["cls"], None
        elif strategy == "S3_perfect":           # oracle: true class now and true class in 3 h
            cls_t, cls_ahead = df["cls"], df["cls_ahead"]
        else:                                    # our model: prediction made 3 h ago, and prediction for 3 h ahead
            cls_t, cls_ahead = df["pred_for_t"].fillna(df["cls"]), df["pred_ahead"]
        sp = cls_t.map(SETPOINT).astype(float)
        if strategy in ("S2_AI_forecast", "S3_perfect"):
            # delayed start: first two office hours stay off if Low is expected (safety override in simulate())
            delay = occ & df["hour"].isin([P["occ_start"], P["occ_start"] + 1]) & (cls_t == 0)
            on = on & ~delay
            # pre-cool: if High is expected in 3 h and it is not High yet, cool to 23 degC now
            pre = occ & (cls_ahead == 2) & (cls_t != 2)
            sp = sp.where(~pre, PRECOOL_SETPOINT)
        if strategy == "S2_AI_no_precool":
            delay = occ & df["hour"].isin([P["occ_start"], P["occ_start"] + 1]) & (cls_t == 0)
            on = on & ~delay
    else:
        raise ValueError(strategy)
    return on.values, sp.values, occ.values


# ---------------------------------------------------------------- 2-node room simulation
def simulate(df, strategy, P=PARAMS):
    on_h, sp_h, occ_h = schedule(df, strategy, P)
    n_sub = int(3600 / P["dt"])
    vol = P["floor_area"] * P["height"]
    t_air, t_mass = 28.0, 28.0
    q_max_total = P["n_units"] * P["cap_max"]

    rec = {k: np.zeros(len(df)) for k in ["t_air", "kwh", "q_sens", "q_lat", "ac_on"]}
    T_out = df["temp"].values
    RH_out = df["rh"].values / 100
    GHI = df["sw_rad"].values

    for i in range(len(df)):
        occ = occ_h[i]
        ach = P["ach_base"] + (P["ach_occupied_extra"] if occ else 0.0)
        ua_inf = ach * vol / 3600 * 1.2 * 1005
        ua = P["ua_envelope"] + ua_inf
        q_int = (P["occupants"] * P["sens_per_person"] + P["lights_w"] + P["equip_w"]) if occ else 0.0
        q_sol = GHI[i] * P["window_area"] * P["shgc"] * P["f_vertical"]
        gain_air = 0.6 * q_int + 0.3 * q_sol
        gain_mass = 0.4 * q_int + 0.7 * q_sol

        running = bool(on_h[i])
        sp = sp_h[i] if not np.isnan(sp_h[i]) else 24.0
        e_wh = 0.0; t_sum = 0.0; qs_sum = 0.0; ql_sum = 0.0
        for _ in range(n_sub):
            # safety override: occupied room too warm -> AC on even if the schedule said off
            if occ and not running and t_air > SAFETY_TEMP:
                running = True
            q_sens = 0.0; q_lat = 0.0
            if running:
                if P["latent"]:
                    w_out = humidity_ratio(T_out[i], RH_out[i])
                    w_in = humidity_ratio(sp, P["indoor_rh"])
                    m_air = ach * vol / 3600 * 1.2
                    q_lat = (P["occupants"] * P["lat_per_person"] if occ else 0.0) + max(0.0, m_air * 2.45e6 * (w_out - w_in))
                    q_lat = min(q_lat, 0.35 * q_max_total)
                free = gain_air + ua * (T_out[i] - t_air) + P["h_mass"] * (t_mass - t_air)
                need = P["c_air"] / P["dt"] * (t_air - sp) + free      # W to land exactly on setpoint
                q_sens = float(np.clip(need, 0.0, q_max_total - q_lat))
                if q_sens <= 0:
                    q_lat = q_lat if occ else 0.0                       # fan/dehumidification still runs
                q_tot = q_sens + q_lat
                if q_tot > 0:
                    p_el = q_tot / cop(q_tot, T_out[i], sp, P)
                    e_wh += p_el * P["dt"] / 3600
            d_air = (gain_air + ua * (T_out[i] - t_air) + P["h_mass"] * (t_mass - t_air) - q_sens) / P["c_air"]
            d_mass = (gain_mass + P["h_mass"] * (t_air - t_mass)) / P["c_mass"]
            t_air += d_air * P["dt"]; t_mass += d_mass * P["dt"]
            t_sum += t_air; qs_sum += q_sens; ql_sum += q_lat
        rec["t_air"][i] = t_sum / n_sub
        rec["kwh"][i] = e_wh / 1000
        rec["q_sens"][i] = qs_sum / n_sub
        rec["q_lat"][i] = ql_sum / n_sub
        rec["ac_on"][i] = running
    out = df[["time", "hour", "month", "weekday", "temp", "cls"]].copy()
    for k, v in rec.items():
        out[k] = v
    out["occ"] = occ_h
    return out


def summarise(sim, mask, P=PARAMS, label=""):
    s = sim[mask]
    days = s.loc[s["weekday"], "time"].dt.date.nunique()
    kwh = s["kwh"].sum()
    occ = s["occ"]
    hot = (s.loc[occ, "t_air"] > P["comfort_max"] + 0.05)
    daily_peak = s.groupby(s["time"].dt.date)["kwh"].max()
    tou_peak = s["weekday"] & s["hour"].between(14, 21)
    return {
        "strategy": label,
        "kWh": round(kwh, 1),
        "kWh_per_weekday": round(kwh / max(days, 1), 2),
        "RM": round(kwh * P["tariff_rm_kwh"], 2),
        "kgCO2": round(kwh * P["co2_kg_kwh"], 1),
        "peak_kW": round(s["kwh"].max(), 2),
        "avg_daily_peak_kW": round(daily_peak[daily_peak > 0].mean(), 2),
        "kWh_in_ToU_peak(14-22)": round(s.loc[tou_peak, "kwh"].sum(), 1),
        "hot_occupied_hours(>26C)": int(hot.sum()),
        "degree_hours_above_26": round((s.loc[occ, "t_air"] - P["comfort_max"]).clip(lower=0).sum(), 1),
        "mean_indoor_occupied": round(s.loc[occ, "t_air"].mean(), 2),
    }


STRATEGIES = ["S0_habit_16C", "S1_fixed_24C", "SR_reactive_now",
              "S2_AI_setpoint_only", "S2_AI_no_precool", "S2_AI_forecast", "S3_perfect"]


def run_all(df, P=PARAMS, period_mask=None, save=False):
    rows = []
    for s in STRATEGIES:
        sim = simulate(df, s, P)
        if save:
            sim.to_csv(f"data/sim_hourly_{s}.csv", index=False)
        m = period_mask if period_mask is not None else np.ones(len(sim), bool)
        rows.append(summarise(sim, m, P, s))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    test = (df["month"] >= 10).values
    pd.set_option("display.width", 250)

    res_test = run_all(df, period_mask=test, save=True)
    print("\nSIMULATED - TEST PERIOD Oct-Dec 2024 (honest out-of-sample predictions)")
    print(res_test.to_string(index=False))

    res_year = run_all(df)
    print("\nSIMULATED - FULL YEAR 2024 (Jan-Sep predictions are leave-one-month-out)")
    print(res_year.to_string(index=False))
    res_test.to_csv("data/results_test.csv", index=False)
    res_year.to_csv("data/results_year.csv", index=False)
