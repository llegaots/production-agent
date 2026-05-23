"""Load YAML E2E scenarios and seed Supabase with isolated id prefixes."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

SCENARIOS_DIR = Path(__file__).resolve().parents[1] / "scenarios"


@dataclass
class ScenarioExpect:
    status: str
    max_iterations: int
    max_high_severity_issues: int = 0
    min_iterations: int = 1
    require_all_jobs_accounted: bool = True
    allow_unassigned: bool = False


@dataclass
class OrchestratorScenario:
    name: str
    description: str
    week_anchor: date
    user_request: str
    expect: ScenarioExpect
    use_llm_critic: bool = False
    use_agent: bool = False
    max_iterations: int = 4
    requires_agent: bool = False
    crews: list[dict[str, Any]] = field(default_factory=list)
    equipment: list[dict[str, Any]] = field(default_factory=list)
    crew_equipment: list[dict[str, Any]] = field(default_factory=list)
    clients: list[dict[str, Any]] = field(default_factory=list)
    job_rows: list[dict[str, Any]] = field(default_factory=list)
    id_prefix: str = ""
    week_start: date | None = None
    week_end: date | None = None
    all_job_ids: list[str] = field(default_factory=list)


def load_scenario(path: Path, *, run_prefix: str) -> OrchestratorScenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    anchor = date.fromisoformat(str(raw["week_anchor"]))
    week_start = anchor
    week_end = anchor + timedelta(days=6)
    exp = raw.get("expect", {})
    expect = ScenarioExpect(
        status=str(exp.get("status", "approved")),
        max_iterations=int(exp.get("max_iterations", 4)),
        max_high_severity_issues=int(exp.get("max_high_severity_issues", 0)),
        min_iterations=int(exp.get("min_iterations", 1)),
        require_all_jobs_accounted=bool(exp.get("require_all_jobs_accounted", True)),
        allow_unassigned=bool(exp.get("allow_unassigned", False)),
    )
    prefix = f"{run_prefix}-{raw['name']}-"
    clients = _prefix_rows(raw.get("clients", []), prefix, "id")
    scenario = OrchestratorScenario(
        name=raw["name"],
        description=raw.get("description", ""),
        week_anchor=anchor,
        user_request=f"{raw['user_request']} [{prefix}]",
        expect=expect,
        use_llm_critic=bool(raw.get("use_llm_critic", False)),
        use_agent=bool(raw.get("use_agent", False)),
        max_iterations=int(raw.get("max_iterations", 4)),
        requires_agent=bool(raw.get("requires_agent", False)),
        crews=_prefix_rows(raw.get("crews", []), prefix, "id"),
        equipment=_prefix_rows(raw.get("equipment", []), prefix, "id"),
        crew_equipment=_prefix_crew_equipment(raw.get("crew_equipment", []), prefix),
        clients=clients,
        id_prefix=prefix,
        week_start=week_start,
        week_end=week_end,
    )
    scenario.job_rows = _expand_jobs(raw.get("jobs", []), prefix, week_start, clients)
    scenario.all_job_ids = [j["id"] for j in scenario.job_rows]
    return scenario


def _prefix_rows(rows: list[dict], prefix: str, key: str) -> list[dict]:
    return [{**row, key: f"{prefix}{row[key]}"} for row in rows]


def _prefix_crew_equipment(rows: list[dict], prefix: str) -> list[dict]:
    return [
        {"crew_id": f"{prefix}{r['crew_id']}", "equipment_id": f"{prefix}{r['equipment_id']}"}
        for r in rows
    ]


def _expand_jobs(
    specs: list[dict],
    prefix: str,
    week_start: date,
    clients: list[dict],
) -> list[dict]:
    rows: list[dict] = []
    idx = 0
    client_id = clients[0]["id"] if clients else f"{prefix}client-01"
    for spec in specs:
        template = spec.get("template", "cluster_job")
        count = int(spec.get("count", 1))
        prefs = [f"{prefix}{p}" for p in spec.get("preferred_crews", [])]
        for n in range(count):
            idx += 1
            jid = f"{prefix}job-{idx:03d}"
            rows.append(_job_from_template(template, spec, jid, client_id, week_start, n, prefs, prefix))
    return rows


def _job_from_template(
    template: str,
    spec: dict,
    job_id: str,
    client_id: str,
    week_start: date,
    index: int,
    preferred_crews: list[str],
    prefix: str,
) -> dict:
    lat = float(spec.get("cluster_lat", 45.5017))
    lng = float(spec.get("cluster_lng", -73.5673))
    spread = float(spec.get("spread", 0.01))
    rng = random.Random(hash(job_id) & 0xFFFFFFFF)
    lat += rng.uniform(-spread, spread)
    lng += rng.uniform(-spread, spread)

    notes = f"e2e {template}"
    earliest = week_start
    latest = week_start + timedelta(days=6)

    if template in ("wfp_job", "ladder_job", "cluster_job"):
        pass
    elif template == "tight_window_job":
        start = int(spec.get("window_start", 60)) + index * int(spec.get("stagger_minutes", 40))
        end = min(int(spec.get("window_end", 420)), start + 120)
        earliest = week_start
        latest = week_start
        notes += f" tw_start:{start} tw_end:{end}"
    elif template == "preference_job":
        earliest = week_start + timedelta(days=index % 5)
        latest = earliest
        m_start = int(spec.get("morning_start", 480))
        m_end = int(spec.get("morning_end", 660))
        notes += f" tw_start:{m_start} tw_end:{m_end}"
        if preferred_crews:
            notes += f" preferred_crew:{preferred_crews[index % len(preferred_crews)]}"

    return {
        "id": job_id,
        "client_id": client_id,
        "service_type": spec.get("service_type", "window_cleaning"),
        "address": f"{100 + index} E2E Street",
        "lat": lat,
        "lng": lng,
        "estimated_minutes": int(spec.get("estimated_minutes", 45)),
        "difficulty": 2,
        "required_skills": list(spec.get("required_skills", ["residential"])),
        "required_equipment": list(spec.get("required_equipment", ["ladder_28"])),
        "earliest_date": earliest.isoformat(),
        "latest_date": latest.isoformat(),
        "price": 200.0,
        "status": "pending",
        "notes": notes,
        "recurrence_rule": "",
    }


def _crew_rows_for_db(crews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map YAML crew fixtures to public.crews columns (equipment via crew_equipment)."""
    out: list[dict[str, Any]] = []
    for crew in crews:
        out.append(
            {
                "id": crew["id"],
                "name": crew["name"],
                "skills": list(crew.get("skills") or []),
                "daily_minutes": int(crew.get("daily_minutes", 480)),
                "base_lat": float(crew["base_lat"]),
                "base_lng": float(crew["base_lng"]),
                "members": list(crew.get("members") or []),
            }
        )
    return out


def seed_scenario_to_supabase(scenario: OrchestratorScenario, db=None) -> None:
    from app.tools._db import tools_db

    db = db or tools_db()
    for table, rows in [
        ("clients", scenario.clients),
        ("crews", _crew_rows_for_db(scenario.crews)),
        ("equipment", scenario.equipment),
    ]:
        if rows:
            db.table(table).upsert(rows).execute()

    if scenario.crew_equipment:
        db.table("crew_equipment").upsert(scenario.crew_equipment).execute()

    crew_skills = []
    for crew in scenario.crews:
        for skill in crew.get("skills", []):
            crew_skills.append({"crew_id": crew["id"], "skill": skill})
    if crew_skills:
        db.table("crew_skills").upsert(crew_skills).execute()

    if scenario.job_rows:
        db.table("jobs").upsert(scenario.job_rows).execute()


def cleanup_scenario_prefix(prefix: str, db=None) -> None:
    """Delete rows created for this E2E prefix."""
    from app.tools._db import tools_db

    db = db or tools_db()

    job_rows = db.table("jobs").select("id").like("id", f"{prefix}%").execute().data or []
    job_ids = [r["id"] for r in job_rows]

    attempt_rows: list[dict] = []
    if job_ids:
        attempt_rows = (
            db.table("schedule_attempts")
            .select("id")
            .overlaps("job_ids", job_ids)
            .execute()
            .data
            or []
        )
    attempt_ids = [r["id"] for r in attempt_rows]
    if attempt_ids:
        db.table("critic_feedback").delete().in_("schedule_attempt_id", attempt_ids).execute()
        db.table("schedule_attempts").delete().in_("id", attempt_ids).execute()

    runs = (
        db.table("schedule_runs")
        .select("id")
        .like("user_request", f"%{prefix}%")
        .execute()
        .data
        or []
    )
    run_ids = [r["id"] for r in runs]
    if run_ids:
        for rid in run_ids:
            db.table("schedule_run_iterations").delete().eq("schedule_run_id", rid).execute()
        db.table("schedule_runs").delete().in_("id", run_ids).execute()

    db.table("jobs").delete().like("id", f"{prefix}%").execute()
    db.table("crew_equipment").delete().like("crew_id", f"{prefix}%").execute()
    db.table("crew_skills").delete().like("crew_id", f"{prefix}%").execute()
    db.table("crews").delete().like("id", f"{prefix}%").execute()
    db.table("clients").delete().like("id", f"{prefix}%").execute()
    db.table("equipment").delete().like("id", f"{prefix}%").execute()
