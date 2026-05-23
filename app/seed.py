"""Realistic West Island (Montreal) seed dataset for ProductionAgent.

29 jobs across 5 service types, 6 neighbourhoods, 4 crews.
Designed to stress-test the scheduler:
  - skill mismatches (rope-access jobs only Charlie can take)
  - equipment conflicts (only one scissor-lift, shared by Bravo; only one rope
    crew for multiple high-rise jobs — job_H04/H05 are the conflict scenario)
  - capacity pressure (full-day jobs that fill a crew by themselves)
  - geo spread (Île-Perrot ↔ Kirkland ↔ Dorval is 30+ km round-trip)
  - tight date windows (some jobs are weekend-only available, forcing
    the scheduler to use the right day)
"""
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

# ─── Depot ───────────────────────────────────────────────────────────────────
# Sainte-Anne-de-Bellevue (far-west anchor of the West Island)
BASE_LAT = 45.4030
BASE_LNG = -73.9470

# The Monday the seed data was designed around.  The QA executor always
# plans against this week so that date-window filters let seed jobs through.
SEED_WEEK_START = date(2026, 7, 6)


# ─── Neighbourhood centroids (lat, lng) ──────────────────────────────────────
_ILE_PERROT      = (45.3820, -73.9380)   # ~8 km S of depot
_PINCOURT        = (45.3760, -73.9850)   # adjacent to Île-Perrot
_VAUDREUIL       = (45.4010, -74.0350)   # ~12 km W of depot
_BAIE_D_URFE     = (45.4580, -73.9150)   # ~8 km NE
_BEACONSFIELD    = (45.4340, -73.8620)   # ~10 km E
_KIRKLAND        = (45.4530, -73.8700)   # ~12 km E
_POINTE_CLAIRE   = (45.4460, -73.8280)   # ~15 km E
_DOLLARD         = (45.4920, -73.8230)   # ~18 km NE
_DORVAL          = (45.4520, -73.7450)   # ~23 km E  (stretch)
_DDO             = (45.4950, -73.8550)   # ~18 km NE


def seed(reset: bool = True) -> None:
    if reset:
        store.clients.clear()
        store.crews.clear()
        store.equipment.clear()
        store.jobs.clear()
        store.latest_plan = None
        store.confirmed_plan = None

    # ── Equipment ─────────────────────────────────────────────────────────────
    equipment = [
        # Pressure washers
        Equipment(id="eq_pw_1",     kind=EquipmentKind.PRESSURE_WASHER, label="Hot-water PW #1 (Bravo)"),
        Equipment(id="eq_pw_2",     kind=EquipmentKind.PRESSURE_WASHER, label="Cold-water PW #2 (Alpha)"),
        Equipment(id="eq_pw_3",     kind=EquipmentKind.PRESSURE_WASHER, label="Cold-water PW #3 (Delta)"),
        # Water-fed poles
        Equipment(id="eq_wfp_1",   kind=EquipmentKind.WATER_FED_POLE,  label="WFP 40ft (Bravo)"),
        Equipment(id="eq_wfp_2",   kind=EquipmentKind.WATER_FED_POLE,  label="WFP 25ft (Alpha)"),
        Equipment(id="eq_wfp_3",   kind=EquipmentKind.WATER_FED_POLE,  label="WFP 25ft (Delta)"),
        # Lifts
        Equipment(id="eq_lift_1",  kind=EquipmentKind.SCISSOR_LIFT,    label="Scissor lift (Bravo only — rental)"),
        # Rope kits
        Equipment(id="eq_rope_1",  kind=EquipmentKind.ROPE_KIT,        label="Rope access kit A (Charlie)"),
        Equipment(id="eq_rope_2",  kind=EquipmentKind.ROPE_KIT,        label="Rope access kit B (Charlie)"),
        # Ladders
        Equipment(id="eq_lad28_1", kind=EquipmentKind.LADDER_28,       label="28ft ext ladder #1 (Alpha)"),
        Equipment(id="eq_lad28_2", kind=EquipmentKind.LADDER_28,       label="28ft ext ladder #2 (Bravo)"),
        Equipment(id="eq_lad28_3", kind=EquipmentKind.LADDER_28,       label="28ft ext ladder #3 (Delta)"),
        Equipment(id="eq_lad32_1", kind=EquipmentKind.LADDER_32,       label="32ft ext ladder (Bravo — gutters)"),
        # Extension poles
        Equipment(id="eq_ext_1",   kind=EquipmentKind.EXTENSION_POLE,  label="Eaves/soffit pole (Alpha)"),
        Equipment(id="eq_ext_2",   kind=EquipmentKind.EXTENSION_POLE,  label="Eaves/soffit pole (Bravo)"),
        Equipment(id="eq_ext_3",   kind=EquipmentKind.EXTENSION_POLE,  label="Eaves/soffit pole (Delta)"),
        # Vans
        Equipment(id="eq_van_1",   kind=EquipmentKind.VAN,             label="Van Alpha"),
        Equipment(id="eq_van_2",   kind=EquipmentKind.VAN,             label="Van Bravo"),
        Equipment(id="eq_van_3",   kind=EquipmentKind.VAN,             label="Van Charlie"),
        Equipment(id="eq_van_4",   kind=EquipmentKind.VAN,             label="Van Delta"),
    ]
    for e in equipment:
        store.equipment[e.id] = e

    # ── Crews ─────────────────────────────────────────────────────────────────
    crews = [
        Crew(
            id="crew_alpha",
            name="Alpha (Residential — West Island)",
            members=["Marco", "Tasha"],
            skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            daily_minutes=8 * 60,   # 480 min
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=["eq_pw_2", "eq_wfp_2", "eq_lad28_1", "eq_ext_1", "eq_van_1"],
            hourly_cost=110.0,
        ),
        Crew(
            id="crew_bravo",
            name="Bravo (Commercial + Gutters — West Island)",
            members=["Devin", "Pia", "Luis"],
            skills=[
                Skill.LADDER_CERT,
                Skill.LIFT_OPERATOR,
                Skill.PRESSURE_WASH,
                Skill.GLASS_RESTORATION,
            ],
            daily_minutes=9 * 60,   # 540 min — 3-person crew, longer day
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=[
                "eq_pw_1", "eq_wfp_1", "eq_lift_1",
                "eq_lad28_2", "eq_lad32_1", "eq_ext_2", "eq_van_2",
            ],
            hourly_cost=180.0,
        ),
        Crew(
            id="crew_charlie",
            name="Charlie (High-rise Rope Access — West Island)",
            members=["Sam", "Quinn"],
            skills=[Skill.ROPE_ACCESS, Skill.LIFT_OPERATOR, Skill.GLASS_RESTORATION],
            daily_minutes=8 * 60,
            base_lat=BASE_LAT,
            base_lng=BASE_LNG,
            equipment_ids=["eq_rope_1", "eq_rope_2", "eq_van_3"],
            hourly_cost=210.0,
        ),
        Crew(
            id="crew_delta",
            name="Delta (Residential + Pressure Wash — East Island)",
            members=["Yuna", "Pavel"],
            skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            daily_minutes=8 * 60,
            base_lat=45.4520,       # Pointe-Claire area base
            base_lng=-73.8280,
            equipment_ids=["eq_pw_3", "eq_wfp_3", "eq_lad28_3", "eq_ext_3", "eq_van_4"],
            hourly_cost=110.0,
        ),
    ]
    for c in crews:
        store.crews[c.id] = c

    # ── Clients ───────────────────────────────────────────────────────────────
    clients = [
        Client(id="cli_001", name="Jeff Clement",             contact_phone="514-297-4807", contact_email="", preferred_contact="phone"),
        Client(id="cli_002", name="Sherif & Isabella Zalidia",contact_phone="514-312-6060", contact_email="", preferred_contact="phone"),
        Client(id="cli_003", name="Claudia Schmidt",          contact_phone="514-312-6060", contact_email="", preferred_contact="phone"),
        Client(id="cli_004", name="Jean-François Fortin",     contact_phone="514-433-4316", contact_email="", preferred_contact="phone"),
        Client(id="cli_005", name="Marilyn Spriggs",          contact_phone="514-457-3342", contact_email="", preferred_contact="phone"),
        Client(id="cli_006", name="Helen Finn",               contact_phone="514-266-7036", contact_email="", preferred_contact="phone"),
        Client(id="cli_007", name="Robert Lavoie",            contact_phone="514-694-3210", contact_email="", preferred_contact="phone"),
        Client(id="cli_008", name="Anne-Marie Tessier",       contact_phone="514-694-4521", contact_email="", preferred_contact="email"),
        Client(id="cli_009", name="Pierre Bouchard",          contact_phone="514-457-8812", contact_email="", preferred_contact="phone"),
        Client(id="cli_010", name="Sandra Ho",                contact_phone="514-426-0011", contact_email="", preferred_contact="email"),
        Client(id="cli_011", name="Mathieu Gagnon",           contact_phone="450-458-7700", contact_email="", preferred_contact="phone"),
        Client(id="cli_012", name="Les Condos du Lac Inc.",   contact_phone="514-630-1234", contact_email="", preferred_contact="email"),
        Client(id="cli_013", name="Laura & David Kim",        contact_phone="514-694-9988", contact_email="", preferred_contact="email"),
        Client(id="cli_014", name="François Mercier",         contact_phone="514-695-3344", contact_email="", preferred_contact="phone"),
        Client(id="cli_015", name="Résidences Harmony Corp.", contact_phone="514-426-5500", contact_email="", preferred_contact="email"),
        Client(id="cli_016", name="Tom & Wendy MacIntosh",    contact_phone="514-697-8820", contact_email="", preferred_contact="phone"),
        Client(id="cli_017", name="Sylvie Delorme",           contact_phone="514-426-4432", contact_email="", preferred_contact="phone"),
        Client(id="cli_018", name="Nathan Park",              contact_phone="514-426-7753", contact_email="", preferred_contact="email"),
        Client(id="cli_019", name="Immeubles Côte-Ouest",     contact_phone="514-630-6677", contact_email="", preferred_contact="email"),
        Client(id="cli_020", name="Diane & Marc Tremblay",    contact_phone="514-457-1155", contact_email="", preferred_contact="phone"),
    ]
    for cl in clients:
        store.clients[cl.id] = cl

    # ── Date windows ─────────────────────────────────────────────────────────
    wk = date(2026, 7, 6)   # Monday of the planning week
    w_end = date(2026, 7, 10)

    # Tight: must happen early in week
    early   = (date(2026, 7, 6),  date(2026, 7, 8))
    # Flexible: full week
    full_wk = (date(2026, 7, 6),  date(2026, 7, 10))
    # Late-week only
    late    = (date(2026, 7, 8),  date(2026, 7, 10))
    # Future window (stress test: should be deferred, not forced in)
    future  = (date(2026, 8, 3),  date(2026, 8, 7))

    # ── Jobs ─────────────────────────────────────────────────────────────────
    # Naming convention:
    #   job_W01..W12  window cleaning (various sizes)
    #   job_G01..G06  gutter cleaning (ladder_32 required)
    #   job_P01..P05  pressure washing (pressure_washer required)
    #   job_H01..H03  high-rise (rope_access required)
    #   job_S01..job_S02  solar panel cleaning
    jobs = [

        # ═══════════════════════════════════════════════════════════════════
        # WINDOW CLEANING — residential (small 60-90 min)
        # ═══════════════════════════════════════════════════════════════════
        Job(
            id="job_W01", client_id="cli_001",
            service_type=ServiceType.WINDOW_CLEANING,
            address="18 Simone-De Beauvoir, Notre-Dame-de-l'Île-Perrot QC J7V 8P4",
            lat=_ILE_PERROT[0], lng=_ILE_PERROT[1],
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=220.0,
            notes="Residential bungalow, int/ext. Group with other Île-Perrot jobs.",
        ),
        Job(
            id="job_W02", client_id="cli_002",
            service_type=ServiceType.WINDOW_CLEANING,
            address="9 Place Bastien, Pincourt QC J7W 7J2",
            lat=_PINCOURT[0], lng=_PINCOURT[1],
            estimated_minutes=60, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=180.0,
            notes="Small bungalow, exterior only. Pair with job_W03.",
        ),
        Job(
            id="job_W03", client_id="cli_003",
            service_type=ServiceType.WINDOW_CLEANING,
            address="9 Place Bastien, Pincourt QC J7W 7J2",
            lat=_PINCOURT[0] + 0.0002, lng=_PINCOURT[1] + 0.0002,
            estimated_minutes=60, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=180.0,
            notes="Same street as W02. Should land same crew/day.",
        ),
        Job(
            id="job_W04", client_id="cli_004",
            service_type=ServiceType.WINDOW_CLEANING,
            address="23 Rue Madore, Île-Perrot QC J7V 0B1",
            lat=_ILE_PERROT[0] - 0.003, lng=_ILE_PERROT[1] + 0.005,
            estimated_minutes=150, difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=340.0,
            notes="2-storey split-level. Int/ext + eaves troughs. Takes 2.5 h.",
        ),
        Job(
            id="job_W05", client_id="cli_006",
            service_type=ServiceType.WINDOW_CLEANING,
            address="99 Meloche, Sainte-Anne-de-Bellevue QC H9X 3Z5",
            lat=BASE_LAT + 0.001, lng=BASE_LNG - 0.001,
            estimated_minutes=120, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=270.0,
            notes="Near depot. Good filler if crew finishes early.",
        ),
        Job(
            id="job_W06", client_id="cli_007",
            service_type=ServiceType.WINDOW_CLEANING,
            address="45 Beaconsfield Blvd, Beaconsfield QC H9W 3X4",
            lat=_BEACONSFIELD[0], lng=_BEACONSFIELD[1],
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=230.0,
            notes="Cluster with Kirkland jobs.",
        ),
        Job(
            id="job_W07", client_id="cli_008",
            service_type=ServiceType.WINDOW_CLEANING,
            address="12 Boul. Kirkland, Kirkland QC H9J 1H7",
            lat=_KIRKLAND[0], lng=_KIRKLAND[1],
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=230.0,
            notes="Cluster with Beaconsfield jobs.",
        ),
        # Medium residential (2–2.5 h)
        Job(
            id="job_W08", client_id="cli_009",
            service_type=ServiceType.WINDOW_CLEANING,
            address="7 Rue des Érables, Pointe-Claire QC H9R 2P1",
            lat=_POINTE_CLAIRE[0], lng=_POINTE_CLAIRE[1],
            estimated_minutes=150, difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=330.0,
            notes="2-storey colonial. All windows + eaves. Can pair with Dollard-des-Ormeaux.",
        ),
        Job(
            id="job_W09", client_id="cli_010",
            service_type=ServiceType.WINDOW_CLEANING,
            address="99 Boul. Hymus, Dollard-des-Ormeaux QC H9B 1Z2",
            lat=_DOLLARD[0], lng=_DOLLARD[1],
            estimated_minutes=120, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=260.0,
            notes="Bungalow near Pointe-Claire border.",
        ),
        # Large residential (3–4 h)
        Job(
            id="job_W10", client_id="cli_011",
            service_type=ServiceType.WINDOW_CLEANING,
            address="50 Boul. Vaudreuil, Vaudreuil-Dorion QC J7V 5V5",
            lat=_VAUDREUIL[0], lng=_VAUDREUIL[1],
            estimated_minutes=210, difficulty=4,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE,
                EquipmentKind.EXTENSION_POLE, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=490.0,
            notes="Large 2-storey home w/ sunroom. 3.5 h. Do not stack more than 1 other stop same day.",
        ),
        # Full-day (should fill crew on its own)
        Job(
            id="job_W11", client_id="cli_012",
            service_type=ServiceType.WINDOW_CLEANING,
            address="200 Boul. Beaconsfield, Beaconsfield QC H9W 4A1",
            lat=_BEACONSFIELD[0] + 0.005, lng=_BEACONSFIELD[1] + 0.005,
            estimated_minutes=420, difficulty=5,
            required_skills=[Skill.LADDER_CERT, Skill.LIFT_OPERATOR, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE,
                EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=1200.0,
            notes="6-unit condo block — exterior all glass + lift required. Full-day Bravo only.",
        ),
        # Future-window job (should be deferred — not schedulable this week)
        Job(
            id="job_W12", client_id="cli_013",
            service_type=ServiceType.WINDOW_CLEANING,
            address="34 Rue du Lac, Dollard-des-Ormeaux QC H9G 1W8",
            lat=_DDO[0], lng=_DDO[1],
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_28, EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=future[0], latest_date=future[1],
            price=225.0,
            notes="Client away until August. Must NOT be scheduled in July week.",
        ),

        # ═══════════════════════════════════════════════════════════════════
        # GUTTER CLEANING (ladder_32 required — only Bravo has it)
        # ═══════════════════════════════════════════════════════════════════
        Job(
            id="job_G01", client_id="cli_005",
            service_type=ServiceType.GUTTER_CLEANING,
            address="32 Oxford, Baie-D'Urfé QC H9X 2T5",
            lat=_BAIE_D_URFE[0], lng=_BAIE_D_URFE[1],
            estimated_minutes=240, difficulty=4,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH, Skill.LIFT_OPERATOR],
            required_equipment=[
                EquipmentKind.LADDER_32, EquipmentKind.PRESSURE_WASHER,
                EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=680.0,
            notes="Full gutter flush + guard inspect. Bravo only (lift + 32ft ladder). 4 h.",
        ),
        Job(
            id="job_G02", client_id="cli_014",
            service_type=ServiceType.GUTTER_CLEANING,
            address="78 Summerhill, Beaconsfield QC H9W 3Y2",
            lat=_BEACONSFIELD[0] - 0.004, lng=_BEACONSFIELD[1] + 0.003,
            estimated_minutes=120, difficulty=3,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_32, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=310.0,
            notes="Standard bungalow gutters. No lift needed. Bravo only (32ft ladder).",
        ),
        Job(
            id="job_G03", client_id="cli_016",
            service_type=ServiceType.GUTTER_CLEANING,
            address="15 Elm Ave, Kirkland QC H9J 2E3",
            lat=_KIRKLAND[0] - 0.003, lng=_KIRKLAND[1] + 0.004,
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.LADDER_32, EquipmentKind.VAN],
            earliest_date=early[0], latest_date=early[1],
            price=250.0,
            notes="Tight window: Mon-Wed only (client out Thu/Fri). Bravo only.",
        ),
        Job(
            id="job_G04", client_id="cli_020",
            service_type=ServiceType.GUTTER_CLEANING,
            address="5 Chemin du Bord-du-Lac, Baie-D'Urfé QC H9X 3M2",
            lat=_BAIE_D_URFE[0] - 0.003, lng=_BAIE_D_URFE[1] + 0.002,
            estimated_minutes=150, difficulty=3,
            required_skills=[Skill.LADDER_CERT, Skill.PRESSURE_WASH],
            required_equipment=[
                EquipmentKind.LADDER_32, EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=380.0,
            notes="2-storey colonial. Gutter flush + soffit wash. Bravo only.",
        ),
        # Impossible gutter job — no crew can satisfy (would need rope + ladder_32, nobody has both)
        Job(
            id="job_G05", client_id="cli_015",
            service_type=ServiceType.GUTTER_CLEANING,
            address="3000 Chemin Sainte-Marie, Sainte-Anne-de-Bellevue QC H9X 3V9",
            lat=BASE_LAT - 0.005, lng=BASE_LNG + 0.003,
            estimated_minutes=180, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS, Skill.LADDER_CERT],
            required_equipment=[
                EquipmentKind.ROPE_KIT, EquipmentKind.LADDER_32, EquipmentKind.VAN,
            ],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=550.0,
            notes="3-storey mansard — needs rope + 32ft ladder. No current crew covers both. "
                  "Should appear in unscheduled + conflicts.",
        ),

        # ═══════════════════════════════════════════════════════════════════
        # PRESSURE WASHING
        # ═══════════════════════════════════════════════════════════════════
        Job(
            id="job_P01", client_id="cli_017",
            service_type=ServiceType.PRESSURE_WASHING,
            address="200 Rue Principale, Pointe-Claire QC H9R 4G5",
            lat=_POINTE_CLAIRE[0] - 0.002, lng=_POINTE_CLAIRE[1] + 0.003,
            estimated_minutes=120, difficulty=3,
            required_skills=[Skill.PRESSURE_WASH],
            required_equipment=[EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=290.0,
            notes="Driveway + patio. Alpha or Delta (both carry PW). 2 h.",
        ),
        Job(
            id="job_P02", client_id="cli_018",
            service_type=ServiceType.PRESSURE_WASHING,
            address="1 Boul. Brunswick, Dollard-des-Ormeaux QC H9A 1A1",
            lat=_DOLLARD[0] - 0.005, lng=_DOLLARD[1] - 0.003,
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.PRESSURE_WASH],
            required_equipment=[EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=220.0,
            notes="Small driveway. Easy fill job. Alpha or Delta.",
        ),
        Job(
            id="job_P03", client_id="cli_019",
            service_type=ServiceType.PRESSURE_WASHING,
            address="500 Boul. Des Sources, Dollard-des-Ormeaux QC H9B 2E4",
            lat=_DOLLARD[0] + 0.003, lng=_DOLLARD[1] + 0.005,
            estimated_minutes=240, difficulty=4,
            required_skills=[Skill.PRESSURE_WASH, Skill.LIFT_OPERATOR],
            required_equipment=[
                EquipmentKind.PRESSURE_WASHER, EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN,
            ],
            earliest_date=late[0], latest_date=late[1],
            price=640.0,
            notes="Commercial strip-mall facade. Lift required. Bravo only. Late-week window.",
        ),
        Job(
            id="job_P04", client_id="cli_013",
            service_type=ServiceType.PRESSURE_WASHING,
            address="88 Hymus Blvd, Pointe-Claire QC H9R 1E2",
            lat=_POINTE_CLAIRE[0] + 0.003, lng=_POINTE_CLAIRE[1] - 0.002,
            estimated_minutes=150, difficulty=3,
            required_skills=[Skill.PRESSURE_WASH],
            required_equipment=[EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=350.0,
            notes="Two-car garage + walkway. Good cluster with job_P01.",
        ),
        Job(
            id="job_P05", client_id="cli_011",
            service_type=ServiceType.PRESSURE_WASHING,
            address="400 Chemin de la Pinède, Vaudreuil-Dorion QC J7V 8M3",
            lat=_VAUDREUIL[0] + 0.003, lng=_VAUDREUIL[1] - 0.002,
            estimated_minutes=180, difficulty=3,
            required_skills=[Skill.PRESSURE_WASH],
            required_equipment=[EquipmentKind.PRESSURE_WASHER, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=420.0,
            notes="Wraparound deck + patio + driveway. Alpha or Delta. Far west — pair with W10.",
        ),

        # ═══════════════════════════════════════════════════════════════════
        # HIGH-RISE / ROPE ACCESS (Charlie only)
        # ═══════════════════════════════════════════════════════════════════
        Job(
            id="job_H01", client_id="cli_015",
            service_type=ServiceType.HIGH_RISE,
            address="2025 Boul. Saint-Charles, Kirkland QC H9H 3C4",
            lat=_KIRKLAND[0] + 0.005, lng=_KIRKLAND[1] + 0.003,
            estimated_minutes=300, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=1800.0,
            notes="8-storey glass tower — full facade west side. Rope access, Charlie only. 5 h.",
        ),
        Job(
            id="job_H02", client_id="cli_019",
            service_type=ServiceType.HIGH_RISE,
            address="3800 Boul. St-Jean, Dollard-des-Ormeaux QC H9G 1X1",
            lat=_DDO[0] - 0.005, lng=_DDO[1] + 0.003,
            estimated_minutes=240, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS, Skill.GLASS_RESTORATION],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=1400.0,
            notes="6-storey condo, water-stain restoration on south face. Charlie only. 4 h.",
        ),
        Job(
            id="job_H03", client_id="cli_012",
            service_type=ServiceType.HIGH_RISE,
            address="1 Rue Airport, Dorval QC H9P 1J3",
            lat=_DORVAL[0], lng=_DORVAL[1],
            estimated_minutes=480, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS, Skill.LIFT_OPERATOR],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.SCISSOR_LIFT, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=2800.0,
            notes="10-storey office tower — full facade. Rope + lift both required. "
                  "Requires Bravo AND Charlie together (Charlie has rope, Bravo has lift). "
                  "Full day. NOTE: no single crew covers all equipment.",
        ),
        # ── Rope-conflict scenario jobs ─────────────────────────────────────
        # Two rope jobs in adjacent zones, ONE rope crew (Charlie) — the
        # scheduler must detect this contention and split them across days.
        Job(
            id="job_H04", client_id="cli_004",
            service_type=ServiceType.HIGH_RISE,
            address="32 Rue Oxford, Baie-D'Urfé QC H9X 2T5",
            lat=_BAIE_D_URFE[0] + 0.003, lng=_BAIE_D_URFE[1] - 0.001,
            estimated_minutes=240, difficulty=5,
            required_skills=[Skill.ROPE_ACCESS],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=1350.0,
            notes="6-storey condo, Baie-D'Urfé. Rope access, Charlie only. "
                  "Equipment conflict scenario: cannot run same day as job_H05 (one rope crew).",
        ),
        Job(
            id="job_H05", client_id="cli_003",
            service_type=ServiceType.HIGH_RISE,
            address="1355 Boul. Des Sources, Dorval QC H9S 5K4",
            lat=_DORVAL[0] + 0.005, lng=_DORVAL[1] - 0.003,
            estimated_minutes=180, difficulty=4,
            required_skills=[Skill.ROPE_ACCESS],
            required_equipment=[EquipmentKind.ROPE_KIT, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=980.0,
            notes="4-storey office, Dorval. Rope access, Charlie only. "
                  "Equipment conflict scenario: cannot run same day as job_H04 (one rope crew).",
        ),

        # ═══════════════════════════════════════════════════════════════════
        # SOLAR PANEL CLEANING
        # ═══════════════════════════════════════════════════════════════════
        Job(
            id="job_S01", client_id="cli_016",
            service_type=ServiceType.SOLAR_PANEL_CLEANING,
            address="77 Beaconsfield Blvd, Beaconsfield QC H9W 3Y8",
            lat=_BEACONSFIELD[0] + 0.002, lng=_BEACONSFIELD[1] - 0.001,
            estimated_minutes=90, difficulty=2,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=195.0,
            notes="12-panel roof array. WFP brush only. Any crew with ladder cert + WFP.",
        ),
        Job(
            id="job_S02", client_id="cli_020",
            service_type=ServiceType.SOLAR_PANEL_CLEANING,
            address="22 Rue des Cedres, Baie-D'Urfé QC H9X 2W1",
            lat=_BAIE_D_URFE[0] + 0.002, lng=_BAIE_D_URFE[1] - 0.002,
            estimated_minutes=60, difficulty=1,
            required_skills=[Skill.LADDER_CERT],
            required_equipment=[EquipmentKind.WATER_FED_POLE, EquipmentKind.VAN],
            earliest_date=full_wk[0], latest_date=full_wk[1],
            price=140.0,
            notes="8-panel, ground-mount. Quick job. Good filler near Baie-D'Urfé gutter jobs.",
        ),
    ]

    for j in jobs:
        j.status = JobStatus.PENDING
        store.jobs[j.id] = j
