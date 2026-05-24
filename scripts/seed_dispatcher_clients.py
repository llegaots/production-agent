#!/usr/bin/env python3
"""
Seed real dispatcher clients from data/dispatcher_clients.yaml.

- One client + one pending job per row (combined services in notes).
- Grouped by postal FSA (J7V, H9X, H4R, H4M, H4K) for routing tests.
- lat/lng stored for future geocoding (optional --geocode with GOOGLE_MAPS_API_KEY).

Usage:
  python scripts/seed_dispatcher_clients.py
  python scripts/seed_dispatcher_clients.py --force
  python scripts/seed_dispatcher_clients.py --geocode
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

DATA_PATH = ROOT / "data" / "dispatcher_clients.yaml"
PREFIX = "disp"


def _fsa(postal: str) -> str:
    clean = postal.upper().replace(" ", "")
    return clean[:3] if len(clean) >= 3 else "UNK"


def _jitter(crm_id: str, scale: float = 0.012) -> tuple[float, float]:
    h = hashlib.sha256(crm_id.encode()).hexdigest()
    a = int(h[:8], 16) / 0xFFFFFFFF - 0.5
    b = int(h[8:16], 16) / 0xFFFFFFFF - 0.5
    return a * scale, b * scale


def _coords(entry: dict, meta: dict) -> tuple[float, float]:
    postal = entry["postal_code"]
    fsa = _fsa(postal)
    groups = meta.get("postal_groups") or {}
    base = groups.get(fsa, {}).get("centroid") or {"lat": 45.5, "lng": -73.7}
    ja, jb = _jitter(entry["crm_id"])
    return base["lat"] + ja, base["lng"] + jb


def _geocode_address(full_address: str) -> tuple[float, float] | None:
    try:
        from app.config import get_settings
        import httpx

        key = get_settings().google_maps_api_key
        if not key:
            return None
        resp = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": full_address, "key": key},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            return None
        loc = data["results"][0]["geometry"]["location"]
        return float(loc["lat"]), float(loc["lng"])
    except Exception:
        return None


def _difficulty(label: str) -> int:
    lower = label.lower()
    if "very easy" in lower:
        return 1
    if "easy" in lower:
        return 2
    if "medium" in lower:
        return 3
    if "hard" in lower:
        return 4
    return 3


def _service_type(services: str) -> str:
    s = services.lower()
    if "gutter" in s or "eaves" in s or "soffit" in s:
        return "gutter_cleaning"
    if "pressure" in s or "siding" in s:
        return "pressure_washing"
    if "solar" in s:
        return "solar_panel_cleaning"
    return "window_cleaning"


def _skills_and_equipment(services: str, ladder: str) -> tuple[list[str], list[str]]:
    skills = ["ladder_cert"]
    if "pressure" in services.lower() or "siding" in services.lower():
        skills.append("pressure_wash")
    equip = ["ladder_28", "van"]
    if "30ft" in ladder.lower() or "30FT" in ladder:
        equip.append("water_fed_pole")
    if "pressure" in services.lower():
        equip.append("pressure_washer")
    if "gutter guard" in services.lower():
        equip.append("extension_pole")
    return skills, equip


def _date_window(intake: str, window_label: str) -> tuple[date, date]:
    earliest = date.fromisoformat(intake)
    if "early" in window_label.lower():
        latest = date(2026, 6, 15)
    else:
        latest = date(2026, 6, 30)
    return earliest, latest


def _estimated_minutes(work_units: int, services: str) -> int:
    base = max(60, min(480, work_units * 15))
    if "soffit" in services.lower() or "siding" in services.lower():
        base = min(480, base + 30)
    return base


def _build_rows(raw: dict, *, geocode: bool) -> tuple[list[dict], list[dict]]:
    meta = raw["meta"]
    clients: list[dict] = []
    jobs: list[dict] = []

    for entry in raw["clients"]:
        crm = entry["crm_id"]
        client_id = f"{PREFIX}-client-{crm}"
        job_id = f"{PREFIX}-job-{crm}"
        postal = entry["postal_code"].strip().upper()
        fsa = _fsa(postal)
        full_address = f"{entry['address']} {postal}"

        lat, lng = _coords(entry, meta)
        if geocode:
            geo = _geocode_address(full_address)
            if geo:
                lat, lng = geo

        phone = entry.get("phone") or "514-000-0000"
        notes_client = (
            f"crm_id={crm}|fsa={fsa}|postal_code={postal}|"
            f"window={entry.get('window_label', '')}"
        )
        if entry.get("phone_alt"):
            notes_client += f"|phone_alt={entry['phone_alt']}"

        clients.append(
            {
                "id": client_id,
                "name": entry["name"],
                "contact_email": f"client{crm}@dispatcher.local",
                "contact_phone": phone,
                "preferred_contact": "phone",
                "notes": notes_client,
            }
        )

        services = entry.get("services_text", "")
        stype = _service_type(services)
        skills, equip = _skills_and_equipment(services, entry.get("ladder", ""))
        earliest, latest = _date_window(entry["intake_date"], entry["window_label"])
        est = _estimated_minutes(int(entry.get("work_units", 5)), services)

        job_notes = (
            f"crm_id={crm}|fsa={fsa}|postal_code={postal}|"
            f"services={services}|ladder={entry.get('ladder', '')}|"
            f"intake={entry['intake_date']}|window={entry['window_label']}|"
            f"geocoded={'yes' if geocode else 'fsa_centroid'}"
        )

        jobs.append(
            {
                "id": job_id,
                "client_id": client_id,
                "service_type": stype,
                "address": full_address,
                "lat": lat,
                "lng": lng,
                "estimated_minutes": est,
                "difficulty": _difficulty(entry.get("difficulty_label", "Medium")),
                "required_skills": skills,
                "required_equipment": equip,
                "earliest_date": earliest.isoformat(),
                "latest_date": latest.isoformat(),
                "price": float(entry.get("price", 0)),
                "status": "pending",
                "notes": job_notes,
            }
        )

    return clients, jobs


def _delete(db) -> None:
    db.table("jobs").delete().like("id", f"{PREFIX}-job-%").execute()
    db.table("clients").delete().like("id", f"{PREFIX}-client-%").execute()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Replace existing disp-* rows")
    parser.add_argument("--geocode", action="store_true", help="Use Google Geocoding API for lat/lng")
    args = parser.parse_args()

    if not DATA_PATH.is_file():
        print(f"Missing {DATA_PATH}")
        return 1

    raw = yaml.safe_load(DATA_PATH.read_text(encoding="utf-8"))
    from app.db.supabase_client import get_supabase_client

    db = get_supabase_client()
    existing = (
        db.table("clients").select("id", count="exact").like("id", f"{PREFIX}-client-%").limit(1).execute()
    )
    if existing.count and not args.force:
        print(f"Dispatcher data exists ({existing.count} clients). Use --force to replace.")
        return 0

    if args.force and existing.count:
        print("Removing prior disp-* rows...")
        _delete(db)

    clients, jobs = _build_rows(raw, geocode=args.geocode)
    db.table("clients").upsert(clients).execute()
    db.table("jobs").upsert(jobs).execute()

    by_fsa: dict[str, int] = {}
    for j in jobs:
        m = re.search(r"fsa=([A-Z0-9]{3})", j["notes"])
        if m:
            by_fsa[m.group(1)] = by_fsa.get(m.group(1), 0) + 1

    print(f"Seeded {len(clients)} clients, {len(jobs)} jobs (prefix {PREFIX}-*)")
    for fsa, n in sorted(by_fsa.items()):
        label = (raw.get("meta", {}).get("postal_groups", {}).get(fsa, {}) or {}).get("label", fsa)
        print(f"  {fsa}: {n} jobs — {label}")
    print(f"\nOptimizer lab: http://localhost:3000/optimizer-lab")
    print(f"  Filter prefix: disp-  |  Suggested date: {raw['meta'].get('default_schedule_date', '2026-06-05')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
