#!/usr/bin/env node
/* ----------------------------------------------------------------------------
   RouteIQ - Demo seed.

   Wipes ALL D2D data and seeds a clean, self-contained demo for a fictional
   window-cleaning company (CrystalClear) operating in the H9X / Baie-D'Urfe
   (West Island, Montréal) area: a team, field reps, real routes (reusing the
   genuine street geometry already in your DB), scheduled shifts, and a
   window-cleaning playbook (script + objection handles + grading criteria).

   Then run `npm run demo` to play live sessions along these routes.

   Usage:  npm run demo:seed
   Requires .env.local with SUPABASE_SERVICE_ROLE_KEY + NEXT_PUBLIC_SUPABASE_URL.
---------------------------------------------------------------------------- */
import fs from "node:fs";

function readEnv() {
  const txt = fs.readFileSync(new URL("../.env.local", import.meta.url), "utf8");
  return Object.fromEntries(
    txt.split("\n").filter((l) => l.includes("=") && !l.trim().startsWith("#")).map((l) => {
      const i = l.indexOf("=");
      return [l.slice(0, i).trim(), l.slice(i + 1).replace(/["']/g, "").trim()];
    }),
  );
}
const env = readEnv();
const SB_URL = env.NEXT_PUBLIC_SUPABASE_URL;
const KEY = env.SUPABASE_SERVICE_ROLE_KEY;
if (!SB_URL || !KEY) {
  console.error("Missing NEXT_PUBLIC_SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in .env.local");
  process.exit(1);
}
const H = {
  apikey: KEY,
  Authorization: `Bearer ${KEY}`,
  "Content-Type": "application/json",
  Prefer: "return=representation",
};
const rest = (method, path, body) =>
  fetch(`${SB_URL}/rest/v1/${path}`, { method, headers: H, body: body ? JSON.stringify(body) : undefined });
async function wipe(table) {
  // PostgREST needs a filter to delete; this matches every real row.
  const r = await rest("DELETE", `${table}?id=neq.00000000-0000-0000-0000-000000000000`);
  if (!r.ok && r.status !== 404 && r.status !== 400) {
    console.warn(`  (couldn't wipe ${table}: ${r.status})`);
  }
}
async function insert(table, rows) {
  const r = await rest("POST", table, rows);
  if (!r.ok) throw new Error(`Insert ${table} failed (${r.status}): ${await r.text()}`);
  return r.json();
}

// ── fixed demo IDs ───────────────────────────────────────────────────────────
const TEAM = "d2d70000-0000-0000-0000-0000000000d0";
const PB = "d2d70000-0000-0000-0000-0000000000df";
const M = ["d1", "d2", "d3", "d4"].map((s) => `d2d70000-0000-0000-0000-0000000000${s}`);
const today = new Date().toISOString().slice(0, 10);

const lerp = (a, b, t) => a + (b - a) * t;
// A boustrophedon (lawnmower) canvassing route across a few blocks of an area,
// so each rep gets their OWN distinct route in their OWN neighbourhood.
function areaRoute(center) {
  const path = [];
  const rows = 4;
  const span = 0.0052; // ~520 m wide
  const gap = 0.0011; // ~110 m between streets
  for (let r = 0; r < rows; r++) {
    const lat = center.lat + r * gap - ((rows - 1) * gap) / 2;
    const x0 = center.lng - span / 2;
    const x1 = center.lng + span / 2;
    const fwd = r % 2 === 0;
    const a = fwd ? x0 : x1;
    const b = fwd ? x1 : x0;
    for (let t = 0; t <= 1.0001; t += 0.12) path.push({ lat, lng: lerp(a, b, t) });
    if (r < rows - 1) path.push({ lat: lat + gap, lng: b }); // connector up to next street
  }
  return path;
}

// One distinct West Island neighbourhood per rep (matches their territory).
const marketers = [
  { id: M[0], name: "Liam Tremblay", tint: "emerald", territory: "Baie-D'Urfé North", center: { lat: 45.4185, lng: -73.9075 } },
  { id: M[1], name: "Chloé Bergeron", tint: "sky", territory: "Baie-D'Urfé South", center: { lat: 45.4085, lng: -73.9150 } },
  { id: M[2], name: "Noah Gagnon", tint: "violet", territory: "Beaconsfield", center: { lat: 45.4300, lng: -73.8640 } },
  { id: M[3], name: "Maya Singh", tint: "amber", territory: "Kirkland", center: { lat: 45.4475, lng: -73.8720 } },
];

const playbook = {
  id: PB,
  team_id: TEAM,
  script_title: "Student Works - Canvassing Script",
  script: `OPENER (keep it light, 6 quick points)
"Hey, happy {weekday}! How's it going?"
1. Greeting.
2. Your name + school: "My name is {name}, I'm a student at {school}."
3. Who you're with: "This is our 3rd year running our business here in {city/area}."
4. Neighbour reference: "I was just speaking with your neighbour {neighbour}..."
5. The offer (below).
6. An open-ended question that starts with "what" (below).

THE OFFER
"We're in the neighbourhood offering FREE ESTIMATES for interior and exterior
painting and staining, as well as window cleaning and eavestrough cleaning."

OPEN-ENDED QUESTION (must start with "what")
"What projects could we take off your hands this year?"

MINDSET
- An objection is a "Yes, but...": yes I have a project, but I don't want you to do it.
- We are not here to change minds. We just want to get in front of the people already
  thinking about painting, staining, window or eavestrough cleaning.
- Wherever a step says "IF YES", you do not actually let them say yes. Handle the
  objection, then go straight into: "What was your name again, sorry?"

OBJECTIONS (acknowledge and ignore, reframe, then ask for the estimate)
Handle each of: "I do all my own painting", "I did all my painting last year",
"We don't have anything to paint", "I already have a painter", "It's too early to
make decisions", "We don't want to use students".
- IF NO: "No worries, can I follow up with you later in the spring or summer?" If still
  no, give a flyer, and get the name for the next door: "Sorry, I didn't catch your name?"
- IF YES: "What was your name again, sorry?" Look down at the clipboard and do not look
  up until they give you all the info. Give the flyer. "Jimmy will be reaching out in the
  next few days. Have a great day!"

HOW TO HANDLE A YES
- Do not show excitement. Stay level headed and collect everything (it shows
  professionalism). Celebrate once you're back in the car.
- Collect: name, at least 2 numbers (home, cell, work, partner's) -
  "What's another number I can reach you at in case I can't get you?", email, and the
  best time of day to call.

ASKING FOR A LAWN SIGN (a friendly homeowner on a busy street, after they decline)
"I understand. If I told you there was a way to help me out that wouldn't cost you
anything, would you be open to it?"
"I'm a student so my marketing budget is limited, and your house gets a lot of traffic.
If you'd let me put a lawn sign on your property for the first 2 weeks of April, it would
generate work for my crew without you doing anything. Would that be ok?"`,
  objections: [
    { id: "obj-diy", trigger: "I do all my own painting", category: "need", handle: "Acknowledge and ignore: 'Amazing, where do you find the time?' Then: 'Wouldn't it make sense to book a free estimate just to see if it makes sense for us to take the project off your hands?' If no, offer a spring or summer follow up; if still no, leave a flyer. Either way capture the name for the next door.", frequency: 48, successRate: 41 },
    { id: "obj-last-year", trigger: "I did all my painting last year", category: "need", handle: "Acknowledge: 'Amazing, what work did you get done last year?' Then surface what they did NOT mention: 'A lot of your neighbours needed work on their (item they didn't mention), when did you last think about that?' Propose a free estimate. If no, follow up later or leave a flyer, and capture the name.", frequency: 39, successRate: 44 },
    { id: "obj-nothing", trigger: "We don't have anything to paint", category: "need", handle: "Acknowledge: 'Got it, when did you last paint, interior or exterior?' Mention neighbours taking care of the opposite (whichever they didn't say), then ask when they last considered it. Propose a free estimate. If no, follow up later or leave a flyer, and capture the name.", frequency: 52, successRate: 38 },
    { id: "obj-have-painter", trigger: "I already have a painter", category: "trust", handle: "Acknowledge: 'Fantastic, what were you planning to have them paint this year?' If they name a project: 'A lot of your neighbours have their own painter too, but most loved giving students a shot, especially since we have multiple teams and can start earlier in the season.' Brief pause, then propose a free estimate. If no, follow up later or leave a flyer, and capture the name.", frequency: 33, successRate: 46 },
    { id: "obj-too-early", trigger: "It's too early to make decisions", category: "timing", handle: "Reframe: 'Now is actually the best time to book, you can check it off your list, and the only way to guarantee early-summer work is to book now. We also have a 10% early-season special.' Then ask what projects they're considering. If a project, propose a free estimate. If no, follow up later or leave a flyer, and capture the name.", frequency: 44, successRate: 52 },
    { id: "obj-no-students", trigger: "We don't want to use students", category: "trust", handle: "Acknowledge: 'I completely get it, as young professionals we have a lot to prove. We go through expert training, our name is on the line, and referrals from quality work are how we grow.' Then: 'Let's schedule an estimate, and if we don't completely blow you away, I wouldn't want you to book with us.' If no, ask to follow up in spring, and capture the name.", frequency: 18, successRate: 49 },
  ],
  grading_criteria: [
    { id: "opener", label: "Opener & rapport", weight: 20, description: "Warm greeting, gives their name and school, mentions it's the 3rd year of the business in the area, and references a neighbour." },
    { id: "offer", label: "Offer clarity", weight: 15, description: "Clearly states FREE estimates for interior and exterior painting and staining, plus window and eavestrough cleaning." },
    { id: "discovery", label: "Open-ended question", weight: 15, description: "Asks an open-ended question starting with 'what' about projects, e.g. 'What projects could we take off your hands this year?'" },
    { id: "objections", label: "Objection handling", weight: 30, description: "Acknowledges and ignores the objection, reframes using neighbours and value, asks to book a free estimate, and offers a follow up or flyer on a no." },
    { id: "close", label: "Close & info capture", weight: 20, description: "On a yes, stays composed (no over-excitement) and collects the name, at least 2 phone numbers, email, and best time to call." },
  ],
};

async function main() {
  console.log("Wiping all D2D data…");
  for (const t of [
    "D2D_TranscriptLines", "D2D_AgentInsights", "D2D_DoorEvents", "D2D_Leads",
    "D2D_Sessions", "D2D_RouteAssignments", "D2D_Shifts", "D2D_Routes",
    "D2D_RouteGenerations", "D2D_Playbooks", "D2D_Marketers", "D2D_Teams",
  ]) {
    await wipe(t);
  }

  console.log("Seeding team + marketers…");
  await insert("D2D_Teams", [{ id: TEAM, name: "Student Works Painting" }]);
  await insert(
    "D2D_Marketers",
    marketers.map((m) => ({
      id: m.id, team_id: TEAM, name: m.name, avatar_tint: m.tint,
      status: "offline", home_territory: m.territory, joined_at: "2025-09-01",
    })),
  );

  console.log("Seeding 4 routes (one per rep, in their own neighbourhood)…");
  const routeRows = marketers.map((m) => {
    const path = areaRoute(m.center);
    return {
      team_id: TEAM,
      name: `Student Works - ${m.territory}`,
      territory: m.territory,
      status: "active",
      path,
      doors_planned: Math.max(24, Math.round(path.length / 2)),
      scheduled_for: today,
    };
  });
  const routes = await insert("D2D_Routes", routeRows); // routes[i] belongs to marketers[i]

  // One rep per route (each rep is solo in their own area for the demo).
  await insert(
    "D2D_RouteAssignments",
    marketers.map((m, i) => ({ route_id: routes[i].id, marketer_id: m.id })),
  );

  console.log("Seeding scheduled shifts (today 09:00-13:00)…");
  await insert(
    "D2D_Shifts",
    marketers.map((m, i) => ({
      marketer_id: m.id,
      route_id: routes[i].id,
      date: today, start_time: "09:00", end_time: "13:00", status: "scheduled",
    })),
  );

  console.log("Seeding painting playbook…");
  await insert("D2D_Playbooks", [playbook]);

  console.log("\n✅ Demo seeded. Student Works Painting is ready.");
  console.log("   • Team: Student Works Painting (4 student reps, 4 routes across the West Island)");
  console.log("   • Playbook: /playbook   • Schedule: /schedule   • Coverage: /coverage");
  console.log("\nNow run:  npm run demo      (live sessions walking the routes)\n");
}

main().catch((e) => {
  console.error("\n❌ Demo seed failed:", e.message);
  process.exit(1);
});
