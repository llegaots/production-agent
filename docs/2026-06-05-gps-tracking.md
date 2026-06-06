# Work log: GPS tracking, live sessions, and demo (2026-06-05)

Focus of the day was the live field tracking: getting the rep's GPS dot and the
green walked trace to show reliably on both the manager overview ("big page")
and the individual session view, plus the supporting demo and analysis pieces.

---

## 1. How the GPS tracking pipeline works

The same path runs whether the location comes from a real phone or the demo
simulator, which is why field use will be simpler than the demo (one real device,
one continuous stream, instead of faking a fleet).

```
phone GPS (watchPosition)            manager views
        |                                  ^
        v                                  |
  recorder.tsx  ──POST──▶ /api/sessions/[id]/position ──▶ D2D_Sessions (lat,lng,trail_path)
                                                   |            |
                                            dwell detected      ├─ Realtime UPDATE (when healthy)
                                                   |            └─ /api/sessions/[id]/trail   (polled fallback)
                                                   v               /api/sessions/live-positions (batch, for cards)
                                         /api/sessions/[id]/doors ──▶ D2D_DoorEvents (Realtime INSERT)
```

Real phone capture is already built:
- `lib/geo/dwell-tracker.ts` uses `navigator.geolocation.watchPosition` with
  `enableHighAccuracy: true`, ignores noisy fixes (> 60 m), and detects a "door"
  when the rep stays within ~16 m for ~18 s.
- `components/record/recorder.tsx` posts each fix to `/position`, posts door
  visits to `/doors`, and grabs a screen wake lock so the phone does not sleep
  mid shift.

---

## 2. Live trace: what was built and fixed

### Trace persistence (so it survives navigation)
- Migration `supabase/migrations/0010_session_trail.sql` adds
  `D2D_Sessions.trail_path` (jsonb), a downsampled list of the walked points.
- `/api/sessions/[id]/position` appends to it (only after moving >= 8 m, capped
  at 1500 points) and always updates `lat`/`lng`. It is resilient: if 0010 is not
  applied yet, it still updates the position and skips the trail write.

### Reliable rendering without depending on flaky Realtime
Door pins and transcript arrive via Realtime INSERT events (those work). The
trace depends on session lat/lng UPDATE events, which were not arriving reliably.
Rather than depend on that, we added an HTTP polling fallback (every 1.5 s):
- `app/api/sessions/[id]/trail/route.ts`  (single session, for the detail view)
- `app/api/sessions/live-positions/route.ts`  (all live sessions, for the cards)
- `lib/realtime/use-live-session.ts` polls the per-session endpoint and grows the
  breadcrumb + moves the live dot.
- `components/sessions/sessions-grid.tsx` polls the batch endpoint for the cards.

Result: the trace shows in both views even if Realtime UPDATE never fires and
even before migration 0010 is applied. 0010 only adds persistence across reload.

### Door pins land on the actual home
- `lib/geo/geocode.ts` `reverseGeocodeDetailed()` returns the matched building's
  own coordinate plus the address.
- `/api/sessions/[id]/doors` snaps each pin to that home (within ~60 m, else keeps
  the GPS point) and stores the address, so a pin sits on "211 Sunny St", not in
  the middle of the road.

### Map rendering fixes (`components/maps/google-field-map.tsx`)
- Overlays now update in place (`setPath` / `setPosition`) instead of being torn
  down and rebuilt on every GPS tick. This removed the choppiness.
- The camera fits the geometry exactly once, and only after real geometry exists
  (a route, a multi point trace, or door pins). This stopped two bugs: the zoom
  resetting on every tick, and a placeholder position pinning the view to the
  wrong place and never recovering (which looked like a "blank map").
- Removed the direction arrows from route polylines.
- Door pins are small fixed size markers, not large metre radius circles.
- The planned route renders as a light grey baseline; the walked trace colours in
  on top of it.

### Hooks crash fix (was blanking the routes page)
- `components/routes/routes-view.tsx`: an early `return` for the route preview was
  placed above a `useMemo`, so opening a preview rendered fewer hooks and React
  threw "Rendered fewer hooks than expected", blanking the whole page. Moved the
  early returns below all hooks.

---

## 3. Live demo simulation

- "Start live demo" / "Stop demo" toggle on the sessions page
  (`components/sessions/demo-button.tsx`) plus `app/api/demo/start` and
  `app/api/demo/stop`.
- `lib/demo/runner.ts` plays each rep through their route server side (positions,
  conversations, knock outcomes via the real endpoints), then patrols the route
  back and forth for ~10 minutes so the session stays live, or until Stop is
  pressed. It checks session status so Stop ends it cleanly.
- `scripts/demo-seed.mjs` now seeds 4 distinct routes, one per rep, each in its
  own West Island neighbourhood (Baie-D'Urfe North/South, Beaconsfield, Kirkland),
  so the four reps show in four different places instead of sharing two routes.

Run order for the demo: apply migrations, `npm run demo:seed`, `npm run dev`
(port 8080), then press Start live demo (or `npm run demo`).

---

## 4. Analysis agents

- `lib/agent/session-grader.ts` (new): after a session ends, grades the transcript
  against the team's playbook (criteria weights, objection handles) and writes the
  0-100 grade plus per criterion and coaching insights. Wired into
  `/api/sessions/[id]/end`.
- `lib/agent/lead-spotter.ts`: a lead now requires a real name AND a phone number.
  A code level guard rejects placeholder names like "the prospect" or "Homeowner".
- `lib/agent/door-classifier.ts` and the spotter are company agnostic now.

---

## 5. Route generation fixes

- Area input is a postal code (with Google Places search to confirm it). When you
  pick a suggestion, its coordinates and bounds are captured and used directly, so
  bare Canadian postal codes like "H9W" no longer fail OSM geocoding
  (`components/routes/postal-autocomplete.tsx`, `app/api/routes/generate/route.ts`,
  `lib/agent/route-planner.ts`). Typed FSAs also retry with ", Canada".
- Generation produces a preview you can refine in chat, then Confirm to schedule.

---

## 6. Company swap to Student Works (painting)

- `supabase/migrations/0011_student_works_playbook.sql`: renames the team and
  replaces the playbook (script, six objection handles, grading criteria).
- `scripts/demo-seed.mjs` and the demo conversation pools were rewritten so the
  reps actually run the Student Works canvassing script and collect name + two
  numbers + email on a yes.

---

## 7. Migrations to apply (Supabase SQL editor)

- `0010_session_trail.sql`  - trace persistence across reload (optional but nice).
- `0011_student_works_playbook.sql`  - Student Works company + playbook.
- Earlier ones still required if not applied: 0004 - 0009.

Note: `npm run demo:seed` reseeds the playbook, so run it after 0011 or it stays
Student Works either way (the seed now matches 0011).

---

## 8. Known limitations and next steps for real field use

The core pipeline is sound and will light up with a single real phone. Before a
real deployment, the real engineering items are:

1. Background / locked phone: a browser web app pauses GPS when the screen locks
   or the browser backgrounds. The wake lock helps only while the app is open. For
   a phone in a pocket all shift, wrap the app in a native shell (Capacitor or
   React Native) for true background GPS + mic.
2. Offline / dead zones: buffer GPS and transcript locally and sync when signal
   returns. Not built yet.
3. Battery: continuous high accuracy GPS + audio is heavy. Position posts are
   throttled; needs field tuning.
4. Permissions: one time location + mic grant per rep.

Suggested quick proof: a single rep "use my real location" mode. Open `/record`
on a real phone, grant location, and watch your own dot and trace move on the
manager view. This exercises the real pipeline end to end without the synthetic
fleet.

---

## Key files

- Phone capture: `components/record/recorder.tsx`, `lib/geo/dwell-tracker.ts`
- Position + trail: `app/api/sessions/[id]/position/route.ts`,
  `app/api/sessions/[id]/trail/route.ts`, `app/api/sessions/live-positions/route.ts`
- Manager views: `components/sessions/session-detail.tsx`,
  `components/sessions/sessions-grid.tsx`, `components/sessions/session-card.tsx`,
  `lib/realtime/use-live-session.ts`
- Maps: `components/maps/google-field-map.tsx`, `components/maps/field-map.tsx`,
  `components/maps/coverage-map.tsx`
- Demo: `lib/demo/runner.ts`, `app/api/demo/start/route.ts`,
  `app/api/demo/stop/route.ts`, `scripts/demo-seed.mjs`, `scripts/simulate-session.mjs`
- Analysis: `lib/agent/session-grader.ts`, `lib/agent/lead-spotter.ts`,
  `lib/agent/door-classifier.ts`
- Migrations: `supabase/migrations/0010_session_trail.sql`,
  `supabase/migrations/0011_student_works_playbook.sql`
