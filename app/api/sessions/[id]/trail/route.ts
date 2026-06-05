import { supabaseRead } from "@/lib/supabase/server";

export const runtime = "nodejs";

/** Current position + persisted walked trail for one session. Polled by the
 *  manager view as a reliable fallback for the live trace, so it shows even if
 *  Realtime UPDATE events are flaky or migration 0010 (trail_path) isn't applied. */
export async function GET(_req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const db = supabaseRead();
  if (!db) return Response.json({ lat: null, lng: null, trailPath: [], status: null });

  // Try with trail_path; if the column isn't there yet, fall back without it.
  let row: Record<string, unknown> | null = null;
  const withTrail = await db.from("D2D_Sessions").select("lat,lng,status,trail_path").eq("id", id).maybeSingle();
  if (withTrail.error) {
    const basic = await db.from("D2D_Sessions").select("lat,lng,status").eq("id", id).maybeSingle();
    row = basic.data ?? null;
  } else {
    row = withTrail.data ?? null;
  }
  if (!row) return Response.json({ error: "Not found" }, { status: 404 });

  return Response.json({
    lat: typeof row.lat === "number" ? row.lat : null,
    lng: typeof row.lng === "number" ? row.lng : null,
    trailPath: Array.isArray(row.trail_path) ? row.trail_path : [],
    status: (row.status as string) ?? null,
  });
}
