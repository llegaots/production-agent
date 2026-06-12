import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { closeDoor } from "@/lib/agent/close-door";
import { detectAndStoreLeads, isLeadSpotterConfigured } from "@/lib/agent/lead-spotter";
import { gradeSession, isSessionGraderConfigured } from "@/lib/agent/session-grader";

export const runtime = "nodejs";
export const maxDuration = 120;

/** End a live session: flip status to completed, record duration + audio path,
 *  and set the rep back to offline. Then (in the background) run the final
 *  lead-detection sweep and the Phase-3 grading agent against the playbook. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  const { id: sessionId } = await params;

  let body: Record<string, unknown> = {};
  try {
    body = await req.json();
  } catch {
    // body is optional
  }
  const durationSec = typeof body.durationSec === "number" ? Math.round(body.durationSec) : null;

  const db = supabaseAdmin();
  const { data: session, error } = await db
    .from("D2D_Sessions")
    .update({
      status: "completed",
      ended_at: new Date().toISOString(),
      audio_path: `${sessionId}/`,
      ...(durationSec !== null ? { duration_sec: durationSec } : {}),
    })
    .eq("id", sessionId)
    .select("marketer_id")
    .single();

  if (error) {
    return Response.json({ error: error.message }, { status: 500 });
  }

  if (session?.marketer_id) {
    await db.from("D2D_Marketers").update({ status: "offline" }).eq("id", session.marketer_id);
  }

  // Background: finalize any door still open (tab closed mid-dwell, or the
  // recorder's un-awaited close lost the race), THEN run the final lead sweep
  // and grade the shift. Sequential so we don't fire two Claude bursts at
  // once; nothing here is allowed to break the session lifecycle.
  after(async () => {
    try {
      const { data: openDoors } = await db
        .from("D2D_DoorEvents")
        .select("id,at")
        .eq("session_id", sessionId)
        .eq("status", "open");
      for (const d of openDoors ?? []) {
        const durationMs = d.at ? Date.now() - new Date(d.at as string).getTime() : null;
        // No close position available: closeDoor keeps the open-phase
        // resolution and the status guard makes a late recorder close a no-op.
        await closeDoor(db, sessionId, d.id as string, { toSeq: null, durationMs });
      }
    } catch {
      // sweep is best-effort
    }
    if (isLeadSpotterConfigured()) await detectAndStoreLeads(sessionId, { maxLines: 200 });
    if (isSessionGraderConfigured()) await gradeSession(sessionId);
  });

  return Response.json({ ok: true });
}
