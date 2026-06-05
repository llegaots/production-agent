#!/usr/bin/env node
/* ----------------------------------------------------------------------------
   RouteIQ — Session simulator.

   Plays the role of a marketer walking a route so you can test the whole
   pipeline WITHOUT a phone: it hits the same API endpoints the rep's recorder
   does — /position (moving GPS), /transcript (doorstep conversations), /doors
   (knocks, which classify the outcome), and /end (final lead sweep). Everything
   downstream is real: transcript persistence, door classification, lead
   detection, GPS→address reverse geocoding, and Realtime streaming to the
   manager view. Open /sessions/<id> and watch it unfold.

   Usage:
     npm run simulate                       # one marketer, synthetic street
     npm run simulate -- --route "Sunny"    # walk a real route from /routes (by name or id)
     npm run simulate -- --route <id> --all # every marketer assigned to that route
     npm run simulate -- --marketer "Sofia Reyes"
     npm run simulate -- --base https://your-app.vercel.app
     npm run simulate -- --delay 250        # speed up (ms between events)

   Requires the dev server running (default http://localhost:8080), Supabase +
   Anthropic env in .env.local, and migrations 0006–0009 applied.
---------------------------------------------------------------------------- */
import fs from "node:fs";

// ── args ─────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const flag = (name, def) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : def;
};
const has = (name) => args.includes(`--${name}`);

const BASE = flag("base", "http://localhost:8080").replace(/\/$/, "");
const DELAY = Number(flag("delay", "550"));
const MARKETER = flag("marketer", null);
const ROUTE = flag("route", null);
const ALL = has("all");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lerp = (a, b, t) => a + (b - a) * t;

// ── env + supabase reads (to resolve marketers, team, routes) ────────────────
function readEnv() {
  const txt = fs.readFileSync(new URL("../.env.local", import.meta.url), "utf8");
  return Object.fromEntries(
    txt
      .split("\n")
      .filter((l) => l.includes("=") && !l.trim().startsWith("#"))
      .map((l) => {
        const i = l.indexOf("=");
        return [l.slice(0, i).trim(), l.slice(i + 1).replace(/["']/g, "").trim()];
      }),
  );
}
async function supa(env, path) {
  const res = await fetch(`${env.NEXT_PUBLIC_SUPABASE_URL}/rest/v1/${path}`, {
    headers: {
      apikey: env.NEXT_PUBLIC_SUPABASE_ANON_KEY,
      Authorization: `Bearer ${env.NEXT_PUBLIC_SUPABASE_ANON_KEY}`,
    },
  });
  if (!res.ok) throw new Error(`Supabase read failed (${res.status}) — check .env.local + migrations.`);
  return res.json();
}
const post = (path, body) =>
  fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// ── scenario: a street of homes with varied outcomes ─────────────────────────
function buildScenario(repFirst) {
  return [
    { kind: "lead", lines: [
      ["rep", `Hi there, I'm ${repFirst} with Apex Exteriors — we're doing free roof inspections on the street this week. Have you had any issues since the last storm?`],
      ["prospect", "Actually, yeah — we lost a few shingles in the spring. How much does an inspection run?"],
      ["rep", "It's completely free, no obligation, and most storm damage is covered by your insurance."],
      ["prospect", "Okay, that sounds good. I'm Sarah Chen, you can reach me at 416-555-0173."],
      ["rep", "Perfect, Sarah. I've got an inspector here tomorrow afternoon — does 2pm work?"],
      ["prospect", "Tomorrow at 2 is great. See you then."],
    ] },
    { kind: "not-interested", lines: [
      ["rep", "Hi, we're offering free roof inspections this week —"],
      ["prospect", "No thank you, we just got a new roof last year. Not interested."],
      ["rep", "No problem at all, have a great day."],
    ] },
    { kind: "no-answer", lines: [
      ["rep", "(knocks) Hello? Apex Exteriors, free roof inspection — anyone home?"],
      ["rep", "Nobody's answering. I'll leave a flyer and move on."],
    ] },
    { kind: "callback", lines: [
      ["rep", "Hi! Free roof inspections in the neighbourhood this week — any concerns with your roof?"],
      ["prospect", "Maybe, but now's really not a good time. Can you call me later this week? It's 647-555-0199."],
      ["rep", "Absolutely — I'll follow up in a couple of days. Thanks!"],
    ] },
    { kind: "answered", lines: [
      ["rep", "Hi, we're doing roof inspections in the area — noticed any leaks or missing shingles?"],
      ["prospect", "Not that I've seen. The roof seems fine to me."],
      ["rep", "Great to hear. Here's my card in case anything ever comes up."],
    ] },
    { kind: "lead", lines: [
      ["rep", "Hi, free roof inspection — have you had yours checked since the spring storms?"],
      ["prospect", "No, but we've actually had a leak in the attic. I'm Mike, this is my place — 437-555-0142."],
      ["rep", "Let's get that looked at. I can do a free inspection Saturday morning — 10am okay?"],
      ["prospect", "Saturday at 10 works. Thanks a lot."],
    ] },
    { kind: "no-answer", lines: [["rep", "(rings the doorbell) Hello? ... no answer here either."]] },
  ];
}

// ── geometry: build the walk plan (house location + path to it per stop) ──────
function samplePoints(arr, n) {
  if (arr.length <= n) return arr;
  const out = [];
  for (let i = 0; i < n; i++) out.push(arr[Math.round((i / (n - 1)) * (arr.length - 1))]);
  return out;
}
function planFromRoute(path, nStops, jitter = 0) {
  const L = path.length;
  const plan = [];
  let prev = 0;
  for (let i = 0; i < nStops; i++) {
    const idx = Math.max(0, Math.min(L - 1, Math.round(((i + 1) / (nStops + 1)) * (L - 1))));
    const walk = samplePoints(path.slice(prev, idx + 1), 6).map((p) => ({
      lat: p.lat + jitter,
      lng: p.lng + jitter,
    }));
    plan.push({ house: { lat: path[idx].lat + jitter, lng: path[idx].lng + jitter }, walk });
    prev = idx;
  }
  return plan;
}
function planSynthetic(base, nStops) {
  const plan = [];
  let prev = { lat: base.lat - 0.0006, lng: base.lng };
  for (let i = 0; i < nStops; i++) {
    const house = { lat: base.lat + i * 0.00022, lng: base.lng };
    const walk = [];
    for (let k = 1; k <= 4; k++)
      walk.push({ lat: lerp(prev.lat, house.lat, k / 4), lng: lerp(prev.lng, house.lng, k / 4) });
    plan.push({ house, walk });
    prev = house;
  }
  return plan;
}

// ── play one marketer through their plan ─────────────────────────────────────
async function runMarketer({ marketer, teamId, routeId, plan }) {
  const repFirst = marketer.name.split(" ")[0];
  const stops = buildScenario(repFirst);

  const start = await post("/api/sessions", {
    marketerId: marketer.id,
    teamId,
    routeId: routeId ?? null,
    territory: marketer.home_territory ?? null,
  });
  const startJson = await start.json();
  if (!start.ok) throw new Error(`Could not start session: ${startJson.error}`);
  const sessionId = startJson.sessionId;
  console.log(`\n▶  ${marketer.name} — watch live: ${BASE}/sessions/${sessionId}`);

  let seq = 0;
  const t0 = Date.now();
  const results = [];

  for (let s = 0; s < stops.length; s++) {
    const stop = stops[s];
    const { house, walk } = plan[s];

    for (const p of walk) {
      await post(`/api/sessions/${sessionId}/position`, p);
      await sleep(DELAY / 3);
    }
    await post(`/api/sessions/${sessionId}/position`, house);

    const fromSeq = seq;
    for (const [speaker, text] of stop.lines) {
      await post(`/api/sessions/${sessionId}/transcript`, {
        lines: [{ seq, at: new Date().toISOString(), speaker, text, isFinal: true }],
      });
      seq += 1;
      await sleep(DELAY);
    }
    const toSeq = seq - 1;

    const door = await post(`/api/sessions/${sessionId}/doors`, {
      lat: house.lat,
      lng: house.lng,
      fromSeq,
      toSeq,
      at: new Date().toISOString(),
    });
    const dJson = await door.json().catch(() => ({}));
    const got = dJson.outcome ?? dJson.error ?? "?";
    results.push({ expected: stop.kind, got });
    console.log(`   🚪 house ${s + 1}: expected ${stop.kind.padEnd(14)} → got ${got}`);
    await sleep(DELAY);
  }

  const durationSec = Math.round((Date.now() - t0) / 1000);
  await post(`/api/sessions/${sessionId}/end`, { durationSec });
  console.log(`⏹  ${marketer.name} — ended (${durationSec}s). Final lead sweep running…`);
  return { sessionId, marketer: marketer.name, results };
}

async function main() {
  const env = readEnv();
  if (!env.NEXT_PUBLIC_SUPABASE_URL || !env.NEXT_PUBLIC_SUPABASE_ANON_KEY)
    throw new Error("Missing NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY in .env.local");

  const teams = await supa(env, "D2D_Teams?select=id&limit=1");
  const teamId = teams[0]?.id ?? null;
  const marketers = await supa(env, "D2D_Marketers?select=id,name,home_territory&order=joined_at.asc");
  if (!marketers.length) throw new Error("No marketers found — seed the team first.");

  // Resolve a route if requested (by id or name substring).
  let route = null;
  if (ROUTE) {
    const byId = /^[0-9a-f-]{36}$/i.test(ROUTE);
    const q = byId
      ? `D2D_Routes?id=eq.${ROUTE}&select=id,name,path`
      : `D2D_Routes?name=ilike.*${encodeURIComponent(ROUTE)}*&select=id,name,path&limit=1`;
    route = (await supa(env, q))[0];
    if (!route) throw new Error(`No route matched "${ROUTE}".`);
    if (!route.path?.length) throw new Error(`Route "${route.name}" has no path points.`);
  }

  // Pick marketers: explicit > all > route-assigned > first.
  let selected;
  if (MARKETER) selected = marketers.filter((m) => m.name.toLowerCase().includes(MARKETER.toLowerCase()));
  else if (ALL) selected = marketers;
  else if (route) {
    const assigns = await supa(env, `D2D_RouteAssignments?route_id=eq.${route.id}&select=marketer_id`);
    const ids = new Set(assigns.map((a) => a.marketer_id));
    const onRoute = marketers.filter((m) => ids.has(m.id));
    selected = onRoute.length ? [onRoute[0]] : [marketers[0]];
  } else selected = [marketers[0]];
  if (!selected.length) throw new Error(`No marketer matched "${MARKETER}".`);

  const nStops = buildScenario("x").length;
  console.log(
    `Simulating ${selected.length} marketer(s) against ${BASE}` +
      (route ? ` along route "${route.name}" (${route.path.length} pts)` : " on a synthetic street"),
  );
  console.log(`(${DELAY}ms cadence — --delay 200 to go faster, --all for everyone)`);

  const summaries = await Promise.all(
    selected.map((m, i) =>
      runMarketer({
        marketer: m,
        teamId,
        routeId: route?.id ?? null,
        plan: route
          ? planFromRoute(route.path, nStops, i * 0.00008)
          : planSynthetic({ lat: 43.6635 + i * 0.001, lng: -79.3285 + i * 0.0035 }, nStops),
      }),
    ),
  );

  console.log("\n── summary ──");
  for (const s of summaries) {
    const ok = s.results.filter((r) => r.expected === r.got).length;
    console.log(`  ${s.marketer}: ${ok}/${s.results.length} doors classified as expected — ${BASE}/sessions/${s.sessionId}`);
  }
  console.log("\n✅ Done. Check /sessions, /leads, and the session map(s).");
}

main().catch((e) => {
  console.error("\n❌ Simulation failed:", e.message);
  process.exit(1);
});
