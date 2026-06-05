import type { NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { classifyDoor } from "@/lib/agent/door-classifier";
import { reverseGeocodeDetailed } from "@/lib/geo/geocode";
import { haversine } from "@/lib/geo/util";

export const runtime = "nodejs";
export const maxDuration = 60;

/** Record a door the rep dwelled at. The client (recorder) detects the dwell via
 *  GPS and posts the location + the transcript seq-range covering the visit; we
 *  pull those lines, classify the outcome, store the pin, and update counters.
 *  The INSERT streams the pin onto the manager's live map via Realtime. */
export async function POST(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  const { id: sessionId } = await params;
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const lat = typeof body.lat === "number" ? body.lat : null;
  const lng = typeof body.lng === "number" ? body.lng : null;
  const fromSeq = typeof body.fromSeq === "number" ? body.fromSeq : 0;
  const toSeq = typeof body.toSeq === "number" ? body.toSeq : fromSeq;
  const at = body.at ? new Date(String(body.at)).toISOString() : new Date().toISOString();

  const db = supabaseAdmin();
  const { data: session } = await db
    .from("D2D_Sessions")
    .select("marketer_id,territory,doors,conversations,no_answers")
    .eq("id", sessionId)
    .maybeSingle();

  // Pull the transcript lines captured during this door visit.
  const { data: lineRows } = await db
    .from("D2D_TranscriptLines")
    .select("speaker,text")
    .eq("session_id", sessionId)
    .gte("seq", fromSeq)
    .lte("seq", toSeq)
    .order("seq", { ascending: true });
  const transcript = (lineRows ?? []).map((r) => ({
    speaker: r.speaker as string,
    text: r.text as string,
  }));

  const { outcome, note } = await classifyDoor(transcript);
  const excerpt = transcript.map((t) => `${t.speaker}: ${t.text}`).join("\n").slice(0, 2000);

  // Snap the pin onto the actual home: reverse-geocode the GPS to the nearest
  // address and use that building's own coordinate (within ~60 m, else keep GPS).
  let pinLat = lat;
  let pinLng = lng;
  let address: string | null = null;
  if (lat !== null && lng !== null) {
    const rev = await reverseGeocodeDetailed(lat, lng);
    if (rev) {
      address = rev.address;
      if (haversine({ lat, lng }, { lat: rev.lat, lng: rev.lng }) <= 60) {
        pinLat = rev.lat;
        pinLng = rev.lng;
      }
    }
  }

  const { data: door, error } = await db
    .from("D2D_DoorEvents")
    .insert({
      session_id: sessionId,
      marketer_id: session?.marketer_id ?? null,
      at,
      lat: pinLat,
      lng: pinLng,
      outcome,
      note,
      address,
      transcript_excerpt: excerpt || null,
      from_seq: fromSeq,
      to_seq: toSeq,
    })
    .select("id")
    .single();

  if (error) {
    const hint = /Could not find the table/.test(error.message)
      ? " - run supabase/migrations/0008_door_events.sql first."
      : "";
    return Response.json({ error: error.message + hint }, { status: 500 });
  }

  // Keep the session's headline counters in step with the door pins.
  const answered = outcome !== "no-answer";
  await db
    .from("D2D_Sessions")
    .update({
      doors: ((session?.doors as number) ?? 0) + 1,
      conversations: ((session?.conversations as number) ?? 0) + (answered ? 1 : 0),
      no_answers: ((session?.no_answers as number) ?? 0) + (answered ? 0 : 1),
    })
    .eq("id", sessionId);

  return Response.json({ id: door.id, outcome });
}
