# Dispatcher client dataset (real jobs)

10 real customers from your export, stored as `disp-*` in Supabase.

## Seed the data

```bash
python scripts/seed_dispatcher_clients.py --force
```

Optional precise coordinates (needs `GOOGLE_MAPS_API_KEY` in `.env`):

```bash
python scripts/seed_dispatcher_clients.py --force --geocode
```

Source file: `data/dispatcher_clients.yaml` (editable).

## Postal groups (FSA)

| FSA | Area | Jobs |
|-----|------|------|
| J7V | Île-Perrot / Notre-Dame-de-l'Île-Perrot | 4 |
| H9X | Baie-d'Urfé | 1 |
| H4R | Saint-Laurent | 1 |
| H4M | Saint-Laurent / Montréal | 3 |
| H4K | Montréal Ouest | 1 |

Each job `notes` field includes `fsa=…`, `postal_code=…`, `crm_id=…` for filtering and future geocoding.

## Optimizer lab

Open: http://localhost:3000/optimizer-lab

Defaults:

- **ID prefix:** `disp-`
- **Schedule date:** `2026-06-05` (within Early/Mid June windows)
- **Postal group:** pick J7V, H4M, etc. or All FSAs

Click **Run optimizer** to build the schedule grid.

## IDs

- Client: `disp-client-{crm_id}` (e.g. `disp-client-184320`)
- Job: `disp-job-{crm_id}`
