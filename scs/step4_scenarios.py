"""
Smart Cooling Advisor - Step 4: where could a 3-hour forecast add value?
Fair test = the SAME action done (a) never, (b) every day, (c) only when the AI forecasts it, (d) with a perfect forecast.
The AI's value = (c) beats both (a) and (b) on the KPIs.
Run: python step4_scenarios.py
"""
import numpy as np
import pandas as pd
import step2_simulate as sim

TOU = dict(peak=0.2852 + 0.0883 + 0.1482, off=0.2443 + 0.0883 + 0.1482)


def make_schedule(trigger, pre_hours, pre_sp=23.0, base_sp=24.0, peak_sp=None, peak_hours=(14, 18)):
    """Pre-cool during pre_hours when trigger(df) is True for that row; optional raised setpoint in peak_hours."""
    def schedule(df, strategy, P):
        occ = df["weekday"] & (df["hour"] >= P["occ_start"]) & (df["hour"] < P["occ_end"])
        sp = pd.Series(base_sp, index=df.index, dtype=float)
        fire = trigger(df)
        pre = occ & df["hour"].isin(pre_hours) & fire
        sp[pre] = pre_sp
        if peak_sp is not None:
            pk = occ & df["hour"].between(peak_hours[0], peak_hours[1] - 1)
            day_fired = fire.groupby(df["time"].dt.date).transform("max") if fire.dtype == bool else fire
            sp[pk & day_fired] = peak_sp
        return occ.values, sp.values, occ.values
    return schedule


def kpis(h, P, label, occ_mask):
    peak = h["weekday"] & h["hour"].between(14, 21)
    hot = h.loc[occ_mask, "t_air"] > P["comfort_max"] + 0.05
    return {
        "strategy": label,
        "kWh": round(h["kwh"].sum(), 1),
        "ToU_RM": round(h.loc[peak, "kwh"].sum() * TOU["peak"] + h.loc[~peak, "kwh"].sum() * TOU["off"], 1),
        "kWh_14_18": round(h.loc[h["weekday"] & h["hour"].between(14, 17), "kwh"].sum(), 1),
        "mean_daily_peak_kW_14_18": round(h[h["weekday"] & h["hour"].between(14, 17)].groupby(h["time"].dt.date)["kwh"].max().mean(), 3),
        "hot_hours": int(hot.sum()),
        "degree_hours>26": round((h.loc[occ_mask, "t_air"] - 26).clip(lower=0).sum(), 1),
    }


def run(df, P, schedules, mask):
    rows = []
    orig = sim.schedule
    for label, sch in schedules.items():
        sim.schedule = sch
        h = sim.simulate(df, label, P)[mask]
        rows.append(kpis(h, P, label, h["occ"].values))
    sim.schedule = orig
    return pd.DataFrame(rows)


def main():
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    test = (df["month"] >= 10).values
    pd.set_option("display.width", 250)
    # trigger at hour t: is High expected 3 h later?  (pre-cool at 10-11 for a 13-14 heat peak)
    ai = lambda d: d["pred_ahead"] == 2
    perfect = lambda d: d["cls_ahead"] == 2
    always = lambda d: pd.Series(True, index=d.index)
    never = lambda d: pd.Series(False, index=d.index)

    # Scenario 1: UNDERSIZED room (1 x 2.0 HP for 30 people) - can pre-cooling on forecast hot days protect comfort?
    P1 = {**sim.PARAMS, "n_units": 1}
    sch1 = {f"{k}": make_schedule(t, pre_hours=[9, 10, 11]) for k, t in
            [("never_precool", never), ("always_precool", always), ("AI_precool", ai), ("perfect_precool", perfect)]}
    r1 = run(df, P1, sch1, test)
    print("\nSCENARIO 1 - undersized room (1 unit), pre-cool 09-12 to 23C. SIMULATED Oct-Dec 2024")
    print(r1.to_string(index=False))

    # Scenario 2: ToU / peak shaving - pre-cool 11-14 then let setpoint float to 25.5C during 14-18 peak window
    P2 = dict(sim.PARAMS)
    sch2 = {
        "S1_fixed_24C": make_schedule(never, pre_hours=[]),
        "always_shift": make_schedule(always, pre_hours=[11, 12, 13], peak_sp=25.5),
        "AI_shift": make_schedule(ai, pre_hours=[11, 12, 13], peak_sp=25.5),
        "perfect_shift": make_schedule(perfect, pre_hours=[11, 12, 13], peak_sp=25.5),
        "always_raise_no_precool": make_schedule(always, pre_hours=[], peak_sp=25.5),
    }
    r2 = run(df, P2, sch2, test)
    print("\nSCENARIO 2 - peak shifting for ToU (pre-cool 11-14, 25.5C in 14-18). SIMULATED Oct-Dec 2024")
    print(r2.to_string(index=False))
    r1.to_csv("data/scenario1_undersized.csv", index=False)
    r2.to_csv("data/scenario2_peakshift.csv", index=False)


if __name__ == "__main__":
    main()


def scenario3():
    """Early shut-off: switch AC off at 16:00 (coast on stored cool) only if the afternoon will not be High."""
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    test = (df["month"] >= 10).values
    P = dict(sim.PARAMS)

    def make(fn):
        def schedule(d, s, P):
            occ = d["weekday"] & (d["hour"] >= P["occ_start"]) & (d["hour"] < P["occ_end"])
            on = occ.copy()
            off = occ & d["hour"].isin([16, 17]) & fn(d)
            on[off] = False
            return on.values, np.full(len(d), 24.0), occ.values
        return schedule
    # forecast for 16:00 made at 13:00 is pred_for_t at 16:00; reactive uses class measured at 16:00 itself
    pred16 = lambda d: d.groupby(d["time"].dt.date)["pred_for_t"].transform(lambda s: s.iloc[16] if len(s) > 16 else np.nan) < 2
    real16 = lambda d: d.groupby(d["time"].dt.date)["cls"].transform(lambda s: s.iloc[16] if len(s) > 16 else np.nan) < 2
    schedules = {
        "never_shutoff (S1)": make(lambda d: pd.Series(False, index=d.index)),
        "always_shutoff_16": make(lambda d: pd.Series(True, index=d.index)),
        "AI_shutoff_if_not_High": make(pred16),
        "reactive_if_not_High_at_16": make(real16),
    }
    r = run(df, P, schedules, test)
    print("\nSCENARIO 3 - early shut-off at 16:00 (safety override >26.5C). SIMULATED Oct-Dec 2024")
    print(r.to_string(index=False))


if __name__ == "__main__":
    scenario3()
