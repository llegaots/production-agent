import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.qa_ai.runner import AIQATeamRunner
from app.qa_ai.schedule_snapshot import format_schedule_markdown
from app.seed import seed


def test_format_schedule_markdown():
    ctx = {
        "week_start": "2026-07-06",
        "crew_days": [
            {
                "crew_id": "crew_alpha",
                "crew_name": "Alpha",
                "day": "2026-07-07",
                "weekday": "Tuesday",
                "utilization": 0.75,
                "total_drive_minutes": 20,
                "stops": [
                    {
                        "order": 1,
                        "job_id": "qa_job_001",
                        "address": "100 Lakeshore, Pointe-Claire QC",
                        "start_time": "08:00",
                        "travel_minutes_before": 0,
                    }
                ],
            }
        ],
        "unscheduled_jobs": [],
        "metrics": {"scheduled_stops": 1, "unscheduled_count": 0, "overbooked_days": 0},
    }
    md = format_schedule_markdown(ctx)
    assert "qa_job_001" in md
    assert "Alpha" in md
    assert "Tuesday" in md


def test_ai_qa_reflective_loop(monkeypatch):
    monkeypatch.setenv("QA_MIN_TEST_JOBS", "1")
    seed(reset=True)
    uid = uuid.uuid4().hex[:8]

    case_a = {
        "fingerprint": f"test_rain_delay_{uid}",
        "title": "Rain delay cluster",
        "persona_story": "Owner after storm",
        "test_jobs": [
            {
                "id": "job_001",
                "service_type": "window_cleaning",
                "address": "100 Lakeshore, Pointe-Claire QC",
                "estimated_minutes": 90,
                "required_skills": ["ladder_cert"],
                "required_equipment": ["ladder_28"],
                "earliest_date": "2026-07-08",
                "latest_date": "2026-07-08",
                "price": 200,
            }
        ],
        "steps": [{"action": "plan", "scheduling_mode": "geo_first"}],
        "what_good_looks_like": "Jobs regrouped by zone",
    }
    case_b = {
        "fingerprint": f"test_fill_trucks_{uid}",
        "title": "Fill trucks",
        "persona_story": "Slow Monday",
        "test_jobs": [
            {
                "id": "job_001",
                "service_type": "gutter_cleaning",
                "address": "50 Elm, Beaconsfield QC",
                "estimated_minutes": 120,
                "required_skills": ["ladder_cert"],
                "required_equipment": ["ladder_32"],
                "earliest_date": "2026-07-07",
                "latest_date": "2026-07-07",
                "price": 300,
            }
        ],
        "steps": [{"action": "reorganize", "instruction": "fill crew days"}],
        "what_good_looks_like": "Higher utilization",
    }

    critiques = [
        {
            "verdict": "retry",
            "viability_score": 55,
            "executive_summary": "Thursday route crosses zones.",
            "placement_critiques": [
                {
                    "job_id": "qa_job_001",
                    "scheduled_day": "2025-05-22",
                    "crew_id": "crew_alpha",
                    "question": "Why send Alpha to Dorval after Pierrefonds?",
                    "severity": "high",
                    "better_alternative": "Pair with job_002 same day",
                }
            ],
            "owner_retry": {"action": "reorganize", "instruction_or_mode": "minimize drive"},
            "code_changes_for_engineers": [],
        },
        {
            "verdict": "pass",
            "viability_score": 88,
            "executive_summary": "Would run this week.",
            "placement_critiques": [],
            "code_changes_for_engineers": [],
        },
        {
            "verdict": "pass",
            "viability_score": 90,
            "executive_summary": "Crew fill looks runnable.",
            "placement_critiques": [],
            "code_changes_for_engineers": [],
        },
    ]

    async def _fake_geocode(address: str):
        from app.geocode import GeocodeResult

        return GeocodeResult(
            input_address=address,
            success=True,
            lat=45.3838,
            lng=-73.8825,
            formatted_address=address,
            confidence=0.92,
            needs_review=False,
            in_service_area=True,
            location_type="ROOFTOP",
            postal_code="J7V 8P4",
            province="QC",
            source="google",
        )

    monkeypatch.setattr("app.agents.geo_cluster.geocoder.geocode", _fake_geocode)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    design_cases = [case_a, case_b]
    critique_iter = iter(critiques)

    async def _design(**_kwargs):
        if design_cases:
            return design_cases.pop(0)
        return None

    async def _critique(**_kwargs):
        return next(critique_iter, critiques[-1])

    async def _synth(**_kwargs):
        return {
            "overall_assessment": "Routing needs geo tightening.",
            "top_bugs": ["Cross-zone day routes"],
            "recommended_cursor_tasks": ["Improve geo_cluster cap in crew_fill mode"],
            "cases_still_failing": [],
        }

    async def _noop_handoff(**_kwargs):
        from app.cursor_client import CursorLaunchResult

        return CursorLaunchResult(launched=False, skipped_reason="test")

    with patch("app.qa_ai.runner.load_succeeded_cases", return_value=[]):
        with patch("app.qa_ai.runner.probe_llm_for_qa", AsyncMock(return_value=None)):
            with patch("app.qa_ai.runner.prepare_qa_run", AsyncMock(return_value={"jobs_in_store": 0})):
                with patch("app.qa_ai.runner.design_test_case", _design):
                    with patch("app.qa_ai.runner.critique_schedule", _critique):
                        with patch("app.qa_ai.runner.synthesize_run", _synth):
                            with patch("app.qa_ai.runner.trigger_automatic_handoff", _noop_handoff):
                                with patch.dict("os.environ", {"QA_MAX_CASES": "2", "QA_MAX_ITERATIONS": "2"}):
                                    report = asyncio.run(
                                        AIQATeamRunner().run(auto_cursor_handoff=False)
                                    )

    assert report.run_id
    assert len(report.scenarios) >= 1
    first = report.scenarios[0]
    assert first.get("iterations")
    assert first["iterations"][0]["critique"]["placement_critiques"]
    assert first["iterations"][0].get("schedule_reviewed") is not None
