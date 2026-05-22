from app.scheduling_prefs import SchedulingMode, geo_cluster_target_cap, parse_mode, placement_score_bonus


def test_parse_mode_aliases():
    assert parse_mode("crew fill") == SchedulingMode.CREW_FILL
    assert parse_mode("location first") == SchedulingMode.GEO_FIRST
    assert parse_mode("balanced") == SchedulingMode.BALANCED


def test_placement_bonus_crew_fill_prefers_headroom():
    crew = placement_score_bonus(SchedulingMode.CREW_FILL, remaining_minutes=400, drive_km=5.0)
    geo = placement_score_bonus(SchedulingMode.GEO_FIRST, remaining_minutes=400, drive_km=5.0)
    assert crew > geo


def test_geo_cluster_cap():
    assert geo_cluster_target_cap(SchedulingMode.CREW_FILL, 10, 8) <= 5
    assert geo_cluster_target_cap(SchedulingMode.GEO_FIRST, 10, 8) == 8
