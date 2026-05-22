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
