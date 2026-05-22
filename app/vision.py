"""Production manager vision — what the app must replace in the field."""

PRODUCTION_MANAGER_VISION = """
ProductionAgent replaces a field production manager for exterior services (window cleaning,
eaves, gutters) in the Montreal West Island territory.

The manager must:
1. Build a feasible weekly schedule: every pending job assigned to a qualified crew/day
   with realistic drive and shift minutes.
2. Respect hard constraints: skills, equipment, job date windows, crew daily capacity.
3. Communicate clearly with clients (confirmations with date, time window, address, CTA).
4. Handle disruption: reschedule single jobs with transparent candidate scoring.
5. Let the owner steer trade-offs via chat: fill crew days vs minimize driving vs balanced.
6. Persist plans and audit trails so nothing is lost between sessions.

Success looks like: high schedule rate, low overbooked days, geocoded addresses in territory,
actionable client messages, and fast re-plan when the owner texts dissatisfaction.
""".strip()

ACCEPTANCE_CRITERIA = [
    {
        "id": "schedule_coverage",
        "title": "Schedule coverage",
        "description": "At least 80% of pending jobs in the planning window are placed on a crew-day.",
        "weight": 25,
    },
    {
        "id": "hard_constraints",
        "title": "Hard constraints",
        "description": "No placed job violates skills, equipment, or daily minute cap (overbook flagged).",
        "weight": 25,
    },
    {
        "id": "geocode_quality",
        "title": "Address verification",
        "description": "Jobs have in-service-area geocodes when Google API is configured.",
        "weight": 15,
    },
    {
        "id": "reschedule_integrity",
        "title": "Reschedule integrity",
        "description": "Reschedule removes job from old slot, places in new slot, updates statuses, persists events.",
        "weight": 20,
    },
    {
        "id": "owner_control",
        "title": "Owner control via chat",
        "description": "Owner can replan with stated preference (crew fill vs geo) without re-entering data.",
        "weight": 15,
    },
]
