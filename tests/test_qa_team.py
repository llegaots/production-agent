import asyncio

import pytest

from app.qa_team import QATeamRunner
from app.seed import seed


@pytest.fixture(autouse=True)
def fresh_seed(monkeypatch):
    seed(reset=True)

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

    async def _fake_llm_chat(*_a, **_kw):
        return None

    monkeypatch.setattr("app.llm.llm.chat", _fake_llm_chat)
    yield


def test_qa_suite_produces_report():
    runner = QATeamRunner()
    report = asyncio.run(runner.run_full_suite(reset_seed=True))
    assert report.overall_score >= 0
    assert len(report.criteria) >= 4
    assert report.report_json_path
    assert report.cursor_handoff_path
