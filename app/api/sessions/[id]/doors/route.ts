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
  const accuracyM = typeof body.accuracyM === "number" ? body.accuracyM : null;
  const durationMs = typeof body.durationMs === "number" ? body.durationMs : null;
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

  // Auto-filter street pauses: a real no-answer is a short knock-and-wait. If the
  // rep was stationary and there was NO conversation for a long time, it's a rest,
  // not a door, so we don't log a phantom no-answer.
  const MAX_SILENT_DWELL_MS = 150_000; // 2.5 min
  const hadSpeech = transcript.some(
    (t) => (t.speaker === "rep" || t.speaker === "prospect") && t.text.trim(),
  );
  if (!hadSpeech && durationMs !== null && durationMs > MAX_SILENT_DWELL_MS) {
    return Response.json({ skipped: "long-silent-pause" });
  }

  const { outcome, note } = await classifyDoor(transcript);
  const excerpt = transcript.map((t) => `${t.speaker}: ${t.text}`).join("\n").slice(0, 2000);

  // Resolve the home address and decide whether to snap the pin onto the building.
  // We only move the pin for a trusted ROOFTOP match within SNAP_MAX_M; otherwise
  // we keep the raw GPS so we never confidently display the wrong house. The
  // confidence + raw fix are stored so the CRM can flag low-confidence addresses.
  const SNAP_MAX_M = 28;
  let pinLat = lat;
  let pinLng = lng;
  let address: string | null = null;
  let addressConfidence = "gps-only";
  let addressSource: string | null = null;
  let snappedLat: number | null = null;
  let snappedLng: number | null = null;
  if (lat !== null && lng !== null) {
    const rev = await reverseGeocodeDetailed(lat, lng);
    if (rev) {
      address = rev.address;
      addressConfidence = rev.confidence;
      addressSource = rev.source;
      if (rev.confidence === "rooftop" && haversine({ lat, lng }, { lat: rev.lat, lng: rev.lng }) <= SNAP_MAX_M) {
        snappedLat = rev.lat;
        snappedLng = rev.lng;
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
      gps_lat: lat,
      gps_lng: lng,
      gps_accuracy_m: accuracyM,
      snapped_lat: snappedLat,
      snapped_lng: snappedLng,
      outcome,
      note,
      address,
      address_source: addressSource,
      address_confidence: addressConfidence,
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

/** Remove a door pin (the rep's "undo" after a phantom no-answer from pausing on
 *  the street) and reverse its contribution to the session's counters. */
export async function DELETE(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  if (!isSupabaseConfigured()) {
    return Response.json({ error: "Supabase is not configured." }, { status: 400 });
  }
  const { id: sessionId } = await params;
  const doorId = new URL(req.url).searchParams.get("id");
  if (!doorId) return Response.json({ error: "id is required." }, { status: 400 });

  const db = supabaseAdmin();
  const { data: door } = await db
    .from("D2D_DoorEvents")
    .select("outcome")
    .eq("id", doorId)
    .eq("session_id", sessionId)
    .maybeSingle();
  if (!door) return Response.json({ ok: true }); // already gone

  await db.from("D2D_DoorEvents").delete().eq("id", doorId);

  const { data: s } = await db
    .from("D2D_Sessions")
    .select("doors,conversations,no_answers")
    .eq("id", sessionId)
    .maybeSingle();
  if (s) {
    const answered = door.outcome !== "no-answer";
    await db
      .from("D2D_Sessions")
      .update({
        doors: Math.max(0, ((s.doors as number) ?? 0) - 1),
        conversations: Math.max(0, ((s.conversations as number) ?? 0) - (answered ? 1 : 0)),
        no_answers: Math.max(0, ((s.no_answers as number) ?? 0) - (answered ? 0 : 1)),
      })
      .eq("id", sessionId);
  }
  return Response.json({ ok: true });
}
