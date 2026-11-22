# Smart Cooling Advisor — extension: user guide, decision log, RF explainer, 3D view

Date: 2026-11-22 · Builds on the MVP (branch `mvp`, spec `2026-11-22-smart-cooling-advisor-mvp-design.md`).
Work happens on a new branch `extend` cut from `mvp`.

## 1. Intent

A lecturer marking this TEB2023 assignment should be able to (1) understand what the system
represents and how to use it from a short guide, (2) see how the random-forest forecaster
works and which parameters drive each recommendation, (3) see that the operator, not the AI,
makes the decision — and have those decisions recorded — and (4) explore an interactive 3D
model of the plant, piping and campus. Explanation and honesty beat visual polish. Every
energy/plant number stays SIMULATED.

## 2. Goals, non-goals, anti-goals

Goals: D1 user guide (artifact + PDF) · D2 decision log (CSV) with a real "Adjust manually"
· D3 "How the AI decided" panel · D4 3D plant view behind a 2D/3D toggle.

Non-goals: phone alert, database, login, cloud, changing `scs/` science or `app/plant.py`
physics, real UTP building data, replacing the 2D view (it stays the default).

Anti-goals (a failure even if it works):
- Presenting impurity importances as "what matters" (they under-rate the simulated weather
  features that carry ~30 % of the skill) without the honest permutation numbers beside them.
- Any number in the 3D view, explainer or log that the browser computed or invented instead of
  receiving from the API.
- Invented building facts (floor areas, real UTP building names, room counts not from the model).
- A decision log full of slider-drag noise.
- Startup over 60 s, or any of the existing 89 tests failing.

## 3. Constraints

Python/FastAPI/plain JS as in the MVP; no build step; works offline (Three.js vendored, pinned);
`scs/` read-only; params passed explicitly, no module-global mutation; every new caption/panel
says SIMULATED; subagent model rules from the MVP brief (Haiku/Sonnet/Opus-high).

## 4. Approaches considered

- 3D: **Three.js vendored in `static/vendor/three/` (chosen)** vs hand-drawn SVG with fake
  rotation (cannot orbit freely) vs CSS 3D transforms (cannot draw curved pipes / flow).
- Explainer compute: **models kept in memory; permutation importance + held-out MAE
  precomputed once at startup; tree spread + decision path per request (chosen)** vs
  everything per request (too slow for slider use) vs precompute every day (wasted startup).
- Guide: **one HTML page → published artifact + Chromium print to PDF (chosen)** vs a PDF
  library (new dependency, no artifact).

## 5. Decisions taken with the user

| # | Decision | Choice |
|---|---|---|
| 1 | Decision log storage | CSV file `data/decision_log.csv` (git-ignored) |
| 2 | Log rows | **Only** on "Approve plan" or a confirmed "Adjust manually" — no slider noise |
| 3 | "Adjust manually" | *(builder's pick, user deferred)* operator types own charge target → same 24-h simulation re-runs with it → "Confirm" logs AI target vs operator target and both outcomes |
| 4 | RF explainer | Both: feature importances + spread of the 400 trees, **and** one tree's decision path showing its **first 5 splits** |
| 5 | Building representation | 3 small blocks: Academic, Library & evening classes, Data centre & labs |
| 6 | 3D placement | **Toggle** beside the existing 2D view; 2D stays default |

## 6. Design

### 6.1 Load split for the three blocks (no invented data)
The synthetic load already has two parts: `base_rt` (24/7: step5 comments it as data centre,
labs, library) and `room_rt` (classrooms; 08:00–17:59 weekday occupancy plus an 18:00–21:59
evening tail at `evening_factor` 0.3 — step5 comments it as library/evening classes). The
scenario's per-hour multiplier already applies to `room_rt` only. Map:
- `academic_rt` = room part at hours 08–17, else 0
- `evening_rt` = room part at hours 18–21, else 0
- `base_rt` = base part (all hours)
Invariant (tested): `academic_rt + evening_rt + base_rt == campus_load_rt` every hour.
The mapping is labelled ASSUMPTION in `assumptions[]`.
Room count: `step5_plant.campus_load` already returns the scale factor (number of reference
60 m² rooms). Persist it with the load cache and expose it as
`plant.room_equivalents` (int). The UI says "≈ N room-equivalents (SIMULATED)" — never a real
UTP room count.

### 6.2 API changes (additive only; existing contract unchanged)
- `POST /recommend` request: new optional `charge_target_override_rth` (0 ≤ x ≤
  tank_capacity_rth; 422 otherwise). Response additions:
  - `hourly[].academic_rt`, `hourly[].evening_rt`, `hourly[].base_rt`
  - `plant.room_equivalents`
  - when the override is present: `operator_plan` = {`charge_target_rth`, `ec_energy_kwh`,
    `vs_always_full_pct`, `daytime_ec_hours`, `shortfall_rth`, `tank_level_21_rth`, `status`,
    `message`} from a 4th `dispatch_day` run with that target, and `hourly` then shows the
    **operator** plan (so charts/3D show what the operator chose). `recommendation` and the
    3-row `comparison` stay the AI's, unchanged. Without the override nothing changes.
- `POST /decisions` body = the /recommend request (+ `action`: "approved" | "adjusted",
  `charge_target_override_rth` required when adjusted). The **server recomputes** the response
  itself (never trusts numbers from the browser) and appends one CSV row; returns the row.
- `GET /decisions` → rows newest first (JSON). `GET /decisions.csv` → file download.
- `GET /explain?source_date=YYYY-MM-DD` → explainer for that day's forecast (see 6.4).
  `source_date` must be an eligible day (else 404). Forecasts are unscaled by day type
  (decision 3 of the MVP), so the date alone determines the explanation.

### 6.3 Decision log CSV
Path from `app.state` (default `data/decision_log.csv`; tests point it at a tmp dir).
Header written when the file is new; appends guarded by a process lock. Columns:
`timestamp` (ISO, local), `action`, the six request inputs, `source_date`,
`source_tmax_c`, `ai_forecast_model_rth`, `ai_forecast_need_rth`, `actual_need_rth`,
`ai_target_rth`, `operator_target_rth` (= ai_target for approved), `chosen_status`,
`chosen_shortfall_rth`, `chosen_daytime_ec_hours`, `chosen_ec_kwh`,
`ec_kwh_always_full`, `ec_kwh_calendar_rule`, `ec_kwh_ai_forecast`, `label` (=SIMULATED).
UI: "Decision log" card under the comparison table, newest 20 rows, a "Download CSV" link.

### 6.4 RF explainer
`DailyForecasts` additionally keeps the 10 fitted models: `models` keyed `"oct_dec"`,
`"m1"`…`"m9"`, and `model_key_by_day`. At startup, per model, compute on its **held-out**
days (Oct–Dec for `oct_dec`; month m for `mN`): permutation importance (MAE-based,
n_repeats 5, random_state 0 — builder may drop to 3 if startup budget needs it; record the
value used), impurity importances, and held-out MAE of the AI vs the calendar rule.
`GET /explain` response:
- `source_date`, `model_key`, `training_months`, `n_training_days`, `n_trees` (400),
  `min_samples_leaf` (3), `held_out_months`, `held_out_mae_ai_rth`, `held_out_mae_rule_rth`
- `features[]`: name, plain-English label, value for this day, unit, provenance
  (from `FEATURE_PROVENANCE`)
- `importance[]`: name, `permutation_mae_increase_rth` (mean, std), `impurity` (0–1)
- `trees`: `mean` (== the day's AI forecast, tested), `min`, `p10`, `median`, `p90`, `max`,
  and a 20-bin histogram of the 400 per-tree predictions
- `path`: tree index 0 (fixed, stated), first 5 split nodes on this day's path —
  feature, threshold, this day's value, direction (≤ / >), samples at node, node mean need —
  plus that tree's own prediction and its full path depth ("… N more splits not shown")
- `classifier`: step1 heat-index classifier accuracy on Oct–Dec (MEASURED), train/test months
- `label`: "SIMULATED"
UI: a "How the AI decided" card (collapsible) with: feature table; two side-by-side bar
charts (permutation vs impurity, with a one-line note why they differ); tree-spread
histogram with the mean marked; the 5-split path as a vertical list of boxes; a short
"Training process" paragraph filled from the response (months, days, trees, leaf size, why
Oct–Dec is never trained on).

### 6.5 3D plant view
- Toggle "2D | 3D" in the plant panel header; 2D default; 3D button disabled with a note when
  WebGL is unavailable.
- Three.js + OrbitControls vendored at a pinned version in `static/vendor/three/`, loaded
  via an import map (no CDN at runtime). License file kept alongside.
- Scene (low-poly): ground plane; 2 teal absorption-chiller boxes; 4 electric-chiller boxes
  (grey → amber when among the first `ec_count`); transparent tank cylinder with an inner water
  cylinder whose height = `tank_level_rth / tank_capacity_rth`; 3 campus blocks with
  transparent floor slabs (Academic tallest, Library & evening, Data centre & labs) each
  labelled with its live RT; reference image inspiration: transparent floors + coloured pipes,
  but no ducts or interior detail.
- Pipes: tube geometry; chilled supply blue, warm return orange. Segments:
  absorption → campus, electric chillers → tank (charging), electric chillers → campus
  (daytime EC), tank → campus (discharge), and return lines back to the plant.
- Flow: small particles move along each segment; shown only when that segment's RT > 0,
  speed proportional to RT (normalised to the plant's max). Direction reverses for
  charge vs discharge on the tank line.
- Controls: drag to orbit, scroll to zoom, "Reset view"; hover tooltip with component name
  and live value (RT or RTh) from the selected hour.
- Sync: same selected-hour state as the scrubber, Play 24 h and the charts.
- Performance target ~60 fps on a laptop; render only while visible.

### 6.6 User guide
`docs/guide/user_guide.html` (self-contained, images alongside) → published as a Claude
artifact (via the Artifact tool at the end, by the controller) → printed to
`docs/user_guide.pdf` by `scripts/build_guide_pdf.py` (Chromium `page.pdf`, A4). ≤ ~8 pages.
Sections: what the system represents; install and run; walkthrough of every control/panel
(one screenshot each, incl. 3D, explainer, log, Adjust); how to read recommendation, charts,
table; SIMULATED / MEASURED / PROPOSED; known limitations.

### 6.7 Screenshots
`scripts/screenshots.py` extended: `3d_night.png` (selected hour 02:00, charging) and
`3d_day.png` (13:00, discharging) from two different camera angles, `rf_panel.png`,
`decision_log.png` (after one approve + one adjust), plus the existing three.

## 7. Left to the builder
Geometry, colours and camera positions; chart forms in the explainer; guide wording;
exact particle counts/speeds; CSV number formatting; permutation `n_repeats` 5 vs 3 within
the startup budget.
