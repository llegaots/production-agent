# OR-Tools Optimizer Lab (test UI)

Interactive page to debug the schedule optimizer **without chat or orchestrator**.

## Open it

```text
http://localhost:3000/optimizer-lab
```

**No login required** for the optimizer lab (chat still requires sign-in).

Restart **both** servers after pulling:

```bash
cd backend && PYTHONPATH=. uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend && npm run dev:clean -- --port 3000
```

Fix QA job equipment/skills once (if schedules show infeasible for bad gear):

```bash
python scripts/fix_qa_jobs_for_optimizer.py
```

## What you can do

1. **Load jobs** — defaults to `qa_job_006` … `qa_job_019` on `2026-07-08` (matches Supabase QA set)
2. **Edit** — service type, minutes, skills, equipment, address → **Save** (writes to Supabase)
3. **Delete** — trash icon removes the job row from Supabase
4. **Run optimizer** — OR-Tools only via `POST /optimizer-lab/run`
5. **Analyze** — right panel shows:
   - Optimizer diagnostics (why infeasible, skill/equipment conflicts)
   - **Schedule grid** (crews × 30-minute slots)
   - Stop order detail
   - Unassigned jobs table

## API (also in `/docs`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/optimizer-lab/jobs` | List/filter jobs |
| PATCH | `/optimizer-lab/jobs/{id}` | Update job |
| DELETE | `/optimizer-lab/jobs/{id}` | Delete job |
| GET | `/optimizer-lab/crews?target_date=` | Crews for a day |
| POST | `/optimizer-lab/run` | Run solver |

## Typical debugging flow

1. Run with default QA jobs → often **infeasible** because e.g. `qa_job_018` needs `ladder_32` + `van` no crew has
2. Read **Optimizer diagnostics**
3. Delete or edit the blocking job (equipment/skills), **Save**, **Run** again
4. Grid should show colored cells when feasible

## Not the same as

- **Chat** (`/chat`) — full product flow with orchestrator
- **HTML script** (`python scripts/run_optimizer_visual.py`) — static report file
