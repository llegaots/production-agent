import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const record = {
    team_id: body.teamId ?? null,
    script_title: String(body.scriptTitle ?? "Cold Approach Script"),
    script: String(body.script ?? ""),
    objections: Array.isArray(body.objections) ? body.objections : [],
    grading_criteria: Array.isArray(body.gradingCriteria) ? body.gradingCriteria : [],
    updated_at: new Date().toISOString(),
  };

  const db = supabaseAdmin();
  try {
    if (record.team_id) {
      const { error } = await db.from("D2D_Playbooks").upsert(record, { onConflict: "team_id" });
      if (error) throw error;
    } else {
      const { data: existing } = await db.from("D2D_Playbooks").select("id").limit(1).maybeSingle();
      const { error } = existing
        ? await db.from("D2D_Playbooks").update(record).eq("id", existing.id as string)
        : await db.from("D2D_Playbooks").insert(record);
      if (error) throw error;
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    const hint = /Could not find the table/.test(msg) ? " - run supabase/migrations/0004_playbook.sql first." : "";
    return Response.json({ error: msg + hint }, { status: 500 });
  }
  return Response.json({ ok: true });
}
