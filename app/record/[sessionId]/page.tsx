import { notFound } from "next/navigation";
import { data } from "@/lib/data";
import { Recorder } from "@/components/record/recorder";

export const dynamic = "force-dynamic";

export default async function RecordSessionPage({
  params,
}: {
  params: Promise<{ sessionId: string }>;
}) {
  const { sessionId } = await params;
  const session = await data.getSession(sessionId);
  if (!session) notFound();
  return (
    <Recorder
      sessionId={session.id}
      repName={session.repName}
      territory={session.territory}
    />
  );
}
