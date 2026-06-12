import { after, type NextRequest } from "next/server";
import { supabaseAdmin, isSupabaseConfigured } from "@/lib/supabase/server";
import { closeDoor, resolvePin } from "@/lib/agent/close-door";
import { footprintCheck } from "@/lib/geo/footprint-check";

export const runtime = "nodejs";
export const maxDuration = 60;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Door events, two-phase. The recorder POSTs `phase:"open"` the moment the
 *  dwell begins (rep standing at the home): we resolve the address right away
 *  and insert the row with status='open', so leads auto-detected MID
 *  conversation inherit the correct home instantly. At walk-away it POSTs
 *  `phase:"close"`: outcome classified from the transcript range, counters
 *  bumped, weaker lead addresses back-filled. The client generates the door id
 *  so a lost open response can never duplicate a door. Posts without `phase`
 *  (older clients) are handled as a single-shot close. */
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

  const phase = body.phase === "open" || body.phase === "close" ? body.phase : null;
  const doorId =
    typeof body.id === "string" && UUID_RE.test(body.id) ? body.id : crypto.randomUUID();
  const lat = typeof body.lat === "number" ? body.lat : null;
  const lng = typeof body.lng === "number" ? body.lng : null;
  const accuracyM = typeof body.accuracyM === "number" ? body.accuracyM : null;
  const durationMs = typeof body.durationMs === "number" ? body.durationMs : null;
  const fromSeq = typeof body.fromSeq === "number" ? body.fromSeq : 0;
  const toSeq = typeof body.toSeq === "number" ? body.toSeq : fromSeq;
  const at = body.at ? new Date(String(body.at)).toISOString() : new Date().toISOString();

  const db = supabaseAdmin();

  if (phase === "open") {
    const { data: session } = await db
      .from("D2D_Sessions")
      .select("marketer_id")
      .eq("id", sessionId)
      .maybeSingle();

    // The one synchronous geocode round trip - the whole point of the open
    // phase: the home is resolved while the rep is still standing at it.
    const pin = await resolvePin(lat, lng);

    const { error } = await db.from("D2D_DoorEvents").upsert(
      {
        id: doorId,
        session_id: sessionId,
        marketer_id: session?.marketer_id ?? null,
        at,
        status: "open",
        lat: pin.pinLat,
        lng: pin.pinLng,
        gps_lat: lat,
        gps_lng: lng,
        gps_accuracy_m: accuracyM,
        snapped_lat: pin.snappedLat,
        snapped_lng: pin.snappedLng,
        // placeholder until the close-phase classifier runs; status='open' is
        // the real "in progress" signal (outcome has a CHECK constraint).
        outcome: "no-answer",
        address: pin.address,
        address_source: pin.addressSource,
        address_confidence: pin.addressConfidence,
        from_seq: fromSeq,
        to_seq: null,
      },
      { onConflict: "id", ignoreDuplicates: true },
    );
    if (error) {
      const hint = /column .* does not exist|violates check constraint/.test(error.message)
        ? " - run supabase/migrations/0014_door_open_close.sql first."
        : "";
      return Response.json({ error: error.message + hint }, { status: 500 });
    }

    // Independent accuracy cross-check (building footprint point-in-polygon)
    // runs after the response so it never slows the open phase down.
    if (lat !== null && lng !== null && pin.address) {
      after(() => footprintCheck(db, doorId, { lat, lng }, pin.address));
    }
    return Response.json({ id: doorId });
  }

  // phase:"close" and legacy single-shot posts share one pipeline: classify,
  // finalize (or insert when the open never landed), count once, back-fill.
  const result = await closeDoor(db, sessionId, doorId, {
    toSeq,
    fromSeq,
    lat,
    lng,
    accuracyM,
    durationMs,
    at,
  });
  if ("error" in result) return Response.json({ error: result.error }, { status: 500 });
  return Response.json(result);
}

/** Remove a door pin (the rep's "undo" after a phantom no-answer from pausing on
 *  the street) and reverse its contribution to the session's counters. Open
 *  doors never touched the counters, so only closed ones are reversed. */
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
    .select("outcome,status")
    .eq("id", doorId)
    .eq("session_id", sessionId)
    .maybeSingle();
  if (!door) return Response.json({ ok: true }); // already gone

  await db.from("D2D_DoorEvents").delete().eq("id", doorId);

  if (door.status !== "open") {
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
  }
  return Response.json({ ok: true });
}
