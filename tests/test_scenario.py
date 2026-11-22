import pandas as pd
import pytest

from app import scenario


def test_prefers_oct_dec_within_1c(bank):
    d = scenario.select_day(bank, "weekday", 31.0)
    assert d.month >= 10 and d.dayofweek < 5 and abs(bank.daily.loc[d, "tmax"] - 31.0) <= 1.0


def test_34c_weekday_stays_in_oct_dec(bank):  # Oct-Dec max weekday is 33.2 C, within 1 C
    d = bank.daily[(bank.daily.index.month >= 10) & (bank.daily.index.dayofweek < 5)]
    assert scenario.select_day(bank, "weekday", 34.0) == pd.Timestamp(d["tmax"].idxmax())


def test_hot_weekday_falls_back_to_whole_year_with_lomo(bank, P):
    s = scenario.build_scenario(bank, "weekday", 34.5, P)
    assert pd.Timestamp(s.source_date).month <= 9
    assert pd.Timestamp(s.source_date).month not in s.training_months
    assert s.forecast_kind.startswith("leave-one-month-out")


def test_out_of_range_temps_report_real_tmax(bank, P):
    hi = scenario.build_scenario(bank, "weekday", 38.0, P)
    lo = scenario.build_scenario(bank, "weekday", 24.0, P)
    assert hi.source_tmax_c == 34.1 and lo.source_tmax_c == 25.7


def test_weekend_picks_weekend(bank):
    assert scenario.select_day(bank, "weekend", 30.0).dayofweek >= 5


def test_profile_is_22_to_21(bank, P):
    s = scenario.build_scenario(bank, "weekday", 31.0, P)
    D = pd.Timestamp(s.source_date)
    tot = bank.load.set_index("time")["total_rt"]
    assert s.load_rt[0] == pytest.approx(tot[D - pd.Timedelta(hours=2)])  # 22:00 D-1
    assert s.load_rt[23] == pytest.approx(tot[D + pd.Timedelta(hours=21)])  # 21:00 D
    assert len(s.load_rt) == 24 == len(s.t_out)


def test_multiplier_scales_room_part_only_and_forecast_unscaled(bank, P):
    wk = scenario.build_scenario(bank, "weekday", 31.0, P)
    br = scenario.build_scenario(bank, "semester_break", 31.0, P)
    assert br.source_date == wk.source_date
    assert br.ai_forecast_model_rth == wk.ai_forecast_model_rth
    assert br.calendar_need_rth == wk.calendar_need_rth
    assert br.actual_need_rth < 0.05 * wk.actual_need_rth
    assert br.load_rt[:10] == pytest.approx(wk.load_rt[:10])  # nights: base load only


def test_actual_need_matches_step5_daily_table_for_weekday(bank, P):
    s = scenario.build_scenario(bank, "weekday", 31.0, P)
    assert s.actual_need_rth == pytest.approx(bank.daily.loc[pd.Timestamp(s.source_date), "need_rth"])
