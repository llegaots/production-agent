# Optimizer-only visual test

Run **just** `run_optimizer` against live Supabase jobs — no orchestrator, no critic, no chat. Opens an HTML report with crew routes and a day timeline.

## Prerequisites

- Repo-root `.env` with `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- Pending jobs in the database whose date window includes your target day

## Command

```bash
# Default: today, up to 15 pending jobs in that day's window
python scripts/run_optimizer_visual.py --open

# Specific day + friendlier job set (residential intake jobs usually schedule)
python scripts/run_optimizer_visual.py --date 2026-05-26 --job-prefix intake-job- --limit 8 --open

# Explicit jobs and crews
python scripts/run_optimizer_visual.py \
  --date 2026-05-26 \
  --job-ids intake-job-abc,intake-job-def \
  --crew-ids crew_alpha,crew_bravo \
  --open
```

Reports are written to `evals/reports/optimizer_visual_<timestamp>.html`.

## What you see

- **Stats** — assigned vs unassigned counts, optimizer status
- **Day timeline** — bars per crew showing when each job is worked
- **Routes table** — stop order, drive gaps, addresses, arrival/work times
- **Unassigned** — jobs the solver could not place (often skill/equipment mismatch on seed data)
- **Equipment check** — inventory conflicts before optimize (optional; use `--no-equipment-check` to hide)

## Tips

- Seed jobs (`seed-job-*`) often require skills like `solar`, `rope_access`, or `high_rise` that do not match crew skills — expect many unassigned. Use `--job-prefix intake-job-` for a cleaner first test.
- `OPTIMIZER_TIME_LIMIT_SECONDS` in `.env` controls solve time (override with `--time-limit 60`).
- Hardcoded scenarios without DB: `python scripts/run_optimizer_demo.py`
