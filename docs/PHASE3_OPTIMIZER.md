# Phase 3 — OR-Tools VRP optimizer (isolated)

Pure Python module with **no database**. Pass structured input in, get crew routes out.

## Module layout

```
backend/app/optimizer/
  models.py      # Pydantic input/output
  solver.py      # OR-Tools routing model
  scenarios.py   # Hardcoded demo instances
  exceptions.py  # InfeasibleScheduleError
```

## Constraints

| Type | Implementation |
|------|----------------|
| Travel times | Square `travel.minutes` matrix + time dimension |
| Time windows | Per-job `time_window` on arrival cumul |
| Shift bounds | Crew `shift_start_minute` / `shift_end_minute` |
| Skills | Hard — only crews with superset of `required_skills` |
| Equipment | Hard — crew `equipment_kinds` must cover job |
| Max jobs / crew | Optional `max_jobs` capacity dimension |
| Preferred crew | Soft — extra arc cost if not `preferred_crew_id` |
| Optional jobs | `mandatory=False` → disjunction penalty |

## Usage

```python
from app.optimizer import solve, InfeasibleScheduleError
from app.optimizer.scenarios import feasible_two_crew_scenario

result = solve(feasible_two_crew_scenario())
print(result.status, result.assigned_job_ids)

# Raise on infeasible mandatory work:
solve(infeasible_skills_scenario(), strict=True)
```

## Node indexing

Each crew has a `depot_index` and each job a `node_index` into the **same** travel matrix. One job per matrix row (co-located jobs need duplicate rows with 0 travel between them).

## Tests

```bash
pytest tests/test_optimizer.py -v
python scripts/run_optimizer_demo.py
```

## Infeasible outcomes

- **Pre-solve:** no crew satisfies skills/equipment → `status=infeasible` + message (optional `strict=True` raises).
- **Solve fail:** time windows / capacity cannot be met → no solution, mandatory jobs listed unassigned.
- **Optional jobs** may be dropped when `mandatory=False`.
