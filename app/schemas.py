"""Pydantic request/response models for the API."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

DayType = Literal["weekday", "exam_week", "semester_break", "weekend"]


class RecommendRequest(BaseModel):
    day_type: DayType
    forecast_max_temp_c: float = Field(ge=24, le=38)
    safety_margin_pct: float = Field(default=10, ge=0, le=60)
    tank_capacity_rth: float = Field(default=10000, ge=5000, le=25000)
    tank_level_22_rth: float = Field(default=1500, ge=0)
    forecast_error_pct: float = Field(default=0, ge=-30, le=30)

    @model_validator(mode="after")
    def _level_within_capacity(self):
        if self.tank_level_22_rth > self.tank_capacity_rth:
            raise ValueError("tank_level_22_rth must be ≤ tank_capacity_rth")
        return self


class Scenario(BaseModel):
    source_date: str
    day_type: DayType
    source_tmax_c: float
    training_months: list[int]
    forecast_kind: str


class ElectricChillers(BaseModel):
    count: int
    start: str
    end: str


class Recommendation(BaseModel):
    charge_target_rth: float
    ai_forecast_need_rth: float
    ai_forecast_model_rth: float
    actual_need_rth: float
    capped: bool
    electric_chillers: ElectricChillers
    daytime_ec_hours: int
    shortfall_rth: float
    status: Literal["ok", "shortfall", "capped"]
    message: str


class HourRow(BaseModel):
    hour: str
    campus_load_rt: float
    sac_rt: float
    tank_out_rt: float
    ec_load_rt: float
    charge_rt: float
    ec_count: int
    ec_kw: float
    tank_level_rth: float
    unmet_rt: float


class ComparisonRow(BaseModel):
    strategy: Literal["always_full", "calendar_rule", "ai_forecast"]
    charge_target_rth: float
    ec_energy_kwh: float
    vs_always_full_pct: float | None
    daytime_ec_hours: int
    shortfall_rth: float
    tank_level_21_rth: float


class Plant(BaseModel):
    sac_available_rt: float
    n_ec: int
    ec_unit_rt: float
    tes_max_discharge_rt: float
    charge_window: str


class RecommendResponse(BaseModel):
    label: Literal["SIMULATED"]
    scenario: Scenario
    recommendation: Recommendation
    hourly: list[HourRow]
    comparison: list[ComparisonRow]
    plant: Plant
    assumptions: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    model_trained: bool
    label: Literal["SIMULATED"]
