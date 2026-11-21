"""
Smart Cooling Advisor - Step 3: sensitivity analysis.
Does the conclusion (S2 vs S1, S2 vs SR) flip when the assumptions change?
Run: python step3_sensitivity.py
"""
import pandas as pd
import step2_simulate as sim

TOU = dict(peak=0.2852 + 0.0883 + 0.1482, off=0.2443 + 0.0883 + 0.1482)  # LV non-domestic ToU, RM/kWh


def tou_cost(h):
    peak = h["weekday"] & h["hour"].between(14, 21)
    return (h.loc[peak, "kwh"].sum() * TOU["peak"] + h.loc[~peak, "kwh"].sum() * TOU["off"])


VARIANTS = {
    "Base case": {},
    "Half occupancy (15 people)": {"occupants": 15},
    "Empty room (0 people, lights on)": {"occupants": 0},
    "Leakier room (UA +30%)": {"ua_envelope": 131.0, "ach_base": 0.65},
    "Tighter room (UA -30%)": {"ua_envelope": 71.0, "ach_base": 0.35},
    "Light building (mass x0.5)": {"c_mass": 6.0e6},
    "Heavy building (mass x2)": {"c_mass": 24.0e6},
    "Weak outdoor COP effect (1.5%/C)": {"cop_out_slope": 0.015},
    "Strong outdoor COP effect (3.5%/C)": {"cop_out_slope": 0.035},
    "No indoor-setpoint COP effect": {"cop_in_slope": 0.0},
    "No latent (humidity) load": {"latent": False},
    "Bigger windows (12 m2)": {"window_area": 12.0},
}


def main():
    df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
    test = (df["month"] >= 10).values
    rows = []
    for name, change in VARIANTS.items():
        P = {**sim.PARAMS, **change}
        res = {}
        for s in ["S1_fixed_24C", "SR_reactive_now", "S2_AI_forecast", "S2_AI_setpoint_only", "S3_perfect"]:
            h = sim.simulate(df, s, P)[test]
            res[s] = (h["kwh"].sum(), tou_cost(h),
                      int((h.loc[h["occ"], "t_air"] > P["comfort_max"] + 0.05).sum()))
        b = res["S1_fixed_24C"][0]
        rows.append({
            "variant": name,
            "S1_kWh": round(b, 0),
            "SR_vs_S1_%": round(100 * (res["SR_reactive_now"][0] / b - 1), 1),
            "S2full_vs_S1_%": round(100 * (res["S2_AI_forecast"][0] / b - 1), 1),
            "S2setpt_vs_S1_%": round(100 * (res["S2_AI_setpoint_only"][0] / b - 1), 1),
            "S3perfect_vs_S1_%": round(100 * (res["S3_perfect"][0] / b - 1), 1),
            "S2full_ToU_RM_vs_S1_%": round(100 * (res["S2_AI_forecast"][1] / res["S1_fixed_24C"][1] - 1), 1),
            "S2full_hot_hrs": res["S2_AI_forecast"][2],
        })
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 250)
    print("\nSIMULATED sensitivity, test period Oct-Dec 2024 (negative % = saves energy vs S1 fixed 24C)")
    print(out.to_string(index=False))
    out.to_csv("data/sensitivity.csv", index=False)


if __name__ == "__main__":
    main()
