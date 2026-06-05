import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { detectAndStoreLeads, isLeadSpotterConfigured } from "@/lib/agent/lead-spotter";

export const runtime = "nodejs";
export const maxDuration = 60;

const SPEAKERS = ["rep", "prospect", "agent"];
// Run live lead detection roughly every this many finalized transcript lines.
const SCAN_EVERY = 16;

interface IncomingLine {
  seq?: number;
  at?: string;
  speaker?: string;
  text?: string;
  sentiment?: number;
  isFinal?: boolean;
}

/** Persist finalized transcript lines. Inserting into D2D_TranscriptLines fans
 *  the lines out to the manager's live view via Supabase Realtime. Accepts a
 *  single `{ ...line }` or a `{ lines: [...] }` batch. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  const { id: sessionId } = await params;

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const incoming: IncomingLine[] = Array.isArray(body.lines)
    ? (body.lines as IncomingLine[])
    : [body as IncomingLine];

  const rows = incoming
    .map((l) => ({
      session_id: sessionId,
      seq: typeof l.seq === "number" ? l.seq : 0,
      at: l.at ? new Date(l.at).toISOString() : new Date().toISOString(),
      speaker: SPEAKERS.includes(String(l.speaker)) ? String(l.speaker) : "prospect",
      text: String(l.text ?? "").trim(),
      sentiment: typeof l.sentiment === "number" ? l.sentiment : null,
      is_final: l.isFinal !== false,
    }))
    .filter((r) => r.text.length > 0);

  if (!rows.length) return Response.json({ inserted: 0 });

  const db = supabaseAdmin();
  const { error } = await db.from("D2D_TranscriptLines").insert(rows);
  if (error) {
    const hint = /Could not find the table/.test(error.message)
      ? " — run supabase/migrations/0006_sessions.sql first."
      : "";
    return Response.json({ error: error.message + hint }, { status: 500 });
  }

  // Every ~SCAN_EVERY finalized lines, run a background lead-detection pass over
  // the recent window so leads surface live (deduped against this session's leads).
  if (isLeadSpotterConfigured()) {
    const seqs = rows.map((r) => r.seq);
    const minSeq = Math.min(...seqs);
    const maxSeq = Math.max(...seqs);
    const crossedScanBoundary =
      Math.floor(maxSeq / SCAN_EVERY) > Math.floor((minSeq - 1) / SCAN_EVERY);
    if (crossedScanBoundary) {
      after(async () => {
        await detectAndStoreLeads(sessionId, { maxLines: 60 });
      });
    }
  }

  return Response.json({ inserted: rows.length });
}
