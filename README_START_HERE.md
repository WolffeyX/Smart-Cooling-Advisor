# Smart Cooling Advisor - start folder for Claude Code

1. Unzip this folder somewhere simple, e.g. C:\dev\smart-cooling-advisor or ~/dev/smart-cooling-advisor
2. Open a terminal in it and run:  git init && git add . && git commit -m "Start: code pack + sketch"
3. Start Claude Code in this folder:  claude
4. Paste the whole of docs/PROMPT_mvp.md as your first message.
5. After the MVP works, paste docs/PROMPT_ui.md in a new session in the same folder.

Contents
- scs/                      original code pack (step1-6, app.py, data/) with step6 bug FIXED
- scs/data/plant_sensitivity.csv              corrected sensitivity results
- scs/data/plant_extra_cases_tank20k_margin40.csv  20,000 RTh tank and 40% margin cases
- scs/step7_extra_cases.py  script that produced the extra cases
- Smart_Cooling_Advisor_plant_dashboard_sketch.pdf   approved UI sketch
- docs/PROMPT_mvp.md        Task 4 prompt
- docs/PROMPT_ui.md         Task 5 prompt
All energy numbers are SIMULATED.
