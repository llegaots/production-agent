#!/usr/bin/env node
/* ----------------------------------------------------------------------------
   RouteIQ - Session simulator.

   Plays the role of marketer(s) walking a route so you can demo / test the whole
   pipeline WITHOUT a phone. It hits the same API endpoints the rep's recorder
   does - /position (moving GPS), /transcript (doorstep conversations + walking
   gaps), /doors (knocks → outcome classification), /end (final lead sweep).
   Everything downstream is real: transcript persistence, door classification,
   lead detection, GPS→address reverse-geocoding, Realtime to the manager view.

   Usage:
     npm run demo                      # all seeded reps walk their routes, live
     npm run simulate -- --route "Sunny"          # one rep on a named route
     npm run simulate -- --all                     # every rep on their assigned route
     npm run simulate -- --marketer "Chloé"
     npm run simulate -- --delay 250               # speed up
     npm run simulate -- --stops 10                # doors per rep
---------------------------------------------------------------------------- */
import fs from "node:fs";

const args = process.argv.slice(2);
const flag = (name, def) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] && !args[i + 1].startsWith("--") ? args[i + 1] : def;
};
const has = (name) => args.includes(`--${name}`);

const BASE = flag("base", "http://localhost:8080").replace(/\/$/, "");
const DEMO = has("demo");
const DELAY = Number(flag("delay", DEMO ? "2200" : "550"));
const N_STOPS = Number(flag("stops", "8"));
const MARKETER = flag("marketer", null);
const ROUTE = flag("route", null);
const ALL = has("all") || DEMO;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lerp = (a, b, t) => a + (b - a) * t;
const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

function readEnv() {
  const txt = fs.readFileSync(new URL("../.env.local", import.meta.url), "utf8");
  return Object.fromEntries(
    txt.split("\n").filter((l) => l.includes("=") && !l.trim().startsWith("#")).map((l) => {
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
  if (!res.ok) throw new Error(`Supabase read failed (${res.status}) - check .env.local + migrations.`);
  return res.json();
}
const post = (path, body) =>
  fetch(`${BASE}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

// ── Student Works canvassing pool: each rep actually runs the script (opener,
//    the offer, an open-ended "what" question, the approved objection handles,
//    and collecting name + 2 numbers + email on a yes). Only the lead scenarios
//    give full contact, so leads = name + phone. ──────────────────────────────
const POOL = {
  lead: [
    (n) => [
      ["rep", `Hey, happy Friday! How's it going? My name is ${n}, I'm a student at McGill and this is our 3rd year running Student Works here in Baie-D'Urfe.`],
      ["rep", "I was just chatting with your neighbour Karen down the street. We're offering free estimates for interior and exterior painting and staining, plus window and eavestrough cleaning. What projects could we take off your hands this year?"],
      ["prospect", "Oh, we've actually been meaning to repaint the back deck and the fence."],
      ["rep", "Perfect, that's exactly what we handle. Wouldn't it make sense to book a quick free estimate just to see if it's worth having us take it off your hands?"],
      ["prospect", "Yeah, let's do that."],
      ["rep", "Amazing. What was your name again, sorry?"],
      ["prospect", "Janet Walsh."],
      ["rep", "Great, Janet. What's the best number to reach you, and a second one in case I can't get you?"],
      ["prospect", "Cell is 514-555-0148, and the house line is 514-555-0192."],
      ["rep", "Perfect, and an email so we can send the quote over?"],
      ["prospect", "janet.walsh@email.com. Mornings are best to call."],
      ["rep", "Got it. Jimmy will reach out in the next few days. Have a great day, Janet!"],
    ],
    (n) => [
      ["rep", `Hey there, happy Saturday! ${n} here, I'm a student at McGill and we're in our 3rd year running Student Works in the area.`],
      ["rep", "We're doing free estimates for interior and exterior painting and staining, and window and eavestrough cleaning. What were you hoping to get done around the house this year?"],
      ["prospect", "We were actually thinking about staining the cedar siding this summer."],
      ["rep", "Love it, cedar comes up beautifully. Wouldn't it make sense to grab a free estimate so you can see if it's worth having us handle it?"],
      ["prospect", "Sure, why not."],
      ["rep", "Awesome. Sorry, what was your name again?"],
      ["prospect", "Daniel Roy."],
      ["rep", "Thanks Daniel. Best number to reach you, and a backup one?"],
      ["prospect", "438-555-0192 is my cell, and work is 514-555-0170."],
      ["rep", "Perfect, and an email for the estimate?"],
      ["prospect", "droy@email.com, afternoons are best for me."],
      ["rep", "Got it. Our estimator will be in touch this week. Have a great one, Daniel!"],
    ],
  ],
  callback: [
    (n) => [
      ["rep", `Hey, how's it going? I'm ${n}, a student running Student Works, 3rd year doing free estimates for painting, staining and window cleaning on the street. What could we take off your hands this year?`],
      ["prospect", "Maybe the trim, but I'm literally heading out the door right now."],
      ["rep", "No worries at all. Can I follow up with you later this spring to see if it makes sense?"],
      ["prospect", "Yeah, give me a call next week."],
      ["rep", "Will do. Sorry, I didn't catch your name?"],
      ["prospect", "It's Dave."],
      ["rep", "Thanks Dave, have a great day!"],
    ],
  ],
  "not-interested": [
    (n) => [
      ["rep", `Hey, happy Friday! ${n} here with Student Works, we're students offering free estimates for painting, staining and window cleaning this week. What projects were you thinking about this year?`],
      ["prospect", "Honestly, I do all my own painting."],
      ["rep", "Amazing, where do you find the time? Wouldn't it make sense to at least grab a free estimate to see if it's worth taking off your plate?"],
      ["prospect", "No, I'm good thanks."],
      ["rep", "No problem at all, have a great day. Sorry, I didn't catch your name?"],
      ["prospect", "Mark."],
      ["rep", "Nice to meet you Mark, take care!"],
    ],
    (n) => [
      ["rep", `Hi, ${n} with Student Works, free estimates for interior and exterior painting this week. What were you hoping to get done?`],
      ["prospect", "It's way too early to be thinking about that."],
      ["rep", "Totally get it, though now is actually the best time to book, you check it off your list and lock in early-summer work, plus we've got a 10% early-season special. What were you thinking of taking care of?"],
      ["prospect", "Nothing right now, really."],
      ["rep", "No worries, I'll leave a flyer and you can call if anything comes up. Have a great day!"],
    ],
  ],
  answered: [
    (n) => [
      ["rep", `Hey, happy Sunday! I'm ${n}, a student running Student Works for our 3rd year here. We're doing free estimates for painting, staining and window cleaning. What could we help you with this year?`],
      ["prospect", "Hmm, nothing really comes to mind right now."],
      ["rep", "No problem at all. Here's a flyer, and if anything comes up this summer just give us a call."],
      ["prospect", "Sounds good, thanks."],
    ],
  ],
  "no-answer": [
    () => [["rep", "(knocks) Hello? Student Works, free painting estimates. Anyone home?"], ["rep", "No answer, I'll leave a flyer and move on."]],
    () => [["rep", "(rings the doorbell) ...nobody home here."]],
  ],
};
// Realistic outcome mix for door-to-door.
const WEIGHTS = [
  ["no-answer", 0.42], ["not-interested", 0.22], ["answered", 0.14], ["lead", 0.15], ["callback", 0.07],
];
function weightedKind() {
  let r = Math.random();
  for (const [k, w] of WEIGHTS) {
    if ((r -= w) <= 0) return k;
  }
  return "no-answer";
}
function assembleScenario(repFirst, n) {
  return Array.from({ length: n }, () => {
    const kind = weightedKind();
    return { kind, lines: pick(POOL[kind])(repFirst) };
  });
}

// ── geometry ─────────────────────────────────────────────────────────────────
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
    const walk = samplePoints(path.slice(prev, idx + 1), 6).map((p) => ({ lat: p.lat + jitter, lng: p.lng + jitter }));
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
    for (let k = 1; k <= 4; k++) walk.push({ lat: lerp(prev.lat, house.lat, k / 4), lng: lerp(prev.lng, house.lng, k / 4) });
    plan.push({ house, walk });
    prev = house;
  }
  return plan;
}

// ── play one rep through their plan ──────────────────────────────────────────
async function runMarketer({ marketer, teamId, routeId, plan }) {
  const repFirst = marketer.name.split(" ")[0];
  const stops = assembleScenario(repFirst, plan.length);

  const start = await post("/api/sessions", {
    marketerId: marketer.id, teamId, routeId: routeId ?? null, territory: marketer.home_territory ?? null,
  });
  const sj = await start.json();
  if (!start.ok) throw new Error(`Could not start session for ${marketer.name}: ${sj.error}`);
  const sessionId = sj.sessionId;
  console.log(`▶  ${marketer.name.padEnd(16)} watch: ${BASE}/sessions/${sessionId}`);

  let seq = 0;
  const t0 = Date.now();
  const results = [];

  for (let s = 0; s < stops.length; s++) {
    const { house, walk } = plan[s];
    // Walking gap - show movement + that nobody's talking between doors.
    if (s > 0) {
      await post(`/api/sessions/${sessionId}/transcript`, {
        lines: [{ seq, at: new Date().toISOString(), speaker: "agent", text: "(walking to the next home - no conversation)", isFinal: true }],
      });
      seq += 1;
      await sleep(DELAY);
    }
    for (const p of walk) {
      await post(`/api/sessions/${sessionId}/position`, p);
      await sleep(DELAY / 3);
    }
    await post(`/api/sessions/${sessionId}/position`, house);

    const fromSeq = seq;
    for (const [speaker, text] of stops[s].lines) {
      await post(`/api/sessions/${sessionId}/transcript`, {
        lines: [{ seq, at: new Date().toISOString(), speaker, text, isFinal: true }],
      });
      seq += 1;
      await sleep(DELAY);
    }
    const toSeq = seq - 1;

    const door = await post(`/api/sessions/${sessionId}/doors`, { lat: house.lat, lng: house.lng, fromSeq, toSeq, at: new Date().toISOString() });
    const dj = await door.json().catch(() => ({}));
    results.push({ expected: stops[s].kind, got: dj.outcome ?? dj.error ?? "?" });
    await sleep(DELAY);
  }

  const durationSec = Math.round((Date.now() - t0) / 1000);
  await post(`/api/sessions/${sessionId}/end`, { durationSec });
  const ok = results.filter((r) => r.expected === r.got).length;
  console.log(`⏹  ${marketer.name.padEnd(16)} done (${durationSec}s) - doors classified ${ok}/${results.length} as planted`);
  return { sessionId, marketer: marketer.name, results };
}

async function main() {
  const env = readEnv();
  if (!env.NEXT_PUBLIC_SUPABASE_URL || !env.NEXT_PUBLIC_SUPABASE_ANON_KEY)
    throw new Error("Missing NEXT_PUBLIC_SUPABASE_URL / _ANON_KEY in .env.local");

  const teams = await supa(env, "D2D_Teams?select=id&limit=1");
  const teamId = teams[0]?.id ?? null;
  const marketers = await supa(env, "D2D_Marketers?select=id,name,home_territory&order=joined_at.asc");
  if (!marketers.length) throw new Error("No marketers - run `npm run demo:seed` first.");
  const routes = await supa(env, "D2D_Routes?select=id,name,path");
  const assignments = await supa(env, "D2D_RouteAssignments?select=route_id,marketer_id");

  let plans = []; // { marketer, routeId, plan }

  if (ROUTE && !ALL) {
    // Single named route, one (assigned) rep.
    const byId = /^[0-9a-f-]{36}$/i.test(ROUTE);
    const route = routes.find((r) => (byId ? r.id === ROUTE : r.name.toLowerCase().includes(ROUTE.toLowerCase())));
    if (!route?.path?.length) throw new Error(`No route matched "${ROUTE}".`);
    const repId = MARKETER
      ? marketers.find((m) => m.name.toLowerCase().includes(MARKETER.toLowerCase()))?.id
      : assignments.find((a) => a.route_id === route.id)?.marketer_id;
    const rep = marketers.find((m) => m.id === repId) ?? marketers[0];
    plans = [{ marketer: rep, routeId: route.id, plan: planFromRoute(route.path, N_STOPS) }];
  } else if (ALL) {
    // Every rep walks a (split) segment of their assigned route, concurrently.
    const routeById = new Map(routes.map((r) => [r.id, r]));
    const repsByRoute = new Map();
    for (const a of assignments) (repsByRoute.get(a.route_id) ?? repsByRoute.set(a.route_id, []).get(a.route_id)).push(a.marketer_id);
    const chosen = MARKETER ? marketers.filter((m) => m.name.toLowerCase().includes(MARKETER.toLowerCase())) : marketers;
    plans = chosen.map((m, i) => {
      const a = assignments.find((x) => x.marketer_id === m.id);
      const route = a && routeById.get(a.route_id);
      if (route?.path?.length) {
        const reps = repsByRoute.get(route.id) ?? [m.id];
        const k = Math.max(0, reps.indexOf(m.id));
        const n = reps.length || 1;
        const L = route.path.length;
        const seg = route.path.slice(Math.floor((k * L) / n), Math.floor(((k + 1) * L) / n));
        return { marketer: m, routeId: route.id, plan: planFromRoute(seg.length > 1 ? seg : route.path, N_STOPS) };
      }
      return { marketer: m, routeId: null, plan: planSynthetic({ lat: 45.413 + i * 0.001, lng: -73.913 + i * 0.0035 }, N_STOPS) };
    });
  } else {
    plans = [{ marketer: marketers[0], routeId: null, plan: planSynthetic({ lat: 45.413, lng: -73.913 }, N_STOPS) }];
  }

  console.log(`Simulating ${plans.length} rep(s) against ${BASE} - ${DELAY}ms cadence${DEMO ? " (DEMO)" : ""}`);
  console.log("Open /sessions to watch them go live, /coverage for the team map.\n");

  const summaries = await Promise.all(plans.map((p) => runMarketer({ ...p, teamId })));

  console.log("\n── summary ──");
  let okAll = 0, total = 0;
  for (const s of summaries) {
    const ok = s.results.filter((r) => r.expected === r.got).length;
    okAll += ok; total += s.results.length;
    console.log(`  ${s.marketer.padEnd(16)} ${ok}/${s.results.length} doors - ${BASE}/sessions/${s.sessionId}`);
  }
  console.log(`\n✅ Done. Door classification ${okAll}/${total} as planted. Check /sessions, /leads, /coverage.`);
}

main().catch((e) => {
  console.error("\n❌ Simulation failed:", e.message);
  process.exit(1);
});
