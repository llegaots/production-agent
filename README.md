# production-agent

Multi-agent **production week planner** for window cleaning and field-service businesses.

Dispatchers juggle equipment, travel, job difficulty, crew skills, weekly hour budgets, and constant **rescheduling / client confirmations**. This project models that workflow as cooperating specialists rather than a single black-box optimizer.

## Quick start

```bash
npm install
npm run plan
```

The demo plans a sample week in Portland: clusters routes, assigns crews, builds day blocks, and drafts confirmation/reschedule messages.

## Agent pipeline

1. **EquipmentAgent** — Can we physically do each job with current inventory?
2. **RoutingAgent** — Cluster nearby jobs; estimate drive time.
3. **CrewAssignmentAgent** — Match difficulty, skills, gear, and **hour budget**.
4. **SchedulerAgent** — Place jobs on days with travel-aware times.
5. **ClientCommunicationsAgent** — Confirmations and reschedules; hold unconfirmed work.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams and extension notes.

## Product roadmap (suggested)

| Phase | Focus |
|-------|--------|
| **Now** | TypeScript orchestrator + domain model + demo data |
| **Next** | Supabase schema, confirmation audit trail, Twilio/SMS |
| **Then** | LLM-assisted explanations + dispatcher approval UI |
| **Later** | Continuous re-plan on weather, declines, and equipment changes |

## License

MIT (add license file when you open-source).
