"""Step 7: extra plant cases (20,000 RTh tank, 40% margin with noisy load). SIMULATED. Run: python step7_extra_cases.py"""
import pandas as pd, step5_plant as pl, step6_plant_sensitivity as s6
df = pd.read_csv("data/predictions.csv", parse_dates=["time"])
B = dict(pl.PLANT); rows=[]
for label, ch, months in [
  ("Tank 20,000 RTh, Oct-Dec", {"tes_capacity_rth":20000.0}, [10,11,12]),
  ("Tank 20,000 RTh, Apr-Jul", {"tes_capacity_rth":20000.0}, [4,5,6,7]),
  ("Tank 20,000 RTh + 3,000 RT discharge, Apr-Jul", {"tes_capacity_rth":20000.0,"tes_max_discharge_rt":3000.0}, [4,5,6,7]),
  ("40% margin, noisy 10%, Oct-Dec", {"margin":0.40,"noise_daily":0.10,"noise_hourly":0.05}, [10,11,12]),
]:
    P = {**B, **ch}; pl.PLANT.clear(); pl.PLANT.update(P)
    rows.append(s6.run_case(df, P, months, label)); pl.PLANT.clear(); pl.PLANT.update(B)
pd.set_option("display.width",250); out=pd.DataFrame(rows); print(out.to_string(index=False)); out.to_csv("data/plant_extra_cases_tank20k_margin40.csv", index=False)
