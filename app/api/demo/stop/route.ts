import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { detectAndStoreLeads, isLeadSpotterConfigured } from "@/lib/agent/lead-spotter";
import { gradeSession, isSessionGraderConfigured } from "@/lib/agent/session-grader";

export const runtime = "nodejs";
export const maxDuration = 120;

/** Stop the running demo: end every live session now. The background playback
 *  notices the status flip and bows out; we run the final lead sweep + grading
 *  for each ended session (same as a natural end). */
export async function POST(_req: NextRequest) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  const db = supabaseAdmin();
  const { data: liveRows } = await db.from("D2D_Sessions").select("id,marketer_id").eq("status", "live");
  const live = liveRows ?? [];
  if (!live.length) return Response.json({ stopped: 0 });

  const now = new Date().toISOString();
  for (const s of live) {
    await db.from("D2D_Sessions").update({ status: "completed", ended_at: now }).eq("id", s.id as string);
    if (s.marketer_id) await db.from("D2D_Marketers").update({ status: "offline" }).eq("id", s.marketer_id as string);
  }

  if (isLeadSpotterConfigured() || isSessionGraderConfigured()) {
    after(async () => {
      for (const s of live) {
        const id = s.id as string;
        if (isLeadSpotterConfigured()) await detectAndStoreLeads(id, { maxLines: 200 });
        if (isSessionGraderConfigured()) await gradeSession(id);
      }
    });
  }

  return Response.json({ stopped: live.length });
}
