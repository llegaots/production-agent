import { data } from "@/lib/data";
import { LeadsView } from "@/components/leads/leads-view";

export const dynamic = "force-dynamic";

export default async function LeadsPage() {
  const [leads, reps, team] = await Promise.all([data.getLeads(), data.getReps(), data.getTeam()]);
  return <LeadsView leads={leads} reps={reps} teamId={team?.id ?? null} />;
}
