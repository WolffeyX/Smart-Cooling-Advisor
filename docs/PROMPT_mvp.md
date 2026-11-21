# ROLE AND GOAL
You are building a working localhost MVP of "Smart Cooling Advisor", a TEB2023 (UTP) student
AI project. It recommends, each night at 22:00, how much the electric chillers at UTP's Gas
District Cooling plant should charge the chilled-water storage tank for tomorrow. Every number
it shows is SIMULATED (model + assumptions). There is no live UTP data and no live connection.
Report due 23 Nov 2026: a working MVP beats polish.

The attached code pack is in ./scs/ (step1_model.py, step2_simulate.py, step5_plant.py,
step6_plant_sensitivity.py, data/seri_iskandar_2024_openmeteo.csv, data/*.csv). The approved
UI sketch is ./Smart_Cooling_Advisor_plant_dashboard_sketch.pdf (page 1 = operator dashboard,
page 2 = phone alert). Read both fully before planning. Do not invent results.

# PROCESS (mandatory, in this order)
1. Run /superpowers:using-superpowers.
2. Use superpowers:brainstorming to settle the open design questions listed under
   "DECISIONS TO CONFIRM". Ask me one question at a time, recommend an answer for each.
3. Use superpowers:writing-plans to write the implementation plan to docs/plan.md, with
   small tasks, each with its test first. STOP and wait for my explicit approval of the plan.
   Do not write production code before I approve.
4. Execute with superpowers:subagent-driven-development. One fresh subagent per task.
   Every implementation task follows superpowers:test-driven-development (failing test first).
5. Review, testing and debugging are done by SEPARATE subagents, never by the agent that wrote
   the code: use superpowers:requesting-code-review after each task group, and
   superpowers:systematic-debugging for any failure (root cause before fix).
6. Before saying anything is done, use superpowers:verification-before-completion: run the
   commands, paste the real output, and check every item in "DONE MEANS".

# MODEL ASSIGNMENT FOR SUBAGENTS (maximum: Opus 5.5 at high effort)
Set the model (and effort) explicitly on every subagent call.
- Haiku: file scaffolding, requirements.txt, README skeleton, lint and formatting (ruff),
  simple unit tests (schema validation, /health).
- Sonnet: feature implementation, refactoring step5 dispatch into a pure function, API
  endpoints, the frontend port of the sketch, writing the tests, routine debugging,
  Playwright screenshots.
- Opus 5.5, effort high, ONLY for:
  a) reviewing the plant dispatch logic (energy balance, tank limits, charging window, margin
     and capping, shortfall accounting);
  b) reviewing the ML pipeline (data leakage, train/test split by date, baselines, that no
     feature uses information after 22:00 the day before, that test months are never seen in
     training);
  c) the final whole-repo code review;
  d) hard bugs that a Sonnet debugging subagent failed to fix in two attempts.
Never use Opus for scaffolding, formatting or routine features.

# KNOWN ISSUES IN THE CODE PACK (handle these, do not copy the bugs)
- step6_plant_sensitivity.py: the original had `B = pl.PLANT` (aliasing), so each case
  leaked its settings into the next. This folder already contains the FIXED version and the
  corrected data/plant_sensitivity.csv. In new code, pass a params dict explicitly and never
  mutate module globals.
- step5_plant.dispatch() runs a whole year with a module-level PLANT dict and a hard-coded
  starting tank level of 5,000 RTh. Refactor into a pure function that takes a 24-hour load
  profile (22:00 to 21:00), the starting tank level, the charge target and a params dict,
  and returns hourly arrays. Keep the same physics (SAC first, then tank in the daytime, then
  electric chillers with staging and the part-load penalty; 95% charge efficiency; 0.4%/h
  standby loss; 10-hour charging window 22:00-08:00; max discharge 2,500 RT).
- The "day-ahead weather forecast" in step5 is the true value plus noise. Keep it, but label
  it as simulated in the UI's assumptions panel.
- Keep all plant parameters in ONE params dict (app/config.py). Default = the code pack's
  values (so results reproduce step5). Add a second preset "published_utp_data" labelled
  ASSUMPTION for a sensitivity toggle later: standby loss 0.05%/h, electric chillers
  0.82 kW/RT + 0.24 kW/RT auxiliaries, absorption chillers 1,800 RT available. Do not expose
  it in the UI in the MVP; just make it switchable by an env var.
- Campus load is synthetic (room model scaled to ~1,250 rooms + 350 RT base load). It is slow
  to build (step2 simulates 5-minute steps for a year), so build it ONCE at startup (or cache
  to data/campus_load_2024.parquet / .csv) and train the forecast model once. Startup must
  finish in under 60 s on a laptop.

# MVP SCOPE
## Backend: Python 3.11+, FastAPI, uvicorn
Package layout:
  app/main.py        FastAPI app, mounts static/ at "/", serves index.html
  app/model.py       wraps step1_model (heat index, features) and the step5 daily forecaster
  app/plant.py       pure dispatch function + strategy comparison (refactored from step5)
  app/scenario.py    turns request inputs into a 24-h load profile and forecasts
  app/schemas.py     Pydantic request/response models
  static/index.html, static/app.js, static/styles.css
  tests/             pytest
Reuse step1_model.py and step5_plant.py by importing them (copy them into app/legacy/ if
imports are awkward); do not rewrite their science.

### GET /health
Returns {"status": "ok", "model_trained": true, "label": "SIMULATED"}.

### POST /recommend
Request (validate ranges, 422 on bad input):
{
  "day_type": "weekday" | "exam_week" | "semester_break" | "weekend",
  "forecast_max_temp_c": number, 24 to 38,
  "safety_margin_pct": number, 0 to 60, default 10,
  "tank_capacity_rth": number, 5000 to 25000, default 10000,
  "tank_level_22_rth": number, 0 to tank_capacity_rth, default 1500,
  "forecast_error_pct": number, -30 to 30, default 0   // "what if the AI is wrong?" slider
}
Scenario construction: pick the 2024 day (test months Oct-Dec preferred) of the matching
calendar type whose daily max temperature is closest to forecast_max_temp_c; use its
synthetic hourly campus load from 22:00 the night before to 21:00, and the AI forecast that
the Jan-Sep-trained model made for it. "Actual need" is that day's simulated tank need and
does not change with the error slider. The slider changes only the forecast:
ai_forecast_used = ai_forecast * (1 + forecast_error_pct/100), so it shows what happens when
the forecast is wrong and actual demand is unchanged. Exam week and
semester break are not in the 2024 data: implement them as multipliers on the room-driven
part of the load, stored in one config dict with the label ASSUMPTION (see DECISIONS).
If no Oct-Dec day of that type is within 1 C of the requested max temperature (for example a
34 C weekday), search the whole year. For any day in Jan-Sep, use an out-of-sample forecast
from a model retrained WITHOUT that day's month (leave-one-month-out, as step6 does); never
show an in-sample forecast. Put the chosen date and the forecast's training months in
`scenario`.

Response (all energy and plant numbers are SIMULATED):
{
  "label": "SIMULATED",
  "scenario": {"source_date": "2024-10-15", "day_type": "...", "source_tmax_c": 31.2},
  "recommendation": {
    "charge_target_rth": number,            // min(capacity, ai_forecast_used * (1+margin))
    "ai_forecast_need_rth": number,
    "actual_need_rth": number,
    "capped": bool,                         // true if the target hit tank capacity
    "electric_chillers": {"count": int, "start": "22:00", "end": "08:00"},
    "daytime_ec_hours": int,
    "shortfall_rth": number,
    "status": "ok" | "shortfall" | "capped",
    "message": "plain-English one-liner"
  },
  "hourly": [  // exactly 24 rows, 22:00 .. 21:00
    {"hour": "22:00", "campus_load_rt": n, "sac_rt": n, "tank_out_rt": n,
     "ec_load_rt": n, "charge_rt": n, "ec_count": int, "ec_kw": n,
     "tank_level_rth": n, "unmet_rt": n}
  ],
  "comparison": [  // always these three, in this order
    {"strategy": "always_full", "charge_target_rth": n, "ec_energy_kwh": n,
     "vs_always_full_pct": null, "daytime_ec_hours": int, "shortfall_rth": n},
    {"strategy": "calendar_rule", ...},
    {"strategy": "ai_forecast", ...}
  ],
  "plant": {"sac_available_rt": 2200, "n_ec": 4, "ec_unit_rt": 325,
            "tes_max_discharge_rt": 2500, "charge_window": "22:00-08:00"},
  "assumptions": ["Campus load is synthetic ...", "Day-ahead weather forecast simulated ...", ...]
}

## Frontend: one page, plain HTML + JS + SVG, no build step, no framework
Port the approved sketch (page 1) faithfully:
- Header: title, "UTP Gas District Cooling · tonight's tank-charging plan", the scenario date,
  badges "SIMULATED prototype · illustrative numbers" and "Model: random forest, day-ahead".
- Left "Test new values" card: day-type segmented buttons (Weekday, Exam week, Semester
  break, Weekend), sliders for forecast max temperature, AI forecast error, safety margin,
  tank usable capacity, tank level at 22:00, and the fixed-plant note.
- Centre: isometric SVG plant view (absorption chillers, 4 electric chillers that light up
  when running, storage tank whose fill height = tank_level_rth / capacity, campus
  buildings, flow lines), Play 24 h / Pause and Reset buttons, a time scrubber over the 24
  hours, and four stat tiles (campus load, absorption chillers, tank in/out, electric
  chillers) for the selected hour.
- Right "Tonight's recommendation" card: charge target, chiller plan, AI forecast vs actual
  need, daytime electric chillers, cooling shortfall, a status note, "Approve plan" and
  "Adjust manually" buttons (they only show a toast: "Demo only, nothing is sent"), and
  "The operator always decides."
- Charts (SVG): stacked hourly bars "Who supplies the cold" (absorption, tank, electric,
  charging) with the selected hour highlighted; "Tank level over the next 24 h".
- Comparison table "Same day, three ways to decide the charge" from `comparison`, with the
  honest footnote: AI beats the weekday/weekend rule by about 1-2% of electric-chiller
  energy in cooler months and ~0% in hot months (SIMULATED).
- Debounce slider changes (300 ms) and call POST /recommend. Every number on screen comes
  from the API; nothing hard-coded except labels.
- Visible "SIMULATED" label on the page and in every chart caption.

## Run
  pip install -r requirements.txt
  uvicorn app.main:app
  open http://localhost:8000

## Tests (pytest; all must pass)
- Model: heat index matches the NWS formula at 3 reference points; the classifier is trained
  only on Jan-Sep and its Oct-Dec accuracy reproduces 0.788 +/- 0.005; no feature column is
  derived from t+3 or later (leakage test); the daily forecaster uses only features known at
  22:00 the day before.
- Dispatch energy balance, for every hour of several scenarios (hot weekday, cool weekday,
  weekend, semester break, tank capacity 5,000 and 25,000, margin 0 and 60):
  sac_rt + tank_out_rt + ec_load_rt + unmet_rt == campus_load_rt (to 1e-6), where
  ec_load_rt is the electric-chiller output that serves the campus (excluding unmet), and
  total electric-chiller output == ec_load_rt + charge_rt <= n_ec * ec_unit_rt; tank level never negative and never above capacity; tank
  discharges only 08:00-21:00 and charges only 22:00-07:00; level change ==
  charge*0.95 - tank_out - standby loss; shortfall_rth == sum(unmet_rt) and is reported.
- Strategy logic: always_full target == capacity; capped == (ai*(1+margin) > capacity);
  with forecast_error 0 and margin 0, ai target equals the model forecast.
- API: /health 200; /recommend returns 24 hourly rows and 3 comparison rows in order;
  out-of-range input returns 422; response label is "SIMULATED".
- Regression: running the refactored year-long dispatch for Oct-Dec reproduces
  step5's plant_results.csv electric-chiller MWh within 0.5%.

# OUT OF SCOPE
Login, any database, cloud deployment, live weather feeds, any connection to UTP systems,
mobile app (the phone alert in the sketch is NOT part of this MVP).

# DECISIONS TO CONFIRM DURING BRAINSTORMING (recommend an answer for each)
1. Exam-week and semester-break load multipliers (suggest exam week 0.9 and semester break
   0.35 on the room-driven load, labelled ASSUMPTION).
2. Scenario construction: nearest 2024 day by type and max temperature (recommended) vs
   scaling a typical profile.
3. Whether the AI forecast for exam week / semester break is the matched weekday's forecast
   times the same multiplier (shows the AI at its best) or the unscaled weekday forecast (shows
   what happens when the model has never seen a break). Recommend showing the honest one.
4. Cache format for the synthetic load (CSV recommended; no extra dependency).

# DONE MEANS (verify each with real command output)
- `pytest -q` passes with zero failures; paste the summary line.
- `uvicorn app.main:app` starts and `curl localhost:8000/health` returns ok.
- README.md with install, run, test steps, the SIMULATED/MEASURED/PROPOSED labelling, the
  assumptions list and known limitations (synthetic load, one year of weather, no PMMD data).
- Screenshots in docs/screenshots/ taken with Playwright at 1440x900, deviceScaleFactor 2:
  hot_weekday.png (weekday, 34 C), cool_weekday.png (weekday, 29 C),
  semester_break.png (semester break, 31 C). Each shows the recommendation and the
  comparison table.
- A final Opus 5.5 (high effort) code review with all Critical/Important findings fixed.
