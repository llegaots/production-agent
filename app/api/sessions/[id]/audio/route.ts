import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";

export const runtime = "nodejs";
// Audio chunks can be a few MB each over a long session.
export const maxDuration = 60;

/** Receive one audio chunk (raw body) and store it in the private `session-audio`
 *  bucket at `{sessionId}/{seq}.webm`. Persisting chunks as they arrive means a
 *  crash loses at most the final unsent slice. The chunk index comes from `?seq=`. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured (.env.local)." }, { status: 400 });
  }
  const { id: sessionId } = await params;

  const seq = Number(req.nextUrl.searchParams.get("seq") ?? "0");
  const contentType = req.headers.get("content-type") || "audio/webm";
  const buf = Buffer.from(await req.arrayBuffer());
  if (!buf.length) return Response.json({ error: "Empty chunk" }, { status: 400 });

  const ext = contentType.includes("mp4") || contentType.includes("aac")
    ? "mp4"
    : contentType.includes("ogg")
      ? "ogg"
      : "webm";
  const path = `${sessionId}/${String(seq).padStart(6, "0")}.${ext}`;

  const db = supabaseAdmin();
  const { error } = await db.storage
    .from("session-audio")
    .upload(path, buf, { contentType, upsert: true });

  if (error) {
    const hint = /Bucket not found/i.test(error.message)
      ? " — create the `session-audio` bucket (run supabase/migrations/0006_sessions.sql)."
      : "";
    return Response.json({ error: error.message + hint }, { status: 500 });
  }
  return Response.json({ path });
}
