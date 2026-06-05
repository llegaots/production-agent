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

  // Don't pile a second demo on top of reps already live.
  const { data: liveRows } = await db.from("D2D_Sessions").select("id").eq("status", "live").limit(1);
  if (liveRows?.length) {
    return Response.json(
      { error: "Reps are already live. End the current sessions before starting a new demo." },
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
