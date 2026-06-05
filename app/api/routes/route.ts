import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

/** Manually create a route (no AI). Geometry is optional — a hand-made route
 *  starts without a drawn path; the pair + target are recorded immediately. */
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
  const name = String(body.name ?? "").trim();
  const territory = String(body.territory ?? "").trim();
  if (!name) return Response.json({ error: "Route name is required." }, { status: 400 });

  const db = supabaseAdmin();
  const { data: routeId, error } = await db.rpc("d2d_insert_route", {
    p_team_id: body.teamId ?? null,
    p_generation_id: null,
    p_name: name,
    p_territory: territory || name,
    p_area_input: body.areaInput ? String(body.areaInput) : null,
    p_status: "scheduled",
    p_path: Array.isArray(body.path) ? body.path : [],
    p_bounds: null,
    p_doors_planned: typeof body.doorsPlanned === "number" ? Math.round(body.doorsPlanned) : 0,
    p_scheduled_for: body.scheduledFor ? String(body.scheduledFor) : null,
  });

  if (error) return Response.json({ error: error.message }, { status: 500 });
  const id = routeId as string;

  const marketerIds = Array.isArray(body.marketerIds) ? (body.marketerIds as string[]) : [];
  if (marketerIds.length) {
    const { error: aErr } = await db
      .from("D2D_RouteAssignments")
      .insert(marketerIds.map((mid) => ({ route_id: id, marketer_id: mid })));
    if (aErr) return Response.json({ error: aErr.message }, { status: 500 });
  }

  return Response.json({ id });
}
