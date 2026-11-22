# Pipe fix and impact vs baseline — short design

Date: 2026-11-22 · Branch `impact-pipes` cut from `mvp` (f4920c7). Approved by the user in chat.

## Why
The user saw three problems in the 3D view:
- the orange return pipe is connected to nothing;
- a blue pipe looks cut off;
- some pipes show no flow.

They also asked the recommendation card to show the impact against a baseline: energy saved and CO₂ reduced.

## Root causes (static/plant3d-scene.js)
1. **Return pipe.** `SEGMENTS.return` ends at (-19, 0.5, -6). That is 2.5 units west of the absorption-chiller boxes, whose west face is at x = -16.5. The pipe never reaches the electric-chiller row, and its collector covers only z = 0..-13, so the Data-centre stub (z = 7) is left dangling.
2. **Supply header.** The thin static header at x = 8 runs to z = 8.5, past the last block (z = 7), and dead-ends. The header and its building stubs are never flow segments, so no water is ever shown entering a building.
3. **Idle pipes.** At hours with 0 electric chillers on, the EC pipes are correctly idle, but nothing in the view explains this.

## Design
### A. Pipes
- **Return route.** A collector runs behind all three blocks (x = 17, z = 7 → -13), then west along z = -13 to x = -19. It then runs south along x = -19 past both absorption chillers to the EC row, with branch stubs that end on the faces of each absorption-chiller box and the EC row. Its flow driver is `campus_load_rt`.
- **Supply header.** It is trimmed to end at the last block's stub. The header becomes a flow segment `campus_header`, driven by `campus_load_rt`. Each building stub becomes its own flow segment, driven by that block's API value:
  - `to_academic` uses `academic_rt`;
  - `to_evening` uses `evening_rt`;
  - `to_base` uses `base_rt`.
- **Idle pipes.** A small key in the 3D view reads: "Moving dots: water flowing this hour · Dim pipe: idle this hour".
- **Connectivity check.** The test hook exposes each segment's endpoints and the component boxes. An e2e test checks that every endpoint lies within 0.6 units of a component box or of another pipe's polyline.
- **Unchanged.** Flow drivers stay API values only. Particles show only when RT > 0. Existing segment keys and the hook fields keep their meaning; only new keys are added.

### B. Impact vs baseline
- **Config.** In `app/config.py`, add `GRID_EMISSION_KG_PER_KWH = 0.740` and `GRID_EMISSION_SOURCE = "Energy Commission (Suruhanjaya Tenaga), Grid Emission Factor, Peninsular Malaysia 2024 (provisional)"`, labelled ASSUMPTION.
- **Response.** `POST /recommend` gains an additive `impact` block, computed on the server from the comparison rows:
  - `vs_always_full`: `{kwh_saved, pct_saved, co2_kg_saved}`;
  - `vs_calendar_rule`: `{kwh_saved, pct_saved, co2_kg_saved}`;
  - `grid_kg_per_kwh`, `grid_source`, and `label` "SIMULATED".
  - "Saved" means baseline minus AI, so a negative value means the AI used more.
  - It is always about the AI recommendation, even when an operator override is active, because the card is the AI's.
  - `pct_saved` is null when the baseline energy is 0.
- **Card.** The recommendation card gains an "Impact on this day" block. Each line shows "X kWh less" or "X kWh more", with the % and "≈ Y kg CO₂ less/more". Below it go one line giving the grid factor and its source (ASSUMPTION), and one caveat line: single-day savings are overstated because cold left in the tank at 21:00 counts as spent, while over Oct–Dec the AI saves about 9 % against always fill. The caveat text is static; its numbers are the already-verified season figures. Every displayed number comes from `impact`.
- **Guide.** The guide, PDF and screenshots are updated to show the fixed pipes and the impact block.

## Non-goals
- No season-total CO₂ number computed in the browser.
- No gas or absorption-chiller emissions. They are the same in every strategy, so the difference is unaffected; the card says the figure covers electricity only.
- No change to plant physics or to `scs/`.
