import "server-only";
import { supabaseAdmin } from "@/lib/supabase/server";

/* ----------------------------------------------------------------------------
   Server-side demo runner - the UI "Start live demo" button kicks this off.
   It mirrors scripts/simulate-session.mjs: creates a live session per seeded rep,
   then (in the background) walks each rep along their route - streaming GPS
   positions, doorstep conversations, and knock outcomes through the SAME API the
   real recorder uses. Everything downstream is real: transcript persistence, door
   classification, lead detection, and post-shift grading against the playbook.
---------------------------------------------------------------------------- */

type LatLng = { lat: number; lng: number };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const pick = <T>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)];

// ── Student Works canvassing pool: each rep actually runs the script (opener +
//    name/school/3rd year/neighbour, the offer, an open-ended "what" question,
//    the approved objection handles, and collecting name + 2 numbers + email on a
//    yes). Only the lead scenarios give full contact, so leads = name + phone. ──
type Line = [string, string];
const POOL: Record<string, ((n: string) => Line[])[]> = {
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
const WEIGHTS: [string, number][] = [
  ["no-answer", 0.42], ["not-interested", 0.22], ["answered", 0.14], ["lead", 0.15], ["callback", 0.07],
];
function weightedKind(): string {
  let r = Math.random();
  for (const [k, w] of WEIGHTS) if ((r -= w) <= 0) return k;
  return "no-answer";
}
function assembleScenario(repFirst: string, n: number) {
  return Array.from({ length: n }, () => {
    const kind = weightedKind();
    return { kind, lines: pick(POOL[kind])(repFirst) };
  });
}

// ── geometry ─────────────────────────────────────────────────────────────────
// `house` = the point on the street the rep walks to; `door` = the actual home,
// offset perpendicular off the road so the pin lands on the house (not the road).
interface Stop { house: LatLng; door: LatLng; walk: LatLng[] }
function samplePoints(arr: LatLng[], n: number): LatLng[] {
  if (arr.length <= n) return arr;
  const out: LatLng[] = [];
  for (let i = 0; i < n; i++) out.push(arr[Math.round((i / (n - 1)) * (arr.length - 1))]);
  return out;
}
/** A point ~15 m perpendicular off the street toward a home, alternating sides. */
function homeOff(prev: LatLng, house: LatLng, side: number): LatLng {
  const dx = house.lng - prev.lng;
  const dy = house.lat - prev.lat;
  const len = Math.hypot(dx, dy) || 1;
  const px = -dy / len; // perpendicular unit (lng)
  const py = dx / len; //  perpendicular unit (lat)
  const off = 0.00015 * side;
  return { lat: house.lat + py * off, lng: house.lng + px * off };
}
function planFromRoute(path: LatLng[], nStops: number): Stop[] {
  const L = path.length;
  const plan: Stop[] = [];
  let prev = 0;
  for (let i = 0; i < nStops; i++) {
    const idx = Math.max(0, Math.min(L - 1, Math.round(((i + 1) / (nStops + 1)) * (L - 1))));
    const walk = samplePoints(path.slice(prev, idx + 1), 6);
    const house = path[idx];
    const before = walk[walk.length - 2] ?? path[Math.max(0, idx - 1)] ?? house;
    plan.push({ house, door: homeOff(before, house, i % 2 === 0 ? 1 : -1), walk });
    prev = idx;
  }
  return plan;
}
function planSynthetic(base: LatLng, nStops: number): Stop[] {
  const plan: Stop[] = [];
  let prev = { lat: base.lat - 0.0006, lng: base.lng };
  for (let i = 0; i < nStops; i++) {
    const house = { lat: base.lat + i * 0.00022, lng: base.lng };
    const walk: LatLng[] = [];
    for (let k = 1; k <= 4; k++) walk.push({ lat: lerp(prev.lat, house.lat, k / 4), lng: lerp(prev.lng, house.lng, k / 4) });
    plan.push({ house, door: homeOff(prev, house, i % 2 === 0 ? 1 : -1), walk });
    prev = house;
  }
  return plan;
}

export interface DemoMarketer { id: string; name: string; home_territory?: string | null }
interface DemoRoute { id: string; name: string; path: LatLng[] }
interface Assignment { route_id: string; marketer_id: string }
export interface DemoPlan { marketer: DemoMarketer; routeId: string | null; plan: Stop[] }

/** Build a plan per rep: walk a split segment of their assigned route; reps with
 *  no route get a synthetic walk so the demo always has something to show. */
export function buildPlans(
  marketers: DemoMarketer[],
  routes: DemoRoute[],
  assignments: Assignment[],
  nStops: number,
): DemoPlan[] {
  const routeById = new Map(routes.map((r) => [r.id, r]));
  const repsByRoute = new Map<string, string[]>();
  for (const a of assignments) {
    const list = repsByRoute.get(a.route_id) ?? [];
    list.push(a.marketer_id);
    repsByRoute.set(a.route_id, list);
  }
  return marketers.map((m, i) => {
    const a = assignments.find((x) => x.marketer_id === m.id);
    const route = a ? routeById.get(a.route_id) : undefined;
    if (route?.path?.length) {
      const reps = repsByRoute.get(route.id) ?? [m.id];
      const k = Math.max(0, reps.indexOf(m.id));
      const n = reps.length || 1;
      const L = route.path.length;
      const seg = route.path.slice(Math.floor((k * L) / n), Math.floor(((k + 1) * L) / n));
      return { marketer: m, routeId: route.id, plan: planFromRoute(seg.length > 1 ? seg : route.path, nStops) };
    }
    return { marketer: m, routeId: null, plan: planSynthetic({ lat: 45.413 + i * 0.001, lng: -73.913 + i * 0.0035 }, nStops) };
  });
}

const post = (base: string, path: string, body: unknown) =>
  fetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null);

/** Create a live session row per rep up front (so the UI shows them immediately)
 *  and mark each rep live. Returns the started sessions. */
export async function createDemoSessions(
  teamId: string | null,
  plans: DemoPlan[],
): Promise<{ sessionId: string; plan: DemoPlan }[]> {
  const db = supabaseAdmin();
  const out: { sessionId: string; plan: DemoPlan }[] = [];
  for (const p of plans) {
    const { data: row } = await db
      .from("D2D_Sessions")
      .insert({
        team_id: teamId,
        marketer_id: p.marketer.id,
        route_id: p.routeId,
        territory: p.marketer.home_territory ?? null,
        status: "live",
        lat: p.plan[0]?.house.lat ?? null,
        lng: p.plan[0]?.house.lng ?? null,
      })
      .select("id")
      .single();
    if (row?.id) {
      out.push({ sessionId: row.id as string, plan: p });
      await db.from("D2D_Marketers").update({ status: "live" }).eq("id", p.marketer.id);
    }
  }
  return out;
}

/** Has the session been stopped (status flipped off 'live' by the Stop control)? */
async function isStopped(sessionId: string): Promise<boolean> {
  const { data } = await supabaseAdmin().from("D2D_Sessions").select("status").eq("id", sessionId).maybeSingle();
  return !data || data.status !== "live";
}

/** Play one rep: a full first pass (walk + conversations + door outcomes), then
 *  keep them alive walking the route back and forth until `maxMs` elapses or the
 *  demo is stopped. Ends the session only if it wasn't stopped externally. */
async function playSession(base: string, sessionId: string, plan: DemoPlan, delayMs: number, maxMs: number) {
  const repFirst = plan.marketer.name.split(" ")[0];
  const stops = assembleScenario(repFirst, plan.plan.length);
  let seq = 0;
  const t0 = Date.now();
  let stopped = false;

  for (let s = 0; s < stops.length; s++) {
    if (await isStopped(sessionId)) {
      stopped = true;
      break;
    }
    const { house, walk } = plan.plan[s];
    if (s > 0) {
      await post(base, `/api/sessions/${sessionId}/transcript`, {
        lines: [{ seq, at: new Date().toISOString(), speaker: "agent", text: "(walking to the next home - no conversation)", isFinal: true }],
      });
      seq += 1;
      await sleep(delayMs);
    }
    for (const p of walk) {
      await post(base, `/api/sessions/${sessionId}/position`, p);
      await sleep(delayMs / 3);
    }
    await post(base, `/api/sessions/${sessionId}/position`, house);

    const fromSeq = seq;
    for (const [speaker, text] of stops[s].lines) {
      await post(base, `/api/sessions/${sessionId}/transcript`, {
        lines: [{ seq, at: new Date().toISOString(), speaker, text, isFinal: true }],
      });
      seq += 1;
      await sleep(delayMs);
    }
    const toSeq = seq - 1;
    const door = plan.plan[s].door;
    await post(base, `/api/sessions/${sessionId}/doors`, { lat: door.lat, lng: door.lng, fromSeq, toSeq, at: new Date().toISOString() });
    await sleep(delayMs);
  }

  // Patrol: keep the rep on the map, walking the route back and forth, so the
  // session stays live for the full duration (the door pins/transcript persist).
  const patrolPts = plan.plan.flatMap((s) => [...s.walk, s.house]);
  let i = 0;
  let dir = 1;
  let tick = 0;
  while (!stopped && patrolPts.length > 1 && Date.now() - t0 < maxMs) {
    if (tick % 4 === 0 && (await isStopped(sessionId))) {
      stopped = true;
      break;
    }
    await post(base, `/api/sessions/${sessionId}/position`, patrolPts[i]);
    i += dir;
    if (i >= patrolPts.length - 1 || i <= 0) dir = -dir;
    tick += 1;
    await sleep(delayMs);
  }

  if (!stopped) {
    const durationSec = Math.round((Date.now() - t0) / 1000);
    await post(base, `/api/sessions/${sessionId}/end`, { durationSec });
  }
}

/** Play all sessions concurrently (call from `after()`). `maxMs` caps how long
 *  the reps keep walking before auto-ending (the Stop control ends them sooner). */
export async function playDemo(
  base: string,
  sessions: { sessionId: string; plan: DemoPlan }[],
  delayMs: number,
  maxMs = 10 * 60 * 1000,
) {
  await Promise.all(sessions.map((s) => playSession(base, s.sessionId, s.plan, delayMs, maxMs)));
}
