#!/usr/bin/env python3
"""
Seed demo data for Phase 2 (idempotent).

Targets: 20 clients (customers), 4 crews, 50 pending jobs, equipment + crew_skills.

Usage (repo root, venv active):
  python scripts/seed.py
  python scripts/seed.py --force   # truncate Phase 2 seed IDs and re-insert
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.supabase_client import get_supabase_client  # noqa: E402

SEED_PREFIX = "seed-"
CREW_IDS = [f"{SEED_PREFIX}crew-{i}" for i in range(1, 5)]
CLIENT_COUNT = 20
JOB_COUNT = 50

SKILLS = ["residential", "commercial", "high_rise", "rope_access", "solar"]
EQUIPMENT_ROWS = [
    ("seed-eq-pw-1", "pressure_washer", "Pressure washer #1", 2),
    ("seed-eq-wfp-1", "water_fed_pole", "Water-fed pole kit", 3),
    ("seed-eq-lad-1", "ladder_28", "28ft ladder", 4),
    ("seed-eq-van-1", "van", "Crew van A", 1),
    ("seed-eq-van-2", "van", "Crew van B", 1),
]

SERVICE_TYPES = [
    "window_cleaning",
    "pressure_washing",
    "gutter_cleaning",
    "solar_panel_cleaning",
    "high_rise",
]

# Montreal-ish coordinates for demo routing
BASE_LAT, BASE_LNG = 45.5017, -73.5673


def _client_rows() -> list[dict]:
    rows = []
    for i in range(1, CLIENT_COUNT + 1):
        cid = f"{SEED_PREFIX}client-{i:02d}"
        rows.append(
            {
                "id": cid,
                "name": f"Seed Customer {i:02d}",
                "contact_email": f"customer{i:02d}@example.com",
                "contact_phone": f"514-555-{1000 + i:04d}",
                "preferred_contact": "email",
                "notes": "Phase 2 seed client",
            }
        )
    return rows


def _crew_rows() -> list[dict]:
    skill_sets = [
        ["residential", "commercial"],
        ["commercial", "high_rise"],
        ["residential", "solar"],
        ["high_rise", "rope_access"],
    ]
    names = ["Alpha Crew", "Bravo Crew", "Charlie Crew", "Delta Crew"]
    rows = []
    for idx, crew_id in enumerate(CREW_IDS):
        lat = BASE_LAT + random.uniform(-0.05, 0.05)
        lng = BASE_LNG + random.uniform(-0.05, 0.05)
        rows.append(
            {
                "id": crew_id,
                "name": names[idx],
                "members": [f"Tech {idx + 1}A", f"Tech {idx + 1}B"],
                "skills": skill_sets[idx],
                "daily_minutes": 480,
                "base_lat": lat,
                "base_lng": lng,
                "hourly_cost": float(55 + idx * 5),
            }
        )
    return rows


def _equipment_rows() -> list[dict]:
    return [
        {"id": eid, "kind": kind, "label": label, "quantity": qty}
        for eid, kind, label, qty in EQUIPMENT_ROWS
    ]


def _crew_equipment_rows() -> list[dict]:
    return [
        {"crew_id": CREW_IDS[0], "equipment_id": "seed-eq-van-1"},
        {"crew_id": CREW_IDS[0], "equipment_id": "seed-eq-lad-1"},
        {"crew_id": CREW_IDS[1], "equipment_id": "seed-eq-van-2"},
        {"crew_id": CREW_IDS[1], "equipment_id": "seed-eq-pw-1"},
        {"crew_id": CREW_IDS[2], "equipment_id": "seed-eq-wfp-1"},
        {"crew_id": CREW_IDS[3], "equipment_id": "seed-eq-lad-1"},
    ]


def _crew_skill_rows(crews: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for crew in crews:
        for skill in crew["skills"]:
            rows.append({"crew_id": crew["id"], "skill": skill})
    return rows


def _job_rows(clients: list[dict]) -> list[dict]:
    today = date.today()
    rows = []
    for i in range(1, JOB_COUNT + 1):
        client = clients[(i - 1) % len(clients)]
        stype = SERVICE_TYPES[i % len(SERVICE_TYPES)]
        lat = BASE_LAT + random.uniform(-0.08, 0.08)
        lng = BASE_LNG + random.uniform(-0.08, 0.08)
        start = today + timedelta(days=random.randint(0, 14))
        rows.append(
            {
                "id": f"{SEED_PREFIX}job-{i:03d}",
                "client_id": client["id"],
                "service_type": stype,
                "address": f"{100 + i} Seed Street, Montreal QC",
                "lat": lat,
                "lng": lng,
                "estimated_minutes": random.choice([45, 60, 90, 120, 180]),
                "difficulty": random.randint(1, 5),
                "required_skills": random.sample(SKILLS, k=random.randint(1, 2)),
                "required_equipment": random.sample(
                    ["pressure_washer", "ladder_28", "water_fed_pole"], k=1
                ),
                "earliest_date": start.isoformat(),
                "latest_date": (start + timedelta(days=7)).isoformat(),
                "price": float(random.randint(120, 450)),
                "status": "pending",
                "notes": "Phase 2 seed job",
            }
        )
    return rows


def _delete_seed_data(db) -> None:
    db.table("service_history").delete().like("client_id", f"{SEED_PREFIX}%").execute()
    db.table("jobs").delete().like("id", f"{SEED_PREFIX}%").execute()
    db.table("crew_equipment").delete().in_("crew_id", CREW_IDS).execute()
    db.table("crew_skills").delete().in_("crew_id", CREW_IDS).execute()
    db.table("crews").delete().in_("id", CREW_IDS).execute()
    db.table("clients").delete().like("id", f"{SEED_PREFIX}%").execute()
    db.table("equipment").delete().like("id", f"{SEED_PREFIX}%").execute()


def seed(*, force: bool = False) -> None:
    db = get_supabase_client()
    existing = (
        db.table("clients").select("id", count="exact").like("id", f"{SEED_PREFIX}%").limit(1).execute()
    )
    if existing.count and not force:
        print(f"Seed data already present ({existing.count} seed clients). Use --force to replace.")
        return

    if force:
        print("Removing prior seed rows...")
        _delete_seed_data(db)

    clients = _client_rows()
    crews = _crew_rows()
    equipment = _equipment_rows()

    print(f"Upserting {len(clients)} clients...")
    db.table("clients").upsert(clients).execute()

    print(f"Upserting {len(crews)} crews...")
    db.table("crews").upsert(crews).execute()

    print(f"Upserting {len(equipment)} equipment...")
    db.table("equipment").upsert(equipment).execute()

    ce = _crew_equipment_rows()
    print(f"Upserting {len(ce)} crew_equipment...")
    db.table("crew_equipment").upsert(ce).execute()

    cs = _crew_skill_rows(crews)
    print(f"Upserting {len(cs)} crew_skills...")
    db.table("crew_skills").upsert(cs).execute()

    jobs = _job_rows(clients)
    print(f"Upserting {len(jobs)} jobs...")
    db.table("jobs").upsert(jobs).execute()

    print("Done.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed Phase 2 demo data")
    parser.add_argument("--force", action="store_true", help="Replace existing seed-* rows")
    args = parser.parse_args()
    try:
        seed(force=args.force)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
