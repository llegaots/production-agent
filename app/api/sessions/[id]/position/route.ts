import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { haversine } from "@/lib/geo/util";

export const runtime = "nodejs";

const MIN_STEP_M = 8; // only append a trail point after moving this far
const MAX_TRAIL = 1500; // cap the stored trail length

/** Update the rep's live GPS position, and (best-effort) append it to the
 *  persisted walked trail. The lat/lng update ALWAYS runs so the live dot + trace
 *  keep moving even if the `trail_path` column (migration 0010) isn't applied yet
 *  - in that case the manager view rebuilds the trace from the live points. */
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
  const update: Record<string, unknown> = { lat, lng };

  // If the trail_path column exists, append a downsampled point to it. selErr is
  // set (column missing) when 0010 hasn't been applied - we just skip the trail.
  const { data: row, error: selErr } = await db
    .from("D2D_Sessions")
    .select("trail_path")
    .eq("id", sessionId)
    .maybeSingle();
  if (!selErr && row && Array.isArray(row.trail_path)) {
    const trail = row.trail_path as { lat: number; lng: number }[];
    const last = trail[trail.length - 1];
    if (!last || haversine(last, { lat, lng }) >= MIN_STEP_M) {
      update.trail_path = [...trail, { lat, lng }].slice(-MAX_TRAIL);
    }
  }

  const { error } = await db.from("D2D_Sessions").update(update).eq("id", sessionId);
  if (error) {
    // A stray trail_path write failure must never block the live position.
    if (update.trail_path) {
      const { error: e2 } = await db.from("D2D_Sessions").update({ lat, lng }).eq("id", sessionId);
      if (e2) return Response.json({ error: e2.message }, { status: 500 });
    } else {
      return Response.json({ error: error.message }, { status: 500 });
    }
  }
  return Response.json({ ok: true });
}
