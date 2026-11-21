# Smart Cooling Advisor — code pack (TEB2023)

1. `pip install -r requirements.txt`
2. `python step1_model.py`        → heat index, 3-h-ahead random forest, baselines, writes data/predictions.csv
3. `python step2_simulate.py`     → energy simulation S0–S3 (one 60 m² room, 2 × Daikin FTKF50C), writes results
4. `python step3_sensitivity.py`  → does the conclusion flip when assumptions change?
5. `streamlit run app.py`         → prototype dashboard
6. `python step4_scenarios.py`    → room-level scenarios (undersized room, peak shift, early shut-off)
7. `python step5_plant.py`        → PLANT-level model of UTP GDC (TES charging decision)
8. `python step6_plant_sensitivity.py` → plant sensitivity, hot season, noisy load

Data: `data/seri_iskandar_2024_openmeteo.csv` — Open-Meteo Historical Weather API, 4.39N 100.97E,
1 Jan–31 Dec 2024, hourly, timezone GMT+8 (grid cell elevation 47 m; the team's earlier file used 20 m,
so class shares differ by <1 percentage point).

All energy figures are SIMULATED. Every assumption is in `PARAMS` at the top of step2_simulate.py.
