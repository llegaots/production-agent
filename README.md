# RouteIQ — Field Intelligence for D2D Teams

Real-time tracking, AI grading and route intelligence for door-to-door sales teams.
Field reps record their knocking sessions; specialized agents process routes + conversations
**live** to grade each rep, auto-detect & transcribe leads into a CRM, and map which areas
are answering vs. unhit.

> This is the **frontend** build. It runs on typed mock data + a simulated real-time stream,
> behind a clean data-access seam (`lib/data`) so a Supabase backend can be dropped in next
> without touching page components.

## Stack

- **Next.js 16** (App Router) · **React 19** · **TypeScript**
- **Tailwind CSS v4** with a custom token theme (`app/globals.css`)
- **Framer Motion** for all animation
- **Radix UI** primitives · **lucide-react** icons
- **@vis.gl/react-google-maps** with a styled vector-map fallback
- Fonts: Plus Jakarta Sans (display) + Inter (body)

## Getting started

```bash
npm install
cp .env.example .env.local   # add your Google Maps key (optional)
npm run dev
```

Open the printed URL (defaults to http://localhost:3000; set `PORT` to change, e.g. `PORT=8080 npm run dev`).

### Environment

| Variable | Purpose |
| --- | --- |
| `NEXT_PUBLIC_GOOGLE_MAPS_API_KEY` | Renders real Google Maps on Routes + Live sessions. Without it, an elegant styled vector map is shown. |
| `NEXT_PUBLIC_SUPABASE_URL` / `_ANON_KEY` | Reserved for the backend phase (not wired yet). |

## Pages

| Route | What it is |
| --- | --- |
| `/` | **Dashboard** — KPIs, door-volume chart, top performers, territory table, live activity |
| `/sessions` | **Live Sessions** command-center — grid of active reps |
| `/sessions/[id]` | **Live drill-in** — streaming transcript, AI grading, detected leads, drawing route |
| `/leads` | **CRM** — table + kanban pipeline + lead drawer |
| `/routes` | **Routes** — Google map, coverage heatmap, create-route flow |
| `/team` | **Team** — leaderboard with grades, pace, trends |
| `/playbook` | **Playbook** — the script + objection handles the agents grade against |
| `/settings` | Workspace, integrations, notifications |

## Project structure

```
app/(app)/             route group with the sidebar + topbar shell
components/ui/          design-system primitives
components/<feature>/   dashboard · sessions · leads · routes · team · playbook
components/maps/        FieldMap → GoogleFieldMap | VectorMap fallback
lib/types.ts           domain model (mirrors planned Supabase tables)
lib/mock/              seed data
lib/realtime/          simulated live event stream (useLiveSession)
lib/data/              data-access seam — swap mock → Supabase here
```

## Next phase (backend)

Wire Supabase behind `lib/data`, replace `lib/realtime` with Supabase Realtime channels,
add audio capture + transcription, and connect the agents to the Claude API for live grading.
