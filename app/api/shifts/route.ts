import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

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
  const date = String(body.date ?? "");
  const start = String(body.start ?? "");
  const end = String(body.end ?? "");
  if (!date || !start || !end) {
    return Response.json({ error: "Date, start and end are required." }, { status: 400 });
  }

  const db = supabaseAdmin();
  const { data, error } = await db
    .from("D2D_Shifts")
    .insert({
      marketer_id: body.marketer_id ? String(body.marketer_id) : null,
      date,
      start_time: start,
      end_time: end,
      status: "scheduled",
      notes: body.notes ? String(body.notes) : null,
    })
    .select("id")
    .single();

  if (error) return Response.json({ error: error.message }, { status: 500 });
  return Response.json({ id: data.id });
}
