# Production Agent

Production Agent is a product blueprint for a multi-agent scheduling and
production planning system for window cleaning and other service businesses.

The core problem is not just putting jobs on a calendar. Dispatchers need to
build production weeks that balance crew capacity, job difficulty, equipment,
travel distance, budgeted labor time, weather, access constraints, and client
confirmation status. When a client cancels, a crew calls out, or weather
changes, the system should help the team reschedule quickly without losing the
reasoning behind the plan.

## Product direction

- Plan weekly production from a backlog of sold jobs.
- Group nearby jobs while respecting appointment windows and client
  preferences.
- Match jobs to crews based on skills, equipment, capacity, and budgeted time.
- Keep client confirmation and reminders visible in the scheduling workflow.
- Provide what-if rescheduling support when a plan changes.
- Explain why a proposed schedule is good or risky so a human dispatcher can
  approve it confidently.

## Key agents

1. **Job Intake Agent** - normalizes new jobs, estimates missing planning data,
   and flags incomplete information.
2. **Client Confirmation Agent** - manages confirmation status, reminders, and
   appointment-window conflicts.
3. **Geographic Clustering Agent** - groups nearby jobs to reduce drive time.
4. **Crew Capacity Agent** - checks crew availability, budgeted hours, skills,
   and fatigue risk.
5. **Equipment Allocation Agent** - verifies that ladders, water-fed poles,
   lifts, vehicles, and specialty tools are available.
6. **Difficulty and Risk Agent** - scores access, height, weather exposure,
   complexity, and safety considerations.
7. **Schedule Optimizer Agent** - proposes weekly and daily schedules from all
   constraints and scoring signals.
8. **Rescheduling Agent** - repairs the schedule when confirmations fail,
   weather changes, jobs run long, or crews become unavailable.
9. **Operations Copilot** - explains the plan, highlights tradeoffs, and asks
   the dispatcher for decisions.

## Documentation

See [docs/product-brief.md](docs/product-brief.md) for the detailed product
brief, domain model, scheduling constraints, agent responsibilities, and MVP
build slice.
