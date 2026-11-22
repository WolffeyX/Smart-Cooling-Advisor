# Pipe fix and impact vs baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Fix the 3D pipe network so that every pipe is connected and shows flow where water moves, and add an energy and CO₂ "impact vs baseline" block to the recommendation card.

**Architecture:** The 3D view gets geometry and segment changes in `static/plant3d-scene.js` and `static/plant3d.js`. The flow drivers are existing API fields. Impact is computed on the server in `app/recommend.py`, using a config emission factor, and rendered by `static/app.js`.

**Tech Stack:** FastAPI, pydantic v2, plain JS, Three.js r170 (vendored), pytest + Playwright.

**Spec:** `docs/superpowers/specs/2026-11-22-pipes-and-impact-design.md`

## Global Constraints
- Branch `impact-pipes`. Run every command as `.venv/Scripts/python -m …`.
- Every number the UI shows comes from an API response; the browser computes none. The existing tile `charge_rt*0.95` is the only exception.
- The API change is additive only. All 163 existing tests stay green. `ruff check app tests scripts` and `ruff format --check app tests scripts` stay clean.
- `scs/` and `app/plant.py` are untouched.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus
1. Some hours have zero campus load in a block (e.g. Academic at night). Expected: that block's stub is dim, with no dots and no errors.
2. When the AI uses more energy than a baseline (e.g. the hot weekday 23 Oct, where the rule wins), the card says "more" with a positive number, never "−X kWh less".
3. If baseline energy is 0, `pct_saved` is null and the card shows kWh only, without "NaN %".
4. An operator override is active. Expected: the impact block still describes the AI recommendation, unchanged.

---

### Task A: Pipe network geometry and flow

**Files:**
- Modify: `static/plant3d-scene.js` (SEGMENTS, static thin pipes, exported endpoint/box data)
- Modify: `static/plant3d.js` (flow drivers for new keys, hook exposure, idle key)
- Modify: `static/index.html` (key element `#plant-3d-key` inside `#plant-3d`)
- Modify: `static/styles.css`
- Test: `tests/test_frontend_e2e.py`

**Interfaces:**
- New segment keys and their drivers (all API fields):
  - `campus_header` uses `campus_load_rt`
  - `to_academic` uses `academic_rt`
  - `to_evening` uses `evening_rt`
  - `to_base` uses `base_rt`
- Existing segment keys keep their drivers: `sac_campus`, `ec_tank`, `ec_campus`, `tank_campus`, `return`.
- The hook adds:
  - `window.__plant3d.segmentEnds`: `{key: [[x,y,z],[x,y,z]]}`, the first and last point of each segment polyline;
  - `window.__plant3d.segmentPoints`: `{key: [[x,y,z],...]}`;
  - `window.__plant3d.boxes`: `[{id, min:[x,y,z], max:[x,y,z]}]`, for the SAC boxes, EC boxes, tank (as a bounding box) and the three blocks.
  - `hook.flows` gains the four new keys.

- [ ] **Step 1: Write the failing e2e tests.**
  - `test_3d_pipes_connected`: every endpoint of every segment lies within 0.6 of some box (distance from a point to an AABB) or within 0.6 of some *other* segment's polyline (distance from a point to a segment).
  - `test_3d_block_stubs_follow_block_load`: at index 15, `flows.to_academic == hourly[15].academic_rt` and `flows.campus_header == hourly[15].campus_load_rt`. At index 4, `flows.to_academic == 0` (Review Focus 1).
  - `test_3d_idle_key_visible`: `#plant-3d-key` is visible in 3D mode and contains "idle".
- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest tests/test_frontend_e2e.py -v -k "pipes_connected or stubs_follow or idle_key"`. Expected: FAIL.
- [ ] **Step 3: Implement** the route from spec §A:
  - Remove the dead-ending static header and the building/return stubs that are replaced by flow segments.
  - Building stubs end on each block's west face (x = 10.5).
  - Return stubs start on each block's east face (x = 15.5).
  - The return trunk ends with stubs on the faces of the SAC boxes and the EC row.
  - Keep the camera HOME/TARGET.
- [ ] **Step 4: Run** the full e2e file and `-m "not e2e"`. Expected: all pass. Take a 3D screenshot at 12:00 and at 02:00 into the scratchpad and look at both. Every pipe must visibly connect.
- [ ] **Step 5: Commit** `fix(3d): connect return and supply pipes, animate building feeds, idle key`.

### Task B: Impact vs baseline (server + card)

**Files:**
- Modify: `app/config.py` (`GRID_EMISSION_KG_PER_KWH = 0.740`, `GRID_EMISSION_SOURCE`)
- Modify: `app/recommend.py` (an `impact` block built from the comparison sums)
- Modify: `app/schemas.py` (`ImpactLine`, `Impact`, and `RecommendResponse.impact: Impact`)
- Modify: `static/index.html`, `static/app.js`, `static/styles.css` (an `#impact` block inside the reco card)
- Test: `tests/test_impact.py`, `tests/test_frontend_e2e.py`

**Interfaces:**
- `ImpactLine`: `{kwh_saved: float, pct_saved: float | None, co2_kg_saved: float}`
- `Impact`: `{vs_always_full: ImpactLine, vs_calendar_rule: ImpactLine, grid_kg_per_kwh: float, grid_source: str, label: Literal["SIMULATED"]}`
- `kwh_saved = baseline_ec_kwh − ai_ec_kwh` (using the same numbers as the comparison rows, rounded to 1 dp).
- `pct_saved = round(100 * kwh_saved / baseline, 1)`, or None if baseline == 0.
- `co2_kg_saved = round(kwh_saved * GRID_EMISSION_KG_PER_KWH, 1)`.
- Element ids: `#impact`, `#impact-full`, `#impact-rule`, `#impact-factor`, `#impact-caveat`.

- [ ] **Step 1: Write the failing tests** (`tests/test_impact.py`, using `client`):
  - `test_impact_matches_comparison`: for weekday 31 °C, `impact.vs_always_full.kwh_saved == comparison[always_full].ec_energy_kwh − comparison[ai_forecast].ec_energy_kwh` (±0.1). The same check applies to the rule. `co2 == kwh × 0.740` (±0.1). `grid_kg_per_kwh == 0.740`, and the source contains "Peninsular".
  - `test_impact_negative_when_ai_worse`: find a request where the rule beats the AI (the hot weekday 33.2 °C day, 2024-10-23, reachable via weekday tmax 33.2). There, `vs_calendar_rule.kwh_saved < 0` and `co2_kg_saved < 0` (Review Focus 2).
  - `test_impact_ignores_override`: the impact with override 9000 equals the impact without it (Review Focus 4).
  - `test_pct_none_when_baseline_zero`: a unit test of the helper with baseline 0 returns None (Review Focus 3).
- [ ] **Step 2: Write the failing e2e test.** `test_impact_card`: `#impact-full` contains the formatted `kwh_saved` and "kWh less" (or "more" when negative), and "CO₂". `#impact-factor` contains "0.740" and "ASSUMPTION". `#impact-caveat` is visible. For a negative case, the text says "more" and never contains "−" before "kWh less".
- [ ] **Step 3: Run** both. Expected: FAIL.
- [ ] **Step 4: Implement.** Card copy:
  - `#impact-full`: "vs always filling the tank: {abs kWh} kWh {less|more} electric-chiller energy ({abs pct} %) · ≈ {abs co2} kg CO₂ {less|more}". Omit the "(… %)" part when `pct_saved` is null.
  - `#impact-rule`: the same pattern, "vs weekday/weekend rule: …".
  - `#impact-factor`: "Grid factor {grid_kg_per_kwh} kg CO₂/kWh, {grid_source} · electricity only · ASSUMPTION".
  - `#impact-caveat`: "One day overstates the saving: cold left in the tank at 21:00 counts as spent. Over Oct–Dec the AI saves about 9 % against always filling (SIMULATED)."
  - Heading: "Impact on this day" with a SIMULATED tag.
- [ ] **Step 5: Run** the full suites and ruff. Expected: all pass.
- [ ] **Step 6: Commit** `feat: impact vs baseline (energy and CO₂) on the recommendation card`.

### Task C: Refresh screenshots and guide

**Files:**
- Modify: `docs/screenshots/*.png` (re-run `scripts/screenshots.py` and its `guide` mode)
- Modify: `docs/guide/user_guide.html` (Step 3 3D text: the idle key and building feeds; Step 4: the impact block and the grid factor, with the source named)
- Modify: `docs/user_guide.pdf`, `README.md` (one line on impact/CO₂)
- Test: `tests/test_readme.py` (still passes; the PDF stays at 4–8 pages)

- [ ] **Step 1: Re-run** `.venv/Scripts/python scripts/screenshots.py` and `.venv/Scripts/python scripts/screenshots.py guide`. View the 3D and recommendation-card images: the pipes connect, and the impact block is visible.
- [ ] **Step 2: Update** the guide text. New numbers may only come from the API or from this spec (grid factor 0.740 and its source). Rebuild with `.venv/Scripts/python scripts/build_guide_pdf.py`. View the pages.
- [ ] **Step 3: Run** `tests/test_readme.py` and ruff. Expected: pass.
- [ ] **Step 4: Commit** `docs: screenshots and guide for connected pipes and impact block`.
- [ ] **Step 5 (controller):** republish the guide artifact at the same URL.

### Task D: Final review and merge (controller)
- [ ] Opus whole-branch review of `mvp..impact-pipes`. One fix wave, then a scoped re-review.
- [ ] Run the full suite plus a live run. Then ask the user whether to merge `impact-pipes` into `mvp`.
