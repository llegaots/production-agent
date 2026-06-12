import { supabaseRead } from "@/lib/supabase/server";
import { snapToRoads, roadsConfigured } from "@/lib/geo/roads";
import type { LatLng } from "@/lib/types";

export const runtime = "nodejs";

// Per-session cache so we snap to roads at most ~once / 4s (the manager polls
// every 1.5s). Between snaps we append the new raw points so the dot still moves.
const snapCache = new Map<string, { at: number; len: number; path: LatLng[] }>();

async function snappedTrail(sessionId: string, raw: LatLng[]): Promise<LatLng[]> {
  if (!roadsConfigured() || raw.length < 2) return raw;
  const cached = snapCache.get(sessionId);
  const now = Date.now();
  if (cached && cached.len === raw.length) return cached.path;
  if (cached && now - cached.at < 4000) return [...cached.path, ...raw.slice(cached.len)];
  const path = await snapToRoads(raw);
  snapCache.set(sessionId, { at: now, len: raw.length, path });
  return path;
}

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

  const rawTrail = Array.isArray(row.trail_path) ? (row.trail_path as LatLng[]) : [];
  const trailPath = await snappedTrail(id, rawTrail);

  return Response.json({
    lat: typeof row.lat === "number" ? row.lat : null,
    lng: typeof row.lng === "number" ? row.lng : null,
    trailPath,
    status: (row.status as string) ?? null,
  });
}
