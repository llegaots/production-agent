import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

/** Start a live recording session for a rep. Returns the new session id; the
 *  rep's capture screen then streams audio to Deepgram and transcript to us. */
export async function POST(req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const marketerId = body.marketerId ? String(body.marketerId) : null;
  if (!marketerId) return Response.json({ error: "marketerId is required." }, { status: 400 });

  const db = supabaseAdmin();
  const { data: session, error } = await db
    .from("D2D_Sessions")
    .insert({
      team_id: body.teamId ? String(body.teamId) : null,
      marketer_id: marketerId,
      route_id: body.routeId ? String(body.routeId) : null,
      shift_id: body.shiftId ? String(body.shiftId) : null,
      territory: body.territory ? String(body.territory) : null,
      status: "live",
      lat: typeof body.lat === "number" ? body.lat : null,
      lng: typeof body.lng === "number" ? body.lng : null,
    })
    .select("id")
    .single();

  if (error) {
    const hint = /Could not find the table/.test(error.message)
      ? " — run supabase/migrations/0006_sessions.sql first."
      : "";
    return Response.json({ error: error.message + hint }, { status: 500 });
  }

  // Mark the rep live so the dashboard / sessions grid reflect it.
  await db.from("D2D_Marketers").update({ status: "live" }).eq("id", marketerId);

  return Response.json({ sessionId: session.id });
}
