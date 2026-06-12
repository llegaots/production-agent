import "server-only";
import type { SupabaseClient } from "@supabase/supabase-js";
import { classifyDoor } from "@/lib/agent/door-classifier";
import { reverseGeocodeDetailed } from "@/lib/geo/geocode";
import { haversine } from "@/lib/geo/util";

/* ----------------------------------------------------------------------------
   Shared door-finalization pipeline. A door row is inserted at dwell OPEN with
   its address already resolved (so mid-conversation leads inherit the right
   home); this module finalizes it at walk-away: classify the outcome from the
   transcript range, keep the better of the open/close position resolutions,
   bump session counters exactly once, and back-fill any leads whose address
   was weaker than the door's final one. Used by the doors route (close phase
   and legacy single-shot posts) and by the /end route's open-door sweep.
---------------------------------------------------------------------------- */

/** Only snap the pin onto the building for a trusted ROOFTOP match this close. */
const SNAP_MAX_M = 28;
/** Below this, open and close fixes are the same spot (GPS noise floor). */
const MOVED_M = 12;
/** A long stationary stretch with zero conversation is a street rest, not a door. */
const MAX_SILENT_DWELL_MS = 150_000;

const CONFIDENCE_RANK: Record<string, number> = { "gps-only": 0, interpolated: 1, rooftop: 2 };
const rank = (c: string | null | undefined) => CONFIDENCE_RANK[c ?? "gps-only"] ?? 0;

export interface ResolvedPin {
  pinLat: number | null;
  pinLng: number | null;
  address: string | null;
  addressConfidence: string;
  addressSource: string | null;
  snappedLat: number | null;
  snappedLng: number | null;
}

/** Resolve the home address for a fix and decide whether to snap the pin onto
 *  the building. We only move the pin for a trusted ROOFTOP match within
 *  SNAP_MAX_M; otherwise we keep the raw GPS so we never confidently display
 *  the wrong house. */
export async function resolvePin(lat: number | null, lng: number | null): Promise<ResolvedPin> {
  const out: ResolvedPin = {
    pinLat: lat,
    pinLng: lng,
    address: null,
    addressConfidence: "gps-only",
    addressSource: null,
    snappedLat: null,
    snappedLng: null,
  };
  if (lat === null || lng === null) return out;
  const rev = await reverseGeocodeDetailed(lat, lng);
  if (!rev) return out;
  out.address = rev.address;
  out.addressConfidence = rev.confidence;
  out.addressSource = rev.source;
  if (rev.confidence === "rooftop" && haversine({ lat, lng }, { lat: rev.lat, lng: rev.lng }) <= SNAP_MAX_M) {
    out.snappedLat = rev.lat;
    out.snappedLng = rev.lng;
    out.pinLat = rev.lat;
    out.pinLng = rev.lng;
  }
  return out;
}

type Row = Record<string, unknown>;

export interface CloseDoorInput {
  /** last transcript seq of the visit; null = derive from the session's lines */
  toSeq?: number | null;
  /** fallback range start when the open row never landed */
  fromSeq?: number | null;
  /** close-position (bestFix of the whole dwell); absent in the /end sweep */
  lat?: number | null;
  lng?: number | null;
  accuracyM?: number | null;
  durationMs?: number | null;
  /** visit start time (insert fallback when the open row never landed) */
  at?: string | null;
}

export type CloseDoorResult =
  | { id: string; outcome: string }
  | { skipped: string }
  | { error: string };

export async function closeDoor(
  db: SupabaseClient,
  sessionId: string,
  doorId: string,
  input: CloseDoorInput,
): Promise<CloseDoorResult> {
  const { data: session } = await db
    .from("D2D_Sessions")
    .select("marketer_id,doors,conversations,no_answers")
    .eq("id", sessionId)
    .maybeSingle();

  const { data: existing } = await db
    .from("D2D_DoorEvents")
    .select("*")
    .eq("id", doorId)
    .eq("session_id", sessionId)
    .maybeSingle();

  // Already finalized (recorder close vs /end sweep race): idempotent no-op.
  if (existing && existing.status === "closed") {
    return { id: doorId, outcome: (existing.outcome as string) ?? "no-answer" };
  }

  const fromSeq =
    typeof existing?.from_seq === "number" ? (existing.from_seq as number) : input.fromSeq ?? 0;
  let toSeq = input.toSeq ?? null;
  if (toSeq === null) {
    const { data: lastLine } = await db
      .from("D2D_TranscriptLines")
      .select("seq")
      .eq("session_id", sessionId)
      .order("seq", { ascending: false })
      .limit(1)
      .maybeSingle();
    toSeq = typeof lastLine?.seq === "number" ? (lastLine.seq as number) : fromSeq;
  }

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
  // rep was stationary with NO conversation for a long time, it's a rest, not a
  // door. The open row (which never touched counters) is removed.
  const hadSpeech = transcript.some(
    (t) => (t.speaker === "rep" || t.speaker === "prospect") && t.text.trim(),
  );
  if (!hadSpeech && input.durationMs != null && input.durationMs > MAX_SILENT_DWELL_MS) {
    if (existing) await db.from("D2D_DoorEvents").delete().eq("id", doorId);
    return { skipped: "long-silent-pause" };
  }

  const { outcome, note } = await classifyDoor(transcript);
  const excerpt = transcript.map((t) => `${t.speaker}: ${t.text}`).join("\n").slice(0, 2000);

  // Address decision: the open row already resolved the home while the rep was
  // standing there. Re-resolve from the close position only when it can improve
  // things (no open row, no/weak address, or the rep genuinely moved); ties go
  // to the close resolution (it is the median of MORE fixes).
  const closeLat = typeof input.lat === "number" ? input.lat : null;
  const closeLng = typeof input.lng === "number" ? input.lng : null;
  const openGpsLat = typeof existing?.gps_lat === "number" ? (existing.gps_lat as number) : null;
  const openGpsLng = typeof existing?.gps_lng === "number" ? (existing.gps_lng as number) : null;
  const openConfidence = (existing?.address_confidence as string | null) ?? "gps-only";
  const openAddress = (existing?.address as string | null) ?? null;

  const movedM =
    closeLat !== null && closeLng !== null && openGpsLat !== null && openGpsLng !== null
      ? haversine({ lat: closeLat, lng: closeLng }, { lat: openGpsLat, lng: openGpsLng })
      : null;
  const canReResolve = closeLat !== null && closeLng !== null;
  const shouldReResolve =
    canReResolve &&
    (!existing || openAddress === null || openConfidence !== "rooftop" || (movedM !== null && movedM > MOVED_M));

  let positionFields: Row;
  let finalAddress: string | null;
  let finalConfidence: string;
  let finalSource: string | null;
  if (shouldReResolve) {
    const closeRes = await resolvePin(closeLat, closeLng);
    if (!existing || rank(closeRes.addressConfidence) >= rank(openConfidence)) {
      positionFields = {
        lat: closeRes.pinLat,
        lng: closeRes.pinLng,
        gps_lat: closeLat,
        gps_lng: closeLng,
        gps_accuracy_m: input.accuracyM ?? null,
        snapped_lat: closeRes.snappedLat,
        snapped_lng: closeRes.snappedLng,
        address: closeRes.address,
        address_source: closeRes.addressSource,
        address_confidence: closeRes.addressConfidence,
      };
      finalAddress = closeRes.address;
      finalConfidence = closeRes.addressConfidence;
      finalSource = closeRes.addressSource;
    } else {
      positionFields = {};
      finalAddress = openAddress;
      finalConfidence = openConfidence;
      finalSource = (existing?.address_source as string | null) ?? null;
    }
  } else {
    positionFields = {};
    finalAddress = openAddress;
    finalConfidence = openConfidence;
    finalSource = (existing?.address_source as string | null) ?? null;
  }

  let counted = false;
  if (existing) {
    // Finalize, guarded against double-close (the guard matched = we own the
    // counter bump; a concurrent close already took it otherwise).
    const { data: updated } = await db
      .from("D2D_DoorEvents")
      .update({
        status: "closed",
        to_seq: toSeq,
        outcome,
        note,
        transcript_excerpt: excerpt || null,
        ...positionFields,
      })
      .eq("id", doorId)
      .eq("session_id", sessionId)
      .eq("status", "open")
      .select("id")
      .maybeSingle();
    counted = Boolean(updated);
  } else {
    // The open POST never landed (offline / old client): single-shot insert.
    const res = shouldReResolve ? null : await resolvePin(closeLat, closeLng);
    const fields = shouldReResolve
      ? positionFields
      : {
          lat: res?.pinLat ?? null,
          lng: res?.pinLng ?? null,
          gps_lat: closeLat,
          gps_lng: closeLng,
          gps_accuracy_m: input.accuracyM ?? null,
          snapped_lat: res?.snappedLat ?? null,
          snapped_lng: res?.snappedLng ?? null,
          address: res?.address ?? null,
          address_source: res?.addressSource ?? null,
          address_confidence: res?.addressConfidence ?? "gps-only",
        };
    if (!shouldReResolve && res) {
      finalAddress = res.address;
      finalConfidence = res.addressConfidence;
      finalSource = res.addressSource;
    }
    const { error } = await db.from("D2D_DoorEvents").insert({
      id: doorId,
      session_id: sessionId,
      marketer_id: session?.marketer_id ?? null,
      at: input.at ? new Date(input.at).toISOString() : new Date().toISOString(),
      status: "closed",
      outcome,
      note,
      transcript_excerpt: excerpt || null,
      from_seq: fromSeq,
      to_seq: toSeq,
      ...fields,
    });
    if (error) {
      const hint = /Could not find the table/.test(error.message)
        ? " - run supabase/migrations/0008_door_events.sql first."
        : /column .* does not exist|violates check constraint/.test(error.message)
          ? " - run supabase/migrations/0014_door_open_close.sql first."
          : "";
      return { error: error.message + hint };
    }
    counted = true;
  }

  // Keep the session's headline counters in step with the door pins (exactly
  // once per door, on whichever close attempt won the status guard).
  if (counted) {
    const answered = outcome !== "no-answer";
    await db
      .from("D2D_Sessions")
      .update({
        doors: ((session?.doors as number) ?? 0) + 1,
        conversations: ((session?.conversations as number) ?? 0) + (answered ? 1 : 0),
        no_answers: ((session?.no_answers as number) ?? 0) + (answered ? 0 : 1),
      })
      .eq("id", sessionId);
  }

  // Back-fill leads with the door's final resolution. Never fails the close.
  try {
    await backfillLeads(db, sessionId, doorId, {
      openAddress,
      finalAddress,
      finalConfidence,
      finalSource,
      finalLat: (positionFields.lat as number | null) ?? (existing?.lat as number | null) ?? closeLat,
      finalLng: (positionFields.lng as number | null) ?? (existing?.lng as number | null) ?? closeLng,
      finalAccuracyM:
        (positionFields.gps_accuracy_m as number | null) ??
        (existing?.gps_accuracy_m as number | null) ??
        input.accuracyM ??
        null,
      transcriptTexts: transcript.map((t) => t.text.toLowerCase()),
    });
  } catch {
    // back-fill is best-effort
  }

  return { id: doorId, outcome };
}

/** Correct leads captured mid-conversation: leads linked to this door whose
 *  address was inherited before the door finalized, plus "orphan" leads (open
 *  POST failed or spotted before the dwell threshold) adopted by transcript
 *  snippet match. Spoken addresses are only overwritten by a STRONGER geocode. */
async function backfillLeads(
  db: SupabaseClient,
  sessionId: string,
  doorId: string,
  door: {
    openAddress: string | null;
    finalAddress: string | null;
    finalConfidence: string;
    finalSource: string | null;
    finalLat: number | null;
    finalLng: number | null;
    finalAccuracyM: number | null;
    transcriptTexts: string[];
  },
): Promise<void> {
  if (!door.finalAddress) return; // nothing better to offer

  const addressFields = {
    address: door.finalAddress,
    lat: door.finalLat,
    lng: door.finalLng,
    gps_accuracy_m: door.finalAccuracyM,
    address_source: door.finalSource,
    address_confidence: door.finalConfidence,
  };
  const shouldOverwrite = (lead: Row) =>
    lead.address == null ||
    (door.openAddress !== null && lead.address === door.openAddress) ||
    rank(door.finalConfidence) > rank(lead.address_confidence as string | null);

  // Leads already linked to this door (inherited the open-phase resolution).
  const { data: linked } = await db
    .from("D2D_Leads")
    .select("id,address,address_confidence")
    .eq("session_id", sessionId)
    .eq("door_event_id", doorId)
    .eq("address_verified", false);
  const linkedIds = (linked ?? []).filter(shouldOverwrite).map((l) => l.id as string);
  if (linkedIds.length) {
    await db.from("D2D_Leads").update(addressFields).in("id", linkedIds);
  }

  // Orphans: auto-detected leads with no door, whose snippet appears in this
  // door's transcript (same matching rule the lead-spotter uses).
  const { data: orphans } = await db
    .from("D2D_Leads")
    .select("id,address,address_confidence,transcript_snippet")
    .eq("session_id", sessionId)
    .is("door_event_id", null)
    .eq("address_verified", false)
    .eq("source", "auto-detected");
  const adopted = (orphans ?? []).filter((l) => {
    const snip = ((l.transcript_snippet as string) ?? "").trim().toLowerCase().slice(0, 40);
    return snip && door.transcriptTexts.some((t) => t.includes(snip));
  });
  const adoptAndFix = adopted.filter(shouldOverwrite).map((l) => l.id as string);
  const adoptOnly = adopted.filter((l) => !shouldOverwrite(l)).map((l) => l.id as string);
  if (adoptAndFix.length) {
    await db.from("D2D_Leads").update({ door_event_id: doorId, ...addressFields }).in("id", adoptAndFix);
  }
  if (adoptOnly.length) {
    await db.from("D2D_Leads").update({ door_event_id: doorId }).in("id", adoptOnly);
  }
}
