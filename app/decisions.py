"""Operator decision log: one CSV row per Approve / confirmed Adjust (SIMULATED)."""

import csv
import threading
from datetime import datetime
from pathlib import Path

COLUMNS = [
    "timestamp",
    "action",
    "day_type",
    "forecast_max_temp_c",
    "safety_margin_pct",
    "tank_capacity_rth",
    "tank_level_22_rth",
    "forecast_error_pct",
    "source_date",
    "source_tmax_c",
    "ai_forecast_model_rth",
    "ai_forecast_need_rth",
    "actual_need_rth",
    "ai_target_rth",
    "operator_target_rth",
    "chosen_status",
    "chosen_shortfall_rth",
    "chosen_daytime_ec_hours",
    "chosen_ec_kwh",
    "ec_kwh_always_full",
    "ec_kwh_calendar_rule",
    "ec_kwh_ai_forecast",
    "label",
]

_INPUTS = [
    "day_type",
    "forecast_max_temp_c",
    "safety_margin_pct",
    "tank_capacity_rth",
    "tank_level_22_rth",
    "forecast_error_pct",
]


def _r(x):
    return round(x, 1) if isinstance(x, float) else x


def decision_row(action: str, req: dict, resp: dict, now: datetime) -> dict:
    """Build a log row from server-computed numbers only."""
    rec = resp["recommendation"]
    sc = resp["scenario"]
    by = {c["strategy"]: c for c in resp["comparison"]}
    ai = by["ai_forecast"]
    if action == "adjusted":
        op = resp["operator_plan"]
        chosen = {
            "operator_target_rth": op["charge_target_rth"],
            "chosen_status": op["status"],
            "chosen_shortfall_rth": op["shortfall_rth"],
            "chosen_daytime_ec_hours": op["daytime_ec_hours"],
            "chosen_ec_kwh": op["ec_energy_kwh"],
        }
    else:
        chosen = {
            "operator_target_rth": rec["charge_target_rth"],
            "chosen_status": rec["status"],
            "chosen_shortfall_rth": rec["shortfall_rth"],
            "chosen_daytime_ec_hours": rec["daytime_ec_hours"],
            "chosen_ec_kwh": ai["ec_energy_kwh"],
        }
    row = {
        "timestamp": now.isoformat(timespec="seconds"),
        "action": action,
        **{k: req[k] for k in _INPUTS},
        "source_date": sc["source_date"],
        "source_tmax_c": sc["source_tmax_c"],
        "ai_forecast_model_rth": rec["ai_forecast_model_rth"],
        "ai_forecast_need_rth": rec["ai_forecast_need_rth"],
        "actual_need_rth": rec["actual_need_rth"],
        "ai_target_rth": rec["charge_target_rth"],
        **chosen,
        "ec_kwh_always_full": by["always_full"]["ec_energy_kwh"],
        "ec_kwh_calendar_rule": by["calendar_rule"]["ec_energy_kwh"],
        "ec_kwh_ai_forecast": ai["ec_energy_kwh"],
        "label": "SIMULATED",
    }
    return {k: _r(row[k]) for k in COLUMNS}


class DecisionLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _header_ok(self) -> bool:
        with open(self.path, newline="", encoding="utf-8") as f:
            return next(csv.reader(f), None) == COLUMNS

    def _rotate(self) -> None:
        dest = self.path.with_suffix(".old.csv")
        n = 1
        while dest.exists():
            dest = self.path.with_suffix(f".old{n}.csv")
            n += 1
        self.path.replace(dest)

    def append(self, row: dict) -> dict:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and not self._header_ok():
                self._rotate()
            new = not self.path.exists()
            with open(self.path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
                if new:
                    w.writeheader()
                w.writerow(row)
        return row

    def rows(self) -> list[dict]:
        with self._lock:
            if not self.path.exists():
                return []
            with open(self.path, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))[::-1]
