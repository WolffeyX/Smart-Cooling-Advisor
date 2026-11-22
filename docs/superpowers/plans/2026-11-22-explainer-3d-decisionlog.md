# Extension (guide, decision log, RF explainer, 3D view) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a real Approve/Adjust flow with a CSV decision log, a "How the AI decided" random-forest explainer, an interactive Three.js 3D plant view behind a 2D/3D toggle, and a user guide (artifact + PDF) to the Smart Cooling Advisor MVP.

**Architecture:** The backend stays the single source of numbers. `/recommend` gains a three-block load split, a room-equivalents count and an optional operator override. New `app/decisions.py` (CSV log) and `app/explain.py` (kept RF models, startup statistics, per-day explanation) back three new endpoint groups. The frontend stays plain JS with no build step: `app.js` broadcasts `sca:data` / `sca:hour` DOM events, and three new files consume them: `decisions.js`, `explain.js`, and `plant3d.js` (an ES module, Three.js via import map).

**Tech Stack:** Python 3.13 venv (`.venv/Scripts/python`), FastAPI, pydantic v2, pandas 3.1.1, numpy, scikit-learn 1.6.1 (`sklearn.inspection.permutation_importance`), pytest + Playwright Chromium, Three.js r170 vendored.

**Spec:** `docs/superpowers/specs/2026-11-22-explainer-3d-decisionlog-design.md` (read it with this plan).

## Global Constraints

- Work on branch `extend`. Every command uses `.venv/Scripts/python -m …` (the system Python lacks pandas).
- `scs/` is read-only. `app/plant.py` physics is unchanged. Params are passed explicitly, and module globals are never mutated.
- The API contract is additive only. All 89 existing tests keep passing, and `ruff check .` and `ruff format --check .` stay clean.
- Every energy/plant/forecast number shown in the UI comes from an API response. The browser never computes a plant number. The one existing exception (`charge_rt * 0.95` in the tile) stays as it is.
- Every new panel or caption carries the word SIMULATED. The step1 classifier accuracy is labelled MEASURED. The block mapping is labelled ASSUMPTION.
- No real UTP building names, floor areas or room counts. Room count = "≈ N room-equivalents (SIMULATED)".
- Startup (bank + explainer statistics) stays under 60 s. Measured before planning: bank ≈ 4.3 s; permutation importance ≈ 1.2 s per model with the model's `n_jobs=1`, versus 4.7 s with `n_jobs=-1`.
- No CDN at runtime: Three.js r170 (`three@0.170.0`) lives in `static/vendor/three/` with its LICENSE.
- The decision log is `data/decision_log.csv` and is git-ignored. Rows are written **only** on Approve or a confirmed Adjust.
- Subagent models:
  - Haiku: scaffolding and vendoring (Tasks 7a, 8).
  - Sonnet: features, tests and frontend.
  - Opus 5.5 at effort high: the Task 4 review (ML explainer), the final whole-branch review, and any bug Sonnet fails twice.

## Review Focus

1. **Override goes stale after inputs change.** The operator types 9,000 RTh and then drags capacity down to 6,000. Expected: any input change clears the override and closes the Adjust box, so the request stays valid (no 422 banner). Covered in Task 5.
2. **Approve is double-clicked.** Expected: the button is disabled while its POST is in flight, so one click makes one row. Covered in Task 5.
3. **Decision log file missing, or written with an older column set.** Expected: `GET /decisions` returns `[]` when the file is missing. A header mismatch renames the old file to `decision_log.<YYYYmmdd-HHMMSS>.old.csv` and starts a fresh one; existing data is never silently mixed or lost. Covered in Task 3.
4. **No WebGL.** Expected: the 3D button is disabled with a note, the 2D view keeps working, and there are no console errors. Covered in Task 7.
5. **`/explain` with a bad date.** An ineligible day (e.g. `2024-01-03`) or a date outside 2024 returns 404 with a reason. A malformed string (`2024-13-40`, `abc`) returns 422 and never a 500. Covered in Task 4.

---

### Task 1: Three-block load split and room equivalents

**Files:**
- Modify: `app/model.py` (`LOAD_COLUMNS`, `campus_load_frame`)
- Modify: `app/scenario.py` (`Scenario`, `build_scenario`)
- Modify: `app/recommend.py` (`_HOURLY_FIELDS`, plant block, `_assumptions`)
- Modify: `app/schemas.py` (`HourRow`, `Plant`)
- Test: `tests/test_blocks.py`

**Interfaces:**
- Produces:
  - `model.LOAD_COLUMNS = ["time", "total_rt", "base_rt", "room_rt", "room_scale"]`. `room_scale` repeats step5's `campus_load` second return value in every row. A cache file with the old 4 columns fails the column check and is rebuilt (existing self-heal).
  - `Scenario.academic_rt`, `.evening_rt` and `.base_rt` (`np.ndarray`, 24 values), and `Scenario.room_equivalents: int` (`round(room_scale)`).
  - `hourly[].academic_rt`, `hourly[].evening_rt` and `hourly[].base_rt` (float), `plant.room_equivalents` (int), and `plant.tank_capacity_rth` (float: the request's capacity, echoed so the 3D view needs no browser-side numbers).

- [ ] **Step 1: Write failing tests** in `tests/test_blocks.py`:
  - `test_blocks_sum_to_campus_load(bank, P)`: for each of the 4 day types at 31 °C, `build_response(bank, req, P, round_values=False)`, every hour satisfies `abs(academic+evening+base − campus_load_rt) < 1e-6`.
  - `test_academic_only_08_17_and_evening_only_18_21(bank, P)`: hourly index 0–9 (22:00–07:00) has `academic_rt == evening_rt == 0`. Indices 10–19 (08–17) have `evening_rt == 0`. Indices 20–23 (18–21) have `academic_rt == 0`.
  - `test_weekend_has_no_academic_load(bank, P)`: weekend request gives `academic_rt == 0` in all hours.
  - `test_semester_break_scales_blocks(bank, P)`: same source day, so the semester_break academic sum ≈ 0.35 × the weekday academic sum (rel 1e-6), and base is identical. Use `select_day` to confirm both pick the same date at the chosen temperature; if they don't, pick a temperature where they do.
  - `test_plant_echoes_capacity(bank, P)`: capacity 12000 gives `plant.tank_capacity_rth == 12000`.
  - `test_room_equivalents(bank, P)`: `plant.room_equivalents` is an int, `1000 <= n <= 1500`, and equals `round(step5_plant.campus_load(w, P)[1])`.
  - `test_old_four_column_cache_is_rebuilt(tmp_path)`: write a 4-column CSV at the cache path; `campus_load_frame` returns the 5 columns and rewrites the file.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_blocks.py -v`. Expected: FAIL (KeyError `academic_rt` / `room_scale`).
- [ ] **Step 3: Implement.**
  - In `build_scenario`, with `room = m * load["room_rt"]` and `h = idx.hour`:
    - `academic = where(8 <= h <= 17, room, 0)`
    - `evening = where(18 <= h <= 21, room, 0)`
    - `base = load_rt − academic − evening` (derived, so the invariant holds exactly, even if `room_rt` is non-zero at night).
  - Add the three keys to `_HOURLY_FIELDS` and the matching `HourRow` fields, and add `room_equivalents` to the plant dict and the `Plant` schema.
  - Append this to `_assumptions`: `"ASSUMPTION: the three campus blocks split the synthetic load by hour — Academic = room load 08:00–17:59, Library & evening classes = room load 18:00–21:59, Data centre & labs = the 24/7 base load. About {n:,} reference 60 m² room-equivalents (SIMULATED); not real UTP buildings."`
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -m "not e2e" -q`. Expected: all pass, including `test_campus_load.py`.
- [ ] **Step 5: Commit** `feat: three-block load split and room equivalents in /recommend`.

### Task 2: Operator override and `operator_plan`

**Files:**
- Modify: `app/schemas.py` (`RecommendRequest`, new `OperatorPlan`, `RecommendResponse`)
- Modify: `app/recommend.py` (`build_response`)
- Test: `tests/test_operator_plan.py`

**Interfaces:**
- Consumes: `dispatch_day`, `summarise_day`, `_message`, `_over_charged` (existing).
- Produces:
  - `RecommendRequest.charge_target_override_rth: float | None = Field(default=None, ge=0)`, with a validator requiring it to be ≤ `tank_capacity_rth`.
  - `OperatorPlan`: `charge_target_rth, ec_energy_kwh: float; vs_always_full_pct: float | None; daytime_ec_hours: int; shortfall_rth, tank_level_21_rth: float; status: Literal["ok","shortfall"]; over_charged: bool; message: str`.
  - `RecommendResponse.operator_plan: OperatorPlan | None = None`. It is `null` without an override.

- [ ] **Step 1: Write failing tests** (use `client` for API and `bank`/`P` for direct calls; BODY = weekday, 31 °C, defaults):
  - `test_no_override_unchanged`: the response with no override has `operator_plan is None`. Sending `"charge_target_override_rth": null` gives a byte-identical response. `hourly` follows the AI run, so `hourly[-1].tank_level_rth` == the `ai_forecast` comparison row's `tank_level_21_rth`.
  - `test_override_adds_operator_plan_and_hourly_follows_it`: with override 9000, `operator_plan.charge_target_rth == 9000`. `recommendation` and `comparison` are identical to the no-override response. `hourly[-1].tank_level_rth == operator_plan.tank_level_21_rth`. `operator_plan.ec_energy_kwh` equals `summarise_day(dispatch_day(..., 9000, p))["ec_energy_kwh"]` (rounded to 1 dp).
  - `test_override_equal_to_ai_target_matches_ai_row`: override = AI target gives operator `ec_energy_kwh` == the `ai_forecast` comparison row.
  - `test_override_zero_on_hot_day_reports_daytime_ec`: weekday at 34 °C with override 0 gives `daytime_ec_hours > 0`, and the message mentions electric chillers.
  - `test_override_over_capacity_422` (capacity 8000, override 8001 → 422), and `test_override_negative_422`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_operator_plan.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** When the override is set, run a 4th `dispatch_day` with it, build `hourly` from that run instead of the AI run, and build `operator_plan`:
  - `status`: "shortfall" if the shortfall is > 1e-6, else "ok".
  - `message`: `_message(status, cap, shortfall, False, hours, target, reached, actual, left_21)`.
  - `vs_always_full_pct`: computed against `e_full`.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -m "not e2e" -q`. Expected: all pass.
- [ ] **Step 5: Commit** `feat: operator charge-target override with operator_plan`.

### Task 3: Decision log backend

**Files:**
- Create: `app/decisions.py`
- Modify: `app/schemas.py` (`DecisionRequest`), `app/main.py` (state and three routes), `.gitignore` (`data/decision_log*.csv`)
- Test: `tests/test_decisions.py`

**Interfaces:**
- Consumes: `build_response`, `RecommendRequest`.
- Produces:
  - `decisions.COLUMNS: list[str]`, exactly the spec §6.3 order: `timestamp, action, day_type, forecast_max_temp_c, safety_margin_pct, tank_capacity_rth, tank_level_22_rth, forecast_error_pct, source_date, source_tmax_c, ai_forecast_model_rth, ai_forecast_need_rth, actual_need_rth, ai_target_rth, operator_target_rth, chosen_status, chosen_shortfall_rth, chosen_daytime_ec_hours, chosen_ec_kwh, ec_kwh_always_full, ec_kwh_calendar_rule, ec_kwh_ai_forecast, label`.
  - `decisions.decision_row(action: str, req: dict, resp: dict, now: datetime) -> dict`. For "approved", the `chosen_*` fields come from the AI recommendation and the `ai_forecast` comparison row. For "adjusted", they come from `operator_plan`. Floats are rounded to 1 dp; `timestamp` is `now.isoformat(timespec="seconds")`; `label` is "SIMULATED".
  - `class DecisionLog(path: Path)` with `append(row: dict) -> dict` and `rows() -> list[dict]` (newest first; `[]` if the file is missing). Appends are guarded by a `threading.Lock`; the header is written when the file is new. A header mismatch triggers the rename in Review Focus 3.
  - `DecisionRequest(RecommendRequest)` adds `action: Literal["approved","adjusted"]`. Its validator requires the override when adjusted and forbids it when approved (422).
  - Routes:
    - `POST /decisions` → `{"row": {...}}`. The server calls `build_response` itself.
    - `GET /decisions` → `{"rows": [...], "label": "SIMULATED"}`.
    - `GET /decisions.csv` → a `FileResponse` with `text/csv` and filename `decision_log.csv`, or a header-only CSV if the file is missing.
  - `app.state.decision_log` is created in the lifespan from env `SCA_DECISION_LOG`, defaulting to `DATA_DIR / "decision_log.csv"`. These routes must be declared before the static mount.

- [ ] **Step 1: Write failing tests.** Use a function-scoped fixture that swaps `client.app.state.decision_log` for `DecisionLog(tmp_path / "log.csv")` and restores it afterwards.
  - `test_approve_appends_one_row_with_server_numbers`: POST approved. The file has the header plus 1 row; `operator_target_rth == ai_target_rth == /recommend recommendation.charge_target_rth`; `ec_kwh_ai_forecast` matches the comparison row.
  - `test_adjust_logs_operator_outcome`: adjusted with 9000 gives `operator_target_rth == 9000` and `chosen_ec_kwh == operator_plan.ec_energy_kwh`.
  - `test_client_numbers_ignored`: extra fields in the body (e.g. `"chosen_ec_kwh": 1`) are ignored or rejected and never logged.
  - `test_adjust_without_override_422` and `test_approve_with_override_422`.
  - `test_get_decisions_newest_first` (two posts, so `rows[0].action` is the second one) and `test_get_decisions_missing_file_empty`.
  - `test_csv_download_header` (`text/csv`, and the first line equals `",".join(COLUMNS)`).
  - `test_header_mismatch_rotates_old_file`: write a file with a different header, then append. The old content sits in a `*.old.csv` sibling, and the new file has the correct header plus 1 row.
  - `test_concurrent_appends`: 20 threads appending give exactly 21 lines and every row parses.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_decisions.py -v`. Expected: FAIL (no module `app.decisions`).
- [ ] **Step 3: Implement** `app/decisions.py`, the schema, the routes and the `.gitignore` line. Use the `csv` module with `newline=""`.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -m "not e2e" -q`. Expected: all pass. `git status` shows no `data/decision_log.csv`.
- [ ] **Step 5: Commit** `feat: decision log (CSV) with approve/adjust endpoints`.

### Task 4: RF explainer backend (Opus review)

**Files:**
- Modify: `app/model.py` (`DailyForecasts` gains `models` and `model_key_by_day`; `train_forecasters` keeps the fitted models)
- Create: `app/explain.py`
- Modify: `app/scenario.py` (`DayBank` gains `features: pd.DataFrame` and `explain_stats: dict`; `build_day_bank` computes them)
- Modify: `app/main.py` (`GET /explain`)
- Test: `tests/test_explain.py`

**Interfaces:**
- Produces:
  - `DailyForecasts.models: dict[str, RandomForestRegressor]` with keys `"oct_dec"` and `"m1"`…`"m9"`. Also `DailyForecasts.model_key_by_day: dict[pd.Timestamp, str]` and `DailyForecasts.calendar_by_model: dict[str, pd.Series]` (dow → mean need from the training months, for the held-out rule MAE). Existing fields and predictions are unchanged.
  - `explain.FEATURE_INFO: dict[str, tuple[str, str]]` maps each feature to (plain label, unit). Use these exact values:
    - `need_today` ("Today's tank need", "RTh")
    - `load_today` ("Today's total campus load", "RT·h")
    - `tmean_today` ("Today's mean temperature", "°C")
    - `himax_today` ("Today's max heat index", "°C")
    - `rain_today` ("Today's rain", "mm")
    - `need_lastweek` ("Tank need 7 days ago", "RTh")
    - `dow_tomorrow` ("Day of week tomorrow (0 = Mon)", "")
    - `weekday_tomorrow` ("Tomorrow is a weekday (1/0)", "")
    - `month` ("Month", "")
    - `fc_tmax` ("Forecast max temperature tomorrow", "°C")
    - `fc_sw` ("Forecast solar radiation tomorrow", "W/m²·h")
    - `fc_rain` ("Forecast rain tomorrow", "mm")
  - `explain.N_REPEATS = 5`.
  - `explain.compute_explain_stats(daily, X, forecasts, weather) -> dict`. It returns `{"models": {key: {"held_out_months", "n_training_days", "held_out_mae_ai_rth", "held_out_mae_rule_rth", "permutation": {feat: (mean, std)}, "impurity": {feat: float}}}, "classifier": train_classifier(weather), "n_repeats": N_REPEATS}`.
    - Permutation importance runs on held-out rows with `scoring="neg_mean_absolute_error"`, `n_repeats=N_REPEATS` and `random_state=0`. Set the model's `n_jobs=1` for the call, then restore it.
    - Report the importance as an MAE increase in RTh (a positive number means shuffling hurts).
  - `explain.explain_day(bank: DayBank, source_date: str) -> dict`. This is the spec §6.4 shape exactly:
    - `trees.histogram` = `{"edges": [21 floats], "counts": [20 ints]}`.
    - `path.splits[]` = `{feature, label, threshold, value, direction: "≤"|">", samples, node_mean_rth}`, plus `path.tree_index` (0), `path.tree_prediction_rth`, `path.depth` and `path.hidden_splits`.
    - `classifier` = `{accuracy, train_months, test_months, label: "MEASURED"}`.
    - Per-tree predictions use `tree.predict(x.to_numpy())`, which avoids feature-name warnings.
    - It raises `KeyError` for a day that is not eligible.
  - `GET /explain?source_date=` takes a string with `pattern=r"^\d{4}-\d{2}-\d{2}$"`. An unparseable date gives 422, and a non-eligible date gives 404 with the detail `"no forecast for that day (eligible: 2024-01-08 to 2024-12-31)"`.

- [ ] **Step 1: Write failing tests** in `tests/test_explain.py` (bank fixture):
  - `test_models_kept_and_predictions_unchanged`: there are 10 models. For each eligible day D, `models[model_key_by_day[D]].predict(features.loc[[D]])` equals `forecasts.ai[D]`. Oct–Dec days map to `"oct_dec"`, and a March day maps to `"m3"`.
  - `test_tree_mean_equals_ai_forecast`: for 2024-10-23 and 2024-03-12, `abs(trees.mean − forecasts.ai[D]) < 1e-6`, and `min <= p10 <= median <= p90 <= max`. The histogram counts sum to 400.
  - `test_path_is_real`: the splits number ≤ 5; for each split, `direction == "≤"` iff `value <= threshold`. `depth == len(splits) + hidden_splits`. `tree_prediction_rth` equals `models[k].estimators_[0].predict(x)`. Samples are non-increasing down the path.
  - `test_importance_shapes`: all 12 features appear. Impurity sums to 1 (±1e-6), and the permutation std is ≥ 0.
  - `test_never_trained_on_held_out`: for `"oct_dec"`, `held_out_months == [10, 11, 12]` and `training_months == [1..9]`. For `"m3"`, 3 is not in training_months. `n_training_days` equals the count of feature-complete days in the training months.
  - `test_held_out_mae_matches_forecasts`: the oct_dec `held_out_mae_ai_rth` equals the mean of |ai − need| over eligible Oct–Dec days (rel 1e-9). The rule MAE is computed the same way from `forecasts.calendar`.
  - `test_classifier_measured`: accuracy is within 0.005 of 0.788, with label "MEASURED".
  - API tests (`client`):
    - 200 for `2024-10-23`, with label "SIMULATED" and the `features[].provenance` values from `FEATURE_PROVENANCE`.
    - 404 for `2024-01-03` and for `2023-06-01`.
    - 422 for `2024-13-40` and `abc` (Review Focus 5).
  - `test_startup_budget` (marked `slow`): `build_day_bank` on a fresh cache dir finishes in < 60 s. Record the measured time in the task report.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_explain.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep `fit_predict`'s logic and store the model under the key. `build_day_bank` keeps `X` as `features` and calls `compute_explain_stats`. A 2023 date must never raise anything other than `KeyError`, which becomes the 404.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q -m "not e2e"`. Expected: all pass, and `test_forecasters.py` is unchanged and green.
- [ ] **Step 5: Commit** `feat: RF explainer endpoint (importances, tree spread, decision path)`.
- [ ] **Step 6: Opus 5.5 (effort high) review.** The review checks:
  - leakage (no permutation or MAE on training months);
  - that the path walk matches sklearn's `decision_path`;
  - that the importance sign and units are right;
  - that nothing in the explainer contradicts `/recommend`.

### Task 5: Frontend — Approve / Adjust and decision log card

**Files:**
- Modify: `static/index.html` (action buttons, Adjust box, log card under the comparison table, `<script src="decisions.js">`)
- Modify: `static/app.js` (override state, real buttons, `sca:data` / `sca:hour` events)
- Create: `static/decisions.js`
- Modify: `static/styles.css`
- Test: `tests/test_frontend_e2e.py` (append). The `server` fixture sets env `SCA_DECISION_LOG` to a temp file.

**Interfaces:**
- Produces, for Tasks 6 and 7:
  - `app.js` dispatches `document.dispatchEvent(new CustomEvent("sca:data", {detail: data}))` after each render.
  - It also dispatches `new CustomEvent("sca:hour", {detail: {idx, row: data.hourly[idx], data}})` on every `renderTime()`.
  - `window.SCA = { getData: () => data, setHour(i) }`.
- `decisions.js` exposes `window.SCADecisions.refresh()`.
- Element ids:
  - `#approve`, `#adjust` and `#adjust-box` (containing `#override-input` type=number, `#override-preview`, `#override-confirm` and `#override-cancel`).
  - `#operator-note` (shown when an override is active: "Operator plan: X RTh · AI recommended Y RTh", all from the API).
  - `#decision-log` (table, newest 20 rows), `#decision-csv` (link to `/decisions.csv`).

- [ ] **Step 1: Write failing e2e tests:**
  - `test_approve_logs_one_row`: click `#approve`. Exactly one `/decisions` POST is sent; the button is disabled until it resolves (Review Focus 2: a double click still gives 1 row); and `#decision-log tbody tr` count goes up by 1, showing "approved".
  - `test_adjust_preview_then_confirm`: open Adjust and type 9000, then Preview. The `/recommend` body contains `charge_target_override_rth: 9000`; `#operator-note` shows "9,000"; and the hero still shows the AI target from `recommendation`. Confirm adds an "adjusted" row with operator target 9,000.
  - `test_input_change_clears_override`: set the override to 9000 and Preview, then set capacity to 6000. The next `/recommend` body has no override key, `#adjust-box` is hidden, and `#api-error` stays hidden (Review Focus 1).
  - `test_slider_drag_logs_nothing`: moving 3 sliders makes 0 POSTs to `/decisions`.
  - `test_csv_link`: `#decision-csv` has the href `/decisions.csv`.
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_frontend_e2e.py -v -k "approve or adjust or override or logs_nothing or csv_link"`. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Remove `data-toast` from the two action buttons. The demo toast stays only on buttons that are still demo-only.
  - Any change to an input (`schedule()` path) clears `override` and hides the Adjust box.
  - The `#override-input` attributes are min 0, max = the current capacity, and the default value is the AI target.
  - After a POST, call `SCADecisions.refresh()` and toast "Logged · SIMULATED".
- [ ] **Step 4: Run** the full e2e file. Expected: all pass, including the existing e2e tests.
- [ ] **Step 5: Commit** `feat(ui): approve/adjust flow and decision log card`.

### Task 6: Frontend — "How the AI decided" card

**Files:**
- Modify: `static/index.html` (collapsible `<details id="explain">` card after the charts, `<script src="explain.js">`)
- Create: `static/explain.js`
- Modify: `static/styles.css`
- Test: `tests/test_frontend_e2e.py` (append)

**Interfaces:**
- Consumes: `sca:data` (from Task 5) and `GET /explain` (from Task 4).
- Element ids:
  - `#explain-features` (table)
  - `#explain-perm` and `#explain-impurity` (SVG bar charts)
  - `#explain-hist` (SVG histogram with the mean marked)
  - `#explain-path` (an `<ol>` of up to 5 boxes plus a "… N more splits not shown" line)
  - `#explain-training` (paragraph)
- Behaviour:
  - It fetches only when `scenario.source_date` changes, caches per date, and drops stale responses (the same seq pattern as `fetchRecommendation`).
  - The card states that the explanation is of the model forecast before the what-if error slider.

- [ ] **Step 1: Write failing e2e tests:**
  - `test_explainer_matches_api`:
    - After load, the `/explain` response's `trees.mean` (formatted) appears in `#explain-hist`, and `recommendation.ai_forecast_model_rth` equals it (±0.5).
    - `#explain-path li` count == `len(path.splits)`.
    - 12 rows appear in `#explain-features`.
    - `#explain-training` text contains every training month and "400".
  - `test_explainer_refetches_only_on_date_change`: changing the margin slider makes 0 `/explain` requests; changing temperature to a value with a new source date makes 1.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the card. Bars are labelled with their values in RTh (permutation) or as shares (impurity). Add a one-line note: "Built-in (impurity) importance favours features with many split points; permutation importance measures how much held-out error rises when a feature is shuffled."
- [ ] **Step 4: Run** the full e2e file. Expected: all pass.
- [ ] **Step 5: Commit** `feat(ui): random-forest explainer card`.

### Task 7: 3D plant view

**Files:**
- Create (7a, Haiku): `static/vendor/three/three.module.js`, `static/vendor/three/addons/controls/OrbitControls.js` and `static/vendor/three/LICENSE`, all from `three@0.170.0` (`build/three.module.js`, `examples/jsm/controls/OrbitControls.js`, `LICENSE`) on the npm registry via cdn.jsdelivr.net. Record the sizes and SHA-256 of each file in `static/vendor/three/VERSION.txt`.
- Modify: `static/index.html`. Add the import map `{"imports": {"three": "./vendor/three/three.module.js", "three/addons/": "./vendor/three/addons/"}}`, the `2D | 3D` toggle `#view-2d` / `#view-3d` in the plant card header, `<div id="plant-3d" hidden>` with `#reset-view` and `#plant-tooltip`, and `<script type="module" src="plant3d.js">`.
- Create: `static/plant3d.js`
- Modify: `static/styles.css`; change the plant heading text from "3D plant view" to "Plant view" in `index.html` and `app.js`.
- Test: `tests/test_frontend_e2e.py` (append). Browser launch args become `["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]` so headless Chromium has WebGL.

**Interfaces:**
- Consumes: `sca:hour` and `sca:data` (Task 5), and `hourly[].academic_rt/evening_rt/base_rt` and `plant.room_equivalents` (Task 1).
- Produces a test hook, `window.__plant3d = {ready: bool, idx: int, flows: {sac_campus, ec_tank, ec_campus, tank_campus, return}, waterFraction: number, labels: {academic, evening, base}}`, updated on each `sca:hour`. Each flow value is the API RT that drives that segment (0 means no particles), and `waterFraction = tank_level_rth / plant.tank_capacity_rth`, both values from the API response.
- Segment drivers:
  - sac_campus = `sac_rt`
  - ec_tank = `charge_rt`
  - ec_campus = `ec_load_rt`
  - tank_campus = `tank_out_rt`
  - return = `campus_load_rt`
- Block labels show `academic_rt`, `evening_rt` and `base_rt` plus "≈ N room-equivalents (SIMULATED)".

- [ ] **Step 1 (7a, Haiku): Vendor Three.js.** Verify it with `client.get("/vendor/three/three.module.js")`: the status is 200, the content-type contains `javascript`, and the body contains `REVISION = '170'`. Add that check as `test_three_vendored` in `tests/test_api.py`. Commit `chore: vendor three.js r170 (MIT)`.
- [ ] **Step 2: Write failing e2e tests:**
  - `test_3d_toggle_and_sync`: 2D is the default (`#plant-svg` visible, `#plant-3d` hidden). Click `#view-3d`, wait for `__plant3d.ready`, then set the scrubber to index 4 (02:00). `__plant3d.idx == 4`, `flows.ec_tank == hourly[4].charge_rt > 0`, `flows.tank_campus == 0`, and `waterFraction ≈ hourly[4].tank_level_rth / 10000` (±1e-6). At index 15 (13:00): `flows.tank_campus == hourly[15].tank_out_rt`, and `flows.ec_tank == 0`.
  - `test_3d_labels_from_api`: the label values equal the hourly block values of the selected hour.
  - `test_3d_orbit_and_reset`: dragging on the canvas changes the camera position (read via the hook's `camera` array), and `#reset-view` restores it (±1e-6).
  - `test_no_webgl_fallback` (Review Focus 4): an `add_init_script` makes `getContext('webgl'|'webgl2')` return null. `#view-3d` is disabled with a visible note, 2D renders, and `page.on("pageerror")` collects nothing.
- [ ] **Step 3: Run** them. Expected: FAIL.
- [ ] **Step 4: Implement `plant3d.js`.**
  - Build the scene, pipes, particles, tooltips (raycaster on hover) and controls per spec §6.5, in low-poly style.
  - Particles move along a `CatmullRomCurve3`, at a speed ∝ RT / max(hourly campus_load_rt). On the tank line they move tank→campus when discharging and EC→tank when charging.
  - The render loop runs only while `#plant-3d` is visible (`requestAnimationFrame` stops when hidden).
  - Detect WebGL with a probe canvas before importing the scene code.
- [ ] **Step 5: Run** the full e2e file plus `-m "not e2e"`. Expected: all pass.
- [ ] **Step 6: Commit** `feat(ui): interactive Three.js plant view with live flows`.

### Task 8: Screenshots (Haiku)

**Files:**
- Modify: `scripts/screenshots.py`
- Create: `docs/screenshots/3d_night.png`, `3d_day.png`, `rf_panel.png`, `decision_log.png`

**Interfaces:**
- Consumes: the element ids from Tasks 5–7 and `window.SCA.setHour`.

- [ ] **Step 1: Extend the script.**
  - Use the same launch args as the e2e tests and set `SCA_DECISION_LOG` to a temp file.
  - For `3d_night`: weekday at 31 °C, toggle 3D, `SCA.setHour(4)`, set the camera via `window.__plant3d.setCamera([x,y,z])`, wait 800 ms, and take an element screenshot of the plant card.
  - For `3d_day`: `setHour(15)` and a different camera position.
  - For `rf_panel`: open `#explain` and take an element screenshot.
  - For `decision_log`: one Approve, then one Adjust at 9000 + Confirm, then an element screenshot of the log card.
  - Keep the existing three screenshots.
  - `setCamera` is added to the hook in this task if Task 7 did not add it.
- [ ] **Step 2: Run** `.venv/Scripts/python scripts/screenshots.py`. Expected: 7 PNGs, each > 50 KB. The controller opens and looks at all four new ones: night shows charging particles and a rising tank, day shows discharge, and the camera angles differ.
- [ ] **Step 3: Commit** `docs: screenshots of 3D view, RF explainer and decision log`.

### Task 9: User guide (HTML → artifact + PDF) and README

**Files:**
- Create: `docs/guide/user_guide.html`, `docs/guide/img/*.png` (copies of the screenshots it uses), `scripts/build_guide_pdf.py`, `docs/user_guide.pdf`
- Modify: `README.md` (new features, the decision log location, and a link to the guide)
- Test: `tests/test_readme.py` (append `test_guide_pdf_exists_and_short`)

**Interfaces:**
- `scripts/build_guide_pdf.py` takes no arguments. It prints `docs/guide/user_guide.html` with Chromium `page.pdf(format="A4", print_background=True, prefer_css_page_size=True)` to `docs/user_guide.pdf` and prints the page count.
- HTML contract, so the same file works as a Claude artifact:
  - `<title>` of 2–4 words ("Smart Cooling Advisor Guide").
  - Colour tokens on `:root`, redefined for dark mode under `@media (prefers-color-scheme: dark)` with `:root:not([data-theme="light"])` and under `:root[data-theme="dark"]`. The print uses light.
  - An explicit `body` background, no external scripts, images as relative `img/…` paths, and readable at 375 px width.
  - `@page { size: A4; margin: 14mm }` and break rules so no heading is orphaned.

- [ ] **Step 1: Write the failing test.** `docs/user_guide.pdf` exists and is > 100 KB. Its page count, `len(re.findall(rb"/Type\s*/Page\b(?!s)", pdf_bytes))`, is between 4 and 8; the build script prints the same number. `docs/guide/user_guide.html` contains "SIMULATED", "Approve", "Adjust", "random forest", "3D" and "decision log" (case-insensitive), and every `img/…` it references exists. `pypdf` is not installed; do not add a dependency.
- [ ] **Step 2: Write the guide.** The sections are those in spec §6.6. Every number quoted must come from the API or from the findings already verified in the MVP. The guide contains no invented UTP facts.
- [ ] **Step 3: Run** `.venv/Scripts/python scripts/build_guide_pdf.py`, then the test. Expected: PASS, with a page count of ≤ 8 printed. The controller views every page image for layout (no orphan headings, no blank pages).
- [ ] **Step 4: Commit** `docs: user guide (HTML + PDF) and README update`.
- [ ] **Step 5 (controller):** load the `artifact-design` skill, publish `docs/guide/user_guide.html` with the Artifact tool (the images go via `files`), and record the link in the final report.

### Task 10: Final verification and whole-branch review (Opus)

- [ ] **Step 1: Run** `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python -m ruff check .` and `.venv/Scripts/python -m ruff format --check .`. Expected: all pass (89 + new), "All checks passed!", already formatted.
- [ ] **Step 2: Run** uvicorn and record the startup time. Then check:
  - `/health` returns ok.
  - `/explain?source_date=2024-10-23` returns 200.
  - POST `/decisions` approved returns a row, and `/decisions.csv` downloads.
  - The log file is not tracked by git.
- [ ] **Step 3: Opus 5.5 (effort high) whole-branch review** of `mvp..extend` against the spec and this plan. Fix every Critical and Important finding, with a Sonnet implementer plus a re-review, then re-run Step 1.
- [ ] **Step 4:** Report the real output pasted, the artifact link, the PDF path, the 4 new screenshots, the startup time, and the `n_repeats` value used.
