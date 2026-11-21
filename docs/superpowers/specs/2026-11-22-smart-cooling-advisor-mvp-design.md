# Smart Cooling Advisor — localhost MVP design

Date: 2026-11-22 · Due: 23 Nov 2026 · Source brief: `docs/PROMPT_mvp.md` (the full spec; this
document records the decisions taken on top of it and does not repeat everything in it).

## 1. Intent

TEB2023 (UTP) student AI project. Every night at 22:00 the advisor recommends how much the
electric chillers (ECs) at UTP's Gas District Cooling plant should charge the chilled-water
storage tank (TES) for tomorrow. The MVP is a localhost FastAPI service plus a one-page
dashboard that ports page 1 of `Smart_Cooling_Advisor_plant_dashboard_sketch.pdf`. It exists to
support the written report: a working, honest demo beats polish.

**Every energy and plant number is SIMULATED** (synthetic campus load driven by real 2024
Seri Iskandar weather, plant model with assumed parameters). Nothing connects to UTP.

## 2. Goals, non-goals, anti-goals

Goals
- `POST /recommend` and `GET /health` exactly as specified in `docs/PROMPT_mvp.md`.
- Dashboard matching the sketch (page 1), driven only by API values.
- Reuses `scs/step1_model.py`, `scs/step2_simulate.py` and `scs/step5_plant.py` science unchanged.
- All tests in the brief pass; three Playwright screenshots; README.

Non-goals (MVP): phone alert (sketch page 2), login, database, cloud, live weather, the full
accessibility/state work in `docs/PROMPT_ui.md` (a later session), exposing the
`published_utp_data` preset in the UI.

Anti-goals (a failure even if it "works")
- Any in-sample forecast shown to the user, or any Oct–Dec data used in training.
- Any number in the UI that does not come from the API.
- Anything that could be read as MEASURED UTP data; missing SIMULATED labels.
- Mutating module globals (the step6 aliasing bug class).

## 3. Constraints

- Python 3.11+, FastAPI, uvicorn, pandas, numpy, scikit-learn; plain HTML/JS/SVG, no build step.
- Startup < 60 s on a laptop (first run builds the load cache; later runs read it).
- Project has its own git repo at `smart-cooling-advisor/` (the user's home folder is also a git
  repo — never commit there). Use a project `.venv` (system `python` lacks pandas).
- Subagent model assignment and process per the brief (Haiku / Sonnet / Opus-high rules).

## 4. Approaches considered

1. **Day bank at startup + pure dispatch per request (chosen).** Build/load the campus load
   once, train the daily forecasters once, precompute for each eligible 2024 day its 24-h
   profile, actual need, out-of-sample AI forecast and calendar-rule forecast. Each request only
   selects a day, applies multipliers/slider, and runs the pure dispatch 3 times (ms).
2. Retrain or re-simulate per request — seconds per slider move, no gain in honesty since the
   forecasts do not depend on the sliders. Rejected.
3. Precompute every response to JSON — impossible, margin/capacity/level are continuous.
   Rejected.

Scenario construction alternatives: nearest real 2024 day (chosen by the user) vs scaling a
typical profile (rejected: invents days the model never saw, breaks the step5 regression link).

## 5. Decisions taken with the user

| # | Decision | Choice |
|---|---|---|
| 1 | Day-type multipliers on the room-driven load (ASSUMPTION) | weekday 1.0, weekend 1.0 (uses real weekend days), **exam_week 0.9**, **semester_break 0.35** |
| 2 | Scenario construction | **Nearest real 2024 day** by calendar type and daily max temperature |
| 3 | AI forecast for exam week / semester break | **Honest:** the matched weekday's forecast **unscaled**. The calendar rule is also unscaled (a weekday/weekend rule does not know about breaks). Only "actual need" gets the multiplier. |
| 4 | Load cache format | **CSV** `data/campus_load_2024_<hash>.csv` |

Known consequence of decision 1: on a semester break the room load peaks ≈ 0.35 × 2,950 RT,
total ≈ 1,400 RT < 2,200 RT absorption chillers, so actual tank need ≈ 0 RTh. With decision 3 the
AI still forecasts a normal weekday need. This is intended: it is the "model has never seen a
break" limitation, shown honestly.

## 6. Design

### 6.1 Layout

```
app/
  config.py      PARAMS presets + DAY_TYPE_MULTIPLIERS + paths; preset chosen by env SCA_PARAMS_PRESET
  legacy/__init__.py   inserts scs/ on sys.path; re-exports step1_model, step2_simulate, step5_plant
  model.py       heat index/features (from step1), campus load build+cache, daily table, forecasters
  plant.py       pure dispatch_day(), dispatch_year() (regression), strategy comparison
  scenario.py    DayBank (startup), select_day(), build_scenario()
  schemas.py     Pydantic request/response
  main.py        FastAPI app, lifespan builds DayBank, /health, /recommend, static mount
static/ index.html app.js styles.css
tests/  pytest
data/   campus_load cache (generated, git-ignored)
docs/   plan.md, screenshots/
```

`scs/` stays untouched (single source of truth). The shim adds `scs/` to `sys.path` so step5's
`import step2_simulate as sim` works as written.

### 6.2 Parameters (`app/config.py`)

- `PRESETS["default"]` = a **copy** of `step5_plant.PLANT` values (so results reproduce step5).
- `PRESETS["published_utp_data"]` (label ASSUMPTION) = default with `standby_loss_per_h=0.0005`,
  `kw_per_rt_full=0.82`, `kw_per_rt_aux=0.24`, `sac_available_rt=1800`.
- `get_params()` returns a fresh dict for the preset named by `SCA_PARAMS_PRESET`
  (default `"default"`). Every function takes `params` explicitly; nothing mutates
  `step5_plant.PLANT`. Legacy functions are always called with `P=params` passed explicitly.
- `DAY_TYPE_MULTIPLIERS = {"weekday": 1.0, "weekend": 1.0, "exam_week": 0.9, "semester_break": 0.35}`,
  labelled ASSUMPTION.

### 6.3 Campus load and cache

- Hourly weather + features from step1 (`load_openmeteo`, `add_features`) on
  `scs/data/seri_iskandar_2024_openmeteo.csv`. `step5.campus_load(df, P)` needs the step1
  columns (`time, temp, rh, sw_rad, hour, month, weekday, cls, ...`); step2's `simulate(..,
  "S1_fixed_24C")` uses only weather + occupancy, not predictions.
- Store per hour: `time, total_rt, base_rt` where `base_rt = base_load_rt*(1+0.03*(temp-27))`
  (same formula as step5) and `room_rt = total_rt - base_rt` is the room-driven part.
- Cache file name includes a short hash of the load-shaping params (`base_load_rt,
  target_peak_rt, evening_factor, noise_daily, noise_hourly`). Missing → build (≈10–40 s) and write.

### 6.4 Daily table and forecasters (no leakage)

- Daily table = `step5.daily_table(df, total_rt, params)` (need_rth = Σ over hours 08–21 of
  max(load − sac_available_rt, 0)).
- Features = step5's `AI_plus_dayahead_weather` set, all known at 22:00 the day before:
  need/load/tmean/himax/rain of the previous day, need 7 days before, dow and weekday flag of
  tomorrow, month, and a **simulated** day-ahead forecast (true tmax + N(0,1) °C, sw ×N(1,.15),
  rain ×N(1,.5)) generated with `default_rng(0)` in step5's order so results match step5.
- Training (RandomForestRegressor 400 trees, min_samples_leaf 3, random_state 42):
  - Oct–Dec days: one model trained on all feature-complete Jan–Sep days (identical to step5).
  - Each Jan–Sep month m: a model trained on Jan–Sep **excluding m**. Oct–Dec never enters any
    training set. 10 models total, trained once at startup.
- Calendar rule: mean need per day-of-week over the same training months as that day's AI model
  (Jan–Sep for Oct–Dec days; Jan–Sep minus m for month m), matching step6's honest refit.
- Eligible scenario days: 8 Jan – 31 Dec 2024 (need the previous day's 22:00/23:00 hours and
  7-day lag features; step5 back-fills the first week with fake values).

### 6.5 Scenario selection (`scenario.py`)

- Calendar type: weekday / exam_week / semester_break → Mon–Fri days; weekend → Sat/Sun.
  (No public holidays in the 2024 data; same as step5.)
- Candidates in Oct–Dec; if the nearest one's `|tmax − forecast_max_temp_c| ≤ 1.0` use it,
  otherwise nearest over the whole eligible year. Ties → earliest date.
- 24-h profile: hours 22, 23 of D−1 then 00–21 of D; load and outdoor temp per hour.
- Multiplier m applies to the room part only: `load = base_rt + m * room_rt` for all 24 hours.
- `actual_need_rth` = Σ_{08..21} max(load − sac, 0) on the (scaled) profile; does not change
  with the error slider.
- `ai_forecast` = the day's out-of-sample forecast (unscaled, decision 3);
  `ai_forecast_used = ai_forecast × (1 + forecast_error_pct/100)`.
  *(Builder's call)* `recommendation.ai_forecast_need_rth` reports `ai_forecast_used` (what the
  operator would act on); an extra field `ai_forecast_model_rth` carries the raw model value.
  The "error 0, margin 0 → target == forecast" test compares against the raw model value.
- `scenario` in the response: `source_date, day_type, source_tmax_c, training_months` (list of
  ints) and `forecast_kind` ("trained Jan–Sep, tested Oct–Dec" or "leave-one-month-out").

### 6.6 Pure dispatch (`plant.py`)

`dispatch_day(load_rt[24], t_out[24], hours[24], tank_level_start, charge_target_rth, params)`
→ dict of 24-length arrays. Per hour, step5 physics in step5 order:

1. `level *= (1 − standby_loss_per_h)` (standby loss for this hour).
2. `sac = min(load, sac_available_rt)`; `rem = load − sac`.
3. Day hours (08–21): `tank_out = min(rem, tes_max_discharge_rt, level)`; `level −= tank_out`; `rem −= tank_out`.
4. Night hours (22–07): `tgt = min(capacity, charge_target)`;
   `needed = max(0, tgt − level)/charge_eff`; `spare = max(0, n_ec*ec_unit_rt − rem)`;
   `charge = min(needed / hours_left, spare)` with step5's `hours_left`; `level += charge*charge_eff`.
5. `ec_total = rem + charge`; `ec_kw, ec_count = step5.ec_power_kw(ec_total, t_out, params)`;
   `unmet = max(0, ec_total − n_ec*ec_unit_rt)`; `ec_load_rt = rem − unmet`.

Margin is NOT applied inside `dispatch_day`; callers pass the final target
(`min(capacity, forecast × (1+margin))`). `dispatch_year(df, load, target_by_date, params,
start_level=5000, use_margin=True)` loops the same per-hour step over the year (step5 semantics,
including the margin there) and exists for the regression test against
`scs/data/plant_results.csv` (Oct–Dec EC MWh within 0.5%, rows always_full, calendar_rule,
AI_plus_dayahead_weather, perfect).

### 6.7 Strategies and recommendation

- Targets: always_full = capacity; calendar_rule = min(cap, cal × (1+margin));
  ai_forecast = min(cap, ai_used × (1+margin)). All start from `tank_level_22_rth`.
- `capped = ai_used × (1+margin) > capacity`.
- `electric_chillers.count` = max ec_count over hours with charge_rt > 0; `start = "22:00"`;
  `end` = the hour after the last hour with charge_rt > 0 (e.g. "08:00"). No charging → count 0,
  start/end null-safe strings ("—").
- `daytime_ec_hours` = count of hours 08–21 with ec_load_rt > 0. `shortfall_rth = Σ unmet_rt`.
- `status`: "shortfall" if shortfall > 0, else "capped" if capped, else "ok". `message`: one
  plain-English line per status.
- Comparison row `ec_energy_kwh` = Σ ec_kw over the 24 h; `vs_always_full_pct` =
  100 × (e/e_full − 1) rounded to 1 dp, null for always_full (and null if e_full == 0).
- Response `label = "SIMULATED"`; `assumptions[]` lists: synthetic load, simulated day-ahead
  weather, day-type multipliers (ASSUMPTION), honest-AI choice for breaks, plant params source,
  one year of weather, training months.

### 6.8 API

As in the brief. `tank_level_22_rth > tank_capacity_rth` → 422 (model validator). `/health`
returns `model_trained: true` once the DayBank is built in the FastAPI lifespan.

### 6.9 Frontend

Port of sketch page 1 as listed in the brief (header + badges, inputs card, isometric SVG plant
with 4 ECs lighting by `ec_count`, tank fill = level/capacity, Play/Pause/Reset, scrubber, four
stat tiles, recommendation card with toast-only buttons, stacked "who supplies the cold" chart,
tank-level chart, comparison table with the honest footnote, assumptions list). 300 ms
debounce; every number from the API; "SIMULATED" in the page and every chart caption. The tank
level slider's max follows capacity.

### 6.10 Step1 classifier

Not used by the dashboard. `model.py` exposes a function that trains step1's classifier on
Jan–Sep and scores Oct–Dec (0.788 ± 0.005); it runs in tests only, not at startup.

## 7. Left to the builder

Exact CSS, SVG geometry, assumption wording, test fixture organisation, ruff config, how the
screenshots are scripted (Playwright Python, 1440×900, deviceScaleFactor 2).
