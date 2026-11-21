# GOAL
Turn the APPROVED "Smart Cooling Advisor" sketch (attached PDF: page 1 operator dashboard,
page 2 phone alert) into the production frontend. Keep the approved layout, hierarchy and
wording; improve only consistency, states and accessibility. Plain HTML + CSS + JavaScript +
inline SVG, no build step, no framework, no external network calls except POST /recommend
and GET /health on the same origin. Every value comes from the /recommend response; nothing
is hard-coded except labels. All numbers are SIMULATED and the UI must say so.

If you are Claude Code: use superpowers:brainstorming only for questions this spec leaves
open, then superpowers:writing-plans, wait for my approval, then build with
superpowers:test-driven-development (Playwright tests for states and interactions) and
finish with superpowers:verification-before-completion (screenshots + axe-core report).
If you are a design tool: produce the screens and states below at 1440x900 and 390x844.

# DATA CONTRACT (POST /recommend)
Request: day_type ("weekday" | "exam_week" | "semester_break" | "weekend"),
forecast_max_temp_c (24-38), safety_margin_pct (0-60), tank_capacity_rth (5000-25000),
tank_level_22_rth (0-capacity), forecast_error_pct (-30 to 30).
Response fields used below: label; scenario.{source_date, day_type, source_tmax_c};
recommendation.{charge_target_rth, ai_forecast_need_rth, actual_need_rth, capped,
electric_chillers.{count,start,end}, daytime_ec_hours, shortfall_rth, status, message};
hourly[24].{hour, campus_load_rt, sac_rt, tank_out_rt, ec_load_rt, charge_rt, ec_count,
ec_kw, tank_level_rth, unmet_rt}; comparison[3].{strategy, charge_target_rth, ec_energy_kwh,
vs_always_full_pct, daytime_ec_hours, shortfall_rth}; plant.{sac_available_rt, n_ec,
ec_unit_rt, tes_max_discharge_rt, charge_window}; assumptions[].
Number format: thousands separator, RTh and RT with 0 decimals, kWh 0 decimals, % 1 decimal
with a true minus sign (−). Times are 24 h "HH:00".

# SCREEN 1: OPERATOR DASHBOARD (desktop, 12-column grid, 1440 px reference)
## 1.1 Header (full width)
- H1 "Smart Cooling Advisor".
- Subtitle "UTP Gas District Cooling · tonight's tank-charging plan · {scenario.source_date
  as 'Tue 15 Oct 2024'}, 21:30".
- Badge A (amber): "SIMULATED prototype · illustrative numbers" (from label).
- Badge B (teal): "Model: random forest, day-ahead".

## 1.2 Left card "Test new values" (3 columns)
- "Tomorrow is a…" segmented control, radio semantics: Weekday, Exam week, Semester break,
  Weekend -> day_type. Arrow keys move between options.
- Sliders, each with a visible label, live value with unit, min/max, step:
  Forecast max temperature 24-38 °C step 0.5 -> forecast_max_temp_c;
  "AI forecast error (what if it's wrong?)" −30 to +30 % step 5 -> forecast_error_pct;
  Safety margin 0-60 % step 5 -> safety_margin_pct;
  Tank usable capacity 5,000-25,000 RTh step 500 -> tank_capacity_rth;
  Tank level at 22:00 0-capacity RTh step 100 -> tank_level_22_rth (max follows capacity;
  clamp the value when capacity drops).
- Grey note from plant: "Fixed plant: 2 × 1,250 RT absorption chillers (≈{sac_available_rt}
  RT available), {n_ec} × {ec_unit_rt} RT electric chillers, overnight charging
  {charge_window}."
- Interaction: any change -> debounce 300 ms -> request. Keep the last good result on screen
  while loading.

## 1.3 Centre "3D plant view" (6 columns, dark panel)
- Title "3D plant view · {selected hour} {tonight|tomorrow}"; caption: one phrase for the
  hour's mode: "Night: charging the tank" if charge_rt > 0, "Day: tank is covering the peak"
  if tank_out_rt > 0, "Day: absorption chillers only", or "Electric chillers covering the
  gap" if ec_load_rt > 0 in the daytime.
- Isometric SVG: 2 absorption chiller blocks (teal), 4 electric chiller blocks (grey when
  off, amber + soft glow when the first ec_count units are on), storage tank (cylinder; water
  fill height = tank_level_rth / tank_capacity_rth, animated 300 ms), campus buildings, a
  dashed flow line that animates direction: plant -> tank when charging, tank -> campus when
  discharging. SVG has role="img" and a <title>/<desc> that states the hour's numbers in text.
- Buttons top right: "Play 24 h" (toggles to "Pause"), "Reset" (selected hour back to 12:00
  tomorrow, stops playback).
- Time scrubber: range input 0-23 labelled "Time scrubber: tonight 22:00 → tomorrow 21:00",
  value text "12:00 tomorrow". Play advances 1 hour every 700 ms and stops at 21:00. Arrow
  keys step by 1 hour, Home/End jump. Respect prefers-reduced-motion (no glow pulse, no flow
  animation, Play steps without tweening).
- Four stat tiles for the selected hour: Campus load {campus_load_rt} RT; Absorption chillers
  {sac_rt} RT; Tank in / out {charge_rt×0.95 as +x or −tank_out_rt} RT; Electric chillers
  {ec_count} on or "all off".

## 1.4 Right card "Tonight's recommendation" (3 columns)
- Hero block (teal): "Charge the tank to" {charge_target_rth} RTh; "Run {count} electric
  chillers from {start} to {end}".
- Rows: "AI forecast of tomorrow's tank need" {ai_forecast_need_rth}; "What tomorrow actually
  needs" {actual_need_rth}; "Electric chillers in daytime" {daytime_ec_hours} h or "none";
  "Cooling shortfall" {shortfall_rth} RTh or "none".
- Status note from recommendation.status/message (see STATES).
- Buttons: "Approve plan" (primary) and "Adjust manually" (secondary). In this prototype
  both open a non-blocking toast: "Demo only. Nothing is sent to the plant."
- Footnote: "The operator always decides. The advisor only suggests the charge amount."

## 1.5 Chart "Who supplies the cold, hour by hour" (8 columns)
- 24 stacked bars, x = hour (22 … 21), y = RT. Segments bottom to top: Absorption chillers
  (sac_rt), Tank (tank_out_rt), Electric chillers (ec_load_rt), Charging tank (charge_rt);
  unmet_rt as a red hatched cap if > 0. Legend with the same order. Selected hour has a 2 px
  outline; clicking a bar sets the scrubber. Hover/focus tooltip lists all four values.
  Caption ends "· SIMULATED".

## 1.6 Chart "Tank level over the next 24 h" (4 columns)
- 24 bars (or area) of tank_level_rth with a dashed capacity line; selected hour highlighted.
- Caption: "Fills overnight (22:00–08:00), drains through the day. Ending near empty at 18:00
  with no daytime electric chillers is the ideal."

## 1.7 Table "Same day, three ways to decide the charge" (full width)
- Native <table> with <caption>. Columns: Strategy | Charge tonight (RTh) | Electric-chiller
  energy (kWh) | vs always full | Daytime chiller hours | Shortfall. Rows in response order:
  "Always fill the tank", "Weekday/weekend rule", "AI forecast" (AI row tinted). "—" for
  vs_always_full_pct null. Right-align numbers.
- Header note right: "Electric-chiller energy for this 24 h · SIMULATED".
- Footnote: "In our 2024 simulation the AI beat the weekday/weekend rule by about 1–2% of
  electric-chiller energy in cooler months and by ~0% in hot months. Try a hot weekday (34
  °C+) to see why: with a 10,000 RTh tank, every strategy fills it completely."
- Below, a collapsible "Assumptions" list from assumptions[].

# SCREEN 2: PHONE ALERT (390 px wide, mobile)
- Lock-screen style: time "21:30", date from scenario.
- Notification card: app name "SMART COOLING ADVISOR", "now", title "Tonight's tank plan is
  ready", body "Charge to {charge_target_rth} RTh. Run {count} electric chillers
  {start}–{end}. Tomorrow: {day_type}, forecast max {forecast_max_temp_c} °C."
- "Plan details" 2×2 tiles: AI forecast need; Safety margin; Tank now (tank_level_22_rth);
  vs fill to full (AI row vs_always_full_pct).
- Disclaimer "Illustrative numbers from our simulation, not live UTP data."
- Buttons "Approve plan" and "Open dashboard" (navigates to Screen 1 with the same inputs in
  the URL query).
- IMPORTANT: the approved sketch shows different numbers on the alert (7,800 RTh, 22:00–06:00)
  and the dashboard (8,364 RTh, 22:00–08:00). Both screens must render from ONE response so
  they always match.
- Deliver as /alert.html (same JS module), with responsive layout, not a native app.

# STATES (implement and test every one)
- Initial loading: skeleton blocks in every card, the plant view shows an empty tank, buttons
  disabled, aria-busy="true" on main.
- Updating: keep the last result, show a thin progress bar at the top, aria-live="polite"
  announces "Plan updated" when done.
- Success / ok: green note "Plan covers tomorrow with the chosen safety margin."
- Shortfall warning (shortfall_rth > 0 or status "shortfall"): red note with icon + text
  "Cooling shortfall of {shortfall_rth} RTh tomorrow. Raise the safety margin or plan daytime
  electric chillers." Red cap on affected bars. Never colour alone: icon + words.
- Tank-capped warning (capped true): amber note "Target capped at tank capacity
  ({tank_capacity_rth} RTh). Tomorrow needs more than the tank can hold; daytime electric
  chillers are expected." Show a "capped" chip on the hero.
- Both warnings can show together (shortfall first).
- Daytime electric chillers > 0 with no shortfall: neutral info note "{daytime_ec_hours} h of
  daytime electric chillers expected."
- API error / offline: banner "Can't reach the advisor service. Showing the last plan." with
  a Retry button; inputs stay usable.
- Validation: sliders cannot leave their ranges; if the API returns 422 show the field message
  next to the control.
- Empty tank/zero need edge: show "0 RTh" not blank; Play still works.

# ACCESSIBILITY (WCAG 2.2 AA)
- Every control has a visible <label> bound by for/id; sliders expose aria-valuetext with
  units ("31 degrees Celsius", "10 percent", "1,500 RTh").
- Touch targets at least 44 × 44 px (segmented buttons, slider thumbs via padding, Play,
  Reset, Approve, Adjust, table toggles, phone buttons).
- Contrast: text ≥ 4.5:1, large text and chart marks/UI boundaries ≥ 3:1, including text on
  the dark plant panel and on the teal hero. Do not rely on colour alone: chart segments get
  patterns or direct labels in the tooltip; warnings use icon + text.
- Full keyboard path in visual order; visible focus ring (2 px, 3:1); Space toggles
  Play/Pause; Escape closes toasts.
- Landmarks: header, main, aside (recommendation), footer; one H1, logical H2s per card.
- Charts: each SVG has role="img", <title>, <desc>, plus a visually hidden data table or
  "View data" toggle with the 24 hourly values.
- aria-live="polite" region for plan updates and warnings (assertive only for shortfall).
- prefers-reduced-motion and prefers-color-scheme supported; layout reflows at 320 px without
  horizontal scroll (cards stack: inputs, recommendation, plant, charts, table).
- Language attribute "en"; numbers formatted with Intl.NumberFormat("en-MY").

# VISUAL TOKENS (match the sketch)
Background #F4F5F8, cards white with 12 px radius and 1 px #E3E6EB border; plant panel
#0F1B2D; teal #0E6F6A (absorption, primary buttons, hero); tank blue #2F80ED; electric
chillers amber #D98E04; charging grey #B8C2CC; danger #C0392B; success bg #E6F4EA. Font:
Inter or system-ui; H1 28/34 semibold, card titles 16/22 semibold, body 14/20, hero number
36/40 bold. Verify all pairs against the contrast rules above and adjust shades if any fail.

# ACCEPTANCE CHECKS
- Playwright: each state above reachable and screenshotted (desktop and 390 px): ok,
  shortfall, capped, both warnings, loading, API error.
- Play runs 22:00→21:00 and stops; scrubber, bars and tiles stay in sync; Reset works.
- axe-core: zero serious/critical violations on both screens.
- Dashboard and alert show identical charge target and chiller plan for the same inputs.
- "SIMULATED" visible in header, chart captions, table note and alert disclaimer.
