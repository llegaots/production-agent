import { notFound } from "next/navigation";
import { data } from "@/lib/data";
import { SessionLive } from "@/components/sessions/session-live";

export const dynamic = "force-dynamic";

export default async function SessionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const session = await data.getSession(id);
  if (!session) notFound();
  const [route, transcript, insights, leads, doors] = await Promise.all([
    data.getRoute(session.routeId),
    data.getSessionTranscript(id),
    data.getSessionInsights(id),
    data.getSessionLeads(id),
    data.getSessionDoors(id),
  ]);
  return (
    <SessionLive
      session={session}
      route={route}
      initialTranscript={transcript}
      initialInsights={insights}
      initialLeads={leads}
      initialDoors={doors}
    />
  );
}
