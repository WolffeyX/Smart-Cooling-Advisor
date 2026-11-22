"""Paths, plant parameter presets and day-type multipliers.

The default preset is written out literally (same keys and values as
scs/step5_plant.py PLANT); it is never read from the legacy module, so the
legacy code can change without silently changing the API defaults.
"""

import copy
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SCS_DIR = ROOT_DIR / "scs"
WEATHER_CSV = SCS_DIR / "data" / "seri_iskandar_2024_openmeteo.csv"
PLANT_RESULTS_CSV = SCS_DIR / "data" / "plant_results.csv"
DATA_DIR = ROOT_DIR / "data"

_DEFAULT_PLANT = {
    "sac_available_rt": 2200.0,
    "ec_unit_rt": 325.0,
    "n_ec": 4,
    "tes_capacity_rth": 10000.0,
    "tes_max_discharge_rt": 2500.0,
    "charge_eff": 0.95,
    "standby_loss_per_h": 0.004,
    "night_hours": list(range(22, 24)) + list(range(8)),
    "kw_per_rt_full": 0.60,
    "kw_per_rt_aux": 0.15,
    "plr_penalty": 0.8,
    "temp_coeff": 0.015,
    "base_load_rt": 350.0,
    "target_peak_rt": 3300.0,
    "evening_factor": 0.3,
    "margin": 0.10,
    "noise_daily": 0.0,
    "noise_hourly": 0.0,
}

PRESETS: dict[str, dict] = {
    "default": _DEFAULT_PLANT,
    "published_utp_data": {
        **_DEFAULT_PLANT,
        "standby_loss_per_h": 0.0005,
        "kw_per_rt_full": 0.82,
        "kw_per_rt_aux": 0.24,
        "sac_available_rt": 1800.0,
    },
}

PRESET_LABELS = {
    "default": "code pack values (SIMULATED)",
    "published_utp_data": "ASSUMPTION",
}

DAY_TYPE_MULTIPLIERS = {
    "weekday": 1.0,
    "weekend": 1.0,
    "exam_week": 0.9,
    "semester_break": 0.35,
}
MULTIPLIER_LABEL = "ASSUMPTION"


def get_params(preset: str | None = None) -> dict:
    """Return a fresh deep copy of the named preset's plant parameters.

    preset=None uses env SCA_PARAMS_PRESET, falling back to "default".
    """
    if preset is None:
        preset = os.environ.get("SCA_PARAMS_PRESET", "default")
    if preset not in PRESETS:
        raise ValueError(f"unknown params preset: {preset!r}")
    return copy.deepcopy(PRESETS[preset])


# ASSUMPTION: grid emission factor used for the CO2 figures (electricity only).
GRID_EMISSION_KG_PER_KWH = 0.740
GRID_EMISSION_SOURCE = (
    "Energy Commission (Suruhanjaya Tenaga), Grid Emission Factor, "
    "Peninsular Malaysia 2024 (provisional)"
)
