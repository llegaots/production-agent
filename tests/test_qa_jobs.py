import asyncio

from app.qa_jobs import job_status_payload, start_background_qa


def test_background_qa_completes(monkeypatch):
    from app.qa_team import QAReport

    fake = QAReport(
        run_id="qa_test123",
        started_at="t0",
        finished_at="t1",
        overall_score=80,
        passed=True,
        scheduling_modes_tested=["geo_first"],
        mode="legacy",
    )

    async def _fake_suite(self, **_kwargs):
        return fake

    monkeypatch.setattr(
        "app.qa_jobs.QATeamRunner.run_full_suite",
        _fake_suite,
    )

    async def _run():
        started = await start_background_qa(
            reset_seed=False, mode="legacy", auto_cursor_handoff=False
        )
        assert started["status"] == "running"
        run_id = started["run_id"]
        for _ in range(50):
            await asyncio.sleep(0.05)
            st = job_status_payload(run_id)
            if st["status"] == "complete":
                return st
        raise AssertionError("job did not complete")

    st = asyncio.run(_run())
    assert st["report"]["overall_score"] == 80
