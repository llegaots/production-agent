# Multi-agent production planning brief

## Product thesis

Window cleaning and service businesses do not only need a calendar. They need a
production planning system that understands how field work actually gets done:
which crew can perform the work, which equipment is required, how hard the job
is, whether the client has confirmed, how much time was sold, and what happens
when the schedule changes.

Production Agent should act like an operations planner that prepares a weekly
schedule, explains its tradeoffs, and helps repair the plan when real-world
events occur.

## Primary users

- **Owner or operations manager:** wants profitable production weeks, high crew
  utilization, fewer forgotten constraints, and a clean view of schedule risk.
- **Dispatcher or scheduler:** needs fast planning tools, client confirmation
  visibility, route grouping, and reliable rescheduling support.
- **Crew lead:** needs a clear day plan, job notes, equipment list, access
  details, and a way to report issues or overruns.
- **Client:** needs simple confirmation, reminders, and clear communication
  when an appointment changes.

## Planning inputs

The system should collect or infer the following fields for every job:

- Client name, service address, contact details, and communication preference.
- Service type, job scope, expected tasks, and special notes.
- Budgeted labor time by crew size, including setup and cleanup assumptions.
- Difficulty signals such as height, access, glass count, screens, storms,
  ladder work, lift needs, water-fed pole suitability, parking, and pets.
- Required equipment, vehicle type, materials, and safety requirements.
- Preferred crew, required skills, or crew exclusions.
- Appointment windows, deadline, recurrence pattern, and blackout dates.
- Confirmation status, last contact attempt, and next reminder time.
- Weather sensitivity and any site-specific access constraints.

## Agent system

### 1. Job Intake Agent

Normalizes jobs from CRM records, spreadsheets, forms, or manual entry. It
identifies missing planning fields and asks for the smallest amount of extra
information needed to schedule safely.

Outputs:

- Structured job profile.
- Missing-information checklist.
- Initial budgeted-time and difficulty confidence score.

### 2. Client Confirmation Agent

Treats confirmation as part of scheduling, not as an afterthought. It tracks
whether each client has confirmed, sends reminders, escalates unconfirmed jobs,
and exposes confirmation risk to the optimizer.

Outputs:

- Confirmation status: uncontacted, pending, confirmed, declined, needs follow
  up, or reschedule requested.
- Contact timeline and next recommended action.
- Schedule locks for confirmed appointment windows.

### 3. Geographic Clustering Agent

Groups jobs by service area and travel cost so production weeks are not built
from isolated calendar slots. It should consider drive time, parking friction,
route shape, and whether jobs can be paired naturally.

Outputs:

- Route clusters for each day or half day.
- Travel-time estimates.
- Warnings for outlier jobs that add too much travel.

### 4. Crew Capacity Agent

Matches jobs to crews based on availability, skills, budgeted hours, crew size,
and expected pace. It should protect against overloading a crew with too much
high-difficulty work in one day.

Outputs:

- Crew-day capacity.
- Skill and certification matches.
- Budgeted versus scheduled labor-hour comparison.
- Overtime and fatigue risk.

### 5. Equipment Allocation Agent

Verifies that required equipment is available when and where it is needed. This
is especially important for ladders, water-fed poles, lifts, vehicles, rope
access, pressure washing equipment, and specialty safety gear.

Outputs:

- Equipment reservations by job and crew.
- Conflicts and missing-equipment alerts.
- Suggested swaps when two crews need the same scarce item.

### 6. Difficulty and Risk Agent

Scores operational risk so the schedule does not accidentally stack several hard
jobs on the same crew or same day. Risk scoring should remain explainable and
editable by operations leaders.

Outputs:

- Difficulty score and reason list.
- Safety, access, or weather flags.
- Review-required marker for jobs above a risk threshold.

### 7. Schedule Optimizer Agent

Generates candidate schedules by combining hard constraints with scored
preferences. It should produce multiple options when tradeoffs are meaningful,
such as shortest drive time versus lowest overtime risk.

Outputs:

- Proposed weekly production plan.
- Daily route sheets.
- Constraint violations, if any.
- Explanation of why each job was assigned to each crew and day.

### 8. Rescheduling Agent

Repairs the schedule after cancellations, failed confirmations, weather events,
job overruns, crew absences, or equipment problems. It should preserve stable
parts of the plan whenever possible and clearly show what changed.

Outputs:

- Impacted jobs, clients, crews, and equipment.
- Replacement schedule options.
- Client communication queue.
- Before-and-after schedule diff.

### 9. Operations Copilot

Gives the dispatcher a conversational interface for questions like:

- "What jobs are risky this week?"
- "Can Crew A handle this route without overtime?"
- "What happens if Thursday morning rains out?"
- "Which unconfirmed jobs should we call first?"
- "Move this job to next week and repair the route."

## Scheduling constraints

### Hard constraints

Hard constraints should not be violated unless a human explicitly overrides
them.

- Crew availability and working hours.
- Required skills, certifications, or crew qualifications.
- Required equipment availability.
- Confirmed client appointment windows.
- Job deadlines or contractual service dates.
- Maximum safe daily labor hours.
- Site access restrictions.

### Soft constraints

Soft constraints should influence scoring and recommendations.

- Keep jobs geographically close together.
- Keep scheduled time close to sold or budgeted time.
- Prefer crews with prior experience at the property.
- Avoid stacking many difficult jobs on one crew or one day.
- Minimize overtime and excessive drive time.
- Respect client preferences where possible.
- Keep recurring clients on consistent days or crews.

## Confirmation workflow

1. When a job enters the backlog, assign a confirmation requirement based on job
   type, client preference, and scheduling horizon.
2. Before the weekly plan is published, surface all unconfirmed jobs that would
   create schedule risk.
3. Send automated confirmation requests through the client's preferred channel.
4. Lock confirmed appointment windows into the optimizer.
5. If a client declines or asks to reschedule, send the event to the
   Rescheduling Agent.
6. Keep a queue of manual follow-up calls for high-value or high-risk jobs.

Recommended statuses:

- `uncontacted`
- `pending_confirmation`
- `confirmed`
- `declined`
- `reschedule_requested`
- `needs_manual_follow_up`
- `cancelled`

## Rescheduling workflow

1. Capture the disruption: cancellation, no confirmation, weather, crew issue,
   equipment conflict, job overrun, or emergency work.
2. Identify all dependent assignments: jobs, routes, crews, equipment,
   confirmations, and client communications.
3. Protect stable commitments, especially confirmed appointments and jobs
   already in progress.
4. Generate repair options with explanations.
5. Ask the dispatcher to approve one option.
6. Notify affected clients and crews.
7. Record why the schedule changed for future planning quality.

## Data model sketch

- `client`: contact details, communication preferences, notes.
- `site`: address, geocode, access notes, parking, hazards.
- `job`: scope, service type, budgeted labor time, deadline, status.
- `job_requirement`: required equipment, skills, crew size, safety constraints.
- `crew`: default vehicle, members, service area, availability.
- `crew_member`: skills, certifications, speed profile, time off.
- `equipment`: type, quantity, location, availability, maintenance status.
- `confirmation`: status, contact attempts, response, appointment window.
- `schedule_assignment`: job, crew, date, start time, expected duration.
- `route`: ordered assignments, travel estimates, total labor, total drive time.
- `schedule_event`: cancellation, weather risk, overrun, manual override.

## MVP build slice

The first useful version should focus on one high-value loop:

1. Import or manually enter a backlog of jobs.
2. Capture budgeted time, address, required equipment, difficulty, appointment
   window, and confirmation status.
3. Create crews with availability, equipment, and daily capacity.
4. Generate a weekly plan with a transparent score.
5. Show unconfirmed jobs and risky assignments before publishing.
6. Let a dispatcher approve, edit, and publish the plan.
7. Simulate a disruption and generate rescheduling options.

This MVP can start with a simple scoring heuristic before introducing more
advanced optimization.

## Candidate schedule scoring

A practical first version can score each candidate assignment with weighted
factors:

```text
score =
  travel_score
  + capacity_fit_score
  + confirmation_score
  + equipment_fit_score
  + crew_skill_score
  + difficulty_balance_score
  + client_preference_score
  - overtime_penalty
  - hard_constraint_penalty
```

Hard-constraint penalties should be high enough to reject the candidate unless
the dispatcher explicitly overrides it.

## Product principles

- Keep the dispatcher in control; agents recommend and explain.
- Make every schedule decision auditable.
- Treat client confirmation and rescheduling as core scheduling data.
- Prefer clear constraints and explanations over opaque automation.
- Optimize for profitable, realistic production weeks, not just full calendars.
