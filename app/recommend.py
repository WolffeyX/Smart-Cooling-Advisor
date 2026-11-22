"""Assemble the POST /recommend response (three strategies, one scenario day)."""

import os

from app.config import (
    GRID_EMISSION_KG_PER_KWH,
    GRID_EMISSION_SOURCE,
    MULTIPLIER_LABEL,
    PRESET_LABELS,
)
from app.plant import HOUR_LABELS, HOURS, dispatch_day, summarise_day
from app.scenario import DayBank, build_scenario

_HOURLY_INT = {"ec_count"}
_SCENARIO_HOURLY = {"academic_rt", "evening_rt", "base_rt"}
_HOURLY_FIELDS = [
    "campus_load_rt",
    "sac_rt",
    "tank_out_rt",
    "ec_load_rt",
    "charge_rt",
    "ec_count",
    "ec_kw",
    "tank_level_rth",
    "unmet_rt",
    "academic_rt",
    "evening_rt",
    "base_rt",
]


def vs_always_full_pct(e: float, e_full: float) -> float | None:
    if e_full == 0:
        return None
    return round(100 * (e / e_full - 1), 1)


def impact_line(baseline_kwh: float, ai_kwh: float) -> dict:
    """Energy and CO2 saved by the AI against one baseline (negative = AI used more)."""
    saved = baseline_kwh - ai_kwh
    return {
        "kwh_saved": round(saved, 1),
        "pct_saved": None if baseline_kwh == 0 else round(100 * saved / baseline_kwh, 1),
        "co2_kg_saved": round(saved * GRID_EMISSION_KG_PER_KWH, 1),
    }


def _num(x: float, round_values: bool) -> float:
    return round(float(x), 1) if round_values else float(x)


def _over_charged(left_21: float, reached: float) -> bool:
    return left_21 > max(1000.0, 0.25 * reached)


def _message(
    status: str,
    cap: float,
    shortfall: float,
    capped: bool,
    daytime_ec_hours: int,
    target: float,
    reached: float,
    actual: float,
    left_21: float,
) -> str:
    n = daytime_ec_hours
    hours = f"{n} daytime hour{'s' if n != 1 else ''}"
    if status == "shortfall":
        msg = (
            f"Cooling shortfall of {shortfall:,.0f} RTh tomorrow even with all electric "
            "chillers running. "
        ) + ("The tank is already at capacity." if capped else "Raise the safety margin.")
    elif status == "capped":
        msg = f"Target capped at tank capacity ({cap:,.0f} RTh)" + (
            f"; electric chillers run {hours} tomorrow."
            if n > 0
            else "; the tank still covers tomorrow."
        )
    elif n > 0:
        msg = f"No cooling shortfall, but the tank runs out and electric chillers run {hours} tomorrow."
    else:
        msg = "Plan covers tomorrow with the chosen safety margin."
    if target - reached > 1:
        msg += f" Chillers can only charge the tank to {reached:,.0f} RTh by 08:00."
    if status != "shortfall" and _over_charged(left_21, reached):
        msg += (
            f" In this 2024 replay the day needed {actual:,.0f} RTh, so {left_21:,.0f} RTh "
            "is still unused in the tank at 21:00."
        )
    return msg


def _assumptions(sc, preset: str, levels: dict) -> list[str]:
    label = PRESET_LABELS.get(preset, "ASSUMPTION")
    months = ", ".join(str(m) for m in sc.training_months)
    return [
        (
            "SIMULATED: campus load is synthetic. It is the code pack's room model scaled to "
            "about 1,250 rooms plus a 350 RT base load, driven by real 2024 Seri Iskandar "
            "weather. The scale is calibrated on all of 2024, including the Oct–Dec test months."
        ),
        (
            "SIMULATED: the day-ahead weather forecast is the observed 2024 weather of that day "
            "plus random error (max temperature σ = 1 °C, solar ±15 %, rain ±50 %; dry days are "
            "known exactly). Real forecasts are worse; without it the model's Oct–Dec error "
            "rises from about 400 to about 550 RTh."
        ),
        (
            "ASSUMPTION: exam week (0.9) and semester break (0.35) are multipliers on the "
            f"room-driven load ({MULTIPLIER_LABEL}); they are not in the 2024 data."
        ),
        (
            "ASSUMPTION: the AI and the weekday/weekend rule treat exam weeks and semester "
            "breaks as normal weekdays, because the model has never seen one."
        ),
        f"Plant parameters: {preset} — {label}.",
        (
            f"The scenario replays a real 2024 day: {sc.source_date} (max {sc.source_tmax_c} °C); "
            f"AI forecast {sc.forecast_kind}, trained on months {months}. Jan–Sep forecasts are "
            "leave-one-month-out: out-of-sample by month, not a true forward forecast."
        ),
        (
            "Single-day comparison (SIMULATED): cold still in the tank at 21:00 is counted as "
            "spent, so strategies that charge more end the day with more stored (always fill "
            f"{levels['always_full']:,.0f} RTh, rule {levels['calendar_rule']:,.0f} RTh, "
            f"AI {levels['ai_forecast']:,.0f} RTh) and the % overstates the AI's saving. "
            "Over Oct–Dec the year-long simulation (code-pack step5 forecaster) gives the AI "
            "about −9 % vs always fill and about −2 % vs the weekday/weekend rule."
        ),
        ("ASSUMPTION: one year of weather only (2024); no measured UTP/PMMD plant data."),
        (
            "ASSUMPTION: the three campus blocks split the synthetic load by hour — Academic = "
            "room load 08:00–17:59, Library & evening classes = room load 18:00–21:59, Data "
            f"centre & labs = the 24/7 base load. About {sc.room_equivalents:,} reference 60 m² "
            "room-equivalents (SIMULATED); not real UTP buildings."
        ),
    ]


def build_response(bank: DayBank, req: dict, base_params: dict, round_values: bool = True) -> dict:
    cap = float(req["tank_capacity_rth"])
    mg = float(req["safety_margin_pct"]) / 100.0
    err = float(req["forecast_error_pct"])
    level0 = float(req["tank_level_22_rth"])
    p = {**base_params, "tes_capacity_rth": cap}

    sc = build_scenario(bank, req["day_type"], float(req["forecast_max_temp_c"]), p)
    ai_used = sc.ai_forecast_model_rth * (1 + err / 100.0)
    ai_target = min(cap, ai_used * (1 + mg))
    targets = {
        "always_full": cap,
        "calendar_rule": min(cap, sc.calendar_need_rth * (1 + mg)),
        "ai_forecast": ai_target,
    }
    runs = {
        name: dispatch_day(sc.load_rt, sc.t_out, HOURS, level0, tgt, p)
        for name, tgt in targets.items()
    }
    sums = {name: summarise_day(r) for name, r in runs.items()}
    e_full = sums["always_full"]["ec_energy_kwh"]

    def n(x):
        return _num(x, round_values)

    comparison = []
    for name, target in targets.items():
        s = sums[name]
        comparison.append(
            {
                "strategy": name,
                "charge_target_rth": n(target),
                "ec_energy_kwh": n(s["ec_energy_kwh"]),
                "vs_always_full_pct": None
                if name == "always_full"
                else vs_always_full_pct(s["ec_energy_kwh"], e_full),
                "daytime_ec_hours": s["daytime_ec_hours"],
                "shortfall_rth": n(s["shortfall_rth"]),
                "tank_level_21_rth": n(runs[name]["tank_level_rth"][-1]),
            }
        )

    # same 1 dp numbers as the comparison rows; always about the AI plan, never the override
    e_ai = round(sums["ai_forecast"]["ec_energy_kwh"], 1)
    impact = {
        "vs_always_full": impact_line(round(e_full, 1), e_ai),
        "vs_calendar_rule": impact_line(round(sums["calendar_rule"]["ec_energy_kwh"], 1), e_ai),
        "grid_kg_per_kwh": GRID_EMISSION_KG_PER_KWH,
        "grid_source": GRID_EMISSION_SOURCE,
        "label": "SIMULATED",
    }

    ai_run, ai_sum = runs["ai_forecast"], sums["ai_forecast"]
    capped = bool(ai_used * (1 + mg) > cap)
    shortfall = ai_sum["shortfall_rth"]
    status = "shortfall" if shortfall > 1e-6 else "capped" if capped else "ok"
    reached = float(ai_run["tank_level_rth"][9])
    left_21 = float(ai_run["tank_level_rth"][-1])
    over_charged = status != "shortfall" and _over_charged(left_21, reached)

    operator_plan = None
    hourly_run = ai_run
    override = req.get("charge_target_override_rth")
    if override is not None:
        op_target = min(cap, float(override))
        hourly_run = dispatch_day(sc.load_rt, sc.t_out, HOURS, level0, op_target, p)
        op_sum = summarise_day(hourly_run)
        op_short = op_sum["shortfall_rth"]
        op_status = "shortfall" if op_short > 1e-6 else "ok"
        op_reached = float(hourly_run["tank_level_rth"][9])
        op_left_21 = float(hourly_run["tank_level_rth"][-1])
        operator_plan = {
            "charge_target_rth": n(op_target),
            "ec_energy_kwh": n(op_sum["ec_energy_kwh"]),
            "vs_always_full_pct": vs_always_full_pct(op_sum["ec_energy_kwh"], e_full),
            "daytime_ec_hours": op_sum["daytime_ec_hours"],
            "shortfall_rth": n(op_short),
            "tank_level_21_rth": n(op_left_21),
            "status": op_status,
            "over_charged": bool(
                op_status != "shortfall" and _over_charged(op_left_21, op_reached)
            ),
            "message": _message(
                op_status,
                cap,
                op_short,
                False,
                op_sum["daytime_ec_hours"],
                op_target,
                op_reached,
                sc.actual_need_rth,
                op_left_21,
            ),
        }

    hourly = []
    for i, label in enumerate(HOUR_LABELS):
        row = {"hour": label}
        for k in _HOURLY_FIELDS:
            if k in _SCENARIO_HOURLY:
                row[k] = n(getattr(sc, k)[i])
            else:
                row[k] = int(hourly_run[k][i]) if k in _HOURLY_INT else n(hourly_run[k][i])
        hourly.append(row)

    preset = os.environ.get("SCA_PARAMS_PRESET", "default")
    return {
        "label": "SIMULATED",
        "scenario": {
            "source_date": sc.source_date,
            "day_type": sc.day_type,
            "source_tmax_c": sc.source_tmax_c,
            "training_months": [int(m) for m in sc.training_months],
            "forecast_kind": sc.forecast_kind,
        },
        "recommendation": {
            "charge_target_rth": n(ai_target),
            "ai_forecast_need_rth": n(ai_used),
            "ai_forecast_model_rth": n(sc.ai_forecast_model_rth),
            "actual_need_rth": n(sc.actual_need_rth),
            "capped": capped,
            "electric_chillers": ai_sum["chillers"],
            "daytime_ec_hours": ai_sum["daytime_ec_hours"],
            "shortfall_rth": n(shortfall),
            "status": status,
            "over_charged": bool(over_charged),
            "message": _message(
                status,
                cap,
                shortfall,
                capped,
                ai_sum["daytime_ec_hours"],
                ai_target,
                reached,
                sc.actual_need_rth,
                left_21,
            ),
        },
        "hourly": hourly,
        "comparison": comparison,
        "plant": {
            "sac_available_rt": n(p["sac_available_rt"]),
            "n_ec": int(p["n_ec"]),
            "ec_unit_rt": n(p["ec_unit_rt"]),
            "tes_max_discharge_rt": n(p["tes_max_discharge_rt"]),
            "charge_window": "22:00-08:00",
            "room_equivalents": int(sc.room_equivalents),
            "tank_capacity_rth": cap,
        },
        "assumptions": _assumptions(
            sc, preset, {k: float(r["tank_level_rth"][-1]) for k, r in runs.items()}
        ),
        "operator_plan": operator_plan,
        "impact": impact,
    }
