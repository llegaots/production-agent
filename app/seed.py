"""Sample data for a fictional window cleaning / exterior services company.

The fictional company "ClearView Exterior Services" operates in the
Austin metro area. Coordinates are real-ish, jobs are illustrative.
"""
from __future__ import annotations

from datetime import date, timedelta

from .models import (
    Client,
    Crew,
    Equipment,
    EquipmentKind,
    Job,
    JobStatus,
    ServiceType,
    Skill,
)
from .storage import store


def _today_monday() -> date:
    today = date.today()
    return today - timedelta(days=today.weekday())


def seed(reset: bool = True) -> None:
    if reset:
        store.clients.clear()
        store.crews.clear()
        store.equipment.clear()
        store.jobs.clear()
        store.latest_plan = None

    # ---- equipment ----
    equipment = [
        Equipment(id="eq_pw_1", kind=EquipmentKind.PRESSURE_WASHER, label="Hot-water PW #1"),
        Equipment(id="eq_pw_2", kind=EquipmentKind.PRESSURE_WASHER, label="Cold-water PW #2"),
        Equipment(id="eq_wfp_1", kind=EquipmentKind.WATER_FED_POLE, label="Water-fed pole 40ft"),
        Equipment(id="eq_wfp_2", kind=EquipmentKind.WATER_FED_POLE, label="Water-fed pole 25ft"),
        Equipment(id="eq_lift_1", kind=EquipmentKind.SCISSOR_LIFT, label="Scissor lift (rental)"),
        Equipment(id="eq_rope_1", kind=EquipmentKind.ROPE_KIT, label="Rope access kit A"),
        Equipment(id="eq_ladder_1", kind=EquipmentKind.LADDER_28, label="28ft extension ladder"),
        Equipment(id="eq_ladder_2", kind=EquipmentKind.LADDER_28, label="28ft extension ladder #2"),
        Equipment(id="eq_van_1", kind=EquipmentKind.VAN, label="Van Alpha"),
        Equipment(id="eq_van_2", kind=EquipmentKind.VAN, label="Van Bravo"),
        Equipment(id="eq_van_3", kind=EquipmentKind.VAN, label="Van Charlie"),
    ]
    for e in equipment:
        store.equipment[e.id] = e

    # ---- crews ----
    crews = [
        Crew(
            id="crew_alpha",
            name="Alpha (Residential)",
            members=["Marco", "Tasha"],
            skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            daily_minutes=8 * 60,
            base_lat=30.2672,
            base_lng=-97.7431,
            equipment_ids=["eq_pw_2", "eq_wfp_2", "eq_ladder_1", "eq_van_1"],
            hourly_cost=110.0,
        ),
        Crew(
            id="crew_bravo",
            name="Bravo (Commercial)",
            members=["Devin", "Pia", "Luis"],
            skills=[
                Skill.LADDER_CERT,
                Skill.LIFT_OPERATOR,
                Skill.PRESSURE_WASH,
                Skill.GLASS_RESTORATION,
            ],
            daily_minutes=9 * 60,
            base_lat=30.2672,
            base_lng=-97.7431,
            equipment_ids=["eq_pw_1", "eq_wfp_1", "eq_lift_1", "eq_ladder_2", "eq_van_2"],
            hourly_cost=180.0,
        ),
        Crew(
            id="crew_charlie",
            name="Charlie (High-rise)",
            members=["Sam", "Quinn"],
            skills=[Skill.ROPE_ACCESS, Skill.LIFT_OPERATOR, Skill.GLASS_RESTORATION],
            daily_minutes=8 * 60,
            base_lat=30.2672,
            base_lng=-97.7431,
            equipment_ids=["eq_rope_1", "eq_van_3"],
            hourly_cost=210.0,
        ),
    ]
    for c in crews:
        store.crews[c.id] = c

    # ---- clients ----
    clients = [
        Client(id="cli_001", name="Maple Ridge HOA", contact_email="hoa@mapleridge.example", contact_phone="512-555-0101"),
        Client(id="cli_002", name="Lake Travis Estate", contact_email="owner@laketravis.example", contact_phone="512-555-0102", preferred_contact="phone"),
        Client(id="cli_003", name="Congress Tower LLC", contact_email="ops@congresstower.example", contact_phone="512-555-0103"),
        Client(id="cli_004", name="Pecan Street Bistro", contact_email="manager@pecanbistro.example", contact_phone="512-555-0104"),
        Client(id="cli_005", name="Soco Lofts", contact_email="board@socolofts.example", contact_phone="512-555-0105"),
        Client(id="cli_006", name="The Vance Residence", contact_email="vance@example.com", contact_phone="512-555-0106"),
        Client(id="cli_007", name="Bouldin Creek Cafe", contact_email="hello@bouldincafe.example", contact_phone="512-555-0107"),
        Client(id="cli_008", name="Domain Northside Mgmt", contact_email="fm@domainnorth.example", contact_phone="512-555-0108"),
        Client(id="cli_009", name="Zilker Bungalow", contact_email="zb@example.com", contact_phone="512-555-0109"),
        Client(id="cli_010", name="Mueller Medical Plaza", contact_email="ops@muellermed.example", contact_phone="512-555-0110"),
    ]
    for cl in clients:
        store.clients[cl.id] = cl

    monday = _today_monday()
    week_end = monday + timedelta(days=4)

    # ---- jobs ----
    jobs = [
        Job(
            id="job_001",
            client_id="cli_001",
            service_type=ServiceType.WINDOW_CLEANING,
            address="4501 Maple Ridge Dr, Austin, TX",
            lat=30.3527, lng=-97.7493,
            estimated_minutes=180, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.LADDER_28, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=620.0,
            notes="20 townhomes, exterior only.",
        ),
        Job(
            id="job_002",
            client_id="cli_002",
            service_type=ServiceType.WINDOW_CLEANING,
            address="22 Vista Trail, Lakeway, TX",
            lat=30.3711, lng=-97.9794,
            estimated_minutes=300, difficulty=4,
            required_skills=[Skill.LADDER_CERT, Skill.GLASS_RESTORATION],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.LADDER_28, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=1850.0,
            notes="Large lakefront home. Hard-water spotting on west elevation.",
        ),
        Job(
            id="job_003",
            client_id="cli_003",
            service_type=ServiceType.HIGH_RISE,
            address="100 Congress Ave, Austin, TX",
            lat=30.2630, lng=-97.7434,
            estimated_minutes=420, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS, Skill.GLASS_RESTORATION],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=3400.0,
            notes="High-rise rope descent. Building requires confirmed window 48h ahead.",
        ),
        Job(
            id="job_004",
            client_id="cli_004",
            service_type=ServiceType.PRESSURE_WASHING,
            address="421 E 6th St, Austin, TX",
            lat=30.2670, lng=-97.7404,
            estimated_minutes=150, difficulty=2,
            required_skills=[Skill.PRESSURE_WASH],
            required_equipment=[EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=480.0,
            notes="Sidewalk + patio. Must be done before 10am open.",
        ),
        Job(
            id="job_005",
            client_id="cli_005",
            service_type=ServiceType.WINDOW_CLEANING,
            address="1500 S Congress Ave, Austin, TX",
            lat=30.2517, lng=-97.7497,
            estimated_minutes=240, difficulty=3,
            required_skills=[Skill.LIFT_OPERATOR, Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=980.0,
            notes="Mixed-use loft building.",
        ),
        Job(
            id="job_006",
            client_id="cli_006",
            service_type=ServiceType.WINDOW_CLEANING,
            address="3007 Westlake Dr, Austin, TX",
            lat=30.2972, lng=-97.8059,
            estimated_minutes=120, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.LADDER_28, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=420.0,
            notes="Repeat customer, prefers mornings.",
        ),
        Job(
            id="job_007",
            client_id="cli_007",
            service_type=ServiceType.GUTTER_CLEANING,
            address="1900 S 1st St, Austin, TX",
            lat=30.2520, lng=-97.7548,
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=280.0,
            notes="Quick cleanout. Cafe closed Tuesdays.",
        ),
        Job(
            id="job_008",
            client_id="cli_008",
            service_type=ServiceType.WINDOW_CLEANING,
            address="11801 Domain Blvd, Austin, TX",
            lat=30.4012, lng=-97.7253,
            estimated_minutes=360, difficulty=4,
            required_skills=[Skill.LIFT_OPERATOR, Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=1640.0,
            notes="Storefront, requires after-hours lift access.",
        ),
        Job(
            id="job_009",
            client_id="cli_009",
            service_type=ServiceType.WINDOW_CLEANING,
            address="2010 Bluebonnet Ln, Austin, TX",
            lat=30.2625, lng=-97.7689,
            estimated_minutes=90, difficulty=1,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=210.0,
        ),
        Job(
            id="job_010",
            client_id="cli_010",
            service_type=ServiceType.SOLAR_PANEL_CLEANING,
            address="1801 East Dean Keeton, Austin, TX",
            lat=30.2902, lng=-97.7264,
            estimated_minutes=180, difficulty=3,
            required_skills=[Skill.LIFT_OPERATOR],
            required_equipment=[EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN],
            earliest_date=monday, latest_date=week_end,
            price=720.0,
            notes="Medical plaza rooftop array.",
        ),
    ]
    for j in jobs:
        j.status = JobStatus.PENDING
        store.jobs[j.id] = j
