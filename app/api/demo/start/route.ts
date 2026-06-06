import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { buildPlans, createDemoSessions, playDemo, type DemoMarketer } from "@/lib/demo/runner";

export const runtime = "nodejs";
export const maxDuration = 800; // local demo playback runs for a few minutes

/** Kick off the live field demo: create a session per seeded rep, then play them
 *  walking their routes in the background (GPS + transcript + doors → classify,
 *  detect leads, grade). Returns immediately with the started session ids. */
export async function POST(req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }

  let body: { delayMs?: number; stops?: number } = {};
  try {
    body = await req.json();
  } catch {
    /* optional body */
  }
  const delayMs = Math.max(300, Math.min(6000, Number(body.delayMs) || 1800));
  const stops = Math.max(3, Math.min(20, Number(body.stops) || 8));

  const db = supabaseAdmin();
  const [{ data: teams }, { data: marketers }, { data: routes }, { data: assignments }] = await Promise.all([
    db.from("D2D_Teams").select("id").limit(1),
    db.from("D2D_Marketers").select("id,name,home_territory").order("joined_at", { ascending: true }),
    db.from("D2D_Routes").select("id,name,path"),
    db.from("D2D_RouteAssignments").select("route_id,marketer_id"),
  ]);

  if (!marketers?.length) {
    return Response.json(
      { error: "No marketers found. Seed the demo first: run `npm run demo:seed`." },
      { status: 400 },
    );
  }

  // Reap orphaned live sessions first: a previous demo whose background playback
  // loop died (typically a dev-server restart) leaves sessions stuck at 'live'
  // forever, which would otherwise block every future demo. A healthy demo
  // auto-ends at ~maxMs (10 min), so anything still live past that window is
  // certainly orphaned and safe to close. Genuinely-recent live reps still block
  // (the 409 below), so we never stomp an actually-running demo.
  const STALE_AFTER_MS = 11 * 60 * 1000;
  const { data: liveRows } = await db
    .from("D2D_Sessions")
    .select("id,marketer_id,started_at")
    .eq("status", "live");
  const liveSessions = liveRows ?? [];
  const staleCutoff = Date.now() - STALE_AFTER_MS;
  const stale = liveSessions.filter((s) => new Date(s.started_at as string).getTime() < staleCutoff);
  const fresh = liveSessions.filter((s) => new Date(s.started_at as string).getTime() >= staleCutoff);
  if (stale.length) {
    const now = new Date().toISOString();
    for (const s of stale) {
      await db.from("D2D_Sessions").update({ status: "completed", ended_at: now }).eq("id", s.id as string);
      if (s.marketer_id) await db.from("D2D_Marketers").update({ status: "offline" }).eq("id", s.marketer_id as string);
    }
  }
  if (fresh.length) {
    return Response.json(
      { error: "Reps are already live. Press Stop demo to end them before starting a new one." },
      { status: 409 },
    );
  }

  const teamId = (teams?.[0]?.id as string) ?? null;
  const plans = buildPlans(
    marketers as DemoMarketer[],
    (routes ?? []).map((r) => ({ id: r.id as string, name: r.name as string, path: (r.path as { lat: number; lng: number }[]) ?? [] })),
    (assignments ?? []).map((a) => ({ route_id: a.route_id as string, marketer_id: a.marketer_id as string })),
    stops,
  );

  const sessions = await createDemoSessions(teamId, plans);
  if (!sessions.length) {
    return Response.json({ error: "Could not start any sessions." }, { status: 500 });
  }

  const base = process.env.DEMO_BASE_URL?.replace(/\/$/, "") || new URL(req.url).origin;
  after(async () => {
    await playDemo(base, sessions, delayMs);
  });

  return Response.json({
    started: sessions.length,
    sessionIds: sessions.map((s) => s.sessionId),
  });
}
