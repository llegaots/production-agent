from datetime import date, timedelta

from app.scheduling_prefs import (
    SchedulingMode,
    balance_day_bonus,
    geo_cluster_target_cap,
    parse_mode,
    placement_score_bonus,
    week_fill_bonus,
)


def test_parse_mode_aliases():
    assert parse_mode("crew fill") == SchedulingMode.CREW_FILL
    assert parse_mode("location first") == SchedulingMode.GEO_FIRST
    assert parse_mode("balanced") == SchedulingMode.BALANCED


def test_week_fill_bonus_prefers_monday_over_friday():
    ws = date(2026, 7, 6)  # Monday
    mon = week_fill_bonus(ws, ws)
    wed = week_fill_bonus(ws, ws + timedelta(days=2))
    fri = week_fill_bonus(ws, ws + timedelta(days=4))
    assert mon > wed > fri
    assert fri == 0.0


def test_week_fill_bonus_zero_outside_planning_window():
    ws = date(2026, 7, 6)
    assert week_fill_bonus(ws, ws + timedelta(days=5)) == 0.0
    assert week_fill_bonus(ws, ws - timedelta(days=1)) == 0.0


def test_week_fill_bonus_respects_pinned_balance_day():
    ws = date(2026, 7, 6)
    wed = date(2026, 7, 8)
    assert week_fill_bonus(ws, ws, balance_day=wed) == 0.0
    assert week_fill_bonus(ws, wed, balance_day=wed) > week_fill_bonus(ws, ws + timedelta(days=4), balance_day=wed)


def test_balance_day_bonus():
    wed = date(2026, 7, 8)
    assert balance_day_bonus(wed, wed) > balance_day_bonus(wed, date(2026, 7, 6))


def test_placement_bonus_crew_fill_prefers_headroom():
    crew = placement_score_bonus(SchedulingMode.CREW_FILL, remaining_minutes=400, drive_km=5.0)
    geo = placement_score_bonus(SchedulingMode.GEO_FIRST, remaining_minutes=400, drive_km=5.0)
    assert crew > geo


def test_geo_cluster_cap():
    assert geo_cluster_target_cap(SchedulingMode.CREW_FILL, 10, 8) <= 5
    assert geo_cluster_target_cap(SchedulingMode.GEO_FIRST, 10, 8) == 8
