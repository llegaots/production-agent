import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

/** Update the rep's live GPS position for the session. Called frequently while
 *  recording (throttled by the client) — kept lightweight; just patches lat/lng.
 *  The UPDATE fans out to the manager's map via Supabase Realtime. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  const { id: sessionId } = await params;
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const lat = typeof body.lat === "number" ? body.lat : null;
  const lng = typeof body.lng === "number" ? body.lng : null;
  if (lat === null || lng === null) {
    return Response.json({ error: "lat and lng are required." }, { status: 400 });
  }

  const db = supabaseAdmin();
  const { error } = await db.from("D2D_Sessions").update({ lat, lng }).eq("id", sessionId);
  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json({ ok: true });
}
