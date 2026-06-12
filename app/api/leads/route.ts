import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

const STATUSES = ["new", "qualified", "callback", "appointment", "won", "lost"];

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
  if (!name) return Response.json({ error: "Name is required." }, { status: 400 });

  const db = supabaseAdmin();
  const { data, error } = await db
    .from("D2D_Leads")
    .insert({
      team_id: body.team_id ?? null,
      marketer_id: body.marketer_id ? String(body.marketer_id) : null,
      name,
      address: body.address ? String(body.address) : null,
      lat: typeof body.lat === "number" ? body.lat : null,
      lng: typeof body.lng === "number" ? body.lng : null,
      phone: body.phone ? String(body.phone) : null,
      email: body.email ? String(body.email) : null,
      status: STATUSES.includes(String(body.status)) ? String(body.status) : "new",
      score: typeof body.score === "number" ? Math.round(body.score) : 50,
      territory: body.territory ? String(body.territory) : null,
      source: body.source === "auto-detected" ? "auto-detected" : "manual",
      summary: body.summary ? String(body.summary) : null,
      tags: Array.isArray(body.tags) ? (body.tags as string[]).slice(0, 8) : [],
    })
    .select("id")
    .single();

  if (error) {
    const hint = /Could not find the table/.test(error.message)
      ? " - run supabase/migrations/0003_leads.sql first."
      : "";
    return Response.json({ error: error.message + hint }, { status: 500 });
  }
  return Response.json({ id: data.id });
}

/** Update a lead. Editing the address marks it verified, clearing the CRM
 *  "needs address check" flag for fully-automatic captures. */
export async function PATCH(req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const id = body.id ? String(body.id) : "";
  if (!id) return Response.json({ error: "id is required." }, { status: 400 });

  const patch: Record<string, unknown> = {};
  if (typeof body.address === "string") {
    patch.address = body.address.trim() || null;
    patch.address_verified = true;
  }
  if (typeof body.status === "string" && STATUSES.includes(body.status)) patch.status = body.status;
  if (typeof body.addressVerified === "boolean") patch.address_verified = body.addressVerified;
  if (!Object.keys(patch).length) return Response.json({ error: "Nothing to update." }, { status: 400 });

  const db = supabaseAdmin();
  const { error } = await db.from("D2D_Leads").update(patch).eq("id", id);
  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json({ ok: true });
}
