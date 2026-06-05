import { supabaseRead } from "@/lib/supabase/server";

export const runtime = "nodejs";

/** Positions + walked trails for all live sessions. Polled by the sessions grid
 *  so the overview cards show the moving dot + trace without depending on
 *  Realtime UPDATE events (which can be flaky). */
export async function GET() {
  const db = supabaseRead();
  if (!db) return Response.json({ sessions: [] });

  let rows: Record<string, unknown>[] = [];
  const withTrail = await db.from("D2D_Sessions").select("id,lat,lng,trail_path").eq("status", "live");
  if (withTrail.error) {
    const basic = await db.from("D2D_Sessions").select("id,lat,lng").eq("status", "live");
    rows = basic.data ?? [];
  } else {
    rows = withTrail.data ?? [];
  }

  return Response.json({
    sessions: rows.map((r) => ({
      id: r.id as string,
      lat: typeof r.lat === "number" ? r.lat : null,
      lng: typeof r.lng === "number" ? r.lng : null,
      trailPath: Array.isArray(r.trail_path) ? r.trail_path : [],
    })),
  });
}
