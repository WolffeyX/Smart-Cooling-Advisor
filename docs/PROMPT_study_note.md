# Prompt template: Smart Cooling Advisor study note (PDF)

Paste everything below the line into Claude Code, run from the repo root
(`smart-cooling-advisor/`). Edit the four settings first if you want something different.

```
SETTINGS
  AUDIENCE   = classmates and the lecturer, assumed to know nothing about district cooling,
               machine learning or this codebase
  LENGTH     = 12–15 A4 pages
  LANGUAGE   = English (keep technical terms such as Random Forest, RTh and kWh, and explain each one)
  OUTPUT     = docs/study_note/study_note.html  ->  docs/study_note.pdf
```

---

## ROLE
You are a patient technical writer and teacher. You are writing a manual-style study note for
readers who know nothing about this project, district cooling or machine learning. They should
finish it able to explain the problem, the solution and the Random Forest model in their own words,
run the app themselves, and find their way around every code file.

## GOAL
Produce one PDF note (`docs/study_note.pdf`, 12–15 A4 pages) that answers five questions, in this order:
1. What is the problem?
2. What is our solution?
3. How does the solution work? This includes a full technical explanation of Random Forest.
4. How do I operate the solution?
5. What does each code file in the repo do?

## GROUND RULES (non-negotiable)
- **Facts come from the repo, never from memory.** Before writing any section, read the files it
  describes. Take numbers only from the running app's API, the code, README.md,
  docs/user_guide.pdf, docs/Smart_Cooling_Advisor_findings.pdf or the test files. If a number
  can't be traced to one of those, leave it out.
- **Be honest about what is simulated.** Use the project's own labels everywhere they apply:
  SIMULATED (synthetic load, simulated forecasts, every energy number), MEASURED (2024 weather,
  classifier accuracy), ASSUMPTION (exam/break multipliers, block split, plant parameters,
  grid factor 0.740 kg CO₂/kWh) and PROPOSED (the advisor itself). Never claim real UTP plant
  data or real building facts.
- **Write for beginners.** Define every term the first time it appears and add it to the glossary.
  Give a plain-language explanation before any technical detail. Use short sentences, active voice
  and concrete examples from this project.
- **Do not change any code**, `scs/` included. This task only reads code and writes the note.

## SECTION-BY-SECTION CONTENT

### 0. Front matter (≈1 page)
- Title, subtitle, "SIMULATED prototype" badge, date.
- A one-paragraph summary of the whole project.
- "How to read this note": what each section is for.
- A glossary box, or a pointer to the glossary at the end.

### 1. What is the problem? (≈1.5 pages)
- What district cooling is. What a Gas District Cooling (GDC) plant does. The parts and their
  roles: absorption chillers driven by waste heat, electric chillers, the thermal-energy-storage
  (TES) tank, and the campus buildings.
- What RT, RTh and kWh mean, each with an everyday comparison.
- The nightly decision: how much cold to store tonight for tomorrow.
  - Overfilling the tank wastes electricity.
  - Underfilling it forces electric chillers to run at the expensive daytime peak.
- Why the decision is hard: tomorrow's cooling need depends on weather and on the kind of day
  (weekday, weekend, exam week, semester break).
- Include one simple diagram: a day-in-the-life timeline. Charge from 22:00 to 08:00, then
  discharge through the day.

### 2. What is our solution? (≈1 page)
- The Smart Cooling Advisor. Each evening it forecasts tomorrow's tank need, adds a safety margin,
  and proposes a charge target. The operator approves it or adjusts it, and the operator always
  decides.
- The main features, one line each:
  - the recommendation
  - the 2D and 3D plant views
  - the charts and the three-strategy comparison
  - "Impact on this day" (energy and CO₂)
  - "How the AI decided"
  - the decision log
- The headline results, labelled SIMULATED. Take them from the findings PDF and README: Oct–Dec
  electric-chiller energy for always-fill, the weekday/weekend rule, the AI and a perfect forecast,
  and the AI's ≈ −9 % against always-fill and ≈ −2 % against the rule. Also state the honest
  limits: the hot-weekday example where the rule wins, and the semester-break over-charge.

### 3. How does the solution work? (≈4–5 pages; the core of the note)

**3a. The data pipeline.** Show it as a diagram: real 2024 Seri Iskandar weather, then synthetic
campus load, then a daily table, then features, then the forecast, then a 24-hour plant
simulation, then the recommendation.

**3b. Random Forest, explained in layers.**
1. *Intuition.* Start from one decision tree, explained as a game of 20 questions. Show a tiny
   hand-drawn example: "is tomorrow a weekday?" then "is it hotter than 31 °C?".
2. *Why one tree is not enough.* Explain overfitting and variance in plain words.
3. *The forest.*
   - Bootstrap sampling: each tree sees a random resample of the training days.
   - Feature randomness at each split.
   - Averaging the trees' predictions, for regression.
   - Why averaging many noisy trees reduces error. Bias and variance in plain words, plus a small
     diagram.
4. *How a regression tree chooses a split.*
   - It minimises the variance of tank need (MSE) in the two child groups.
   - Show a small numeric worked example with 6 made-up days, clearly marked as an illustration.
5. *Our model's real settings.* Read these from `app/model.py` (`_rf`, `FEATURE_PROVENANCE`,
   `build_features`, `train_forecasters`):
   - number of trees, min_samples_leaf and random_state;
   - the 12 input features with plain-English meanings and where each comes from (observed lag,
     calendar, simulated day-ahead forecast);
   - the target: tomorrow's tank need in RTh.
6. *Honest testing.*
   - Training is Jan–Sep and testing is Oct–Dec, which the model never sees in training.
   - Jan–Sep forecasts use leave-one-month-out.
   - Explain the "no leakage" 22:00 decision window.
   - Explain why held-out error (MAE) is the fair score.
   - Quote the held-out MAE for the AI and for the rule from GET /explain.
7. *Reading the "How the AI decided" card.* Use a real day: call GET /explain for the default
   scenario's source date. Show:
   - the 12 inputs;
   - permutation importance versus built-in (impurity) importance, why they differ, and why month
     shows 0 by design;
   - the 400 trees' spread, whose mean equals the forecast;
   - one tree's first 5 splits.
   Include the screenshot docs/screenshots/rf_panel.png or the guide's g_rf_* crops.
8. *The step-1 heat-class classifier.* What it predicts, and its accuracy, labelled MEASURED.

**3c. From forecast to plan.**
- How the plant is simulated hour by hour. Read `app/plant.py` `dispatch_day`: the order in
  which absorption chillers, the tank and the electric chillers serve the load, the charge and
  discharge windows, and the limits.
- How the charge target is computed: forecast × (1 + error) × (1 + margin), capped at tank
  capacity.
- The three strategies compared, and the "Impact on this day" block: kWh and CO₂ against each
  baseline, with the one-day caveat.

### 4. How do I operate the solution? (≈2–3 pages)
- **Install and run.** Exact PowerShell commands taken from README.md: create the venv,
  `pip install -r requirements.txt`, then `python -m uvicorn app.main:app`, then open
  http://127.0.0.1:8000. Include the expected startup time and what to do if port 8000 is busy.
- **A guided tour.** Number the steps and give each one a screenshot:
  1. Pick a day type.
  2. Move the temperature, error, margin, capacity and level sliders.
  3. Read the recommendation.
  4. Read "Impact on this day".
  5. Scrub or Play through 24 hours.
  6. Switch to 3D: orbit, hover, and the idle key.
  7. Read the charts and the comparison table.
  8. Open "How the AI decided".
  9. Approve, or Adjust → Preview → Confirm.
  10. Read and download the decision log.
- **Three worked scenarios.** For each, show what to set, what you should see, and what it
  means. Get the values by actually calling the API:
  - hot weekday;
  - cool weekday;
  - semester break, including the over-charge warning.
- **Troubleshooting.** No WebGL, a 422 error, a slow first start, and how to run the tests.

### 5. What does each code file do? (≈3–4 pages)
Read each file before describing it. Cover every file below, using a table per folder with the
columns *File · What it does · Key functions/parts · Used by*. Add one short paragraph per folder
on its role in the system.
- **Repo root:** README.md, README_START_HERE.md, requirements.txt, pyproject.toml and .gitignore.
- **scs/ (the original code pack, read-only):** README.md, step1_model.py, step2_simulate.py,
  step3_sensitivity.py, step4_scenarios.py, step5_plant.py, step6_plant_sensitivity.py,
  step7_extra_cases.py and app.py, plus the scs/data/ files (described as a group). Say which
  steps our app reuses through app/legacy and which are reference only.
- **app/ (the backend):**
  - `__init__.py`, config.py, legacy/__init__.py, model.py, scenario.py and plant.py;
  - recommend.py, schemas.py, decisions.py, explain.py and main.py, including every API endpoint.
- **static/ (the web page):** index.html, styles.css, app.js, decisions.js, explain.js, plant3d.js
  and plant3d-scene.js. Describe the vendor/three/ folder in one line: the third-party Three.js
  r170 library, MIT licence, kept offline.
- **tests/:** one line per test file saying what it proves; group them into backend, API and
  browser (e2e) tests.
- **scripts/:** screenshots.py (including its `guide` mode) and build_guide_pdf.py.
- **docs/:** what each document is for (user guide, findings PDF, specs, plans, prompts).

End the section with one diagram showing how the files call each other for a single
`POST /recommend` request: browser → main.py → recommend.py → scenario.py / model.py / plant.py
→ response → app.js and the other front-end files.

### 6. Back matter (≈1 page)
- Known limitations, taken from the guide and the README.
- A full glossary, alphabetical, of every term introduced.
- "Where to look next": file paths for anyone who wants to go deeper.

## FORMAT AND BUILD
- Write `docs/study_note/study_note.html` as one self-contained HTML page with images alongside
  in `docs/study_note/img/`.
  - Use inline SVG for diagrams. Colour every chart and diagram from CSS tokens.
  - Style: A4 print layout with `@page { size: A4; margin: 14mm }`, body text 10–10.5 pt in print,
    numbered section headings, and boxed "Key idea" and "Watch out" callouts.
  - Use `break-inside: avoid` on figures, tables and callouts, and keep each heading with the
    content that follows it.
- Reuse existing screenshots from docs/screenshots/ and docs/guide/img/. To capture a new one, add
  a mode to scripts/screenshots.py rather than writing a throwaway script. Every figure must be
  readable when printed: labels at about 7 pt or larger.
- Build the PDF with Playwright Chromium (follow scripts/build_guide_pdf.py, or add
  `scripts/build_study_note_pdf.py`): `page.pdf(format="A4", print_background=True,
  prefer_css_page_size=True)`, emulating print media and a light colour scheme, after fonts and
  images have loaded.

## VERIFY BEFORE SAYING IT IS DONE
1. The PDF exists and has 12–15 pages. Count pages with the regex `/Type\s*/Page\b(?!s)` on the bytes.
2. Render every page to an image and look at each one. Check for:
   - no blank or near-empty pages, and no heading stranded at the bottom of a page;
   - no clipped or unreadable figures;
   - consistent numbering.
3. Cross-check every number in the note against its source (the API, code, README or findings
   PDF). List any you removed because they could not be traced.
4. Confirm every code file listed in section 5 is actually covered, and that no file is described
   that doesn't exist.
5. Report:
   - the PDF path and the page count;
   - a one-line summary per section;
   - the numbers you quoted with their sources;
   - anything you were unsure about.

Commit only `docs/study_note/`, `docs/study_note.pdf` and any script you added, and only if I ask.
Do not commit `app/package-lock.json` or `docs/Smart_Cooling_Advisor_findings.pdf`.
