"use client";

/* ----------------------------------------------------------------------------
   Subscribes a manager's live-session view to Supabase Realtime. New transcript
   lines, agent insights, and auto-detected leads stream in via Postgres Changes;
   session metric/status updates patch the session in place. Server-rendered
   initial data seeds the state, so the page is useful before the socket opens.
   Degrades gracefully (returns the initial data) when the browser client isn't
   configured.
---------------------------------------------------------------------------- */
import { useEffect, useState } from "react";
import type {
  RealtimePostgresDeletePayload,
  RealtimePostgresInsertPayload,
  RealtimePostgresUpdatePayload,
} from "@supabase/supabase-js";
import { supabaseBrowser } from "@/lib/supabase/client";
import type {
  AgentInsight,
  DoorOutcome,
  DoorPing,
  LatLng,
  Lead,
  Session,
  Speaker,
  TranscriptLine,
} from "@/lib/types";

type Row = Record<string, unknown>;

export interface LiveSessionState {
  session: Session | null;
  transcript: TranscriptLine[];
  insights: AgentInsight[];
  detectedLeads: Lead[];
  doors: DoorPing[];
  /** the rep's accumulated GPS trail this session (grows as they walk) */
  breadcrumb: LatLng[];
  connected: boolean;
}

function mapDoor(r: Row): DoorPing {
  return {
    id: r.id as string,
    at: (r.at as string) ?? (r.created_at as string),
    position: { lat: (r.lat as number) ?? 0, lng: (r.lng as number) ?? 0 },
    outcome: (r.outcome as DoorOutcome) ?? "no-answer",
    address: (r.address as string) ?? undefined,
    note: (r.note as string) ?? undefined,
    status: (r.status as DoorPing["status"]) ?? undefined,
  };
}

function mapTranscript(r: Row): TranscriptLine {
  return {
    id: r.id as string,
    at: (r.at as string) ?? (r.created_at as string),
    speaker: (r.speaker as Speaker) ?? "prospect",
    text: (r.text as string) ?? "",
    sentiment: typeof r.sentiment === "number" ? (r.sentiment as number) : undefined,
  };
}

function mapInsight(r: Row): AgentInsight {
  return {
    id: r.id as string,
    at: (r.at as string) ?? (r.created_at as string),
    kind: (r.kind as AgentInsight["kind"]) ?? "coaching",
    title: (r.title as string) ?? "",
    detail: (r.detail as string) ?? "",
    score: typeof r.score === "number" ? (r.score as number) : undefined,
    objectionId: (r.objection_id as string) ?? undefined,
  };
}

function mapLead(r: Row): Lead {
  return {
    id: r.id as string,
    name: (r.name as string) ?? "New lead",
    address: (r.address as string) ?? "",
    position: { lat: (r.lat as number) ?? 43.6532, lng: (r.lng as number) ?? -79.3832 },
    phone: (r.phone as string) ?? undefined,
    email: (r.email as string) ?? undefined,
    status: (r.status as Lead["status"]) ?? "new",
    score: (r.score as number) ?? 50,
    repId: (r.marketer_id as string) ?? "",
    repName: "",
    territory: (r.territory as string) ?? "",
    capturedAt: (r.captured_at as string) ?? (r.created_at as string),
    source: (r.source as Lead["source"]) ?? "auto-detected",
    summary: (r.summary as string) ?? "",
    transcriptSnippet: (r.transcript_snippet as string) ?? "",
    tags: (r.tags as string[]) ?? [],
  };
}

const appendUnique = <T extends { id: string }>(list: T[], item: T): T[] =>
  list.some((x) => x.id === item.id) ? list : [...list, item];

/** Replace an existing item by id, or append it (doors update on close). */
const upsertById = <T extends { id: string }>(list: T[], item: T): T[] =>
  list.some((x) => x.id === item.id)
    ? list.map((x) => (x.id === item.id ? item : x))
    : [...list, item];

/** Insert a transcript line keeping the list ordered by timestamp. Realtime
 *  events (and the rep's batched POSTs) can arrive out of order; ordering by
 *  `at` - assigned on the rep's device when each line is finalized - keeps the
 *  displayed conversation in true chronological order. */
function insertByAt(list: TranscriptLine[], item: TranscriptLine): TranscriptLine[] {
  if (list.some((x) => x.id === item.id)) return list;
  let i = list.length;
  while (i > 0 && list[i - 1].at > item.at) i--;
  return [...list.slice(0, i), item, ...list.slice(i)];
}

export function useLiveSession(
  sessionId: string,
  initial?: {
    session?: Session | null;
    transcript?: TranscriptLine[];
    insights?: AgentInsight[];
    detectedLeads?: Lead[];
    doors?: DoorPing[];
  },
): LiveSessionState {
  const [session, setSession] = useState<Session | null>(initial?.session ?? null);
  const [transcript, setTranscript] = useState<TranscriptLine[]>(initial?.transcript ?? []);
  const [insights, setInsights] = useState<AgentInsight[]>(initial?.insights ?? []);
  const [detectedLeads, setDetectedLeads] = useState<Lead[]>(initial?.detectedLeads ?? []);
  const [doors, setDoors] = useState<DoorPing[]>(initial?.doors ?? []);
  // Seed only from the persisted trail; never from the single live position
  // (which may be a placeholder). The poll/Realtime then grow it from real GPS.
  const [breadcrumb, setBreadcrumb] = useState<LatLng[]>(initial?.session?.trailPath ?? []);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const db = supabaseBrowser();
    if (!db) return; // no anon key → stay on server-rendered initial data

    // NOTE: we deliberately do NOT use server-side `filter: session_id=eq.…`.
    // Postgres only honors Realtime filters on non-PK columns when the table has
    // REPLICA IDENTITY FULL; without it, every event is silently dropped. So we
    // subscribe unfiltered and match the session in the client - guaranteed to
    // deliver, and fine at team scale.
    const channel = db
      .channel(`session:${sessionId}`)
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_TranscriptLines" },
        (p: RealtimePostgresInsertPayload<Row>) => {
          if (p.new.session_id !== sessionId) return;
          setTranscript((prev) => insertByAt(prev, mapTranscript(p.new)));
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_AgentInsights" },
        (p: RealtimePostgresInsertPayload<Row>) => {
          if (p.new.session_id !== sessionId) return;
          setInsights((prev) => appendUnique(prev, mapInsight(p.new)));
        },
      )
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "D2D_Sessions" },
        (p: RealtimePostgresUpdatePayload<Row>) => {
          if (p.new.id !== sessionId) return;
          const hasPos = typeof p.new.lat === "number" && typeof p.new.lng === "number";
          const pos = hasPos ? { lat: p.new.lat as number, lng: p.new.lng as number } : null;
          // Prefer the persisted (downsampled) trail from the row; fall back to
          // appending the live point so the trace is never lost.
          if (Array.isArray(p.new.trail_path) && (p.new.trail_path as LatLng[]).length) {
            setBreadcrumb(p.new.trail_path as LatLng[]);
          } else if (pos) {
            setBreadcrumb((prev) => {
              const last = prev[prev.length - 1];
              if (last && Math.abs(last.lat - pos.lat) < 1e-6 && Math.abs(last.lng - pos.lng) < 1e-6) return prev;
              return [...prev, pos];
            });
          }
          setSession((prev) =>
            prev
              ? {
                  ...prev,
                  status: (p.new.status as Session["status"]) ?? prev.status,
                  doors: (p.new.doors as number) ?? prev.doors,
                  conversations: (p.new.conversations as number) ?? prev.conversations,
                  leads: (p.new.leads as number) ?? prev.leads,
                  noAnswers: (p.new.no_answers as number) ?? prev.noAnswers,
                  grade: (p.new.grade as number) ?? prev.grade,
                  endedAt: (p.new.ended_at as string) ?? prev.endedAt,
                  position: pos ?? prev.position,
                }
              : prev,
          );
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_DoorEvents" },
        (p: RealtimePostgresInsertPayload<Row>) => {
          if (p.new.session_id !== sessionId) return;
          setDoors((prev) => appendUnique(prev, mapDoor(p.new)));
        },
      )
      // Doors now open ("Knocking...") and later close with their classified
      // outcome - the UPDATE recolors the pin; the DELETE removes silent-pause
      // phantoms and undone pins.
      .on(
        "postgres_changes",
        { event: "UPDATE", schema: "public", table: "D2D_DoorEvents" },
        (p: RealtimePostgresUpdatePayload<Row>) => {
          if (p.new.session_id !== sessionId) return;
          setDoors((prev) => upsertById(prev, mapDoor(p.new)));
        },
      )
      .on(
        "postgres_changes",
        { event: "DELETE", schema: "public", table: "D2D_DoorEvents" },
        (p: RealtimePostgresDeletePayload<Row>) => {
          const goneId = p.old?.id as string | undefined;
          if (!goneId) return;
          setDoors((prev) => prev.filter((d) => d.id !== goneId));
        },
      )
      .on(
        "postgres_changes",
        { event: "INSERT", schema: "public", table: "D2D_Leads" },
        (p: RealtimePostgresInsertPayload<Row>) => {
          if (p.new.session_id !== sessionId) return;
          setDetectedLeads((prev) => appendUnique(prev, mapLead(p.new)));
        },
      )
      .subscribe((status) => setConnected(status === "SUBSCRIBED"));

    return () => {
      void db.removeChannel(channel);
    };
  }, [sessionId]);

  // Reliable trace fallback: poll the session's position + walked trail over HTTP.
  // This keeps the live dot moving and the green trace growing even when Realtime
  // UPDATE events don't arrive (the door/transcript INSERT events are separate).
  useEffect(() => {
    let alive = true;
    let done = false;
    const tick = async () => {
      try {
        const r = await fetch(`/api/sessions/${sessionId}/trail`, { cache: "no-store" });
        if (!r.ok || !alive) return;
        const j = (await r.json()) as { lat?: number; lng?: number; trailPath?: LatLng[]; status?: string };
        const path = Array.isArray(j.trailPath) ? j.trailPath : [];
        if (path.length > 1) {
          setBreadcrumb(path);
        } else if (typeof j.lat === "number" && typeof j.lng === "number") {
          const pos = { lat: j.lat, lng: j.lng };
          setBreadcrumb((prev) => {
            const last = prev[prev.length - 1];
            if (last && Math.abs(last.lat - pos.lat) < 1e-6 && Math.abs(last.lng - pos.lng) < 1e-6) return prev;
            return [...prev, pos];
          });
        }
        if (typeof j.lat === "number" && typeof j.lng === "number") {
          const pos = { lat: j.lat, lng: j.lng };
          setSession((prev) => (prev ? { ...prev, position: pos } : prev));
        }
        if (j.status && j.status !== "live") done = true;
      } catch {
        /* keep polling */
      }
    };
    void tick();
    const iv = setInterval(() => {
      if (done) {
        clearInterval(iv);
        return;
      }
      void tick();
    }, 1500);
    return () => {
      alive = false;
      clearInterval(iv);
    };
  }, [sessionId]);

  return { session, transcript, insights, detectedLeads, doors, breadcrumb, connected };
}
