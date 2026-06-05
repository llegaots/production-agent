"use client";

import { useRouter } from "next/navigation";
import { useLiveSession } from "@/lib/realtime/use-live-session";
import { SessionDetail } from "./session-detail";
import type { AgentInsight, DoorPing, Lead, Route, Session, TranscriptLine } from "@/lib/types";

/** Client wrapper: subscribes to the session's Realtime channel and feeds live
 *  transcript / insights / detected leads / door pins into the (unchanged)
 *  SessionDetail UI. Server-rendered initial data seeds the first paint. */
export function SessionLive({
  session,
  route,
  initialTranscript,
  initialInsights = [],
  initialLeads = [],
  initialDoors = [],
}: {
  session: Session;
  route: Route | null;
  initialTranscript: TranscriptLine[];
  initialInsights?: AgentInsight[];
  initialLeads?: Lead[];
  initialDoors?: DoorPing[];
}) {
  const router = useRouter();
  const live = useLiveSession(session.id, {
    session,
    transcript: initialTranscript,
    insights: initialInsights,
    detectedLeads: initialLeads,
    doors: initialDoors,
  });

  async function endSession() {
    if (!confirm("End this session for the rep?")) return;
    await fetch(`/api/sessions/${session.id}/end`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }).catch(() => {});
    router.refresh();
  }

  // Feed door pins onto the map via the session's `trail`, and keep the live dot
  // (`position`) current from GPS updates.
  const mapSession = { ...(live.session ?? session), trail: live.doors };

  return (
    <SessionDetail
      session={mapSession}
      route={route}
      breadcrumb={live.breadcrumb}
      transcript={live.transcript}
      insights={live.insights}
      detectedLeads={live.detectedLeads}
      onEndSession={endSession}
    />
  );
}
