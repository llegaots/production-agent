"""Parse pasted spreadsheet rows (tab-separated) into import records."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .address import parse_address, refine_with_llm
from .geocode import GEOCODE_CONFIRM_THRESHOLD, geocoder
from .models import Client, EquipmentKind, Job, JobStatus, ServiceType, Skill

PHONE_RE = re.compile(
    r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}"
)
MONEY_RE = re.compile(r"\$[\d,]+(?:\.\d{2})?")
ID_SUFFIX_RE = re.compile(r"(\d{5,7})\s*$")


def _split_name_and_id(cell: str) -> tuple[str, str]:
    cell = cell.strip()
    m = ID_SUFFIX_RE.search(cell)
    if m:
        return cell[: m.start()].strip(), f"cli_{m.group(1)}"
    return cell, ""


def _map_services(text: str) -> tuple[ServiceType, list[Skill], list[EquipmentKind], int, int]:
    t = (text or "").lower()
    skills: list[Skill] = []
    equip: list[EquipmentKind] = [EquipmentKind.VAN]
    minutes = 120
    difficulty = 2

    if "high" in t and "rise" in t:
        st = ServiceType.HIGH_RISE
        skills = [Skill.ROPE_ACCESS, Skill.GLASS_RESTORATION]
        equip = [EquipmentKind.ROPE_KIT, EquipmentKind.VAN]
        minutes, difficulty = 360, 5
    elif "pressure" in t:
        st = ServiceType.PRESSURE_WASHING
        skills = [Skill.PRESSURE_WASH]
        equip = [EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN]
        minutes, difficulty = 150, 2
    elif "gutter" in t or "eaves" in t or "soffit" in t:
        st = ServiceType.GUTTER_CLEANING
        skills = [Skill.LADDER_CERT]
        equip = [EquipmentKind.LADDER_28, EquipmentKind.VAN]
        minutes, difficulty = 90, 2
    elif "solar" in t:
        st = ServiceType.SOLAR_PANEL_CLEANING
        skills = [Skill.LIFT_OPERATOR]
        equip = [EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN]
        minutes, difficulty = 180, 3
    else:
        st = ServiceType.WINDOW_CLEANING
        skills = [Skill.LADDER_CERT]
        equip = [EquipmentKind.WATER_FED_POLE, EquipmentKind.LADDER_28, EquipmentKind.VAN]
        if "int/ext" in t or ("ext" in t and "window" in t):
            minutes, difficulty = 180, 3
        else:
            minutes, difficulty = 120, 2

    if "lift" in t or "guard" in t:
        skills = list({*skills, Skill.LIFT_OPERATOR})
        if EquipmentKind.SCISSOR_LIFT not in equip:
            equip.append(EquipmentKind.SCISSOR_LIFT)

    return st, skills, equip, minutes, difficulty


def parse_pasted_text(text: str) -> list[dict]:
    """Parse multi-line paste. Expects tab-separated rows like the booking spreadsheet."""
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    rows: list[dict] = []

    for i, line in enumerate(lines):
        if i == 0 and re.search(r"customer|name|address|phone", line, re.I):
            continue

        cells = [c.strip() for c in line.split("\t")] if "\t" in line else re.split(r"\s{2,}", line)
        cells = [c for c in cells if c]
        if len(cells) < 3:
            continue

        name, client_id_hint = _split_name_and_id(cells[0])

        # Standard layout: name | phone | address | … | services
        phone = ""
        address_raw = cells[2] if len(cells) > 2 else ""
        if len(cells) > 1:
            pm = PHONE_RE.search(cells[1])
            if pm:
                phone = pm.group(0)
        if len(cells) <= 2:
            for c in cells[1:]:
                if PHONE_RE.search(c):
                    phone = PHONE_RE.search(c).group(0)  # type: ignore[union-attr]
                elif not address_raw and len(c) > 12:
                    address_raw = c

        service_text = ""
        if len(cells) >= 9:
            service_text = ", ".join(cells[8:])
        elif len(cells) >= 6:
            service_text = ", ".join(c for c in cells[5:] if not MONEY_RE.match(c) and not re.match(r"^\d{1,3}$", c))

        amounts = [float(x.replace("$", "").replace(",", "")) for x in MONEY_RE.findall(line)]
        price = amounts[-1] if amounts else 0.0

        rows.append(
            {
                "row_index": i,
                "name": name,
                "client_id_hint": client_id_hint or f"cli_import_{i}",
                "phone": phone,
                "email": f"import+{client_id_hint or i}@clearview.local",
                "address_raw": address_raw,
                "service_text": service_text,
                "price": price,
                "notes": service_text,
            }
        )

    return rows


async def build_import_batch(text: str, week_start: Optional[date] = None) -> dict:
    raw_rows = parse_pasted_text(text)
    ws = week_start or (date.today() - timedelta(days=date.today().weekday()))
    we = ws + timedelta(days=4)

    parsed: list[dict] = []
    any_needs_confirm = False

    for r in raw_rows:
        addr = parse_address(r["address_raw"])
        if addr.confidence < 0.88:
            addr = await refine_with_llm(addr)

        geo = await geocoder.geocode(addr.formatted or r["address_raw"])
        addr_dict = addr.to_dict()
        addr_dict["geocode"] = geo.to_dict()
        if geo.success and geo.lat is not None and geo.lng is not None:
            addr_dict["lat"] = geo.lat
            addr_dict["lng"] = geo.lng
            if geo.formatted_address:
                addr_dict["formatted"] = geo.formatted_address
        if geo.needs_review or addr.needs_confirmation:
            any_needs_confirm = True
        if geo.confidence < GEOCODE_CONFIRM_THRESHOLD:
            any_needs_confirm = True

        st, skills, equip, minutes, diff = _map_services(r.get("service_text") or "window")

        parsed.append(
            {
                **r,
                "address": addr_dict,
                "service_type": st.value,
                "required_skills": [s.value for s in skills],
                "required_equipment": [e.value for e in equip],
                "estimated_minutes": minutes,
                "difficulty": diff,
                "earliest_date": ws.isoformat(),
                "latest_date": we.isoformat(),
            }
        )

    return {
        "rows": parsed,
        "total": len(parsed),
        "needs_confirmation": any_needs_confirm,
        "confirm_threshold": 0.82,
    }


def materialize_import(
    rows: list[dict],
    *,
    address_overrides: Optional[dict[str, str]] = None,
) -> tuple[list[Client], list[Job]]:
    """Create Client + Job records after user confirms addresses."""
    address_overrides = address_overrides or {}
    clients: list[Client] = []
    jobs: list[Job] = []
    seen_clients: set[str] = set()

    for i, r in enumerate(rows):
        idx = str(r.get("row_index", i))
        addr_d = r["address"]
        formatted = address_overrides.get(idx, addr_d["formatted"])
        if idx in address_overrides:
            addr_d = parse_address(formatted).to_dict()

        cid = r.get("client_id_hint") or f"cli_import_{i}"
        if cid not in seen_clients:
            seen_clients.add(cid)
            clients.append(
                Client(
                    id=cid,
                    name=r["name"],
                    contact_email=r.get("email") or f"{cid}@import.local",
                    contact_phone=r.get("phone") or "",
                    preferred_contact="phone" if r.get("phone") else "email",
                    notes="Imported from spreadsheet",
                )
            )

        geo = addr_d.get("geocode") or {}
        lat = addr_d.get("lat") or geo.get("lat") or 45.5017
        lng = addr_d.get("lng") or geo.get("lng") or -73.5673
        geo_note = ""
        if geo.get("confidence") is not None:
            geo_note = f" [geocode {int(float(geo['confidence']) * 100)}%]"

        jobs.append(
            Job(
                id=f"job_{cid}_{i}",
                client_id=cid,
                service_type=ServiceType(r["service_type"]),
                address=formatted,
                lat=lat,
                lng=lng,
                estimated_minutes=r["estimated_minutes"],
                difficulty=r["difficulty"],
                required_skills=[Skill(s) for s in r["required_skills"]],
                required_equipment=[EquipmentKind(e) for e in r["required_equipment"]],
                earliest_date=date.fromisoformat(r["earliest_date"]),
                latest_date=date.fromisoformat(r["latest_date"]),
                price=float(r.get("price") or 0),
                status=JobStatus.PENDING,
                notes=(r.get("notes") or "") + geo_note,
            )
        )

    return clients, jobs
