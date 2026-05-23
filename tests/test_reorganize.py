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


def test_parse_reorganize_next_monday():
    """'next Monday' should target the following week's Monday."""
    ws = date(2025, 5, 19)  # current week Monday
    intent = parse_reorganize_instruction("move job_H04 to next Monday", ws)
    assert intent.job_id == "job_h04"
    assert intent.target_is_next_week is True
    assert intent.target_day == date(2025, 5, 26)  # next Monday


def test_parse_reorganize_next_week_thursday():
    """'next week Thursday' should target the following week's Thursday."""
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction(
        "reschedule job_H05 to next week Thursday", ws
    )
    assert intent.job_id == "job_h05"
    assert intent.target_is_next_week is True
    assert intent.target_day == date(2025, 5, 29)  # following Thursday


def test_parse_reorganize_next_week_no_day():
    """'next week' without a specific day targets the following Monday."""
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("push this job to next week", ws)
    assert intent.target_is_next_week is True
    assert intent.target_day == date(2025, 5, 26)  # next Monday


def test_parse_reorganize_7am_early_start():
    """'compress Thursday 7am' should extract start_time and target Thursday."""
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction(
        "compress job_H01 into Thursday 7am start", ws
    )
    assert intent.target_day == date(2025, 5, 22)  # Thursday
    assert intent.start_time == "07:00"


def test_parse_reorganize_early_start_keyword():
    """'early start' should set start_time to 07:00."""
    ws = date(2025, 5, 19)
    intent = parse_reorganize_instruction("early start Monday for job_G01", ws)
    assert intent.start_time == "07:00"
    assert intent.target_day == date(2025, 5, 19)  # Monday
