import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

const TINTS = ["emerald", "sky", "violet", "amber", "rose"];

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
    .from("D2D_Marketers")
    .insert({
      team_id: body.team_id ?? null,
      name,
      email: body.email ? String(body.email) : null,
      phone: body.phone ? String(body.phone) : null,
      avatar_tint: TINTS.includes(String(body.avatar_tint)) ? String(body.avatar_tint) : "emerald",
      status: "offline",
      home_territory: body.territory ? String(body.territory) : null,
    })
    .select("id")
    .single();

  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json({ id: data.id });
}
