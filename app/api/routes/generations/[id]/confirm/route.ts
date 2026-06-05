import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import type { GeoCache } from "@/lib/agent/preview";
import type { RoutePreview } from "@/lib/types";

export const runtime = "nodejs";

export async function POST(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  const { id } = await params;
  const db = supabaseAdmin();

  const { data: row, error } = await db
    .from("D2D_RouteGenerations")
    .select("team_id,area_input,status,preview,geo_cache")
    .eq("id", id)
    .maybeSingle();
  if (error) return Response.json({ error: error.message }, { status: 500 });
  if (!row) return Response.json({ error: "Generation not found." }, { status: 404 });
  if (row.status === "confirmed") return Response.json({ error: "Already scheduled." }, { status: 400 });

  const preview = row.preview as RoutePreview | null;
  const cache = row.geo_cache as GeoCache | null;
  if (!preview?.routes?.length) {
    return Response.json({ error: "No preview to confirm." }, { status: 400 });
  }

  const teamId = (row.team_id as string) ?? null;
  const date = preview.date;
  const windowById = new Map((cache?.marketers ?? []).map((m) => [m.id, { start: m.start, end: m.end }]));
  const routeIds: string[] = [];

  try {
    for (const r of preview.routes) {
      if (r.path.length < 2) continue;
      const lats = r.path.map((p) => p.lat);
      const lngs = r.path.map((p) => p.lng);
      const { data: routeId, error: insErr } = await db.rpc("d2d_insert_route", {
        p_team_id: teamId,
        p_generation_id: id,
        p_name: r.name,
        p_territory: r.territory,
        p_area_input: row.area_input as string,
        p_status: "scheduled",
        p_path: r.path,
        p_bounds: { minLat: Math.min(...lats), maxLat: Math.max(...lats), minLng: Math.min(...lngs), maxLng: Math.max(...lngs) },
        p_doors_planned: r.doors,
        p_scheduled_for: date,
      });
      if (insErr) throw new Error(`insert route failed: ${insErr.message}`);
      const rid = routeId as string;
      routeIds.push(rid);

      if (r.marketerIds.length) {
        const { error: aErr } = await db
          .from("D2D_RouteAssignments")
          .insert(r.marketerIds.map((mid) => ({ route_id: rid, marketer_id: mid })));
        if (aErr) throw new Error(`assignment failed: ${aErr.message}`);
      }

      // schedule each crew member: link their shift that day to this route (create one if absent)
      for (const mid of r.marketerIds) {
        const { data: shift } = await db
          .from("D2D_Shifts")
          .select("id")
          .eq("marketer_id", mid)
          .eq("date", date)
          .maybeSingle();
        if (shift) {
          await db.from("D2D_Shifts").update({ route_id: rid }).eq("id", shift.id as string);
        } else {
          const w = windowById.get(mid) ?? { start: "16:00", end: "21:00" };
          await db.from("D2D_Shifts").insert({
            marketer_id: mid,
            route_id: rid,
            date,
            start_time: w.start,
            end_time: w.end,
            status: "scheduled",
          });
        }
      }
    }

    await db
      .from("D2D_RouteGenerations")
      .update({ status: "confirmed", stage: "Scheduled", completed_at: new Date().toISOString() })
      .eq("id", id);
  } catch (e) {
    return Response.json({ error: e instanceof Error ? e.message : String(e) }, { status: 500 });
  }

  return Response.json({ ok: true, routeIds, count: routeIds.length });
}
