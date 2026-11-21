"""
Smart Cooling Advisor - Streamlit prototype.
Run:  pip install streamlit pandas numpy scikit-learn
      python step1_model.py          # creates data/predictions.csv
      streamlit run app.py
"""
import numpy as np
import pandas as pd
import streamlit as st

import step2_simulate as sim

CLASS_NAME = {0: "Low", 1: "Medium", 2: "High"}
CLASS_COLOUR = {0: "#4CAF50", 1: "#FFB300", 2: "#E53935"}
ACTION = {
    0: "Low cooling need: set 26 °C. Keep doors closed; switch off AC in empty rooms.",
    1: "Medium cooling need: set 25 °C.",
    2: "High cooling need: set 24 °C. Avoid going below 24 °C — it does not cool faster.",
}

st.set_page_config(page_title="Smart Cooling Advisor", layout="wide")
st.title("Smart Cooling Advisor — UTP prototype")
st.caption("Based on 2024 modelled weather for Seri Iskandar (Open-Meteo). Energy figures are SIMULATED for one "
           "reference room. Not a live forecast and not connected to UTP systems.")


@st.cache_data
def load():
    return pd.read_csv("data/predictions.csv", parse_dates=["time"])


df = load()

# ---------------------------------------------------------------- sidebar: assumptions
st.sidebar.header("Reference room & AC assumptions")
P = dict(sim.PARAMS)
P["occupants"] = st.sidebar.slider("Occupants", 0, 60, 30)
P["floor_area"] = st.sidebar.slider("Floor area (m²)", 30, 120, 60)
P["n_units"] = st.sidebar.selectbox("Number of 2.0 HP inverter units", [1, 2, 3], index=1)
P["tariff_rm_kwh"] = st.sidebar.number_input("Tariff (RM/kWh)", value=0.5068, step=0.01, format="%.4f")
st.sidebar.caption("Defaults: Daikin FTKF50C datasheet; TNB non-domestic LV general tariff from 1 Jul 2025 "
                   "(energy + capacity + network); grid factor 0.740 kgCO2/kWh (Energy Commission, 2024 provisional).")

# ---------------------------------------------------------------- tab 1: hourly advice
tab1, tab2, tab3 = st.tabs(["Hourly advice", "Energy comparison", "About & limitations"])

with tab1:
    c1, c2 = st.columns([1, 2])
    with c1:
        day = st.date_input("Day (2024)", value=pd.Timestamp("2024-10-15"),
                            min_value=pd.Timestamp("2024-01-01"), max_value=pd.Timestamp("2024-12-31"))
        hour = st.slider("Current hour", 0, 23, 10)
    now = df[(df["time"].dt.date == day) & (df["hour"] == hour)].iloc[0]
    ahead = now["pred_ahead"]
    with c1:
        st.metric("Now: temperature / humidity", f"{now['temp']:.1f} °C / {now['rh']:.0f} %")
        st.metric("Now: heat index (feels like)", f"{now['hi']:.1f} °C ({CLASS_NAME[int(now['cls'])]})")
    with c2:
        if pd.notna(ahead):
            k = int(ahead)
            st.markdown(f"### Forecast for {(hour + 3) % 24:02d}:00 → "
                        f"<span style='color:{CLASS_COLOUR[k]}'>{CLASS_NAME[k]}</span>", unsafe_allow_html=True)
            st.info(ACTION[k])
            actual = now["cls_ahead"]
            if pd.notna(actual):
                st.caption(f"What actually happened at {(hour + 3) % 24:02d}:00: {CLASS_NAME[int(actual)]}")
    day_df = df[df["time"].dt.date == day].copy()
    day_df["Predicted"] = day_df["pred_for_t"].map(CLASS_NAME)
    day_df["Actual"] = day_df["cls"].map(CLASS_NAME)
    st.subheader("24-hour strip (office hours 08:00–18:00)")
    day_df["hi"] = day_df["hi"].round(1)
    strip = day_df[["hour", "Predicted", "Actual", "hi"]].set_index("hour").T.astype(str)
    st.dataframe(strip, width="stretch")
    st.line_chart(day_df.set_index("hour")[["temp", "hi"]].rename(columns={"temp": "Outdoor temp", "hi": "Heat index"}))

# ---------------------------------------------------------------- tab 2: energy
with tab2:
    period = st.radio("Period", ["Selected day", "Test period (Oct–Dec)"], horizontal=True)
    if period == "Selected day":
        mask = (df["time"].dt.date == day).values
    else:
        mask = (df["month"] >= 10).values
    strategies = {
        "S1 Fixed 24 °C (baseline)": "S1_fixed_24C",
        "SR Reactive rule, no AI": "SR_reactive_now",
        "S2 AI forecast-guided": "S2_AI_forecast",
        "S3 Perfect forecast": "S3_perfect",
        "S0 Habit 16 °C": "S0_habit_16C",
    }
    rows, hourly = [], {}
    with st.spinner("Simulating..."):
        for label, key in strategies.items():
            h = sim.simulate(df, key, P)
            rows.append(sim.summarise(h, mask, P, label))
            hourly[label] = h[mask]
    res = pd.DataFrame(rows).set_index("strategy")
    base = res.loc["S1 Fixed 24 °C (baseline)", "kWh"]
    res["vs baseline"] = ((res["kWh"] / base - 1) * 100).round(1).astype(str) + " %"
    st.dataframe(res[["kWh", "vs baseline", "RM", "kgCO2", "peak_kW", "hot_occupied_hours(>26C)",
                      "mean_indoor_occupied"]], width="stretch")
    if period == "Selected day":
        st.subheader("Indoor temperature and AC power through the day")
        temp_df = pd.DataFrame({k: v["t_air"].values for k, v in hourly.items()}, index=range(24))
        kw_df = pd.DataFrame({k: v["kwh"].values for k, v in hourly.items()}, index=range(24))
        st.line_chart(temp_df)
        st.bar_chart(kw_df)
    st.warning("These energy figures are SIMULATED from assumptions (room size, occupancy, AC datasheet, tariff). "
               "They are estimates for one reference room, not measurements of UTP buildings.")

with tab3:
    st.markdown("""
**What this tool does:** predicts whether outdoor cooling need will be Low / Medium / High **3 hours ahead**
(random forest trained on Jan–Sep 2024, tested on Oct–Dec 2024) and turns it into an AC setpoint suggestion.

**What it does not do:** measure indoor temperature, control any AC, use a live forecast, or know room occupancy.

**Honest result:** in our simulation, the forecast-guided strategy did not save energy compared with a fixed
24 °C schedule, and a simple no-AI rule based on the current weather saved more. The biggest saving comes from
not setting the AC to 16–18 °C (a habit change, not AI). See the report for details.
""")
