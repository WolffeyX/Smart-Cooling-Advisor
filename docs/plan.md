# Smart Cooling Advisor MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Every task follows superpowers:test-driven-development (failing test first). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A localhost FastAPI service + one-page dashboard that recommends tonight's TES charge target for UTP GDC, with every number SIMULATED.

**Architecture:** At startup a `DayBank` builds (or reads from CSV cache) the synthetic 2024 campus load, builds step5's daily table and trains the day-ahead forecasters once (Jan–Sep for Oct–Dec days, leave-one-month-out within Jan–Sep for Jan–Sep days). `POST /recommend` selects the nearest real 2024 day, applies the day-type multiplier and the error slider, and runs a pure 24-h dispatch three times (always_full / calendar_rule / ai_forecast). Static HTML/JS/SVG renders the response.

**Tech Stack:** Python 3.13 venv, FastAPI, uvicorn, pydantic v2, pandas, numpy, scikit-learn==1.6.1 (pinned: reproduces step1 0.788 and step5 results), pytest, httpx, ruff, Playwright (Python) + Chromium.

**Spec:** `docs/superpowers/specs/2026-11-22-smart-cooling-advisor-mvp-design.md` (decisions) and `docs/PROMPT_mvp.md` (full brief: API contract, UI, tests, DONE MEANS). Executors read both.

## Global Constraints

- All paths below are relative to the repo root `smart-cooling-advisor/` (its own git repo; never commit in `C:\Users\Wafi`).
- Interpreter: `.venv/Scripts/python` (Windows). Every command below uses it.
- `scs/` is read-only. Legacy code is imported through `app/legacy` only; never edit `scs/`, never write into `scs/data/`.
- Never mutate `step5_plant.PLANT` or any module global. Every function takes `params: dict` explicitly; derive per-request params with `{**params, "tes_capacity_rth": cap}`.
- Every response has `"label": "SIMULATED"`. Every UI chart caption contains "SIMULATED". UI numbers come only from the API.
- No in-sample forecast ever reaches a response; Oct–Dec (months 10–12) never appear in any training set.
- Hour order everywhere: `["22:00","23:00","00:00",…,"21:00"]` (24 rows). Day hours = 08–21 (tank may discharge); night hours = 22–07 (tank may charge).
- Validation ranges (422 outside): forecast_max_temp_c 24–38, safety_margin_pct 0–60 (default 10), tank_capacity_rth 5000–25000 (default 10000), tank_level_22_rth 0–capacity (default 1500), forecast_error_pct −30–30 (default 0), day_type ∈ {weekday, exam_week, semester_break, weekend}.
- Subagent models: Haiku = scaffolding/README skeleton/ruff/simple tests; Sonnet = features, tests, frontend, screenshots, routine debugging; Opus 5.5 effort high = plant-dispatch review, ML review, final review, and bugs Sonnet failed twice.

## Review Focus

1. **Capacity slider dropped below the current tank level** → API returns 422 with a field message; frontend clamps `tank_level_22_rth` to the new capacity before sending (Task 8 API test, Task 9 Playwright test).
2. **Temperature outside 2024's range (24 °C or 38 °C)** → nearest real day is used and `scenario.source_tmax_c` honestly reports its real max (e.g. 34.1, not 38) (Task 6 test).
3. **Semester break with tank already full** (`tank_level_22_rth == capacity`): no charging at all → chiller plan count 0 with start/end "—", always_full energy may be 0 → `vs_always_full_pct` is null, never a division error (Task 7 test).
4. **Any slider combination produces NaN/inf** (e.g. a day with missing features) → JSON crash. Sweep every day_type × temps 24..38 step 0.5: all 200 with finite numbers (Task 8 test).
5. **Out-of-order responses while dragging sliders** → the frontend ignores any response older than the latest request (Task 9 Playwright test).

---

### Task 1: Scaffold, config presets, legacy shim  *(Haiku)*

**Files:**
- Create: `requirements.txt`, `pyproject.toml` (ruff + pytest config: `testpaths=["tests"]`, `markers=["slow","e2e"]`), `app/__init__.py`, `app/legacy/__init__.py`, `app/config.py`, `tests/__init__.py`, `tests/test_config.py`
- Modify: `.gitignore` (add `data/campus_load_*.csv`)

**Interfaces:**
- Produces:
  - `app.legacy`: module attributes `step1_model`, `step2_simulate`, `step5_plant` (it inserts the absolute `scs/` dir at `sys.path[0]` then imports them).
  - `app.config`: `ROOT_DIR`, `SCS_DIR`, `WEATHER_CSV` (= `SCS_DIR/"data"/"seri_iskandar_2024_openmeteo.csv"`), `PLANT_RESULTS_CSV` (= `SCS_DIR/"data"/"plant_results.csv"`), `DATA_DIR` (= `ROOT_DIR/"data"`), `PRESETS: dict[str, dict]` with keys `"default"`, `"published_utp_data"`, `PRESET_LABELS = {"default": "code pack values (SIMULATED)", "published_utp_data": "ASSUMPTION"}`, `get_params(preset: str | None = None) -> dict` (fresh `copy.deepcopy`; `None` → env `SCA_PARAMS_PRESET` or `"default"`; unknown → `ValueError`), `DAY_TYPE_MULTIPLIERS = {"weekday": 1.0, "weekend": 1.0, "exam_week": 0.9, "semester_break": 0.35}`, `MULTIPLIER_LABEL = "ASSUMPTION"`.

- [ ] **Step 1: Create venv and requirements**

`requirements.txt`: `fastapi`, `uvicorn`, `pydantic>=2`, `pandas`, `numpy`, `scikit-learn==1.6.1`, `httpx`, `pytest`, `ruff`, `playwright`.
Run: `py -3.13 -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt && .venv/Scripts/python -m playwright install chromium`
Expected: installs succeed (if 1.6.1 has no wheel for 3.13, use `py -3.12` instead and note it in the commit message).

- [ ] **Step 2: Write the failing tests** in `tests/test_config.py`

```python
from app import config
from app.legacy import step5_plant

def test_default_preset_equals_step5_plant():
    assert config.get_params("default") == step5_plant.PLANT

def test_get_params_returns_fresh_copy():
    p = config.get_params("default"); p["sac_available_rt"] = 1.0; p["night_hours"].append(99)
    assert config.get_params("default")["sac_available_rt"] == 2200.0
    assert 99 not in config.get_params("default")["night_hours"]
    assert step5_plant.PLANT["sac_available_rt"] == 2200.0

def test_published_preset_values():
    p = config.get_params("published_utp_data")
    assert (p["standby_loss_per_h"], p["kw_per_rt_full"], p["kw_per_rt_aux"], p["sac_available_rt"]) == (0.0005, 0.82, 0.24, 1800.0)
    assert config.PRESET_LABELS["published_utp_data"] == "ASSUMPTION"

def test_env_var_selects_preset(monkeypatch):
    monkeypatch.setenv("SCA_PARAMS_PRESET", "published_utp_data")
    assert config.get_params()["sac_available_rt"] == 1800.0

def test_unknown_preset_raises():
    import pytest
    with pytest.raises(ValueError): config.get_params("nope")

def test_multipliers():
    assert config.DAY_TYPE_MULTIPLIERS == {"weekday": 1.0, "weekend": 1.0, "exam_week": 0.9, "semester_break": 0.35}
```

- [ ] **Step 3: Run** `.venv/Scripts/python -m pytest tests/test_config.py -q` → FAIL (ModuleNotFoundError: app).
- [ ] **Step 4: Implement** `app/legacy/__init__.py` and `app/config.py`. The default preset is written out literally in `config.py` (same keys and values as `step5_plant.PLANT`), not read from it.
- [ ] **Step 5: Run** the same command → 6 passed. Run `.venv/Scripts/python -m ruff check app tests` → no errors.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: scaffold, params presets, legacy shim"`

---

### Task 2: Weather, heat index and step1 classifier wrapper  *(Sonnet)*

**Files:**
- Create: `app/model.py`, `tests/test_model_step1.py`

**Interfaces:**
- Consumes: `app.legacy.step1_model`, `app.config.WEATHER_CSV`.
- Produces (in `app/model.py`):
  - `load_weather() -> pd.DataFrame` = `step1.add_features(step1.load_openmeteo(WEATHER_CSV))`; 8784 hourly rows, columns include `time, temp, rh, cloud, sw_rad, wind, rain, hi, cls, hour, month, weekday, target`.
  - `heat_index_c` (re-export of step1's).
  - `CLASSIFIER_FEATURES = step1.FEATURES`.
  - `train_classifier(weather: pd.DataFrame) -> dict` with keys `accuracy: float` (Oct–Dec), `train_months: set[int]`, `test_months: set[int]`; same RF settings as step1 (`n_estimators=300, min_samples_leaf=3, random_state=42`).

- [ ] **Step 1: Write the failing tests**

```python
import numpy as np, pytest
from app import model

F2C = lambda f: (f - 32) * 5 / 9
@pytest.mark.parametrize("t_f,rh,nws_table_f", [(90, 70, 106), (96, 50, 108), (86, 90, 105)])
def test_heat_index_matches_nws(t_f, rh, nws_table_f):
    hi_f = model.heat_index_c(np.array([F2C(t_f)]), np.array([rh]))[0] * 9 / 5 + 32
    assert abs(hi_f - nws_table_f) <= 0.5      # NWS heat-index table values (°F)

def test_classifier_trained_jan_sep_scores_oct_dec():
    r = model.train_classifier(model.load_weather())
    assert r["train_months"] == set(range(1, 10)) and r["test_months"] == {10, 11, 12}
    assert abs(r["accuracy"] - 0.788) <= 0.005

def test_no_classifier_feature_uses_t_plus_3_or_later():
    w = model.load_weather()
    assert "target" not in model.CLASSIFIER_FEATURES and "cls_ahead" not in model.CLASSIFIER_FEATURES
    # every feature at row t equals a value computed from row t alone: perturb rows t+1.. and recompute
    w2 = w.copy(); w2.loc[100:, ["temp", "rh", "cloud", "sw_rad", "wind", "rain"]] += 5.0
    from app.legacy import step1_model as s1
    f1 = s1.add_features(w[["time","temp","rh","cloud","sw_rad","wind","rain"]])
    f2 = s1.add_features(w2[["time","temp","rh","cloud","sw_rad","wind","rain"]])
    assert (f1.loc[:99, model.CLASSIFIER_FEATURES].values == f2.loc[:99, model.CLASSIFIER_FEATURES].values).all()
    assert (f1["target"].iloc[:97] == f1["cls"].shift(-3).iloc[:97]).all()   # target is exactly t+3
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_model_step1.py -q` → FAIL (no `app.model`).
- [ ] **Step 3: Implement** the three functions above in `app/model.py` by calling step1.
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit** `git commit -am "feat: weather + step1 classifier wrapper" ` (add new files first).

---

### Task 3: Synthetic campus load with CSV cache  *(Sonnet)*

**Files:**
- Modify: `app/model.py`
- Create: `tests/test_campus_load.py`

**Interfaces:**
- Consumes: `load_weather()`, `step5_plant.campus_load(df, P)`.
- Produces:
  - `LOAD_KEYS = ("base_load_rt", "target_peak_rt", "evening_factor", "noise_daily", "noise_hourly")`
  - `load_hash(params: dict) -> str` — first 8 hex chars of sha1 of `json.dumps({k: params[k] for k in LOAD_KEYS}, sort_keys=True)`.
  - `campus_load_frame(weather: pd.DataFrame, params: dict, cache_dir: Path = DATA_DIR) -> pd.DataFrame` — columns `time, total_rt, base_rt, room_rt`; 8784 rows; `base_rt = params["base_load_rt"] * (1 + 0.03 * (weather["temp"] - 27))`; `room_rt = total_rt - base_rt`; reads `cache_dir / f"campus_load_2024_{load_hash(params)}.csv"` if present, else computes with `step5.campus_load(weather, params)` and writes it (creating `cache_dir`).

- [ ] **Step 1: Write the failing tests** (use `tmp_path` as `cache_dir`)

```python
def test_load_matches_step5_and_writes_cache(tmp_path):
    w = model.load_weather(); p = config.get_params("default")
    fr = model.campus_load_frame(w, p, cache_dir=tmp_path)
    expected, _ = step5_plant.campus_load(w, p)
    assert len(fr) == 8784 and np.allclose(fr["total_rt"], expected)
    assert np.allclose(fr["base_rt"] + fr["room_rt"], fr["total_rt"])
    assert (tmp_path / f"campus_load_2024_{model.load_hash(p)}.csv").exists()

def test_cache_is_reused(tmp_path, monkeypatch):
    w = model.load_weather(); p = config.get_params("default")
    model.campus_load_frame(w, p, cache_dir=tmp_path)
    monkeypatch.setattr(model.step5_plant, "campus_load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("rebuilt")))
    fr = model.campus_load_frame(w, p, cache_dir=tmp_path)
    assert len(fr) == 8784

def test_hash_changes_with_load_params_not_plant_params():
    p = config.get_params("default")
    assert model.load_hash(p) != model.load_hash({**p, "target_peak_rt": 3600.0})
    assert model.load_hash(p) == model.load_hash(config.get_params("published_utp_data"))

def test_room_part_zero_on_weekend_daytime():
    w = model.load_weather(); fr = model.campus_load_frame(w, config.get_params("default"))
    assert np.allclose(fr.loc[~w["weekday"].values, "room_rt"], 0, atol=1e-6)
```
(`model` must import `step5_plant` at module level as `from app.legacy import step5_plant` so the monkeypatch works.)

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_campus_load.py -q` → FAIL.
- [ ] **Step 3: Implement** `LOAD_KEYS`, `load_hash`, `campus_load_frame`. Write CSV with `float_format` unspecified (full precision) so reread values equal computed ones.
- [ ] **Step 4: Run** → 4 passed (if `test_room_part_zero_on_weekend_daytime` fails, stop and report: it means step2's S1 schedule cools on weekends, and the multiplier design needs revisiting — do not change the test).
- [ ] **Step 5: Commit.**

**Review checkpoint A** (after Tasks 1–3): `superpowers:requesting-code-review` with a **Sonnet** reviewer.

---

### Task 4: Pure dispatch + year-long regression  *(Sonnet)*

**Files:**
- Create: `app/plant.py`, `tests/test_plant_dispatch.py`

**Interfaces:**
- Consumes: `step5_plant.ec_power_kw(load_rt, t_out, P)`, `step5_plant.forecasts`, `step5_plant.daily_table`, `step5_plant.plant_kpis` (regression only), `config.PLANT_RESULTS_CSV`.
- Produces:
  - `HOUR_LABELS = ["22:00", "23:00", "00:00", …, "21:00"]`; `HOURS = [22, 23, 0, 1, …, 21]`.
  - `dispatch_day(load_rt: np.ndarray, t_out: np.ndarray, hours: list[int], tank_level_start: float, charge_target_rth: float, params: dict) -> dict[str, np.ndarray]` — 24-length arrays with keys `campus_load_rt, sac_rt, tank_out_rt, ec_load_rt, charge_rt, ec_count, ec_kw, tank_level_rth, unmet_rt, standby_loss_rth`. `tank_level_rth` is the level at the end of the hour. Margin is NOT applied here.
  - `dispatch_year(weather: pd.DataFrame, load_rt: np.ndarray, target_by_date: dict, params: dict, start_level: float = 5000.0, use_margin: bool = True) -> pd.DataFrame` — same columns as `step5_plant.dispatch` (`ec_kw, ec_n, tes_out, ec_day_rt, unmet, soc, charge_rt`), indexed like `weather`.
  - Both use one private per-hour function `_hour_step(level, load, t_out, hour, target, params) -> (new_level, row_dict)` implementing design §6.6 steps 1–5 in that order; `hours_left = 8 - h if h < 8 else 32 - h`; night = `h in params["night_hours"]`.

- [ ] **Step 1: Write the failing tests**

```python
P = config.get_params("default")
def flat(v): return np.full(24, float(v))

def test_charges_only_at_night_and_discharges_only_by_day():
    load = np.array([1500]*10 + [3200]*14, float)          # 22..07 night, 08..21 day
    r = plant.dispatch_day(load, flat(30), plant.HOURS, 1500.0, 9000.0, P)
    assert (r["charge_rt"][10:] == 0).all() and (r["tank_out_rt"][:10] == 0).all()
    assert r["charge_rt"][:10].sum() > 0 and r["tank_out_rt"][10:].sum() > 0

def test_level_change_is_charge_eff_minus_out_minus_standby():
    load = np.array([1500]*10 + [3200]*14, float)
    r = plant.dispatch_day(load, flat(30), plant.HOURS, 1500.0, 9000.0, P)
    prev = np.r_[1500.0, r["tank_level_rth"][:-1]]
    assert np.allclose(r["tank_level_rth"] - prev, r["charge_rt"]*0.95 - r["tank_out_rt"] - r["standby_loss_rth"], atol=1e-6)
    assert np.allclose(r["standby_loss_rth"], prev * 0.004)

def test_tank_out_capped_at_max_discharge_and_level():
    r = plant.dispatch_day(flat(6000), flat(30), plant.HOURS, 10000.0, 10000.0, P)
    assert r["tank_out_rt"].max() <= 2500 + 1e-9 and r["tank_level_rth"].min() >= -1e-9

def test_unmet_when_ec_capacity_exceeded():
    r = plant.dispatch_day(flat(5000), flat(30), plant.HOURS, 0.0, 0.0, P)   # 5000-2200=2800 > 1300 EC
    assert np.allclose(r["unmet_rt"][10:], 2800 - 1300) and (r["ec_count"] <= 4).all()

def test_regression_oct_dec_matches_step5_plant_results():
    w = model.load_weather(); load = model.campus_load_frame(w, P)["total_rt"].values
    g = step5_plant.daily_table(w, load, P); f = step5_plant.forecasts(g)
    ref = pd.read_csv(config.PLANT_RESULTS_CSV).set_index("strategy")["EC_MWh"]
    test = (w["month"] >= 10).values
    for name in ["always_full", "calendar_rule", "AI_plus_dayahead_weather", "perfect"]:
        tgt = {pd.Timestamp(k): v for k, v in f[name].items()}
        res = plant.dispatch_year(w, load, tgt, P, use_margin=(name != "perfect"))
        got = step5_plant.plant_kpis(w, res, test, name)["EC_MWh"]
        assert abs(got / ref[name] - 1) <= 0.005, (name, got, ref[name])
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_plant_dispatch.py -q` → FAIL.
- [ ] **Step 3: Implement** `app/plant.py`. In `dispatch_year`, the night target for hour h follows step5: date = tomorrow if h ≥ 22 else today; `tgt = target_by_date.get(date, capacity)`; then `min(capacity, tgt*(1+margin) if use_margin else tgt)`.
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit.**

---

### Task 5: Daily forecasters without leakage  *(Sonnet)*

**Files:**
- Modify: `app/model.py`
- Create: `tests/test_forecasters.py`

**Interfaces:**
- Consumes: `step5_plant.daily_table`, `campus_load_frame`.
- Produces:
  - `FEATURE_PROVENANCE: dict[str, str]` — every forecaster feature → one of `"observed_lag1"`, `"observed_lag7"`, `"calendar"`, `"simulated_dayahead"`. Exactly: `need_today, load_today, tmean_today, himax_today, rain_today` → lag1; `need_lastweek` → lag7; `dow_tomorrow, weekday_tomorrow, month` → calendar; `fc_tmax, fc_sw, fc_rain` → simulated_dayahead.
  - `build_features(g: pd.DataFrame, seed: int = 0) -> pd.DataFrame` — the 12 columns in that order, built exactly as step5 `forecasts()` builds `Xw` (same rng draw order: tmax, sw, rain).
  - `@dataclass DailyForecasts: ai: pd.Series; calendar: pd.Series; training_months: dict[pd.Timestamp, list[int]]; eligible: pd.DatetimeIndex`
  - `train_forecasters(g: pd.DataFrame, X: pd.DataFrame) -> DailyForecasts` — RF regressor `(400, min_samples_leaf=3, random_state=42, n_jobs=-1)`. One model on feature-complete Jan–Sep days → predicts Oct–Dec days. For m in 1..9, a model on feature-complete days with month ∈ {1..9}∖{m} → predicts month m days. `calendar` for a day = mean `need_rth` per `dow` over that day's training months. `eligible` = 2024-01-08 … 2024-12-31 (all feature-complete).
  - `TRAINING_MONTHS_OCT_DEC = list(range(1, 10))`.

- [ ] **Step 1: Write the failing tests** (module-scoped fixture `fx` = `SimpleNamespace(w, g, X, fc)` built once from default params: `w = load_weather()`, `g = step5_plant.daily_table(w, campus_load_frame(w, P)["total_rt"].values, P)`, `X = build_features(g)`, `fc = train_forecasters(g, X)`)

```python
def test_every_feature_has_provenance_and_none_is_same_day_observed(fx):
    assert list(fx.X.columns) == list(model.FEATURE_PROVENANCE)
    assert set(model.FEATURE_PROVENANCE.values()) <= {"observed_lag1","observed_lag7","calendar","simulated_dayahead"}

def test_observed_features_use_only_previous_days(fx):
    g2 = fx.g.copy(); d = pd.Timestamp("2024-11-15")
    g2.loc[d:, ["need_rth","load_rth","tmean","himax","rain"]] *= 3      # change day D and later
    X2 = model.build_features(g2)
    lag = [c for c, k in model.FEATURE_PROVENANCE.items() if k.startswith("observed")]
    assert np.allclose(fx.X.loc[d, lag], X2.loc[d, lag])                # day D's features unchanged

def test_oct_dec_forecast_equals_step5_and_test_months_never_trained(fx):
    f5 = step5_plant.forecasts(fx.g)["AI_plus_dayahead_weather"]
    od = fx.fc.ai.index[fx.fc.ai.index.month >= 10]
    assert np.allclose(fx.fc.ai[od], f5[od])
    for day, months in fx.fc.training_months.items():
        assert not ({10, 11, 12} & set(months))
        if day.month <= 9: assert day.month not in months and len(months) == 8
        else: assert months == list(range(1, 10))

def test_eligible_days(fx):
    assert fx.fc.eligible[0] == pd.Timestamp("2024-01-08") and fx.fc.eligible[-1] == pd.Timestamp("2024-12-31")
    assert fx.fc.ai[fx.fc.eligible].notna().all() and fx.fc.calendar[fx.fc.eligible].notna().all()

def test_jan_sep_forecast_is_out_of_sample(fx):
    # zeroing May's targets must not change any May forecast: May was not in its training set
    d = pd.Timestamp("2024-05-14"); g2 = fx.g.copy(); g2.loc[g2.index.month == 5, "need_rth"] = 0.0
    fc2 = model.train_forecasters(g2, fx.X)      # X held fixed: only targets change
    assert fc2.ai[d] == pytest.approx(fx.fc.ai[d])
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_forecasters.py -q` → FAIL.
- [ ] **Step 3: Implement** in `app/model.py`.
- [ ] **Step 4: Run** → 5 passed.
- [ ] **Step 5: Commit.**

**Review checkpoint B — ML pipeline** (after Tasks 2, 3, 5): `superpowers:requesting-code-review` with **Opus 5.5, effort high**: data leakage, split by date, baselines, that no feature uses information after 22:00 the day before, that test months are never seen in training.

---

### Task 6: DayBank and scenario construction  *(Sonnet)*

**Files:**
- Create: `app/scenario.py`, `tests/test_scenario.py`, `tests/conftest.py` (session-scoped fixtures `P = get_params("default")` and `bank = build_day_bank(P)`; Task 8 adds `client`)

**Interfaces:**
- Consumes: `load_weather`, `campus_load_frame`, `build_features`, `train_forecasters`, `step5_plant.daily_table`, `DAY_TYPE_MULTIPLIERS`, `plant.HOURS`, `plant.HOUR_LABELS`.
- Produces:
  - `@dataclass DayBank: weather: pd.DataFrame; load: pd.DataFrame; daily: pd.DataFrame; forecasts: DailyForecasts; params: dict`
  - `build_day_bank(params: dict, cache_dir: Path = DATA_DIR) -> DayBank`
  - `select_day(bank: DayBank, day_type: str, tmax_c: float) -> pd.Timestamp` — weekday/exam_week/semester_break → Mon–Fri eligible days; weekend → Sat/Sun. Nearest Oct–Dec day by `|daily.tmax − tmax_c|`; if that distance > 1.0, nearest over all eligible days. Ties → earliest.
  - `@dataclass Scenario: source_date: str; day_type: str; source_tmax_c: float; training_months: list[int]; forecast_kind: str; load_rt: np.ndarray; t_out: np.ndarray; actual_need_rth: float; ai_forecast_model_rth: float; calendar_need_rth: float`
  - `build_scenario(bank: DayBank, day_type: str, tmax_c: float, params: dict) -> Scenario` — profile = hours 22, 23 of D−1 then 00–21 of D; `load_rt = base_rt + m * room_rt`; `actual_need_rth = Σ_{i=10..23} max(load_rt[i] − params["sac_available_rt"], 0)`; `ai_forecast_model_rth = forecasts.ai[D]` and `calendar_need_rth = forecasts.calendar[D]` both unscaled; `forecast_kind = "trained Jan–Sep, tested Oct–Dec"` for months ≥ 10 else `"leave-one-month-out (trained on Jan–Sep except this month)"`; `source_tmax_c` rounded to 1 dp.

- [ ] **Step 1: Write the failing tests** (module-scoped `bank = build_day_bank(get_params("default"))`)

```python
def test_prefers_oct_dec_within_1c(bank):
    d = scenario.select_day(bank, "weekday", 31.0)
    assert d.month >= 10 and d.dayofweek < 5 and abs(bank.daily.loc[d, "tmax"] - 31.0) <= 1.0

def test_34c_weekday_stays_in_oct_dec(bank):          # Oct–Dec max weekday is 33.2 °C, within 1 °C
    assert scenario.select_day(bank, "weekday", 34.0) == pd.Timestamp(bank.daily[(bank.daily.index.month >= 10) & (bank.daily.index.dayofweek < 5)]["tmax"].idxmax())

def test_hot_weekday_falls_back_to_whole_year_with_lomo(bank, P):
    s = scenario.build_scenario(bank, "weekday", 34.5, P)
    assert pd.Timestamp(s.source_date).month <= 9 and pd.Timestamp(s.source_date).month not in s.training_months
    assert s.forecast_kind.startswith("leave-one-month-out")

def test_out_of_range_temps_report_real_tmax(bank, P):
    hi = scenario.build_scenario(bank, "weekday", 38.0, P); lo = scenario.build_scenario(bank, "weekday", 24.0, P)
    assert hi.source_tmax_c == 34.1 and lo.source_tmax_c == 25.7

def test_weekend_picks_weekend(bank):
    assert scenario.select_day(bank, "weekend", 30.0).dayofweek >= 5

def test_profile_is_22_to_21(bank, P):
    s = scenario.build_scenario(bank, "weekday", 31.0, P); D = pd.Timestamp(s.source_date)
    tot = bank.load.set_index("time")["total_rt"]
    assert s.load_rt[0] == pytest.approx(tot[D - pd.Timedelta(hours=2)])        # 22:00 D-1
    assert s.load_rt[23] == pytest.approx(tot[D + pd.Timedelta(hours=21)])      # 21:00 D
    assert len(s.load_rt) == 24 == len(s.t_out)

def test_multiplier_scales_room_part_only_and_forecast_unscaled(bank, P):
    wk = scenario.build_scenario(bank, "weekday", 31.0, P); br = scenario.build_scenario(bank, "semester_break", 31.0, P)
    assert br.source_date == wk.source_date
    assert br.ai_forecast_model_rth == wk.ai_forecast_model_rth and br.calendar_need_rth == wk.calendar_need_rth
    assert br.actual_need_rth < 0.05 * wk.actual_need_rth
    assert (br.load_rt[:10] == pytest.approx(wk.load_rt[:10]))                   # nights: base load only

def test_actual_need_matches_step5_daily_table_for_weekday(bank, P):
    s = scenario.build_scenario(bank, "weekday", 31.0, P)
    assert s.actual_need_rth == pytest.approx(bank.daily.loc[pd.Timestamp(s.source_date), "need_rth"])
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_scenario.py -q` → FAIL.
- [ ] **Step 3: Implement** `app/scenario.py`.
- [ ] **Step 4: Run** → 8 passed.
- [ ] **Step 5: Commit.**

---

### Task 7: Strategies, recommendation and response assembly  *(Sonnet)*

**Files:**
- Create: `app/recommend.py` (response assembly; my addition to the brief's layout so `plant.py` stays physics-only), `tests/test_recommend.py`, `tests/test_energy_balance.py`
- Modify: `app/plant.py` (add `summarise_day`)

**Interfaces:**
- Consumes: `dispatch_day`, `HOUR_LABELS`, `build_scenario`, `DayBank`.
- Produces:
  - `plant.summarise_day(r: dict) -> dict` with `ec_energy_kwh` (Σ ec_kw), `daytime_ec_hours` (count of i in 10..23 with `ec_load_rt > 1e-9`), `shortfall_rth` (Σ unmet_rt), `chillers` = `{"count": max ec_count over hours with charge_rt > 1e-9 (0 if none), "start": "22:00" or "—", "end": HOUR_LABELS[last charging index + 1] or "—"}`.
  - `recommend.build_response(bank: DayBank, req: dict, base_params: dict) -> dict` — the full `/recommend` response dict per the brief (plus `scenario.training_months`, `scenario.forecast_kind`, `recommendation.ai_forecast_model_rth`). Steps: `p = {**base_params, "tes_capacity_rth": cap}`; `ai_used = ai_model * (1 + err/100)`; targets: always_full = cap, calendar_rule = `min(cap, cal*(1+mg))`, ai = `min(cap, ai_used*(1+mg))`; three `dispatch_day` runs from `tank_level_22_rth`; `capped = ai_used*(1+mg) > cap`; `status` = "shortfall" if shortfall > 1e-6 else "capped" if capped else "ok"; `message` per status (ok: "Plan covers tomorrow with the chosen safety margin."; capped: "Target capped at tank capacity ({cap:,} RTh); daytime electric chillers are expected."; shortfall: "Cooling shortfall of {x:,} RTh tomorrow. Raise the safety margin or plan daytime electric chillers."); `vs_always_full_pct = round(100*(e/e_full − 1), 1)` for calendar/ai, `None` for always_full and when `e_full == 0`. `plant` block from p. Every float is a plain Python float, rounded to 1 dp. `assumptions` (strings): synthetic campus load (~1,250 rooms + 350 RT base, real 2024 weather); simulated day-ahead weather forecast (true value + noise); day-type multipliers exam 0.9 / break 0.35 on room load (ASSUMPTION); AI and weekday/weekend rule treat exam weeks and breaks as normal weekdays (the model never saw one); plant parameters from the code pack, preset name; scenario uses a real 2024 day (source date, training months); one year of weather only.

- [ ] **Step 1: Write the failing tests**

`tests/test_recommend.py`:
```python
REQ = dict(day_type="weekday", forecast_max_temp_c=31.0, safety_margin_pct=10, tank_capacity_rth=10000, tank_level_22_rth=1500, forecast_error_pct=0)
def run(bank, **kw): return recommend.build_response(bank, {**REQ, **kw}, config.get_params("default"))

def test_always_full_target_is_capacity(bank):
    assert run(bank, tank_capacity_rth=12000)["comparison"][0]["charge_target_rth"] == 12000

def test_zero_error_zero_margin_target_equals_model_forecast(bank):
    r = run(bank, safety_margin_pct=0); rec = r["recommendation"]
    assert rec["charge_target_rth"] == pytest.approx(min(10000, rec["ai_forecast_model_rth"]), abs=0.1)

@pytest.mark.parametrize("temp,margin,cap", [(31, 10, 10000), (34, 60, 5000), (29, 0, 25000), (34, 10, 10000)])
def test_capped_flag(bank, temp, margin, cap):
    rec = run(bank, forecast_max_temp_c=temp, safety_margin_pct=margin, tank_capacity_rth=cap)["recommendation"]
    assert rec["capped"] == (rec["ai_forecast_need_rth"] * (1 + margin/100) > cap)

def test_error_slider_moves_forecast_not_actual(bank):
    a, b = run(bank)["recommendation"], run(bank, forecast_error_pct=-20)["recommendation"]
    assert b["actual_need_rth"] == a["actual_need_rth"]
    assert b["ai_forecast_need_rth"] == pytest.approx(0.8 * a["ai_forecast_model_rth"], abs=0.1)

def test_order_and_shape(bank):
    r = run(bank)
    assert [c["strategy"] for c in r["comparison"]] == ["always_full", "calendar_rule", "ai_forecast"]
    assert r["comparison"][0]["vs_always_full_pct"] is None and len(r["hourly"]) == 24
    assert r["hourly"][0]["hour"] == "22:00" and r["hourly"][-1]["hour"] == "21:00" and r["label"] == "SIMULATED"

def test_full_tank_semester_break_has_no_charging(bank):   # Review Focus 3
    r = run(bank, day_type="semester_break", tank_level_22_rth=10000)   # AI target < level after standby loss
    assert r["recommendation"]["electric_chillers"] == {"count": 0, "start": "—", "end": "—"}
    assert all(c["vs_always_full_pct"] is None or math.isfinite(c["vs_always_full_pct"]) for c in r["comparison"])

def test_vs_pct_handles_zero_baseline():
    assert recommend.vs_always_full_pct(0.0, 0.0) is None and recommend.vs_always_full_pct(90.0, 100.0) == -10.0
```
(`recommend.vs_always_full_pct(e: float, e_full: float) -> float | None` is the helper used for the comparison rows.)

`tests/test_energy_balance.py` — parametrize over the brief's scenarios: (weekday 34), (weekday 29), (weekend 30), (semester_break 31), (weekday 31, cap 5000), (weekday 31, cap 25000), (weekday 31, margin 0), (weekday 31, margin 60), (exam_week 32), plus forecast_error −30 and +30. For every response and every hourly row, with `p` = default params:
```python
assert h["sac_rt"] + h["tank_out_rt"] + h["ec_load_rt"] + h["unmet_rt"] == pytest.approx(h["campus_load_rt"], abs=1e-6)
assert h["ec_load_rt"] + h["charge_rt"] <= 4 * 325 + 1e-6
assert -1e-9 <= h["tank_level_rth"] <= cap + 1e-6
night = i < 10; assert (h["charge_rt"] == 0) if not night else (h["tank_out_rt"] == 0)
prev = req["tank_level_22_rth"] if i == 0 else r["hourly"][i-1]["tank_level_rth"]
assert h["tank_level_rth"] - prev == pytest.approx(h["charge_rt"]*0.95 - h["tank_out_rt"] - prev*0.004, abs=1e-6)
assert rec["shortfall_rth"] == pytest.approx(sum(h["unmet_rt"] for h in r["hourly"]), abs=0.1)
```
These balance assertions run on **unrounded** arrays: `build_response` takes `round_values: bool = True`; the balance test calls it with `round_values=False`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_recommend.py tests/test_energy_balance.py -q` → FAIL.
- [ ] **Step 3: Implement** `summarise_day` and `app/recommend.py`.
- [ ] **Step 4: Run** → all pass.
- [ ] **Step 5: Commit.**

**Review checkpoint C — plant dispatch** (after Tasks 4, 7): `superpowers:requesting-code-review` with **Opus 5.5, effort high**: energy balance, tank limits, charging window, margin and capping, shortfall accounting, parity with step5 physics.

---

### Task 8: Schemas and FastAPI app  *(Sonnet; the /health and schema-range tests may be written by Haiku)*

**Files:**
- Create: `app/schemas.py`, `app/main.py`, `tests/test_api.py`
- Modify: `tests/conftest.py` (add session-scoped `client` = `TestClient(main.app)` used as a context manager so the lifespan runs)
- Create: `static/index.html` placeholder containing `SIMULATED` (replaced in Task 9)

**Interfaces:**
- Consumes: `build_day_bank`, `build_response`, `get_params`.
- Produces:
  - `schemas.RecommendRequest` (pydantic v2, fields and ranges from Global Constraints; `model_validator(mode="after")` raises if `tank_level_22_rth > tank_capacity_rth` with message "tank_level_22_rth must be ≤ tank_capacity_rth") and response models mirroring the brief (`RecommendResponse` with `label: Literal["SIMULATED"]`).
  - `main.app` — lifespan builds `app.state.bank = build_day_bank(get_params())`; `GET /health` → `{"status": "ok", "model_trained": True, "label": "SIMULATED"}`; `POST /recommend` → `RecommendResponse`; `StaticFiles(directory=ROOT_DIR/"static", html=True)` mounted at `/` **after** the API routes.

- [ ] **Step 1: Write the failing tests**

```python
def test_health(client):
    r = client.get("/health"); assert r.status_code == 200 and r.json() == {"status": "ok", "model_trained": True, "label": "SIMULATED"}

def test_recommend_shape(client):
    r = client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": 31}); j = r.json()
    assert r.status_code == 200 and j["label"] == "SIMULATED" and len(j["hourly"]) == 24
    assert [c["strategy"] for c in j["comparison"]] == ["always_full", "calendar_rule", "ai_forecast"]

@pytest.mark.parametrize("bad", [{"forecast_max_temp_c": 23.9}, {"forecast_max_temp_c": 38.1}, {"safety_margin_pct": 61},
    {"tank_capacity_rth": 4999}, {"tank_capacity_rth": 25001}, {"forecast_error_pct": -31}, {"day_type": "holiday"},
    {"tank_capacity_rth": 6000, "tank_level_22_rth": 7000}])
def test_out_of_range_is_422(client, bad):
    assert client.post("/recommend", json={"day_type": "weekday", "forecast_max_temp_c": 31, **bad}).status_code == 422

def test_root_serves_html(client):
    r = client.get("/"); assert r.status_code == 200 and "SIMULATED" in r.text

@pytest.mark.slow
def test_sweep_all_inputs_finite(client):              # Review Focus 4
    for dt in ["weekday", "exam_week", "semester_break", "weekend"]:
        for t in np.arange(24, 38.01, 0.5):
            j = client.post("/recommend", json={"day_type": dt, "forecast_max_temp_c": float(t)}).json()
            nums = [v for h in j["hourly"] for v in h.values() if isinstance(v, (int, float))]
            assert all(math.isfinite(v) for v in nums)

def test_cold_start_under_60s(tmp_path):
    t = time.perf_counter(); scenario.build_day_bank(config.get_params(), cache_dir=tmp_path)
    assert time.perf_counter() - t < 60
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_api.py -q` → FAIL.
- [ ] **Step 3: Implement** `app/schemas.py`, `app/main.py`, placeholder `static/index.html`.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` → all pass. Then manual check:
  `.venv/Scripts/python -m uvicorn app.main:app` (background) and `curl -s localhost:8000/health` → `{"status":"ok","model_trained":true,"label":"SIMULATED"}`.
- [ ] **Step 5: Commit.**

---

### Task 9: Frontend port of sketch page 1  *(Sonnet)*

**Files:**
- Create/replace: `static/index.html`, `static/app.js`, `static/styles.css`, `tests/test_frontend_e2e.py` (marker `e2e`; session fixture starts uvicorn on port 8765 in a subprocess and waits for `/health`)

**Interfaces:**
- Consumes: `POST /recommend`, `GET /health` (same origin). Response shape from Task 7.
- Produces: element ids the e2e tests and screenshots use: `#day-type` (buttons with `data-value`), `#temp`, `#error`, `#margin`, `#capacity`, `#level` (range inputs), `#hero-target`, `#chiller-plan`, `#ai-need`, `#actual-need`, `#daytime-ec`, `#shortfall`, `#status-note`, `#plant-svg`, `#scrubber`, `#play`, `#reset`, `#tile-load`, `#tile-sac`, `#tile-tank`, `#tile-ec`, `#chart-supply` (24 `.bar` groups), `#chart-tank`, `#comparison` (table, 3 body rows), `#assumptions`, `#scenario-date`, `#toast`.

Layout, wording, colours and components exactly as `docs/PROMPT_mvp.md` "Frontend" and the sketch page 1 (tokens from `docs/PROMPT_ui.md` "VISUAL TOKENS" may be used). Number format `Intl.NumberFormat("en-MY")`, true minus sign for negatives. Debounce 300 ms; each request carries an increasing sequence number and responses older than the latest are dropped. Level slider max = capacity; when capacity drops below level, clamp level before sending. Play advances one hour per 700 ms and stops at 21:00; Reset → 12:00 and stops. Approve / Adjust → toast "Demo only, nothing is sent". Footnote and every chart caption include "SIMULATED".

- [ ] **Step 1: Write the failing e2e tests** (Playwright sync API, Chromium, viewport 1440×900)

```python
def test_initial_render_uses_api(page, server):
    page.goto(server); page.wait_for_selector("#hero-target:not(:empty)")
    api = page.request.post(f"{server}/recommend", data={"day_type":"weekday","forecast_max_temp_c":31,"safety_margin_pct":10,"tank_capacity_rth":10000,"tank_level_22_rth":1500,"forecast_error_pct":0}).json()
    assert page.inner_text("#hero-target").replace("\u00a0"," ").startswith(f'{round(api["recommendation"]["charge_target_rth"]):,}')
    assert page.locator("#chart-supply .bar").count() == 24 and page.locator("#comparison tbody tr").count() == 3
    assert "SIMULATED" in page.inner_text("body")

def test_day_type_change_refetches(page, server):
    page.goto(server); page.wait_for_selector("#hero-target:not(:empty)")
    with page.expect_response("**/recommend"): page.click('#day-type [data-value="semester_break"]')

def test_capacity_drop_clamps_level(page, server):            # Review Focus 1
    page.goto(server); page.fill("#level", "9000"); page.fill("#capacity", "6000")
    page.wait_for_timeout(500); assert float(page.input_value("#level")) <= 6000

def test_stale_responses_ignored(page, server):               # Review Focus 5
    page.goto(server); page.wait_for_selector("#hero-target:not(:empty)")
    calls = {"n": 0}
    def handler(route):
        calls["n"] += 1
        if calls["n"] == 1: page.wait_for_timeout(1500)     # first (weekend) response arrives last
        route.continue_()
    page.route("**/recommend", handler)
    page.click('#day-type [data-value="weekend"]'); page.wait_for_timeout(400)
    page.click('#day-type [data-value="weekday"]'); page.wait_for_timeout(2500)
    weekday_date = page.request.post(f"{server}/recommend", data={"day_type":"weekday","forecast_max_temp_c":31}).json()["scenario"]["source_date"]
    assert page.get_attribute("#scenario-date", "data-date") == weekday_date   # #scenario-date carries data-date = source_date

def test_play_stops_at_21_and_reset(page, server):
    page.goto(server); page.wait_for_selector("#hero-target:not(:empty)")
    page.click("#play"); page.wait_for_function("document.querySelector('#scrubber').value == '23'", timeout=20000)
    page.wait_for_timeout(1000); assert page.input_value("#scrubber") == "23"
    page.click("#reset"); assert page.input_value("#scrubber") == "14"   # index of 12:00

def test_approve_shows_toast(page, server):
    page.goto(server); page.click("text=Approve plan"); assert "Demo only, nothing is sent" in page.inner_text("#toast")
```

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_frontend_e2e.py -q` → FAIL.
- [ ] **Step 3: Implement** `static/index.html`, `static/app.js`, `static/styles.css`.
- [ ] **Step 4: Run** → all pass; then take one throwaway screenshot and compare it against the sketch by eye (layout, wording) before committing.
- [ ] **Step 5: Commit.**

**Review checkpoint D** (after Tasks 8–9): `superpowers:requesting-code-review` with a **Sonnet** reviewer (API contract vs brief, UI vs sketch, no hard-coded numbers).

---

### Task 10: Screenshots and README  *(Sonnet for the screenshot script; Haiku may draft the README skeleton, Sonnet fills it)*

**Files:**
- Create: `scripts/screenshots.py`, `docs/screenshots/hot_weekday.png`, `docs/screenshots/cool_weekday.png`, `docs/screenshots/semester_break.png`, `README.md`, `tests/test_readme.py`

**Interfaces:**
- Consumes: running server (script starts uvicorn itself on 8765, like the e2e fixture), element ids from Task 9.

- [ ] **Step 1: Write the failing test** `tests/test_readme.py`

```python
def test_readme_and_screenshots_exist():
    t = (config.ROOT_DIR / "README.md").read_text(encoding="utf-8")
    for s in ["pip install -r requirements.txt", "uvicorn app.main:app", "pytest", "SIMULATED", "MEASURED", "PROPOSED",
              "Assumptions", "Known limitations", "synthetic", "one year of weather", "PMMD", "SCA_PARAMS_PRESET"]:
        assert s in t, s
    for n in ["hot_weekday", "cool_weekday", "semester_break"]:
        assert (config.ROOT_DIR / "docs" / "screenshots" / f"{n}.png").stat().st_size > 50_000
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Write** `scripts/screenshots.py` (Playwright, viewport 1440×900, `device_scale_factor=2`, `full_page=True` so the recommendation and comparison table are both captured; scenarios: weekday 34 °C, weekday 29 °C, semester_break 31 °C, other inputs default) and run it: `.venv/Scripts/python scripts/screenshots.py`.
- [ ] **Step 4: Write** `README.md`: install (venv + pip + `playwright install chromium`), run, test (`pytest -q`, `-m "not e2e"`), labelling (SIMULATED = model + assumptions output, MEASURED = step1 classifier accuracy on real 2024 weather, PROPOSED = the advisor decision itself), assumptions list (mirrors the API's), the `SCA_PARAMS_PRESET` toggle, known limitations (synthetic load, one year of weather, no PMMD/UTP plant data, simulated day-ahead forecast, no holidays, AI never saw exam/break days).
- [ ] **Step 5: Run** `.venv/Scripts/python -m pytest -q` → all pass. Open each PNG and confirm it shows the recommendation card and the comparison table.
- [ ] **Step 6: Commit.**

---

### Task 11: Final review and verification  *(orchestrator + Opus 5.5 high reviewer)*

- [ ] **Step 1:** Final whole-repo review (`superpowers:requesting-code-review`, **Opus 5.5, effort high**). Fix every Critical/Important finding via a fresh Sonnet subagent per fix (TDD; `superpowers:systematic-debugging` for any failure; escalate to Opus only after two failed Sonnet attempts).
- [ ] **Step 2:** `superpowers:verification-before-completion`: run and paste real output of `.venv/Scripts/python -m pytest -q` (summary line), `uvicorn app.main:app` + `curl localhost:8000/health`, `ruff check .`, list `docs/screenshots/`, and tick every item in the brief's DONE MEANS.
