import asyncio
import uuid
from unittest.mock import AsyncMock, patch

from app.qa_ai.runner import AIQATeamRunner
from app.seed import seed


def test_ai_qa_reflective_loop(monkeypatch):
    seed(reset=True)
    uid = uuid.uuid4().hex[:8]

    case_a = {
        "fingerprint": f"test_rain_delay_{uid}",
        "title": "Rain delay cluster",
        "persona_story": "Owner after storm",
        "steps": [{"action": "plan", "scheduling_mode": "geo_first"}],
        "what_good_looks_like": "Jobs regrouped by zone",
    }
    case_b = {
        "fingerprint": f"test_fill_trucks_{uid}",
        "title": "Fill trucks",
        "persona_story": "Slow Monday",
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
                    "job_id": "job_001",
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
