from datetime import date

from app.reorganize import parse_reorganize_instruction
from app.scheduling_prefs import SchedulingMode


def test_parse_reorganize_crew_fill():
    ws = date(2025, 5, 19)  # Monday
    intent = parse_reorganize_instruction("Please reorganize and fill up the crews", ws)
    assert intent.scheduling_mode == SchedulingMode.CREW_FILL
    assert intent.job_id is None


def test_parse_reorganize_job_and_day():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction(
        "minimize drive for job_003 on Thursday", ws
    )
    assert intent.scheduling_mode == SchedulingMode.GEO_FIRST
    assert intent.job_id == "job_003"
    assert intent.target_day == date(2025, 5, 22)


# Bug 4 — emergency keyword detection
def test_parse_reorganize_urgent_keyword_sets_crew_fill():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("URGENT — water damage risk, need crew TODAY", ws)
    assert intent.scheduling_mode == SchedulingMode.CREW_FILL


def test_parse_reorganize_emergency_keyword():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("Emergency! flooding at the site", ws)
    assert intent.scheduling_mode == SchedulingMode.CREW_FILL


def test_parse_reorganize_emergency_targets_earliest_slot():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("URGENT water damage for job_007", ws)
    assert intent.scheduling_mode == SchedulingMode.CREW_FILL
    # Emergency jobs should target the earliest available day (week_start)
    assert intent.target_day == ws


def test_parse_reorganize_normal_instruction_not_emergency():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("Please balance the workload this week", ws)
    assert intent.scheduling_mode == SchedulingMode.BALANCED
    assert intent.target_day is None


def test_parse_reorganize_level_out_load():
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction(
        "Level this out — Alpha is overloaded Tuesday while Delta sits idle", ws
    )
    assert intent.scheduling_mode == SchedulingMode.BALANCED
