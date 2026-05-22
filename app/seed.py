"""Sample data — West Island (Montreal) window / exterior services bookings."""
from __future__ import annotations

from datetime import date

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

# Sainte-Anne-de-Bellevue depot (West Island)
BASE_LAT = 45.4030
BASE_LNG = -73.9470


def seed(reset: bool = True) -> None:
    if reset:
        store.clients.clear()
        store.crews.clear()
        store.equipment.clear()
        store.jobs.clear()
        store.latest_plan = None

    equipment = [
        Equipment(id="eq_pw_1", kind=EquipmentKind.PRESSURE_WASHER, label="Hot-water PW #1"),
        Equipment(id="eq_pw_2", kind=EquipmentKind.PRESSURE_WASHER, label="Cold-water PW #2"),
        Equipment(id="eq_wfp_1", kind=EquipmentKind.WATER_FED_POLE, label="Water-fed pole 40ft"),
        Equipment(id="eq_wfp_2", kind=EquipmentKind.WATER_FED_POLE, label="Water-fed pole 25ft"),
        Equipment(id="eq_lift_1", kind=EquipmentKind.SCISSOR_LIFT, label="Scissor lift (rental)"),
        Equipment(id="eq_rope_1", kind=EquipmentKind.ROPE_KIT, label="Rope access kit A"),
        Equipment(id="eq_ladder_1", kind=EquipmentKind.LADDER_28, label="28ft extension ladder"),
        Equipment(id="eq_ladder_2", kind=EquipmentKind.LADDER_28, label="28ft extension ladder #2"),
        Equipment(id="eq_ext_1", kind=EquipmentKind.EXTENSION_POLE, label="Eaves / soffit pole #1"),
        Equipment(id="eq_ext_2", kind=EquipmentKind.EXTENSION_POLE, label="Eaves / soffit pole #2"),
        Equipment(id="eq_van_1", kind=EquipmentKind.VAN, label="Van Alpha"),
        Equipment(id="eq_van_2", kind=EquipmentKind.VAN, label="Van Bravo"),
        Equipment(id="eq_van_3", kind=EquipmentKind.VAN, label="Van Charlie"),
    ]
    for e in equipment:
        store.equipment[e.id] = e

    crews = [
        Crew(
            id="crew_alpha",
            name="Alpha (Residential — West Island)",
            members=["Marco", "Tasha"],
            skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            daily_minutes=8 * 60,
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=["eq_pw_2", "eq_wfp_2", "eq_ladder_1", "eq_ext_1", "eq_van_1"],
            hourly_cost=110.0,
        ),
        Crew(
            id="crew_bravo",
            name="Bravo (Commercial — West Island)",
            members=["Devin", "Pia", "Luis"],
            skills=[
                Skill.LADDER_CERT,
                Skill.LIFT_OPERATOR,
                Skill.PRESSURE_WASH,
                Skill.GLASS_RESTORATION,
            ],
            daily_minutes=9 * 60,
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=["eq_pw_1", "eq_wfp_1", "eq_lift_1", "eq_ladder_2", "eq_ext_2", "eq_van_2"],
            hourly_cost=180.0,
        ),
        Crew(
            id="crew_charlie",
            name="Charlie (High-rise — West Island)",
            members=["Sam", "Quinn"],
            skills=[Skill.ROPE_ACCESS, Skill.LIFT_OPERATOR, Skill.GLASS_RESTORATION],
            daily_minutes=8 * 60,
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=["eq_rope_1", "eq_van_3"],
            hourly_cost=210.0,
        ),
    ]
    for c in crews:
        store.crews[c.id] = c

    clients = [
        Client(id="cli_001", name="Jeff Clement", contact_email="", contact_phone="514-297-4807", preferred_contact="phone", notes="JOB-001"),
        Client(id="cli_002", name="Sherif & Isabella Zalidia", contact_email="", contact_phone="514-312-6060", preferred_contact="phone", notes="JOB-002"),
        Client(id="cli_003", name="Claudia Schmidt", contact_email="", contact_phone="514-312-6060", preferred_contact="phone", notes="JOB-003 — same address as JOB-002"),
        Client(id="cli_004", name="Jean Francois Fortin", contact_email="", contact_phone="514-433-4316", preferred_contact="phone", notes="JOB-004"),
        Client(id="cli_005", name="Marilyn Spriggs", contact_email="", contact_phone="514-457-3342", preferred_contact="phone", notes="JOB-005"),
        Client(id="cli_006", name="Helen Finn", contact_email="", contact_phone="514-266-7036", preferred_contact="phone", notes="JOB-006"),
    ]
    for cl in clients:
        store.clients[cl.id] = cl

    may_start = date(2026, 5, 18)
    may_end = date(2026, 5, 29)
    june_start = date(2026, 6, 1)
    june_end = date(2026, 6, 30)

    jobs = [
        Job(
            id="job_001",
            client_id="cli_001",
            service_type=ServiceType.WINDOW_CLEANING,
            address="18 Simone-De Beauvoir, Notre-Dame-de-l'Île-Perrot QC J7V 8P4",
            lat=45.3838,
            lng=-73.8825,
            estimated_minutes=90,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=may_start,
            latest_date=may_end,
            notes="JOB-001 · Île-Perrot · Interior/Exterior Windows. Standard residential job. Unscheduled.",
        ),
        Job(
            id="job_002",
            client_id="cli_002",
            service_type=ServiceType.WINDOW_CLEANING,
            address="9 Place Bastien, Pincourt QC J7W 7J2",
            lat=45.3762,
            lng=-73.9852,
            estimated_minutes=150,
            difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28,
                EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE,
                EquipmentKind.VAN,
            ],
            earliest_date=may_start,
            latest_date=may_end,
            notes="JOB-002 · Pincourt · Windows + Eaves. Needs eaves; allow buffer. Unscheduled.",
        ),
        Job(
            id="job_003",
            client_id="cli_003",
            service_type=ServiceType.WINDOW_CLEANING,
            address="9 Place Bastien, Pincourt QC J7W 7J2",
            lat=45.3764,
            lng=-73.9850,
            estimated_minutes=90,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=may_start,
            latest_date=may_end,
            notes="JOB-003 · Pincourt · Same address/area as JOB-002. Unscheduled.",
        ),
        Job(
            id="job_004",
            client_id="cli_004",
            service_type=ServiceType.WINDOW_CLEANING,
            address="23 Rue Madore, Île-Perrot QC J7V 0B1",
            lat=45.3810,
            lng=-73.8780,
            estimated_minutes=150,
            difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28,
                EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE,
                EquipmentKind.VAN,
            ],
            earliest_date=may_start,
            latest_date=may_end,
            notes="JOB-004 · Île-Perrot · Windows + Eaves. Verify preferred timing. Unscheduled.",
        ),
        Job(
            id="job_005",
            client_id="cli_005",
            service_type=ServiceType.GUTTER_CLEANING,
            address="32 Oxford, Baie-D'Urfé QC H9X 2T5",
            lat=45.4582,
            lng=-73.9155,
            estimated_minutes=240,
            difficulty=4,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH, Skill.LIFT_OPERATOR],
            required_equipment=[
                EquipmentKind.LADDER_28,
                EquipmentKind.PRESSURE_WASHER,
                EquipmentKind.WATER_FED_POLE,
                EquipmentKind.SCISSOR_LIFT,
                EquipmentKind.VAN,
            ],
            earliest_date=june_start,
            latest_date=june_end,
            notes="JOB-005 · Baie-D'Urfé · Interior/Eaves/Soft cleaning/Gutter guard. Large job; do not overpack day. Unscheduled.",
        ),
        Job(
            id="job_006",
            client_id="cli_006",
            service_type=ServiceType.WINDOW_CLEANING,
            address="99 Meloche, Sainte-Anne-de-Bellevue QC H9X 3Z5",
            lat=45.4035,
            lng=-73.9478,
            estimated_minutes=120,
            difficulty=2,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28,
                EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE,
                EquipmentKind.VAN,
            ],
            earliest_date=may_start,
            latest_date=may_end,
            notes="JOB-006 · Sainte-Anne-de-Bellevue · Windows + Eaves. Group with Baie-D'Urfé / West Island jobs. Unscheduled.",
        ),
    ]
    for j in jobs:
        j.status = JobStatus.PENDING
        store.jobs[j.id] = j
